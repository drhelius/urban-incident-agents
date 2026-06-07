from __future__ import annotations

from incident_core.config import Settings, get_settings
from incident_core.hosted_client import run_hosted_workflow, run_local_responses_workflow
from incident_core.models import IncidentWorkflowResult
from incident_core.observability import record_incident_metrics
from incident_core.workflow import run_local_workflow


async def process_incident_report(
    report: str, settings: Settings | None = None
) -> IncidentWorkflowResult:
    active_settings = settings or get_settings()
    backend = active_settings.orchestration_backend
    if backend == "local_responses":
        result = await run_local_responses_workflow(report, active_settings)
    elif backend == "hosted":
        result = await run_hosted_workflow(report, active_settings)
    elif backend == "local":
        result = await run_local_workflow(report, active_settings)
    else:
        raise ValueError("ORCHESTRATION_BACKEND must be 'local', 'local_responses', or 'hosted'.")

    record_incident_metrics(
        status=result.status,
        priority=result.routing.priority,
        department=result.routing.department,
    )
    return result
