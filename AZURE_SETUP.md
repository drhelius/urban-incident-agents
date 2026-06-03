# Azure Setup

This is the deployment runbook for the Urban Incident Agents scenario.

It covers two deployment targets:

1. **Foundry Hosted Agents** for the orchestrator workflow and the three independent agents.
2. **Azure Container Apps** for the Streamlit frontend and FastAPI bridge.

The flow follows the Microsoft Hosted Agents lifecycle:

```text
Build image -> Push to ACR -> Create hosted-agent version -> Wait until active -> Invoke
```

It also follows a common Container Apps pattern: create Azure resources, build images in ACR, configure managed identity pull access, and deploy with Container App YAML descriptors.

## Step 1: Set Variables

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

IMAGE_TAG=$(date +%Y%m%d%H%M%S)

# Optional. Leave empty if you do not want ACA-side OTEL export.
APPLICATIONINSIGHTS_CONNECTION_STRING=""
```

ACR names must be globally unique and can contain only lowercase letters and numbers.

## Step 2: Prepare Azure CLI

```bash
az login
az upgrade
az extension add --name containerapp --upgrade --allow-preview true

azd auth login
azd ext install azure.ai.agents

az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ContainerRegistry
```

## Step 3: Create Resource Group, ACR, and ACA Environment

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
  --location "$LOCATION"

ACR_ID=$(az acr show --name "$ACR_NAME" --resource-group "$APP_RG" --query id -o tsv)
ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --resource-group "$APP_RG" --query loginServer -o tsv)
```

## Step 4: Grant ACR Build Permissions to Your User

Because the ACR uses `rbac-abac`, ACR quick builds must use `--source-acr-auth-id "[caller]"`, and your signed-in identity needs repository permissions.

```bash
CALLER_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null)

# If signed-in-user is empty, you are likely using a service principal or managed identity.
# In that case, use the current account name/appId as the assignee.
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

## Step 5: Configure azd for Hosted Agents

If you already built images manually with `az acr build`, that is okay. You can leave those images in ACR. The `azd deploy` path below will build and push its own image versions using the `IMAGE_TAG` value configured in azd. To avoid overwriting a manually built tag, set a fresh `IMAGE_TAG` before running `azd deploy`.

The repository includes a root [azure.yaml](azure.yaml) with four `azure.ai.agent` services:

| azd service | Folder | Agent |
| --- | --- | --- |
| `municipal-incident-orchestrator` | `orchestrator/` | Hosted coordinator workflow |
| `intake-agent` | `agents/intake-agent/` | Intake Agent |
| `routing-agent` | `agents/routing-agent/` | Routing Agent |
| `notification-agent` | `agents/notification-agent/` | Notification Agent |

Each service folder contains an `agent.yaml` that uses the current `azd` hosted-agent schema: top-level `kind: hosted`, `name`, `protocols`, `resources`, and `environment_variables`.

Bind azd to the existing tenant, subscription, region, Foundry project, model deployment, and ACR:

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

If you want to reuse manually built images instead of letting `azd deploy` build again, keep the image tag aligned with the service's `agent.yaml` and deploy path. For this demo, the recommended path is `azd deploy` for all four hosted agents.

## Step 6: Allow Foundry to Pull Hosted-Agent Images

The Foundry project managed identity must be able to pull hosted-agent images from ACR. In this registry, `roleAssignmentMode` is `AbacRepositoryPermissions`, so use the ABAC-compatible ACR roles.

Resolve the Foundry project managed identity:

```bash
FOUNDRY_PROJECT_PRINCIPAL_ID=$(az resource show \
  --ids "$FOUNDRY_PROJECT_ID" \
  --query identity.principalId -o tsv)
```

Grant ACR pull permissions:

```bash
for ROLE in \
  "Container Registry Repository Reader" \
  "Container Registry Repository Catalog Lister"; do
  az role assignment create \
    --assignee "$FOUNDRY_PROJECT_PRINCIPAL_ID" \
    --role "$ROLE" \
    --scope "$ACR_ID"
