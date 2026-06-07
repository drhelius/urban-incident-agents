from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from orchestrator.config import load_dotenv_if_available

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def configure_observability() -> None:
    load_dotenv_if_available()

    if not _is_foundry_hosted():
        _configure_local_azure_monitor()

    try:
        from agent_framework.observability import enable_instrumentation

        enable_instrumentation(enable_sensitive_data=_record_content())
    except Exception as exc:
        logger.warning("Agent Framework instrumentation was not enabled: %s", exc)


def _configure_local_azure_monitor() -> None:
    connection_string = _normalize_connection_string(
        os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    )
    if not _valid_connection_string(connection_string):
        logger.info("APPLICATIONINSIGHTS_CONNECTION_STRING is not set; OTEL export is disabled.")
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(connection_string=connection_string, enable_live_metrics=True)
    except Exception as exc:
        logger.info("Azure Monitor OpenTelemetry exporter was not configured: %s", exc)


def mark_agent_created(agent_id: str, agent_name: str) -> None:
    try:
        from opentelemetry import trace
    except Exception:
        return

    with trace.get_tracer("urban-incident-agents").start_as_current_span("create_agent") as span:
        span.set_attribute("gen_ai.operation.name", "create_agent")
        span.set_attribute("gen_ai.agent.id", agent_id)
        span.set_attribute("gen_ai.agent.name", agent_name)


_INCIDENT_REPORTS_COUNTER: Any | None = None
_metrics_disabled = False


def _incident_reports_counter() -> Any | None:
    global _INCIDENT_REPORTS_COUNTER, _metrics_disabled
    if _INCIDENT_REPORTS_COUNTER is not None or _metrics_disabled:
        return _INCIDENT_REPORTS_COUNTER
    try:
        from opentelemetry import metrics

        meter = metrics.get_meter("urban-incident-agents")
        _INCIDENT_REPORTS_COUNTER = meter.create_counter(
            "urban_incident.reports",
            unit="{report}",
            description=(
                "Incident reports processed, dimensioned by status, priority, and department."
            ),
        )
    except Exception as exc:
        logger.info("Custom incident metrics are unavailable: %s", exc)
        _metrics_disabled = True
    return _INCIDENT_REPORTS_COUNTER


def record_incident_metrics(status: str, priority: str, department: str) -> None:
    """Emit one counter increment per processed report.

    The single ``urban_incident.reports`` counter carries ``status``,
    ``priority``, and ``department`` dimensions so a dashboard can derive the
    total volume, accepted volume, and per-priority / per-department breakdowns
    from one metric.
    """
    counter = _incident_reports_counter()
    if counter is None:
        return
    try:
        counter.add(
            1,
            {
                "status": status,
                "priority": priority,
                "department": department,
            },
        )
    except Exception as exc:
        logger.debug("Failed to record incident metrics: %s", exc)


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    context: Any | None = None,
) -> Iterator[None]:
    try:
        from opentelemetry import trace
    except Exception:
        yield
        return

    with trace.get_tracer("urban-incident-agents").start_as_current_span(
        name, context=context
    ) as span:
        for key, value in (attributes or {}).items():
            span.set_attribute(key, value)
        yield


def inject_trace_context(headers: dict[str, str] | None = None) -> dict[str, str]:
    carrier = dict(headers or {})
    try:
        from opentelemetry.propagate import inject

        inject(carrier)
    except Exception:
        return carrier
    return carrier


def extract_trace_context(headers: Any | None = None) -> Any | None:
    """Build an OpenTelemetry context from incoming W3C trace headers.

    Returns ``None`` when no headers are supplied or propagation is unavailable,
    in which case callers fall back to the current (local) context.
    """
    if not headers:
        return None
    try:
        from opentelemetry.propagate import extract
    except Exception:
        return None
    return extract(dict(headers))


def _record_content() -> bool:
    value = os.getenv("ENABLE_SENSITIVE_DATA", "false")
    return value.strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _is_foundry_hosted() -> bool:
    return bool(os.getenv("FOUNDRY_HOSTING_ENVIRONMENT"))


def _valid_connection_string(value: str | None) -> bool:
    if not value:
        return False
    stripped = value.strip()
    return "InstrumentationKey=" in stripped or "ConnectionString=" in stripped


def _normalize_connection_string(value: str | None) -> str | None:
    if not value:
        return value

    parts: list[str] = []
    for part in value.split(";"):
        if "=" not in part:
            if part:
                parts.append(part)
            continue
        key, raw_part_value = part.split("=", 1)
        part_value = raw_part_value.strip()
        if key.lower().endswith("endpoint"):
            part_value = part_value.rstrip("/")
        parts.append(f"{key}={part_value}")
    return ";".join(parts)

