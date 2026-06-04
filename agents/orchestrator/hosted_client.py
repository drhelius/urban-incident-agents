from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import httpx

from orchestrator.agent_prompts import (
    build_intake_prompt,
    build_notification_prompt,
    build_routing_prompt,
)
from orchestrator.config import Settings, get_settings, load_dotenv_if_available
from orchestrator.json_utils import extract_json_object
from orchestrator.models import (
    IncidentWorkflowResult,
    IntakeResult,
    NotificationResult,
    RoutingResult,
)
from orchestrator.observability import inject_trace_context, trace_span


class HostedAgentResponsesClient:
    def __init__(self, settings: Settings):
        load_dotenv_if_available()
        self.settings = settings
        self._credential = None

    async def run(self, agent_name: str, prompt: str) -> str:
        token = await self._token()
        endpoint = _responses_endpoint(self.settings.foundry_project_endpoint, agent_name)
        headers = inject_trace_context(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )
        payload = {"input": prompt, "stream": False}
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        with trace_span(
            "orchestrator.call_hosted_agent",
            {
                "gen_ai.agent.name": agent_name,
                "http.url": endpoint,
            },
        ):
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise RuntimeError(
                        f"Hosted agent {agent_name!r} call failed with "
                        f"{response.status_code}: {response.text}"
                    ) from exc
            return _responses_text(response.json())

    async def _token(self) -> str:
        if self._credential is None:
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError as exc:
                raise RuntimeError(
                    "Hosted orchestration requires azure-identity. Install dependencies with: pip install -e ."
                ) from exc
            self._credential = DefaultAzureCredential()

        access_token = await asyncio.to_thread(
            self._credential.get_token, self.settings.foundry_token_scope
        )
        return access_token.token


async def run_hosted_workflow(
    report: str, settings: Settings | None = None
) -> IncidentWorkflowResult:
    active_settings = settings or get_settings()
    if not report.strip():
        raise ValueError("Incident report text is required.")

    client = HostedAgentResponsesClient(active_settings)
    names = active_settings.hosted_agent_names

    intake_text = await client.run(names["intake"], build_intake_prompt(report))
    intake = IntakeResult.from_mapping(extract_json_object(intake_text), raw_report=report)

    if intake.is_urban_incident:
        routing_text = await client.run(names["routing"], build_routing_prompt(report, intake))
        routing = RoutingResult.from_mapping(extract_json_object(routing_text))
    else:
        routing = RoutingResult.not_applicable()

    notification_text = await client.run(
        names["notification"], build_notification_prompt(report, intake, routing)
    )
    notification = NotificationResult.from_mapping(extract_json_object(notification_text))
    return IncidentWorkflowResult(
        status="accepted" if intake.is_urban_incident else "rejected",
        correlation_id=f"inc-{uuid4().hex[:12]}",
        intake=intake,
        routing=routing,
        notification=notification,
    )


async def run_local_responses_workflow(
    report: str, settings: Settings | None = None
) -> IncidentWorkflowResult:
    active_settings = settings or get_settings()
    if not report.strip():
        raise ValueError("Incident report text is required.")

    payload = {"input": report.strip(), "stream": False}
    timeout = httpx.Timeout(active_settings.request_timeout_seconds)
    with trace_span(
        "orchestrator.call_local_responses",
        {
            "http.url": active_settings.local_orchestrator_responses_url,
        },
    ):
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                active_settings.local_orchestrator_responses_url,
                json=payload,
                headers=inject_trace_context(),
            )
            response.raise_for_status()

    return IncidentWorkflowResult.from_mapping(
        extract_json_object(_responses_text(response.json())),
        correlation_id=f"inc-{uuid4().hex[:12]}",
    )


def _responses_endpoint(project_endpoint: str, agent_name: str) -> str:
    return (
        project_endpoint.rstrip("/")
        + f"/agents/{agent_name}/endpoint/protocols/openai/responses?api-version=v1"
    )


def _responses_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output = payload.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if isinstance(content_item, dict):
                    text = content_item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        if parts:
            return "\n".join(parts)

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message", {})
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    return str(payload)