done
```

If `azd deploy` still reports image pull authorization errors immediately after this step, wait a minute for RBAC propagation and retry the deploy.

## Step 7: Deploy Hosted Agents to Foundry with azd

Deploy these four hosted-agent services from [azure.yaml](azure.yaml). Deploy the three worker agents before the orchestrator because the hosted orchestrator calls them by Foundry agent name.

- `intake-agent`
- `routing-agent`
- `notification-agent`
- `municipal-incident-orchestrator`

The azd extension reads each service folder's `agent.yaml`, builds the configured Dockerfile, pushes the image to ACR, and creates a Foundry hosted-agent version. The exact pushed image name is managed by azd and printed in the deploy output.

Deploy all hosted-agent services:

```bash
azd deploy intake-agent
azd deploy routing-agent
azd deploy notification-agent
azd deploy municipal-incident-orchestrator
```

Or deploy one service while iterating:

```bash
azd deploy intake-agent
```

`azd deploy` builds the container image, pushes it to ACR, creates a hosted-agent version in Foundry Agent Service, waits for provisioning, and prints the hosted-agent playground/endpoint details.

`AZURE_AI_MODEL_DEPLOYMENT_NAME` is declared in the hosted-agent definitions. The orchestrator definition also declares the worker agent names it calls: `INTAKE_AGENT_NAME`, `ROUTING_AGENT_NAME`, and `NOTIFICATION_AGENT_NAME`.

Foundry injects these platform values automatically at runtime:

- `FOUNDRY_PROJECT_ENDPOINT`
- `APPLICATIONINSIGHTS_CONNECTION_STRING`
- hosted-agent name/version/session values

If `azd deploy` reports ACR pull or role-assignment failures, verify that your account has Foundry Project Manager at project scope plus enough Azure RBAC permission to assign roles, or ask an administrator to grant the hosted-agent permissions described in the Microsoft Hosted Agents documentation.

## Step 8: Verify Hosted Agents with azd

After each version is active, invoke it with azd. Check the worker agents first:

```bash
azd ai agent invoke intake-agent "Water leak near City Hospital is flooding the road"
azd ai agent invoke routing-agent "<paste Intake Agent JSON here>"
azd ai agent invoke notification-agent "<paste Routing Agent envelope JSON here>"
```

Then invoke the full coordinator workflow:

```bash
azd ai agent invoke municipal-incident-orchestrator "Water leak near City Hospital is flooding the road"
```

You can also monitor logs for a selected service:

```bash
azd ai agent monitor municipal-incident-orchestrator --follow
```

## Step 9: Configure End-to-End Observability

The Streamlit frontend, FastAPI bridge, local Responses server path, deployed hosted-agent client path, and hosted agents are all OTEL-instrumented.

To see one connected trace in Foundry/Application Insights, use the same Application Insights resource for every component:

- Foundry Hosted Agents receive `APPLICATIONINSIGHTS_CONNECTION_STRING` automatically from the platform.
- The FastAPI Container App receives it through `orchestrator/containerapp.yaml`.
- The Streamlit frontend receives it through `frontend/containerapp.yaml`.

The hosted-agent manifests also set:

- `ENABLE_INSTRUMENTATION=true` so Agent Framework emits spans and metrics.
- `ENABLE_SENSITIVE_DATA=true` so demo traces include prompt and response details. Set it to `false` before using real citizen data.
- `OTEL_SERVICE_NAME=<agent-name>` so Azure Monitor and Foundry group telemetry by agent.
- `OTEL_TRACES_SAMPLER=always_on` so demo invocations are not sampled out.

The app propagates W3C trace context from:

```text
Streamlit -> FastAPI -> local Responses server or deployed Foundry hosted agents
```

Foundry can show a complete span tree when all components export to the same Application Insights resource and the gateway preserves the `traceparent` header.

## Step 10: Build ACA Images

These images are for Azure Container Apps:

- FastAPI bridge: `orchestrator/Dockerfile`
- Streamlit frontend: `frontend/Dockerfile`

```bash
az acr build \
  --registry "$ACR_NAME" \
  --image urban-incidents-orchestrator:$IMAGE_TAG \
  --platform linux/amd64 \
  --source-acr-auth-id "[caller]" \
  --file orchestrator/Dockerfile \
  .

