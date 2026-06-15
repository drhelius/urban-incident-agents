from __future__ import annotations

from uuid import uuid4

from agent_framework import (
    Agent,
    AgentExecutor,
    Executor,
    Message,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowAgent,
    handler,
)
from agent_framework.observability import AgentTelemetryLayer

from incident_core.prompts import (
    build_intake_prompt,
    build_notification_prompt,
    build_routing_prompt,
    intake_agent_instructions,
    notification_agent_instructions,
    routing_agent_instructions,
)
from incident_core.config import Settings, get_settings
from incident_core.hosted_client import HostedAgentResponsesClient
from incident_core.json_utils import dumps_compact, extract_json_object
from incident_core.llm import agent_result_text, build_foundry_chat_client
from incident_core.models import (
    IncidentWorkflowResult,
    IntakeResult,
    NotificationResult,
    RoutingResult,
)
from incident_core.observability import configure_observability, mark_agent_created


ORCHESTRATOR_AGENT_ID = "municipal-incident-orchestrator"
ORCHESTRATOR_AGENT_NAME = "municipal-incident-orchestrator"
ORCHESTRATOR_AGENT_DESCRIPTION = (
    "Coordinates Intake, Routing, and Notification as separately deployed Foundry hosted agents."
)


class ObservableWorkflowAgent(AgentTelemetryLayer, WorkflowAgent):
    def run(
        self,
        messages=None,
        *,
        stream: bool = False,
        session=None,
        checkpoint_id: str | None = None,
        checkpoint_storage=None,
        function_invocation_kwargs=None,
        client_kwargs=None,
    ):
        return self._trace_agent_invocation(
            messages=messages,
            session=session,
            merged_options={},
            client_kwargs=client_kwargs,
            stream=stream,
            execute=lambda: WorkflowAgent.run(
                self,
                messages,
                stream=stream,
                session=session,
                checkpoint_id=checkpoint_id,
                checkpoint_storage=checkpoint_storage,
                function_invocation_kwargs=function_invocation_kwargs,
                client_kwargs=client_kwargs,
            ),
        )


class IncidentRequestEnvelope(Executor):
    def __init__(self) -> None:
        super().__init__(id="incident-request-envelope")

    @handler
    async def handle(self, report: str, ctx: WorkflowContext[str]) -> None:
        clean_report = report.strip()
        if not clean_report:
            raise ValueError("Incident report text is required.")
        await ctx.send_message(_incident_request_payload(clean_report))

    @handler(input=list[Message], output=str)
    async def handle_messages(self, messages, ctx) -> None:
        clean_report = _messages_text(messages)
        if not clean_report:
            raise ValueError("Incident report text is required.")
        await ctx.send_message(_incident_request_payload(clean_report))


class RemoteHostedAgentExecutor(Executor):
    def __init__(
        self,
        *,
        id: str,
        client: HostedAgentResponsesClient,
        agent_name: str,
        agent_version: str | None = None,
        invocation_mode: str = "framework",
    ) -> None:
        super().__init__(id=id)
        self.client = client
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.invocation_mode = invocation_mode

    async def _run_agent(self, prompt: str) -> str:
        return await self.client.run(
            self.agent_name,
            prompt,
            self.agent_version,
            invocation_mode=self.invocation_mode,
        )


class RemoteIntakeAgentExecutor(RemoteHostedAgentExecutor):
    @handler(input=str, output=str)
    async def handle(self, payload, ctx) -> None:
        request = extract_json_object(payload)
        report = str(request.get("report") or "").strip()
        if not report:
            raise ValueError("Incident report text is required.")

        response_text = await self._run_agent(build_intake_prompt(report))
        intake = IntakeResult.from_mapping(extract_json_object(response_text), raw_report=report)
        await ctx.send_message(
            dumps_compact(
                {
                    "correlation_id": str(request.get("correlation_id") or ""),
                    "report": report,
                    "intake": intake.to_dict(),
                }
            )
        )


class RemoteRoutingAgentExecutor(RemoteHostedAgentExecutor):
    @handler(input=str, output=str)
    async def handle(self, payload, ctx) -> None:
        request = extract_json_object(payload)
        report = str(request.get("report") or "").strip()
        intake = IntakeResult.from_mapping(_mapping(request.get("intake")), raw_report=report)

        if intake.is_urban_incident:
            response_text = await self._run_agent(build_routing_prompt(report, intake))
            response = extract_json_object(response_text)
            routing = RoutingResult.from_mapping(_mapping(response.get("routing")) or response)
        else:
            routing = RoutingResult.not_applicable()

        await ctx.send_message(
            dumps_compact(
                {
                    "correlation_id": str(request.get("correlation_id") or ""),
                    "report": report,
                    "intake": intake.to_dict(),
                    "routing": routing.to_dict(),
                }
            )
        )


class RemoteNotificationAgentExecutor(RemoteHostedAgentExecutor):
    @handler(input=str, workflow_output=str)
    async def handle(self, payload, ctx) -> None:
        request = extract_json_object(payload)
        correlation_id = str(request.get("correlation_id") or "")
        report = str(request.get("report") or "").strip()
        intake = IntakeResult.from_mapping(_mapping(request.get("intake")), raw_report=report)
        routing = RoutingResult.from_mapping(_mapping(request.get("routing")))

        response_text = await self._run_agent(build_notification_prompt(report, intake, routing))
        response = extract_json_object(response_text)
        notification = NotificationResult.from_mapping(
            _mapping(response.get("notification")) or response
        )
        result = IncidentWorkflowResult(
            status="accepted" if intake.is_urban_incident else "rejected",
            correlation_id=correlation_id,
            intake=intake,
            routing=routing,
            notification=notification,
        )
        await ctx.yield_output(dumps_compact(result.to_dict()))


