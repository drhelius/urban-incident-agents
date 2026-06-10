from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Any

import azure.functions as func
import httpx
from azure.core.exceptions import ResourceExistsError
from azure.data.tables import TableServiceClient, UpdateMode
from azure.identity import DefaultAzureCredential
from azure.storage.queue import QueueClient

logger = logging.getLogger(__name__)
app = func.FunctionApp()

INBOUND_EVENT_TYPE = "Microsoft.Communication.AdvancedMessageReceived"
DELIVERY_STATUS_EVENT_TYPE = "Microsoft.Communication.AdvancedMessageDeliveryStatusUpdated"
QUEUE_NAME = os.getenv("WHATSAPP_QUEUE_NAME", "whatsapp-incidents")
STATE_TABLE = os.getenv("WHATSAPP_STATE_TABLE", "whatsappincidentstate")


@lru_cache(maxsize=1)
def _configure_observability() -> None:
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(connection_string=connection_string, enable_live_metrics=True)
    except Exception as exc:
        logger.info("Azure Monitor OpenTelemetry exporter was not configured: %s", exc)


@lru_cache(maxsize=1)
def _queue_client() -> QueueClient:
    account_name = os.getenv("WHATSAPP_STORAGE_ACCOUNT_NAME")
    if account_name:
        client = QueueClient(
            account_url=f"https://{account_name}.queue.core.windows.net",
            queue_name=QUEUE_NAME,
            credential=DefaultAzureCredential(),
        )
    else:
        client = QueueClient.from_connection_string(
            os.environ["AzureWebJobsStorage"], queue_name=QUEUE_NAME
        )
    try:
        client.create_queue()
    except ResourceExistsError:
        pass
    return client


@lru_cache(maxsize=1)
def _state_table():
    account_name = os.getenv("WHATSAPP_STORAGE_ACCOUNT_NAME")
    if account_name:
        service = TableServiceClient(
            endpoint=f"https://{account_name}.table.core.windows.net",
            credential=DefaultAzureCredential(),
        )
    else:
        service = TableServiceClient.from_connection_string(os.environ["AzureWebJobsStorage"])
    service.create_table_if_not_exists(STATE_TABLE)
    return service.get_table_client(STATE_TABLE)


@app.function_name(name="acs_whatsapp_events")
@app.event_grid_trigger(arg_name="event")
def acs_whatsapp_events(event: func.EventGridEvent) -> None:
    """Normalize ACS Advanced Messaging events and enqueue work.

    Event Grid handlers should return quickly. The slow work (calling the incident
    workflow and sending WhatsApp replies) runs in the queue-triggered worker.
    """
    _configure_observability()
    _handle_event_grid_event(event.id, event.event_type, event.get_json() or {})


