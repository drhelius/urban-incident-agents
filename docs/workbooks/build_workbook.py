#!/usr/bin/env python3
"""Generate the "Urban Incident Triage — Operations" Azure Monitor workbook.

Writes two canonical, version-controlled artifacts next to this script:

* ``incident-operations.workbook``       — portal-importable workbook content.
* ``incident-operations.template.json``  — ARM template for repeatable deploys.

The committed artifacts are deliberately free of any subscription or resource
identifiers: the App Insights binding is emitted as the ``<APPINSIGHTS_RESOURCE_ID>``
placeholder and substituted at deploy time by ``deploy.sh`` (which resolves the
real resource id from your current Azure context). The presentation-only values
below can still be overridden:

    WORKBOOK_LOCATION      Azure region for the workbook resource
    WORKBOOK_DISPLAY_NAME  display name shown in the Workbooks gallery

Run ``python3 build_workbook.py`` after editing, then ``./deploy.sh`` to publish.
"""
from __future__ import annotations

import json
import os
import pathlib
import uuid

HERE = pathlib.Path(__file__).resolve().parent

# Placeholder only — never a real resource id. ``deploy.sh`` swaps this for the
# resource id it resolves at runtime, so nothing environment-specific is ever
# written to the committed workbook (safe for a public repository).
APPI_ID = "<APPINSIGHTS_RESOURCE_ID>"
LOCATION = os.environ.get("WORKBOOK_LOCATION", "swedencentral")
DISPLAY_NAME = os.environ.get("WORKBOOK_DISPLAY_NAME", "Urban Incident Triage — Operations")

# Deterministic GUID so re-deploys update the same workbook instead of duplicating.
WORKBOOK_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "urban-incident-operations-dashboard"))


def text(name: str, markdown: str) -> dict:
    return {"type": 1, "content": {"json": markdown}, "name": name}


def query(
    name: str,
    title: str,
    kql: str,
    visualization: str,
    *,
    width: str | None = None,
    extra_content: dict | None = None,
) -> dict:
    content = {
        "version": "KqlItem/1.0",
        "query": kql,
        "size": 0,
        "title": title,
        "timeContext": {"durationMs": 0},
        "timeContextFromParameter": "TimeRange",
        "queryType": 0,
        "resourceType": "microsoft.insights/components",
        "crossComponentResources": [APPI_ID],
        "visualization": visualization,
    }
    if extra_content:
        content.update(extra_content)
    item = {"type": 3, "content": content, "name": name}
    if width:
        item["customWidth"] = width
    return item


M = '| where name == "urban_incident.reports"'

kpi_kql = f"""customMetrics
{M}
| extend status = tostring(customDimensions.status)
| summarize Total = sum(valueSum), Accepted = sumif(valueSum, status == "accepted")
| extend Rejected = Total - Accepted
| extend Rate = iff(Total > 0, round(100.0 * Accepted / Total, 1), 0.0)
| project Names = dynamic(["Total Reports", "Accepted", "Rejected", "Acceptance %"]),
          Vals = pack_array(Total, Accepted, Rejected, Rate)
| mv-expand Metric = Names to typeof(string), Value = Vals to typeof(real)
| project Metric, Value"""

priority_kql = f"""customMetrics
{M}
| extend Priority = tostring(customDimensions.priority)
| summarize Reports = sum(valueSum) by Priority
| order by Priority asc"""

status_kql = f"""customMetrics
{M}
| extend Status = tostring(customDimensions.status)
| summarize Reports = sum(valueSum) by Status
| order by Reports desc"""

dept_kql = f"""customMetrics
{M}
| extend Department = tostring(customDimensions.department)
| summarize Reports = sum(valueSum) by Department
| order by Reports desc"""

time_kql = f"""customMetrics
{M}
| extend Priority = tostring(customDimensions.priority)
| summarize Reports = sum(valueSum) by bin(timestamp, 1h), Priority
| order by timestamp asc"""

matrix_kql = f"""customMetrics
{M}
| extend Priority = tostring(customDimensions.priority),
         Department = tostring(customDimensions.department)
| summarize Reports = sum(valueSum) by Department, Priority
| evaluate pivot(Priority, sum(Reports), Department)
| order by Department asc"""

agents_kql = """dependencies
| where name startswith "invoke_agent "
| extend Agent = tostring(substring(name, 13))
| where Agent startswith "municipal-incident-"
| summarize Invocations = count() by Agent
| order by Invocations desc"""

latency_kql = """dependencies
| where name == "api.triage_incident"
| summarize ["p50 (ms)"] = percentile(duration, 50),
            ["p95 (ms)"] = percentile(duration, 95)
            by bin(timestamp, 30m)
| order by timestamp asc"""

