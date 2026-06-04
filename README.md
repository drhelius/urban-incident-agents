# Urban Incident Agents

Municipal incident triage app with a Streamlit frontend, FastAPI API, Microsoft Agent Framework, Microsoft Foundry hosted worker agents, and Azure Container Apps.

## 1. Install Local Dependencies

```bash
cp agents/orchestrator/env.example .env
az login
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,api,frontend,hosted,observability]"
```

Set `.env`:

```bash
FOUNDRY_PROJECT_ENDPOINT=https://<foundry-account-name>.services.ai.azure.com/api/projects/<foundry-project-name>
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-5.4
ORCHESTRATION_BACKEND=local
APPLICATIONINSIGHTS_CONNECTION_STRING=<foundry-app-insights-connection-string>
INTAKE_AGENT_NAME=municipal-incident-intake
ROUTING_AGENT_NAME=municipal-incident-routing
NOTIFICATION_AGENT_NAME=municipal-incident-notification
```

## 2. Run Local CLI

```bash
ORCHESTRATION_BACKEND=local \
urban-incidents --pretty "Water leak near City Hospital is flooding the road"
```

## 3. Run Local API And Frontend

Terminal 1:

```bash
ORCHESTRATION_BACKEND=local \
uvicorn orchestrator.api:app --reload --host 0.0.0.0 --port 8000
```

Terminal 2:

```bash
INCIDENT_API_URL=http://localhost:8000 \
streamlit run frontend/app.py --server.port 8501
```

Open:

```text
http://localhost:8501
```

## 4. Set Azure Variables

```bash
LOCATION="<azure-region>"
APP_RG="<resource-group>"

ACR_NAME="<acr-name>"
ACA_ENV_NAME="<container-apps-env-name>"
ACA_ORCHESTRATOR_NAME="<orchestrator-container-app-name>"
ACA_FRONTEND_NAME="<frontend-container-app-name>"

FOUNDRY_ACCOUNT_NAME="<foundry-account-name>"
FOUNDRY_PROJECT_NAME="<foundry-project-name>"
FOUNDRY_PROJECT_ENDPOINT="https://<foundry-account-name>.services.ai.azure.com/api/projects/<foundry-project-name>"
FOUNDRY_PROJECT_ID=$(az resource list \
  --resource-type Microsoft.CognitiveServices/accounts/projects \
  --query "[?name=='$FOUNDRY_ACCOUNT_NAME/$FOUNDRY_PROJECT_NAME'].id | [0]" \
  -o tsv)
AZURE_AI_MODEL_DEPLOYMENT_NAME="gpt-5.4"

APP_INSIGHTS_NAME="<foundry-connected-app-insights-name>"
APP_INSIGHTS_RG="$APP_RG"

IMAGE_TAG=$(date +%Y%m%d%H%M%S)
```

## 5. Prepare Azure CLI

```bash
az login
az upgrade
az extension add --name containerapp --upgrade --allow-preview true
az extension add --name application-insights --upgrade

azd auth login
azd ext install azure.ai.agents

az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ContainerRegistry
```

## 6. Create Azure Resources

```bash
az group create \
  --name "$APP_RG" \
  --location "$LOCATION"

az acr create \
  --resource-group "$APP_RG" \
  --name "$ACR_NAME" \
  --sku Standard \
  --location "$LOCATION" \
  --role-assignment-mode rbac-abac

az containerapp env create \
  --name "$ACA_ENV_NAME" \
  --resource-group "$APP_RG" \
  --location "$LOCATION" \
  --logs-destination none

ACR_ID=$(az acr show --name "$ACR_NAME" --resource-group "$APP_RG" --query id -o tsv)
ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --resource-group "$APP_RG" --query loginServer -o tsv)

APPLICATIONINSIGHTS_CONNECTION_STRING=$(az monitor app-insights component show \
  --app "$APP_INSIGHTS_NAME" \
  --resource-group "$APP_INSIGHTS_RG" \
  --query connectionString \
  -o tsv)
```

## 7. Grant ACR Build Access

