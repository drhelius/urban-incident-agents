# Urban Incident Agents

Municipal incident triage and routing built with Python, Microsoft Agent Framework, Microsoft Foundry hosted agents, Streamlit, FastAPI, and Azure Container Apps.

## Folder Layout

```text
frontend/                     Streamlit web form
agents/
  orchestrator/               FastAPI bridge plus hosted coordinator agent
                              WorkflowBuilder orchestration, Dockerfiles, ACA/Foundry config, env example
  municipal-incident-intake/               Intake Agent prompt, entrypoint, Dockerfile, Foundry config
  municipal-incident-routing/              Routing Agent prompt, entrypoint, Dockerfile, Foundry config
  municipal-incident-notification/         Notification Agent prompt, entrypoint, Dockerfile, Foundry config
docs/                         Optional GitHub Actions deployment template
AZURE_SETUP.md                Azure infrastructure and deployment setup guide
```

The root stays intentionally small: project metadata, README, license, and system folders.

## Workflow

```text
frontend -> orchestrator API or hosted orchestrator agent -> Intake Agent -> Routing Agent -> Notification Agent
```

Local development uses real Foundry model calls by default. Copy [agents/orchestrator/env.example](agents/orchestrator/env.example) to `.env` and set your own Foundry project values:

- Foundry project endpoint: `https://<YOUR-RESOURCE>.services.ai.azure.com/api/projects/<YOUR-PROJECT>`
- Model deployment: `gpt-5.4`

The local orchestrator is aligned with the Microsoft Agent Framework agents-in-workflows samples: it builds three `Agent` instances, wraps them with `AgentExecutor(context_mode="last_agent")`, wires them with `WorkflowBuilder`, and can run the full workflow in process for development.

The hosted orchestrator follows the same `WorkflowBuilder` shape, but its nodes are custom `Executor` steps that call `FoundryAgent(...)` references to the separately deployed `municipal-incident-intake`, `municipal-incident-routing`, and `municipal-incident-notification` resources in Foundry. That keeps the three agents separated in the Foundry control plane while still exposing one end-to-end coordinator.

You can run either:

- each independent hosted agent: Intake, Routing, Notification
- the hosted coordinator workflow: Municipal Incident Orchestrator
- the FastAPI bridge for the Streamlit frontend

After the three individual agents are deployed as Foundry hosted agents, set `ORCHESTRATION_BACKEND=hosted` so the FastAPI bridge calls the deployed agents. If you deploy the orchestrator as a Foundry hosted agent, clients can invoke that hosted coordinator directly through Foundry; it calls the same three deployed agents by name.

## Observability

Every agent entrypoint and the orchestrator call [agents/orchestrator/observability.py](agents/orchestrator/observability.py), which enables Agent Framework instrumentation. Foundry hosted agents use the platform telemetry exporters that are injected at runtime. Local and Container Apps frontend/API runs export to Application Insights when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set.

The hosted-agent manifests set `ENABLE_SENSITIVE_DATA=true` for this demo so Foundry traces can show prompt and response details. Set it to `false` before using real citizen data.

## Local Run Options

```bash
cp agents/orchestrator/env.example .env
az login
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,api,frontend,observability]"
```

Install the hosted extra as well when you want to run any `ResponsesHostServer` entrypoint locally:

```bash
pip install -e ".[dev,api,frontend,hosted,observability]"
```

There are four useful ways to run the scenario locally or remotely.

### Option 1: CLI End-to-End Workflow

This is the simplest local end-to-end check. It does not start HTTP servers. The CLI runs the complete `WorkflowBuilder` chain in-process and calls the real Foundry model.

```bash
urban-incidents --pretty "Water leak near City Hospital is flooding the road"
```

Use this when you want to verify the agent flow quickly.

### Option 2: Frontend -> FastAPI -> In-Process Workflow

