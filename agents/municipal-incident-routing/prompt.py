from __future__ import annotations

from incident_core.json_utils import dumps_compact
from incident_core.models import IntakeResult

ALLOWED_DEPARTMENTS_TEXT = """
- Public Works and Infrastructure
- Waste Management and Street Cleaning
- Water and Sewerage Services
- Environment and Sustainability
- Traffic and Mobility
- Local Police and Public Safety
- Civil Protection and Emergencies
- Animal Welfare
- General Administration and Citizen Services
""".strip()

ROUTING_RESPONSE_SCHEMA = """
{
  "correlation_id": "copy from intake JSON when present, otherwise empty string",
  "intake": { ...the provided intake JSON... },
  "routing": {
    "priority": "P1 | P2 | P3 | P4",
    "sla": "immediate response | 24 hours | 72 hours | planned maintenance",
    "department": "one allowed department name from the list below",
    "rationale": "brief operational rationale",
    "escalation_required": false,
    "work_order": {
      "operational_summary": "summary for dispatch/work management",
      "field_team_instructions": ["specific field checks or actions"],
      "required_skills": ["crew skills or trades"],
      "tags": ["routing tags"]
    }
  }
}
""".strip()

ROUTING_PRIORITY_GUIDE = """
- P1: highest priority. Use for immediate danger to people, active road/traffic hazard, blocked emergency access, flooding near critical services, exposed electrical risk, major obstruction, or incidents requiring urgent public safety response.
- P2: high priority. Use for safety-sensitive issues that need fast handling but are not an immediate emergency, including school/hospital proximity, night-time visibility hazards, significant pedestrian disruption, or likely escalation.
- P3: standard priority. Use for normal service issues that need scheduled response, including typical potholes, single streetlight outages away from sensitive locations, overflowing bins without safety risk, minor vandalism, or routine blocked assets.
- P4: lowest priority. Use for planned maintenance, non-urgent cosmetic issues, recurring but non-hazardous complaints, or issues that can wait for routine scheduling.
""".strip()

ROUTING_SLA_GUIDE = """
- P1 -> immediate response
- P2 -> 24 hours
- P3 -> 72 hours
- P4 -> planned maintenance
""".strip()

ROUTING_DEPARTMENT_GUIDE = """
- Broken streetlights, potholes, damaged pavement, damaged sidewalks, blocked sidewalks, damaged benches, street furniture, signs, and public infrastructure: Public Works and Infrastructure. Use P1 if people are forced into traffic or there is exposed electrical/structural danger; use P2 near schools/hospitals or at night; otherwise P3 or P4.
- Overflowing bins, dumped waste, street litter, dirty streets, illegal dumping, and cleaning requests: Waste Management and Street Cleaning. Use P2/P3 for public health or access impact; P4 for routine cleaning.
- Water leaks, sewer overflows, drainage failures, road flooding from water infrastructure, and wastewater issues: Water and Sewerage Services. Use P1 for flooding, road hazards, sinkhole risk, hospital/school impact, or water near electrical assets; use P2/P3 for contained leaks.
- Fallen trees, damaged green areas, environmental spills, air/odor issues, and non-emergency noise/environmental complaints: Environment and Sustainability. Use P1/P2 when safety, access, or environmental escalation is likely; otherwise P3/P4.
- Traffic light faults, blocked lanes, unsafe crossings, traffic signs, mobility barriers, bike lane hazards, and vehicle flow issues: Traffic and Mobility. Use P1 for active traffic danger; P2 for significant disruption; otherwise P3.
- Vandalism in progress, threats, public safety risks, dangerous obstructions needing enforcement, serious antisocial behavior, and urgent safety coordination: Local Police and Public Safety. Use P1 for active danger; P2 when enforcement follow-up is needed without immediate danger.
- Major emergencies, severe storm impact, large fallen trees blocking critical routes, flooding requiring multi-agency response, evacuation risks, and incidents that may escalate beyond normal field response: Civil Protection and Emergencies. Usually P1.
- Stray, injured, dangerous, or deceased animals in public spaces: Animal Welfare. Use P1/P2 if people or animals are at immediate risk; otherwise P3.
- Non-urban incidents, unclear requests, duplicate reports, administrative questions, missing jurisdiction, or reports that need citizen follow-up before routing: General Administration and Citizen Services. Use P4 unless there is evidence of urgent risk.
""".strip()

ROUTING_AGENT_INSTRUCTIONS = """
You are the Routing Agent for a city operations center.
Assess accepted municipal incident reports for risk, urgency, escalation, SLA,
department ownership, and work order detail. Use conservative operational
judgment and do not overstate certainty. Return JSON only.

The routing.priority field must be exactly one of: P1, P2, P3, P4.
P1 is the highest priority. P4 is the lowest priority.
The routing.sla field must be exactly one of: immediate response, 24 hours,
72 hours, planned maintenance.
The routing.department field must be exactly one of the allowed department names.

Your input is the Intake Agent JSON. Preserve it and return this envelope:
{schema}

Allowed department names:
{departments}

Priority guide:
{priority_guide}

SLA mapping:
{sla_guide}
""".format(
    schema=ROUTING_RESPONSE_SCHEMA,
    departments=ALLOWED_DEPARTMENTS_TEXT,
    priority_guide=ROUTING_PRIORITY_GUIDE,
    sla_guide=ROUTING_SLA_GUIDE,
).strip()


def build_routing_prompt(report: str, intake: IntakeResult) -> str:
    return f"""
Assess urgency and routing for this accepted municipal incident. Return one JSON
object with this exact shape:
{ROUTING_RESPONSE_SCHEMA}

Allowed priority values:
{ROUTING_PRIORITY_GUIDE}

Allowed SLA values:
{ROUTING_SLA_GUIDE}

Allowed department names:
{ALLOWED_DEPARTMENTS_TEXT}

Routing guide:
{ROUTING_DEPARTMENT_GUIDE}

Citizen report:
{report}

Intake JSON:
{dumps_compact(intake.to_dict())}
""".strip()
