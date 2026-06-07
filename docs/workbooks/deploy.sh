#!/usr/bin/env bash
# Deploy the "Urban Incident Triage — Operations" workbook to Azure Monitor.
#
# Builds deployment parameters from the committed .workbook (the source of
# truth), resolves the App Insights resource id from your current Azure context,
# injects it in place of the <APPINSIGHTS_RESOURCE_ID> placeholder, and applies
# the ARM template idempotently. The deterministic workbook GUID means repeated
# runs update the existing workbook instead of creating duplicates.
#
# Nothing environment-specific is committed; override any of these via env vars:
#   RESOURCE_GROUP, APP_INSIGHTS_NAME, APPINSIGHTS_ID, WORKBOOK_LOCATION,
#   WORKBOOK_DISPLAY_NAME, WORKBOOK_ID
set -euo pipefail
cd "$(dirname "$0")"

RESOURCE_GROUP="${RESOURCE_GROUP:-urban-incidents}"
APP_INSIGHTS_NAME="${APP_INSIGHTS_NAME:-urban-incidents}"
WORKBOOK_LOCATION="${WORKBOOK_LOCATION:-swedencentral}"
WORKBOOK_DISPLAY_NAME="${WORKBOOK_DISPLAY_NAME:-Urban Incident Triage — Operations}"
# Deterministic: uuid5(NAMESPACE_URL, "urban-incident-operations-dashboard").
WORKBOOK_ID="${WORKBOOK_ID:-9f78b892-74ca-5442-b944-af52f6b7c81c}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

# Resolve the App Insights resource id from the current Azure context instead of
# hardcoding it, so no subscription / resource identifiers live in the repo.
if [[ -z "${APPINSIGHTS_ID:-}" ]]; then
  echo "Resolving App Insights resource id for '$APP_INSIGHTS_NAME' in '$RESOURCE_GROUP'..."
  APPINSIGHTS_ID="$(az monitor app-insights component show \
    --app "$APP_INSIGHTS_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query id -o tsv)"
fi

if [[ -z "$APPINSIGHTS_ID" ]]; then
  echo "ERROR: could not resolve App Insights resource id. Set APPINSIGHTS_ID or run 'az login'." >&2
  exit 1
fi

PARAMS_FILE="$(mktemp)"
trap 'rm -f "$PARAMS_FILE"' EXIT

echo "Building deployment parameters from incident-operations.workbook..."
WORKBOOK_DISPLAY_NAME="$WORKBOOK_DISPLAY_NAME" \
WORKBOOK_ID="$WORKBOOK_ID" \
APPINSIGHTS_ID="$APPINSIGHTS_ID" \
WORKBOOK_LOCATION="$WORKBOOK_LOCATION" \
  "$PYTHON_BIN" - "$PARAMS_FILE" <<'PY'
import json
import os
import sys

placeholder = "<APPINSIGHTS_RESOURCE_ID>"
appinsights_id = os.environ["APPINSIGHTS_ID"]

with open("incident-operations.workbook", encoding="utf-8") as handle:
    raw = handle.read()

# Inject the real resource id into the committed (placeholder-only) workbook.
serialized = raw.replace(placeholder, appinsights_id)
json.loads(serialized)  # fail fast if substitution broke the JSON

params = {
    "$schema": (
        "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"
    ),
    "contentVersion": "1.0.0.0",
    "parameters": {
        "workbookDisplayName": {"value": os.environ["WORKBOOK_DISPLAY_NAME"]},
        "workbookId": {"value": os.environ["WORKBOOK_ID"]},
        "workbookSourceId": {"value": appinsights_id},
        "location": {"value": os.environ["WORKBOOK_LOCATION"]},
        "serializedData": {"value": serialized},
    },
}

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(params, handle)
PY

echo "Deploying workbook to resource group '$RESOURCE_GROUP'..."
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --name urban-incident-workbook \
  --template-file incident-operations.template.json \
  --parameters @"$PARAMS_FILE" \
  --query "{state:properties.provisioningState, workbook:properties.outputs.workbookResourceId.value}" \
  -o json