az acr build \
  --registry "$ACR_NAME" \
  --image urban-incidents-frontend:$IMAGE_TAG \
  --platform linux/amd64 \
  --source-acr-auth-id "[caller]" \
  --file frontend/Dockerfile \
  .
```

## Step 11: Create ACA Apps with Managed Identity

Create placeholder apps first. This lets you assign managed identities before deploying the final private ACR images.

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

Capture identity principal IDs:

```bash
ACA_ORCHESTRATOR_PRINCIPAL_ID=$(az containerapp identity show \
  --name "$ACA_ORCHESTRATOR_NAME" \
  --resource-group "$APP_RG" \
  --query principalId -o tsv)

ACA_FRONTEND_PRINCIPAL_ID=$(az containerapp identity show \
  --name "$ACA_FRONTEND_NAME" \
  --resource-group "$APP_RG" \
  --query principalId -o tsv)
```

Grant ACR pull roles to both Container Apps:

```bash
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
```

Configure each app to pull from ACR with its managed identity:

```bash
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

## Step 12: Allow the ACA Orchestrator to Call Foundry

The FastAPI bridge calls Foundry when `ORCHESTRATION_BACKEND=hosted`, so its managed identity needs `Foundry User`.

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

If the Foundry account is not in `$APP_RG`, set the correct resource group before running the command.

## Step 13: Deploy ACA YAML

Prepare and apply the orchestrator Container App descriptor:

```bash
cp orchestrator/containerapp.yaml /tmp/containerapp-orchestrator.yaml

sed -i "s/{acr-name}/$ACR_NAME/g" /tmp/containerapp-orchestrator.yaml
sed -i "s/{image-tag}/$IMAGE_TAG/g" /tmp/containerapp-orchestrator.yaml
sed -i "s|{foundry-project-endpoint}|$FOUNDRY_PROJECT_ENDPOINT|g" /tmp/containerapp-orchestrator.yaml
sed -i "s|{model-deployment-name}|$AZURE_AI_MODEL_DEPLOYMENT_NAME|g" /tmp/containerapp-orchestrator.yaml
sed -i "s|{application-insights-connection-string}|$APPLICATIONINSIGHTS_CONNECTION_STRING|g" /tmp/containerapp-orchestrator.yaml

az containerapp update \
  --name "$ACA_ORCHESTRATOR_NAME" \
  --resource-group "$APP_RG" \
  --yaml /tmp/containerapp-orchestrator.yaml
```

Get the orchestrator URL:

```bash
ORCHESTRATOR_FQDN=$(az containerapp show \
  --name "$ACA_ORCHESTRATOR_NAME" \
  --resource-group "$APP_RG" \
  --query properties.configuration.ingress.fqdn -o tsv)

ORCHESTRATOR_URL="https://$ORCHESTRATOR_FQDN"
```

Prepare and apply the frontend Container App descriptor:

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

## Step 14: Verify ACA Deployment

Get the frontend URL:

```bash
FRONTEND_FQDN=$(az containerapp show \
  --name "$ACA_FRONTEND_NAME" \
  --resource-group "$APP_RG" \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "Frontend: https://$FRONTEND_FQDN"
echo "API health: $ORCHESTRATOR_URL/health"
```

Check logs if needed:

```bash
az containerapp logs show \
  --name "$ACA_ORCHESTRATOR_NAME" \
  --resource-group "$APP_RG" \
  --follow
```

## Optional: GitHub Actions

The optional workflow template is:

```text
docs/deploy-aca.yml
```

Copy it to:

```text
.github/workflows/deploy-aca.yml
```

Configure these repository secrets:

| Secret | Value |
| --- | --- |
| `AZURE_CREDENTIALS` | Service principal JSON for Azure login |
| `ACR_NAME` | ACR name without `.azurecr.io` |
| `ACA_RG` | Resource group name |
| `ACA_ENV_NAME` | Container Apps environment name |
| `ACA_ORCHESTRATOR_NAME` | FastAPI Container App name |
| `ACA_FRONTEND_NAME` | Streamlit Container App name |
| `INCIDENT_API_URL` | Public URL of the FastAPI orchestrator |