```bash
CALLER_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null)

if [ -z "$CALLER_OBJECT_ID" ]; then
  CALLER_OBJECT_ID=$(az account show --query user.name -o tsv)
fi

for ROLE in \
  "Container Registry Repository Writer" \
  "Container Registry Repository Reader" \
  "Container Registry Repository Catalog Lister"; do
  az role assignment create \
    --assignee "$CALLER_OBJECT_ID" \
    --role "$ROLE" \
    --scope "$ACR_ID"
done
```

## 8. Configure azd

```bash
azd env new <azd-environment-name>

azd env set AZURE_TENANT_ID "$(az account show --query tenantId -o tsv)"
azd env set AZURE_SUBSCRIPTION_ID "$(az account show --query id -o tsv)"
azd env set AZURE_LOCATION "$LOCATION"
azd env set AZURE_AI_PROJECT_ID "$FOUNDRY_PROJECT_ID"
azd env set AZURE_AI_PROJECT_ENDPOINT "$FOUNDRY_PROJECT_ENDPOINT"
azd env set FOUNDRY_PROJECT_ENDPOINT "$FOUNDRY_PROJECT_ENDPOINT"
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME "$AZURE_AI_MODEL_DEPLOYMENT_NAME"
azd env set AZURE_CONTAINER_REGISTRY_NAME "$ACR_NAME"
azd env set AZURE_CONTAINER_REGISTRY_ENDPOINT "$ACR_LOGIN_SERVER"
azd env set IMAGE_TAG "$IMAGE_TAG"
```

## 9. Grant Foundry ACR Pull Access

```bash
FOUNDRY_PROJECT_PRINCIPAL_ID=$(az resource show \
  --ids "$FOUNDRY_PROJECT_ID" \
  --query identity.principalId -o tsv)

for ROLE in \
  "Container Registry Repository Reader" \
  "Container Registry Repository Catalog Lister"; do
  az role assignment create \
    --assignee "$FOUNDRY_PROJECT_PRINCIPAL_ID" \
    --role "$ROLE" \
    --scope "$ACR_ID"
done
```

## 10. Deploy Foundry Worker Agents

```bash
azd deploy municipal-incident-intake
azd deploy municipal-incident-routing
azd deploy municipal-incident-notification
```

## 11. Verify Foundry Worker Agents

```bash
azd ai agent invoke municipal-incident-intake "Water leak near City Hospital is flooding the road"
azd ai agent invoke municipal-incident-routing "<paste Intake Agent JSON here>"
azd ai agent invoke municipal-incident-notification "<paste Routing Agent envelope JSON here>"
```

## 12. Build ACA Images

```bash
az acr build \
  --registry "$ACR_NAME" \
  --image urban-incidents-orchestrator:$IMAGE_TAG \
  --platform linux/amd64 \
  --source-acr-auth-id "[caller]" \
  --file agents/orchestrator/Dockerfile \
  .

az acr build \
  --registry "$ACR_NAME" \
  --image urban-incidents-frontend:$IMAGE_TAG \
  --platform linux/amd64 \
  --source-acr-auth-id "[caller]" \
  --file frontend/Dockerfile \
  .
```

## 13. Create ACA Apps

```bash
az containerapp create \
  --name "$ACA_ORCHESTRATOR_NAME" \
  --resource-group "$APP_RG" \
  --environment "$ACA_ENV_NAME" \
  --image mcr.microsoft.com/k8se/quickstart:latest \
  --target-port 80 \
  --ingress external \
  --system-assigned

az containerapp create \
  --name "$ACA_FRONTEND_NAME" \
  --resource-group "$APP_RG" \
  --environment "$ACA_ENV_NAME" \
  --image mcr.microsoft.com/k8se/quickstart:latest \
  --target-port 80 \
  --ingress external \
  --system-assigned
```

## 14. Grant ACA ACR Pull Access

