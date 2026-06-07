from __future__ import annotations

from incident_core.json_utils import dumps_compact
from incident_core.models import IntakeResult, RoutingResult

NOTIFICATION_AGENT_INSTRUCTIONS = """
You are the Notification Agent for a municipal service desk.
Write concise, friendly citizen-facing responses that explain classification,
priority, routing, next steps, and missing information. Avoid promises about
exact completion and do not invent ticket IDs. Return JSON only.

The notification.message field is mandatory and must be non-empty. It must be a
simple natural-language prose response for the citizen. Do not use markdown,
labels, headings, bullets, numbered lists, tables, or section names. Do not place
the citizen response only in classification, priority, routing, or next_steps
fields.

Your input is the Routing Agent envelope containing intake and routing objects.
Return the final workflow envelope:
{
  "correlation_id": "...copy from input when present...",
  "status": "accepted | rejected",
  "intake": { ...intake JSON... },
  "routing": { ...routing JSON... },
  "notification": { ...notification JSON... }
}
""".strip()


def build_notification_prompt(report: str, intake: IntakeResult, routing: RoutingResult) -> str:
    return f"""
Create a citizen-facing response. Return one JSON object with this exact shape:
{{
  "correlation_id": "copy from input when present, otherwise empty string",
  "status": "accepted | rejected",
  "intake": {{ ...the provided intake JSON... }},
  "routing": {{ ...the provided routing JSON... }},
  "notification": {{
    "message": "required non-empty simple prose response to the citizen",
    "needs_more_information": false,
    "requested_information": ["specific details still needed"]
  }}
}}

Rules:
- Explain what happened with the incident in a simple way: what it was classified as, priority, responsible department, expected next step, and any useful missing detail.
- Final message must be concise, citizen-friendly prose in one short paragraph.
- Do not use markdown syntax.
- If the report is not an urban incident, politely say it cannot be handled by this municipal incident service.
- Mention missing details only when they affect follow-up.
- Avoid promising exact repair or completion times.
- Always populate notification.message even if you also include other notification fields.

Citizen report:
{report}

Intake JSON:
{dumps_compact(intake.to_dict())}

Routing JSON:
{dumps_compact(routing.to_dict())}
""".strip()
