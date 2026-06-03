from __future__ import annotations

from orchestrator.config import Settings, get_settings
from orchestrator.hosted_client import run_hosted_workflow, run_local_responses_workflow
from orchestrator.models import IncidentWorkflowResult
from orchestrator.workflow import run_local_workflow


async def process_incident_report(
    report: str, settings: Settings | None = None
) -> IncidentWorkflowResult:
    active_settings = settings or get_settings()
    if active_settings.orchestration_backend == "local_responses":
        return await run_local_responses_workflow(report, active_settings)
    if active_settings.orchestration_backend == "hosted":
        return await run_hosted_workflow(report, active_settings)
    if active_settings.orchestration_backend != "local":
        raise ValueError("ORCHESTRATION_BACKEND must be 'local', 'local_responses', or 'hosted'.")
    return await run_local_workflow(report, active_settings)
