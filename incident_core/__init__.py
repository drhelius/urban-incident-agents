from incident_core.config import Settings, get_settings
from incident_core.models import IncidentWorkflowResult

__all__ = ["IncidentWorkflowResult", "Settings", "get_settings", "process_incident_report"]


def __getattr__(name: str):
    if name == "process_incident_report":
        from incident_core.service import process_incident_report

        return process_incident_report
    raise AttributeError(name)
