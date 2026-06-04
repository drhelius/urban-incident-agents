from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from orchestrator.config import get_settings
from orchestrator.observability import configure_observability, trace_span
from orchestrator.service import process_incident_report

configure_observability()

app = FastAPI(
    title="Urban Incident Triage API",
    version="0.1.0",
    description="Sequential Intake Agent, Routing Agent, and Notification Agent API.",
)


class IncidentRequest(BaseModel):
    report: str = Field(min_length=1, max_length=4000)


class IncidentResponse(BaseModel):
    status: str
    correlation_id: str
    intake: dict[str, Any]
    routing: dict[str, Any]
    notification: dict[str, Any]


@app.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    return {"status": "healthy", "config": settings.sanitized()}


@app.post("/api/incidents", response_model=IncidentResponse)
async def triage_incident(request: IncidentRequest) -> dict[str, Any]:
    with trace_span(
        "api.triage_incident",
        {
            "urban_incident.component": "orchestrator-api",
            "urban_incident.report.length": len(request.report),
        },
    ):
        try:
            result = await process_incident_report(request.report)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Incident workflow failed: {exc}") from exc
        return result.to_dict()


@app.post("/triage", response_model=IncidentResponse)
async def triage_alias(request: IncidentRequest) -> dict[str, Any]:
    return await triage_incident(request)
