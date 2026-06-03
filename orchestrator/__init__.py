from orchestrator.config import Settings, get_settings
from orchestrator.models import IncidentWorkflowResult

__all__ = ["IncidentWorkflowResult", "Settings", "get_settings", "process_incident_report"]


def __getattr__(name: str):
    if name == "process_incident_report":
        from orchestrator.service import process_incident_report

        return process_incident_report
    raise AttributeError(name)
