from __future__ import annotations

from orchestrator.config import Settings, get_settings
from orchestrator.hosted_client import run_hosted_workflow, run_local_responses_workflow
from orchestrator.models import IncidentWorkflowResult
from orchestrator.observability import record_incident_metrics
from orchestrator.workflow import run_local_workflow


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