def build_orchestrator_agent(settings: Settings | None = None):
    active_settings = settings or get_settings()
    configure_observability()
    client = build_foundry_chat_client(active_settings)

    intake_agent = Agent(
        client=client,
        name="Intake Agent",
        instructions=intake_agent_instructions(),
        default_options={"store": False},
    )
    routing_agent = Agent(
        client=client,
        name="Routing Agent",
        instructions=routing_agent_instructions(),
        default_options={"store": False},
    )
    notification_agent = Agent(
        client=client,
        name="Notification Agent",
        instructions=notification_agent_instructions(),
        default_options={"store": False},
    )

    mark_agent_created("municipal-incident-intake", "Intake Agent")
    mark_agent_created("municipal-incident-routing", "Routing Agent")
    mark_agent_created("municipal-incident-notification", "Notification Agent")
    mark_agent_created(ORCHESTRATOR_AGENT_ID, ORCHESTRATOR_AGENT_NAME)

    intake_executor = AgentExecutor(intake_agent, context_mode="last_agent")
    routing_executor = AgentExecutor(routing_agent, context_mode="last_agent")
    notification_executor = AgentExecutor(notification_agent, context_mode="last_agent")

    return (
        WorkflowBuilder(start_executor=intake_executor, output_from=[notification_executor])
        .add_edge(intake_executor, routing_executor)
        .add_edge(routing_executor, notification_executor)
        .build()
        .as_agent(id=ORCHESTRATOR_AGENT_ID, name=ORCHESTRATOR_AGENT_NAME)
    )


def build_remote_orchestrator_agent(settings: Settings | None = None):
    active_settings = settings or get_settings()
    configure_observability()

    names = active_settings.hosted_agent_names
    versions = active_settings.hosted_agent_versions
    invocation_mode = "prompt" if active_settings.child_agent_mode == "prompt" else "framework"
    hosted_client = HostedAgentResponsesClient(active_settings)

    mark_agent_created(names["intake"], "Intake Agent")
    mark_agent_created(names["routing"], "Routing Agent")
    mark_agent_created(names["notification"], "Notification Agent")
    mark_agent_created(ORCHESTRATOR_AGENT_ID, ORCHESTRATOR_AGENT_NAME)

    request_executor = IncidentRequestEnvelope()
    intake_executor = RemoteIntakeAgentExecutor(
        id="call-municipal-incident-intake",
        client=hosted_client,
        agent_name=names["intake"],
        agent_version=versions["intake"],
        invocation_mode=invocation_mode,
    )
    routing_executor = RemoteRoutingAgentExecutor(
        id="call-municipal-incident-routing",
        client=hosted_client,
        agent_name=names["routing"],
        agent_version=versions["routing"],
        invocation_mode=invocation_mode,
    )
    notification_executor = RemoteNotificationAgentExecutor(
        id="call-municipal-incident-notification",
        client=hosted_client,
        agent_name=names["notification"],
        agent_version=versions["notification"],
        invocation_mode=invocation_mode,
    )

    workflow = (
        WorkflowBuilder(
            start_executor=request_executor,
            output_from=[notification_executor],
            name=ORCHESTRATOR_AGENT_NAME,
            description=ORCHESTRATOR_AGENT_DESCRIPTION,
        )
        .add_edge(request_executor, intake_executor)
        .add_edge(intake_executor, routing_executor)
        .add_edge(routing_executor, notification_executor)
        .build()
    )
    return ObservableWorkflowAgent(
        workflow,
        id=ORCHESTRATOR_AGENT_ID,
        name=ORCHESTRATOR_AGENT_NAME,
        description=ORCHESTRATOR_AGENT_DESCRIPTION,
        otel_agent_provider_name="azure.ai.foundry",
    )


async def run_local_workflow(
    report: str, settings: Settings | None = None
) -> IncidentWorkflowResult:
    active_settings = settings or get_settings()
    clean_report = report.strip()
    if not clean_report:
        raise ValueError("Incident report text is required.")

    correlation_id = f"inc-{uuid4().hex[:12]}"
    result = await build_orchestrator_agent(active_settings).run(clean_report)
    return IncidentWorkflowResult.from_mapping(
        extract_json_object(agent_result_text(result)), correlation_id=correlation_id
    )


def _incident_request_payload(report: str) -> str:
    correlation_id = f"inc-{uuid4().hex[:12]}"
    try:
        parsed = extract_json_object(report)
    except Exception:
        parsed = {}

    if isinstance(parsed.get("report"), str) and parsed["report"].strip():
        return dumps_compact(
            {
                "correlation_id": str(parsed.get("correlation_id") or correlation_id),
                "report": parsed["report"].strip(),
            }
        )

    return dumps_compact({"correlation_id": correlation_id, "report": report})


def _messages_text(messages: list[Message]) -> str:
    parts: list[str] = []
    for message in messages:
        text = getattr(message, "text", None)
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}
