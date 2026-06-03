from __future__ import annotations

import asyncio
import html
import os
from typing import Any

import httpx
import streamlit as st

from orchestrator.observability import configure_observability, inject_trace_context, trace_span

API_URL = os.getenv("INCIDENT_API_URL", "http://localhost:8000").rstrip("/")
configure_observability()


def humanize(value: Any) -> str:
    text = str(value or "")
    return text.replace("_", " ").replace("-", " ").strip().title() or "Not Provided"


def as_text_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def render_response_message(message: str) -> None:
    safe_message = html.escape(message)
    st.markdown(
        f"""
        <div class="citizen-response" role="status">
            <div class="citizen-response__label">Response for citizen</div>
            <div class="citizen-response__message">{safe_message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_summary_table(intake: dict[str, Any], routing: dict[str, Any]) -> None:
    summary_rows = [
        {"Field": "Classification", "Value": humanize(intake.get("incident_type"))},
        {"Field": "Priority", "Value": humanize(routing.get("priority"))},
        {"Field": "Department", "Value": str(routing.get("department") or "Not routed")},
        {"Field": "SLA", "Value": humanize(routing.get("sla"))},
        {"Field": "Location", "Value": str(intake.get("location") or "Location not specified")},
        {
            "Field": "Escalation",
            "Value": "Required" if routing.get("escalation_required") else "Not required",
        },
    ]
    st.dataframe(summary_rows, hide_index=True, width="stretch")


st.markdown(
    """
    <style>
    .citizen-response {
        border: 1px solid rgba(46, 160, 67, 0.45);
        border-left: 5px solid #2ea043;
        border-radius: 6px;
        padding: 1rem 1.1rem;
        margin: 1rem 0 1.25rem;
        background: rgba(46, 160, 67, 0.10);
        color: inherit;
    }
    .citizen-response__label {
        color: #3fb950;
        font-size: 0.85rem;
        font-weight: 700;
        margin-bottom: 0.45rem;
        text-transform: uppercase;
    }
    .citizen-response__message {
        color: inherit;
        font-size: 1rem;
        line-height: 1.55;
        white-space: pre-wrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


async def submit_report(report: str) -> dict[str, Any]:
    with trace_span(
        "frontend.submit_incident",
        {
            "http.url": f"{API_URL}/api/incidents",
            "urban_incident.component": "frontend",
        },
    ):
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{API_URL}/api/incidents",
                json={"report": report},
                headers=inject_trace_context(),
            )
            response.raise_for_status()
            return response.json()


def run_submit(report: str) -> dict[str, Any]:
    try:
        return asyncio.run(submit_report(report))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(submit_report(report))
        finally:
            loop.close()


st.set_page_config(page_title="Municipal Incident Report", page_icon="cityscape", layout="centered")
st.title("Municipal Incident Report")

report = st.text_area(
    "Report",
    placeholder="Broken streetlight near 4th Avenue and Pine Street, close to the school crossing.",
    height=80,
    label_visibility="collapsed",
)

submitted = st.button("Send report", type="primary", width="stretch")

if submitted:
    if not report.strip():
        st.warning("Add a report before sending.")
    else:
        with st.spinner("Assessing report"):
            try:
                result = run_submit(report.strip())
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text
                st.error(f"The service could not process the report. {detail}")
            except httpx.HTTPError as exc:
                st.error(f"The service is not reachable at {API_URL}. {exc}")
            else:
                response = result.get("notification", {})
                intake = result.get("intake", {})
                routing = result.get("routing", {})
                message = response.get("message")
                if not message:
                    st.error("Notification Agent did not return notification.message.")
                    st.stop()
                render_response_message(str(message))

                st.subheader("Case summary")
                render_summary_table(intake, routing)

                if response.get("needs_more_information"):
                    details = as_text_list(response.get("requested_information"))
                    if details:
                        st.info("Requested details: " + ", ".join(details))

                with st.expander("Operational details"):
                    st.json(result)
