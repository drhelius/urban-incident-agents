# Architecture Overview

## Purpose

Urban Incident Agents is a municipal incident triage system. Citizens submit free-text reports about public-space issues such as streetlights, potholes, fallen trees, blocked sidewalks, water leaks, overflowing bins, vandalism, noise complaints, and traffic hazards.

The system uses a multi-agent workflow to classify the report, assess urgency, route it to the correct municipal department, and generate a clear citizen-facing notification.

## Main Systems

The repository is organized by independently understandable and deployable systems.

### Frontend

The frontend is a Streamlit web form. It exposes a single text area and send button for citizen reports. It does not contain workflow logic. It sends the report to the orchestrator API and displays the final classification, priority, department, citizen message, and operational details.

### Orchestrator

The orchestrator is the system boundary for the complete workflow. It has two roles:

- A FastAPI bridge for the Streamlit frontend.
- A Foundry hosted-agent compatible workflow agent.

The local orchestrator is aligned with the Microsoft Agent Framework agents-in-workflows samples. It can build three Agent Framework agents, wrap them with `AgentExecutor` using last-agent context, and wire them with `WorkflowBuilder` for local development.

The deployed application path uses the FastAPI bridge to call already deployed hosted worker agents directly. That means Intake, Routing, and Notification remain separate Foundry control-plane resources with their own versions, traces, metrics, and cost attribution.

This means the full flow can be run as one deployable orchestrator agent, while the individual agents can also be deployed and invoked independently.

### Intake Agent

The Intake Agent reads the citizen report and extracts operational facts:

- Whether the report is an urban incident.
- Incident type.
- Location.
- Affected public assets.
- Risk indicators.
- Missing details.
- A concise operational summary.

It rejects reports that are not related to municipal urban incidents.

### Routing Agent

The Routing Agent receives the intake output and evaluates urgency and ownership. It determines:

- Priority.
- SLA target.
- Responsible department.
- Escalation requirement.
- Rationale.
- Suggested work order details.

The routing logic considers public safety, traffic and pedestrian impact, sensitive locations such as hospitals and schools, escalation potential, and issue type.

### Notification Agent

The Notification Agent receives the intake and routing outputs and writes the final citizen-facing response. It explains:

- How the report was classified.
- The assigned priority.
- Which department owns the case.
- What the expected next steps are.
- What additional information is needed, if any.

It avoids overpromising and does not invent ticket IDs or completion guarantees.

## Runtime Flow

At a high level, the workflow is:

```text
Citizen -> Frontend -> Orchestrator -> Intake Agent -> Routing Agent -> Notification Agent
```

The response flows back through the orchestrator to the frontend.

The final response object contains:

- Workflow status.
- Correlation ID.
- Intake result.
- Routing result.
- Notification result.

## Deployment Modes

The system supports multiple deployment and execution modes.

### Local Orchestrated Mode

The orchestrator runs locally and creates the three Agent Framework agents in process. Each agent calls the configured Foundry model. This is useful for local development and fast end-to-end testing without deploying the hosted agents.

### Independent Hosted Agents

Each of the three agents can be deployed independently as a Foundry Hosted Agent:

- Intake Agent.
- Routing Agent.
- Notification Agent.

This mode allows each agent to be invoked, scaled, tested, observed, and versioned independently.

### Hosted Coordinator Agent

The orchestrator can also be deployed as a Foundry Hosted Agent for hosted-coordinator experiments. In this mode, the complete workflow is exposed as a single Responses-compatible hosted coordinator. Internally, it calls the deployed Intake, Routing, and Notification hosted agents in sequence through Agent Framework workflow composition.

This mode is optional and is not required for the supported ACA frontend/API deployment path.

### Frontend and API on Azure Container Apps

The Streamlit frontend and FastAPI bridge can be deployed to Azure Container Apps. The FastAPI bridge can either run the workflow itself or call the three deployed worker hosted agents, depending on configuration.

## Foundry Integration

The system uses Microsoft Foundry in three ways:

- Model access through the configured Foundry project and model deployment.
- Hosted-agent deployment through Foundry Agent Service.
- Observability through Application Insights and Foundry Control Plane trace correlation.

The Foundry project endpoint is configured through `FOUNDRY_PROJECT_ENDPOINT`, for example:

```text
https://<YOUR-RESOURCE>.services.ai.azure.com/api/projects/<YOUR-PROJECT>
```

The configured model deployment is:

```text
gpt-5.4
```

## Observability

Each agent entrypoint and the orchestrator configure OpenTelemetry instrumentation. When an Application Insights connection string is provided, traces are exported to the Application Insights resource associated with the Foundry project.

The code emits agent creation spans with generative AI semantic attributes so Foundry Control Plane can correlate traces with registered or hosted agents.

The frontend, FastAPI bridge, and deployed hosted-agent client path use W3C trace-context propagation. The frontend injects trace headers into API calls, and the API injects trace headers into deployed Responses calls. For a complete end-to-end trace, every component should export to the same Application Insights resource, and each network hop must preserve the `traceparent` context.

The observability goals are:

- Trace each workflow execution.
- Correlate frontend, API, orchestrator, and agent spans when trace context is preserved.
- Observe model calls.
- Correlate agent activity by agent ID and name.
- Support Foundry Control Plane monitoring for custom and hosted agents.

## Ownership Boundaries

Each deployable owns its own runtime and deployment assets:

- `frontend/` owns the Streamlit app, frontend container, and frontend Container Apps descriptor.
- `agents/orchestrator/` owns the API bridge, workflow, hosted coordinator entrypoint, orchestrator containers, Foundry metadata, and Container Apps descriptor.
- `agents/municipal-incident-intake/` owns the Intake Agent prompt, entrypoint, container, requirements, and Foundry metadata.
- `agents/municipal-incident-routing/` owns the Routing Agent prompt, entrypoint, container, requirements, and Foundry metadata.
- `agents/municipal-incident-notification/` owns the Notification Agent prompt, entrypoint, container, requirements, and Foundry metadata.
- `README.md` owns Azure infrastructure and deployment setup guidance.
- `docs/` owns reusable operational templates such as the optional GitHub Actions workflow.

This keeps deployable concerns close to the system that owns them and avoids a central mixed deployment-assets folder.

## Design Intent

The architecture intentionally supports two complementary operating models:

- Independent agents for isolated deployment, testing, versioning, and observability.
- A full workflow orchestrator for end-to-end citizen incident processing.

This gives the city operations workflow flexibility: teams can inspect or improve each agent separately, while applications can still call one complete incident-processing flow.