```bash
ACA_ORCHESTRATOR_PRINCIPAL_ID=$(az containerapp identity show \
  --name "$ACA_ORCHESTRATOR_NAME" \
  --resource-group "$APP_RG" \
  --query principalId -o tsv)

ACA_FRONTEND_PRINCIPAL_ID=$(az containerapp identity show \
  --name "$ACA_FRONTEND_NAME" \
  --resource-group "$APP_RG" \
  --query principalId -o tsv)

for PRINCIPAL_ID in "$ACA_ORCHESTRATOR_PRINCIPAL_ID" "$ACA_FRONTEND_PRINCIPAL_ID"; do
  az role assignment create \
    --assignee "$PRINCIPAL_ID" \
    --role "Container Registry Repository Reader" \
    --scope "$ACR_ID"

  az role assignment create \
    --assignee "$PRINCIPAL_ID" \
    --role "Container Registry Repository Catalog Lister" \
    --scope "$ACR_ID"
done

az containerapp registry set \
  --name "$ACA_ORCHESTRATOR_NAME" \
  --resource-group "$APP_RG" \
  --server "$ACR_LOGIN_SERVER" \
  --identity system

az containerapp registry set \
  --name "$ACA_FRONTEND_NAME" \
  --resource-group "$APP_RG" \
  --server "$ACR_LOGIN_SERVER" \
  --identity system
```

## 15. Grant ACA Foundry Access

```bash
FOUNDRY_ACCOUNT_ID=$(az cognitiveservices account show \
  --name "$FOUNDRY_ACCOUNT_NAME" \
  --resource-group "$APP_RG" \
  --query id -o tsv)

az role assignment create \
  --assignee "$ACA_ORCHESTRATOR_PRINCIPAL_ID" \
  --role "Foundry User" \
  --scope "$FOUNDRY_ACCOUNT_ID"
```

## 16. Deploy ACA API

```bash
cp agents/orchestrator/containerapp.yaml /tmp/containerapp-orchestrator.yaml

sed -i "s/{acr-name}/$ACR_NAME/g" /tmp/containerapp-orchestrator.yaml
sed -i "s/{image-tag}/$IMAGE_TAG/g" /tmp/containerapp-orchestrator.yaml
sed -i "s|{foundry-project-endpoint}|$FOUNDRY_PROJECT_ENDPOINT|g" /tmp/containerapp-orchestrator.yaml
sed -i "s|{model-deployment-name}|$AZURE_AI_MODEL_DEPLOYMENT_NAME|g" /tmp/containerapp-orchestrator.yaml
sed -i "s|{application-insights-connection-string}|$APPLICATIONINSIGHTS_CONNECTION_STRING|g" /tmp/containerapp-orchestrator.yaml

az containerapp update \
  --name "$ACA_ORCHESTRATOR_NAME" \
  --resource-group "$APP_RG" \
  --yaml /tmp/containerapp-orchestrator.yaml

ORCHESTRATOR_FQDN=$(az containerapp show \
  --name "$ACA_ORCHESTRATOR_NAME" \
  --resource-group "$APP_RG" \
  --query properties.configuration.ingress.fqdn -o tsv)

ORCHESTRATOR_URL="https://$ORCHESTRATOR_FQDN"
```

## 17. Deploy ACA Frontend

```bash
cp frontend/containerapp.yaml /tmp/containerapp-frontend.yaml

sed -i "s/{acr-name}/$ACR_NAME/g" /tmp/containerapp-frontend.yaml
sed -i "s/{image-tag}/$IMAGE_TAG/g" /tmp/containerapp-frontend.yaml
sed -i "s|{api-url}|$ORCHESTRATOR_URL|g" /tmp/containerapp-frontend.yaml
sed -i "s|{application-insights-connection-string}|$APPLICATIONINSIGHTS_CONNECTION_STRING|g" /tmp/containerapp-frontend.yaml

az containerapp update \
  --name "$ACA_FRONTEND_NAME" \
  --resource-group "$APP_RG" \
  --yaml /tmp/containerapp-frontend.yaml
```

## 18. Verify ACA

```bash
FRONTEND_FQDN=$(az containerapp show \
  --name "$ACA_FRONTEND_NAME" \
  --resource-group "$APP_RG" \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "Frontend: https://$FRONTEND_FQDN"
echo "API health: $ORCHESTRATOR_URL/health"

curl -sS "$ORCHESTRATOR_URL/health"
```

## 19. Run Remote Orchestrator Exerciser

```bash
urban-incidents-exerciser \
  --threads 4 \
  --min-seconds 2 \
  --max-seconds 10
```