@app.function_name(name="acs_whatsapp_events_webhook")
@app.route(
    route="acs-whatsapp-events",
    methods=["POST"],
    auth_level=func.AuthLevel.FUNCTION,
)
def acs_whatsapp_events_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP Event Grid webhook fallback for direct ACS delivery.

    Event Grid's AzureFunction destination can return Busy before invoking code
    on some hosting paths. The webhook destination still delivers directly to
    this Function App, while letting this code perform subscription validation.
    """
    _configure_observability()
    try:
        payload = req.get_json()
    except ValueError:
        logger.warning("Received invalid Event Grid webhook payload")
        return func.HttpResponse("Invalid JSON", status_code=400)

    events = payload if isinstance(payload, list) else [payload]
    for raw_event in events:
        if not isinstance(raw_event, dict):
            logger.warning("Ignoring non-object Event Grid webhook item")
            continue

        event_type = str(raw_event.get("eventType") or raw_event.get("type") or "")
        data = raw_event.get("data") or {}

        if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
            validation_code = data.get("validationCode")
            if not validation_code:
                return func.HttpResponse("Missing validationCode", status_code=400)
            return func.HttpResponse(
                json.dumps({"validationResponse": validation_code}),
                status_code=200,
                mimetype="application/json",
            )

        event_id = str(raw_event.get("id") or raw_event.get("eventId") or "")
        _handle_event_grid_event(event_id, event_type, data)

    return func.HttpResponse(status_code=204)


def _handle_event_grid_event(event_id: str, event_type: str, data: dict[str, Any]) -> None:
    """Normalize one ACS Event Grid event and enqueue work when needed."""

    if event_type == DELIVERY_STATUS_EVENT_TYPE:
        _record_delivery_status(event_id, data)
        return

    if event_type != INBOUND_EVENT_TYPE:
        logger.info("Ignoring unsupported Event Grid event type %s", event_type)
        return

    if str(data.get("channelType", "")).lower() != "whatsapp":
        logger.info("Ignoring non-WhatsApp advanced message event %s", event_id)
        return

    sender = _sender_identity(data)
    channel_registration_id = os.getenv("WHATSAPP_CHANNEL_REGISTRATION_ID") or data.get("to")
    message_id = str(data.get("messageId") or event_id)
    report_text = _message_text(data)

    if not sender or not channel_registration_id:
        logger.warning(
            "Cannot process WhatsApp event %s: missing sender or channel id", event_id
        )
        return

    if not _mark_inbound_seen(message_id, event_id):
        logger.info("Skipping duplicate WhatsApp inbound message %s", message_id)
        return

    job = {
        "event_id": event_id,
        "message_id": message_id,
        "sender": sender,
        "channel_registration_id": channel_registration_id,
        "report": report_text,
        "message_type": data.get("messageType"),
        "received_timestamp": data.get("receivedTimestamp"),
    }
    if not report_text:
        job["reply_override"] = (
            "Please send a short text description of the municipal incident, "
            "including the location if you know it."
        )

    _queue_client().send_message(json.dumps(job))
    logger.info(
        "Queued WhatsApp incident message %s (type=%s, has_text=%s)",
        message_id,
        data.get("messageType"),
        bool(report_text),
    )


@app.function_name(name="process_whatsapp_incident")
@app.queue_trigger(arg_name="message", queue_name=QUEUE_NAME, connection="AzureWebJobsStorage")
def process_whatsapp_incident(message: func.QueueMessage) -> None:
    """Call the existing incident API and reply to the WhatsApp sender."""
    _configure_observability()
    job = json.loads(message.get_body().decode("utf-8"))
    message_id = str(job["message_id"])

    if _outbound_already_sent(message_id):
        logger.info("Skipping already-replied WhatsApp message %s", message_id)
        return

    reply = _format_whatsapp_reply(
        job.get("reply_override") or _process_incident(job["report"], message_id)
    )
    receipt = _send_whatsapp_reply(
        channel_registration_id=job["channel_registration_id"],
        recipient=job["sender"],
        content=reply,
    )
    _mark_outbound_sent(message_id, receipt)
    logger.info("Sent WhatsApp reply for inbound message %s", message_id)


def _process_incident(report: str, message_id: str) -> str:
    incident_api_url = os.environ["INCIDENT_API_URL"].rstrip("/")
    headers = {"Content-Type": "application/json"}
    try:
        from opentelemetry.propagate import inject

        inject(headers)
    except Exception:
        pass

    with httpx.Client(timeout=float(os.getenv("INCIDENT_API_TIMEOUT_SECONDS", "180"))) as client:
        response = client.post(
            f"{incident_api_url}/api/incidents",
            headers=headers,
            json={"report": report},
        )
        response.raise_for_status()
        result = response.json()

    _update_inbound_status(
        message_id,
        status=result.get("status"),
        correlation_id=result.get("correlation_id"),
        priority=(result.get("routing") or {}).get("priority"),
        department=(result.get("routing") or {}).get("department"),
    )
    notification = result.get("notification") or {}
    reply = str(notification.get("message") or "")
    if not reply.strip():
        raise RuntimeError("Incident API response did not contain notification.message")
    return reply.strip()


def _format_whatsapp_reply(content: str) -> str:
    cleaned = re.sub(r"[ \t]+", " ", content.strip())
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    if "\n" in cleaned:
        return cleaned

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    if len(sentences) <= 1:
        return cleaned
    return "\n\n".join(sentences)


def _send_whatsapp_reply(
    *, channel_registration_id: str, recipient: str, content: str
) -> dict[str, str | None]:
    from azure.communication.messages import NotificationMessagesClient
    from azure.communication.messages.models import TextNotificationContent

    client = NotificationMessagesClient.from_connection_string(
        os.environ["COMMUNICATION_SERVICES_CONNECTION_STRING"]
    )
    result = client.send(
        TextNotificationContent(
            channel_registration_id=channel_registration_id,
            to=[recipient],
            content=content,
        )
    )
    receipt = result.receipts[0] if getattr(result, "receipts", None) else None
    return {
        "message_id": getattr(receipt, "message_id", None),
        "to": getattr(receipt, "to", None),
    }


def _message_text(data: dict[str, Any]) -> str:
    message_type = str(data.get("messageType") or "").lower()
    if message_type == "text":
        return str(data.get("content") or "").strip()
    if message_type == "button":
        button = data.get("button") or {}
        return str(button.get("text") or button.get("payload") or "").strip()
    if message_type == "interactive":
        interactive = data.get("interactive") or {}
        button_reply = interactive.get("buttonReply") or {}
        list_reply = interactive.get("listReply") or {}
        return str(
            button_reply.get("title")
            or button_reply.get("id")
            or list_reply.get("title")
            or list_reply.get("description")
            or list_reply.get("id")
            or ""
        ).strip()
    media = data.get("media") or {}
    return str(media.get("caption") or "").strip()


def _sender_identity(data: dict[str, Any]) -> str:
    sender = str(data.get("from") or "").strip()
    if sender:
        return _normalize_phone_number(sender)
    return str(data.get("fromBSUID") or "").strip()


def _normalize_phone_number(value: str) -> str:
    compact = re.sub(r"[\s()\-]", "", value.strip())
    if compact.startswith("+"):
        return compact
    if compact.isdigit():
        return f"+{compact}"
    return value.strip()


def _safe_row_key(value: str) -> str:
    return re.sub(r"[\\/#?\x00-\x1f\x7f-\x9f]", "_", value)[:1024]


def _mark_inbound_seen(message_id: str, event_id: str) -> bool:
    entity = {
        "PartitionKey": "inbound",
        "RowKey": _safe_row_key(message_id),
        "eventId": event_id,
        "status": "queued",
    }
    try:
        _state_table().create_entity(entity)
        return True
    except ResourceExistsError:
        return False


def _update_inbound_status(message_id: str, **values: Any) -> None:
    entity = {
        "PartitionKey": "inbound",
        "RowKey": _safe_row_key(message_id),
        **{key: value for key, value in values.items() if value is not None},
    }
    _state_table().upsert_entity(entity=entity, mode=UpdateMode.MERGE)


def _outbound_already_sent(message_id: str) -> bool:
    try:
        _state_table().get_entity("outbound", _safe_row_key(message_id))
        return True
    except Exception:
        return False


def _mark_outbound_sent(message_id: str, receipt: dict[str, str | None]) -> None:
    entity = {
        "PartitionKey": "outbound",
        "RowKey": _safe_row_key(message_id),
        "status": "sent",
        "acsMessageId": receipt.get("message_id"),
        "to": receipt.get("to"),
    }
    _state_table().upsert_entity(
        entity={key: value for key, value in entity.items() if value is not None},
        mode=UpdateMode.MERGE,
    )


def _record_delivery_status(event_id: str, data: dict[str, Any]) -> None:
    message_id = str(data.get("messageId") or event_id)
    entity = {
        "PartitionKey": "delivery",
        "RowKey": _safe_row_key(message_id),
        "eventId": event_id,
        "status": data.get("status"),
        "channelType": data.get("channelType"),
        "to": data.get("toBSUID") or data.get("to"),
        "error": json.dumps(data.get("error")) if data.get("error") else None,
    }
    _state_table().upsert_entity(
        entity={key: value for key, value in entity.items() if value is not None},
        mode=UpdateMode.MERGE,
    )
    logger.info("Recorded WhatsApp delivery status for ACS message %s", message_id)