This is the normal local web-app path. The frontend calls FastAPI on port `8000`. FastAPI runs the orchestrator workflow in-process.

Set:

```bash
ORCHESTRATION_BACKEND=local
```

Start the API:

```bash
uvicorn orchestrator.api:app --reload --host 0.0.0.0 --port 8000
```

Start the frontend in another terminal:

```bash
INCIDENT_API_URL=http://localhost:8000 streamlit run frontend/app.py --server.port 8501
```

Open `http://localhost:8501`.

### Option 3: Frontend -> FastAPI -> Local ResponsesHostServer

This uses two local orchestrator processes and the three deployed Foundry hosted agents:

- [agents/orchestrator/main.py](agents/orchestrator/main.py) runs the hosted-agent-compatible Responses server on port `8088` and coordinates deployed hosted agents.
- FastAPI runs on port `8000` and proxies incident requests to that local Responses endpoint.

Start the local hosted-agent-compatible orchestrator server:

```bash
python -m orchestrator.main
```

It exposes the Responses protocol on `http://localhost:8088/responses`.

In another terminal, start the FastAPI bridge with:

```bash
ORCHESTRATION_BACKEND=local_responses \
LOCAL_ORCHESTRATOR_RESPONSES_URL=http://localhost:8088/responses \
uvicorn orchestrator.api:app --reload --host 0.0.0.0 --port 8000
```

Then start the frontend:

```bash
INCIDENT_API_URL=http://localhost:8000 streamlit run frontend/app.py --server.port 8501
```

Use this when you want the local web app to exercise the same Responses protocol shape used by Foundry Hosted Agents while still keeping Intake, Routing, and Notification as separate Foundry resources.

### Option 4: Frontend -> FastAPI -> Deployed Foundry Hosted Agents

This is the distributed hosted-agent path. FastAPI calls deployed Foundry hosted agents by name through the Foundry project endpoint.

Set:

```bash
ORCHESTRATION_BACKEND=hosted
INTAKE_AGENT_NAME=municipal-incident-intake
ROUTING_AGENT_NAME=municipal-incident-routing
NOTIFICATION_AGENT_NAME=municipal-incident-notification
```

Then run the API and frontend as in Option 2.

Use this after the three independent hosted agents are deployed to Foundry.

### Direct Hosted Orchestrator Invocation

The orchestrator itself can also be deployed or run as a Foundry hosted coordinator agent. In that case, clients can call its Responses endpoint directly and do not need the FastAPI bridge unless they want the Streamlit web UI or the `/api/incidents` API shape. The deployed orchestrator expects the three independent hosted agents to exist in the same Foundry project.

## Hosted Agent Entry Points

Each hosted agent has its own code folder:

- [agents/municipal-incident-intake](agents/municipal-incident-intake)
- [agents/municipal-incident-routing](agents/municipal-incident-routing)
- [agents/municipal-incident-notification](agents/municipal-incident-notification)
- [agents/orchestrator](agents/orchestrator)

Each agent folder owns its prompt, `main.py`, `Dockerfile`, `requirements.txt`, and `agent.yaml`.
The orchestrator owns the same hosted-agent assets plus `Dockerfile.hosted` for Foundry hosted-agent deployment and `Dockerfile` for the FastAPI bridge. Its hosted entrypoint coordinates deployed agents; the CLI and local API mode still support an in-process workflow for development.

## API

```bash
curl -sS -X POST http://localhost:8000/api/incidents \
  -H "Content-Type: application/json" \
  -d '{"report":"Broken streetlight near Pine Street school crossing and it is very dark at night"}'
```

The response has this shape:

```json
{
  "status": "accepted",
  "correlation_id": "inc-...",
  "intake": {},
  "routing": {},
  "notification": {}
}
```

## Deployment

See [AZURE_SETUP.md](AZURE_SETUP.md) for Azure CLI commands covering ACR, Foundry hosted agents, ACA, identities, and RBAC.