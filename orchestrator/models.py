from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

ALLOWED_DEPARTMENTS = {
    "Public Works and Infrastructure",
    "Waste Management and Street Cleaning",
    "Water and Sewerage Services",
    "Environment and Sustainability",
    "Traffic and Mobility",
    "Local Police and Public Safety",
    "Civil Protection and Emergencies",
    "Animal Welfare",
    "General Administration and Citizen Services",
}

PRIORITY_TO_SLA = {
    "P1": "immediate response",
    "P2": "24 hours",
    "P3": "72 hours",
    "P4": "planned maintenance",
}


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(value)]


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "urban", "accepted"}
    return bool(value)


@dataclass
class IntakeResult:
    is_urban_incident: bool
    incident_type: str
    location: str
    affected_assets: list[str] = field(default_factory=list)
    risk_indicators: list[str] = field(default_factory=list)
    missing_details: list[str] = field(default_factory=list)
    summary: str = ""
    raw_report: str = ""

    @classmethod
    def from_mapping(cls, data: dict[str, Any], raw_report: str = "") -> "IntakeResult":
        incident_type = str(data.get("incident_type") or data.get("category") or "unknown")
        return cls(
            is_urban_incident=_bool(
                data.get(
                    "is_urban_incident", incident_type not in {"unknown", "not_urban_incident"}
                )
            ),
            incident_type=incident_type,
            location=str(data.get("location") or "Location not specified"),
            affected_assets=_list(data.get("affected_assets") or data.get("assets")),
            risk_indicators=_list(data.get("risk_indicators") or data.get("hazards")),
            missing_details=_list(data.get("missing_details") or data.get("missing_information")),
            summary=str(data.get("summary") or ""),
            raw_report=str(data.get("raw_report") or raw_report),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkOrder:
    operational_summary: str
    field_team_instructions: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "WorkOrder":
        return cls(
            operational_summary=str(
                data.get("operational_summary")
                or data.get("site_notes")
                or data.get("primary_action")
                or ""
            ),
            field_team_instructions=_list(data.get("field_team_instructions")),
            required_skills=_list(data.get("required_skills") or data.get("skills")),
            tags=_list(data.get("tags") or data.get("hazards") or data.get("secondary_actions")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoutingResult:
    priority: str
    sla: str
    department: str
    rationale: str
    escalation_required: bool
    work_order: WorkOrder

    @classmethod
    def not_applicable(
        cls, reason: str = "Report is not related to a municipal incident"
    ) -> "RoutingResult":
        return cls(
            priority="P4",
            sla="planned maintenance",
            department="General Administration and Citizen Services",
            rationale=reason,
            escalation_required=False,
            work_order=WorkOrder(
                operational_summary="No work order created.",
                field_team_instructions=[],
                required_skills=[],
                tags=["not-urban-incident"],
            ),
        )

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "RoutingResult":
        work_order_data = data.get("work_order") or data.get("work_order_detail")
        if not isinstance(work_order_data, dict):
            work_order_data = {}
        priority = _normalize_priority(data.get("priority") or data.get("urgency"))
        return cls(
            priority=priority,
            sla=_normalize_sla(data.get("sla"), priority),
            department=_normalize_department(
                data.get("department") or data.get("department_owner")
            ),
            rationale=str(data.get("rationale") or data.get("risk_level") or ""),
            escalation_required=_bool(data.get("escalation_required")),
            work_order=WorkOrder.from_mapping(work_order_data),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NotificationResult:
    message: str
    needs_more_information: bool = False
    requested_information: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(
        cls,
        data: dict[str, Any],
    ) -> "NotificationResult":
        requested_information = _list(
            data.get("requested_information") or data.get("missing_information")
        )
        message = data.get("message")
        if not message:
            raise ValueError("Notification Agent response did not include notification.message.")
        return cls(
            message=str(message),
            needs_more_information=_bool(data.get("needs_more_information"))
            or bool(requested_information),
            requested_information=requested_information,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IncidentWorkflowResult:
    status: str
    correlation_id: str
    intake: IntakeResult
    routing: RoutingResult
    notification: NotificationResult

    @classmethod
    def from_mapping(
        cls, data: dict[str, Any], correlation_id: str = ""
    ) -> "IncidentWorkflowResult":
        intake_data = _mapping(data.get("intake"))
        intake = IntakeResult.from_mapping(intake_data)
        routing = RoutingResult.from_mapping(_mapping(data.get("routing")))
        return cls(
            status=str(
                data.get("status") or ("accepted" if intake.is_urban_incident else "rejected")
            ),
            correlation_id=str(data.get("correlation_id") or correlation_id),
            intake=intake,
            routing=routing,
            notification=NotificationResult.from_mapping(_mapping(data.get("notification"))),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_priority(value: Any) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if text in {"P1", "IMMEDIATE", "URGENT", "CRITICAL", "EMERGENCY", "HIGH"}:
        return "P1"
    if text in {"P2", "24_HOURS", "24_HOUR", "EXPEDITED", "ELEVATED", "MEDIUM_HIGH"}:
        return "P2"
    if text in {"P3", "72_HOURS", "72_HOUR", "STANDARD", "NORMAL", "MEDIUM"}:
        return "P3"
    if text in {"P4", "PLANNED_MAINTENANCE", "LOW", "ROUTINE", "PLANNED"}:
        return "P4"
    return "P3"


def _normalize_sla(value: Any, priority: str) -> str:
    text = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    if "immediate" in text or "urgent" in text or "1 hour" in text:
        return "immediate response"
    if "24" in text:
        return "24 hours"
    if "72" in text:
        return "72 hours"
    if "planned" in text or "maintenance" in text or "routine" in text:
        return "planned maintenance"
    return PRIORITY_TO_SLA[priority]


def _normalize_department(value: Any) -> str:
    text = str(value or "").strip()
    if text in ALLOWED_DEPARTMENTS:
        return text
    normalized = text.lower().replace("_", " ").replace("-", " ")

    if any(term in normalized for term in ["water", "sewer", "drain", "flood"]):
        return "Water and Sewerage Services"
    if any(term in normalized for term in ["waste", "clean", "bin", "trash", "rubbish"]):
        return "Waste Management and Street Cleaning"
    if any(term in normalized for term in ["traffic", "mobility", "lane", "signal", "crossing"]):
        return "Traffic and Mobility"
    if any(term in normalized for term in ["police", "safety", "enforcement", "vandal"]):
        return "Local Police and Public Safety"
    if any(term in normalized for term in ["civil", "emergency", "protection", "disaster"]):
        return "Civil Protection and Emergencies"
    if any(term in normalized for term in ["animal", "dog", "cat", "wildlife"]):
        return "Animal Welfare"
    if any(
        term in normalized for term in ["environment", "tree", "park", "green", "noise", "sustain"]
    ):
        return "Environment and Sustainability"
    if any(
        term in normalized
        for term in [
            "public works",
            "road",
            "sidewalk",
            "streetlight",
            "lighting",
            "pothole",
            "infrastructure",
            "pavement",
        ]
    ):
        return "Public Works and Infrastructure"
    return "General Administration and Citizen Services"