tile_settings = {
    "chartSettings": {},
    "tileSettings": {
        "titleContent": {"columnMatch": "Metric", "formatter": 1},
        "leftContent": {
            "columnMatch": "Value",
            "formatter": 12,
            "formatOptions": {"palette": "blue"},
        },
        "showBorder": True,
        "size": "auto",
    },
}

pie_settings = {"chartSettings": {"showLegend": True}}

header_md = (
    "# 🏙️ Urban Incident Triage — Operations\n"
    "End-to-end view of municipal incident reports processed by the Intake → Routing → "
    "Notification agent pipeline. Volume, acceptance, priority and department breakdowns are "
    "derived from the `urban_incident.reports` custom metric. Use the time range selector to "
    "scope every tile below."
)

ops_md = (
    "## ⚙️ Pipeline health\n"
    "Agent activity and end-to-end processing latency for the orchestrated workflow."
)

content = {
    "version": "Notebook/1.0",
    "items": [
        text("text-header", header_md),
        {
            "type": 9,
            "content": {
                "version": "KqlParameterItem/1.0",
                "parameters": [
                    {
                        "id": "time-range-param",
                        "version": "KqlParameterItem/1.0",
                        "name": "TimeRange",
                        "label": "Time range",
                        "type": 4,
                        "isRequired": True,
                        "typeSettings": {
                            "selectableValues": [
                                {"durationMs": 3600000},
                                {"durationMs": 14400000},
                                {"durationMs": 86400000},
                                {"durationMs": 604800000},
                                {"durationMs": 2592000000},
                            ],
                            "allowCustom": True,
                        },
                        "value": {"durationMs": 604800000},
                    }
                ],
                "style": "pills",
                "queryType": 0,
            },
            "name": "params-time-range",
        },
        query("kpi-tiles", "Report volume", kpi_kql, "tiles", extra_content=tile_settings),
        query(
            "reports-by-priority",
            "Reports by priority",
            priority_kql,
            "piechart",
            width="50",
            extra_content=pie_settings,
        ),
        query(
            "reports-by-status",
            "Accepted vs rejected",
            status_kql,
            "piechart",
            width="50",
            extra_content=pie_settings,
        ),
        query("reports-by-department", "Reports by department", dept_kql, "barchart"),
        query("reports-over-time", "Report volume over time (by priority)", time_kql, "timechart"),
        query("priority-department-matrix", "Priority × department breakdown", matrix_kql, "table"),
        text("text-pipeline-health", ops_md),
        query(
            "agent-invocations",
            "Agent invocations",
            agents_kql,
            "barchart",
            width="50",
        ),
        query(
            "processing-latency",
            "End-to-end processing latency",
            latency_kql,
            "timechart",
            width="50",
        ),
    ],
    "isLocked": False,
    "fallbackResourceIds": [APPI_ID],
    "$schema": (
        "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/"
        "schema/workbook.json"
    ),
}

arm_template = {
    "$schema": (
        "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
    ),
    "contentVersion": "1.0.0.0",
    "parameters": {
        "workbookDisplayName": {"type": "string"},
        "workbookId": {"type": "string", "defaultValue": WORKBOOK_ID},
        "workbookSourceId": {"type": "string"},
        "location": {"type": "string"},
        "serializedData": {"type": "string"},
    },
    "resources": [
        {
            "type": "microsoft.insights/workbooks",
            "apiVersion": "2022-04-01",
            "name": "[parameters('workbookId')]",
            "location": "[parameters('location')]",
            "kind": "shared",
            "properties": {
                "displayName": "[parameters('workbookDisplayName')]",
                "serializedData": "[parameters('serializedData')]",
                "version": "1.0",
                "sourceId": "[parameters('workbookSourceId')]",
                "category": "workbook",
            },
        }
    ],
    "outputs": {
        "workbookResourceId": {
            "type": "string",
            "value": "[resourceId('microsoft.insights/workbooks', parameters('workbookId'))]",
        }
    },
}


def main() -> None:
    workbook_path = HERE / "incident-operations.workbook"
    template_path = HERE / "incident-operations.template.json"
    workbook_path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    template_path.write_text(json.dumps(arm_template, indent=2) + "\n", encoding="utf-8")
    print(f"workbook -> {workbook_path}")
    print(f"template -> {template_path}")
    print(f"workbookId(GUID) -> {WORKBOOK_ID}")
    print(f"items: {len(content['items'])}")


if __name__ == "__main__":
    main()
