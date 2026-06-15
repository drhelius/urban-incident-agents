from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import httpx
from agent_framework import AgentSession

from incident_core.config import Settings, get_settings, load_dotenv_if_available
from incident_core.json_utils import extract_json_object
from incident_core.models import IncidentWorkflowResult
from incident_core.observability import inject_trace_context, trace_span


class HostedAgentResponsesClient:
    def __init__(self, settings: Settings):
        load_dotenv_if_available()
        self.settings = settings
        self._credential = None

    async def run(
        self,
        agent_name: str,
        prompt: str,
        agent_version: str | None = None,
        invocation_mode: str = "framework",
    ) -> str:
        with trace_span(
            "orchestrator.call_hosted_agent",
            {
                "gen_ai.agent.name": agent_name,
                "gen_ai.agent.version": agent_version or "latest",
                "gen_ai.agent.invocation_mode": invocation_mode,
            },
        ):
            if invocation_mode == "prompt":
                return await self._run_prompt_agent(agent_name, prompt)
            return await self._run_foundry_agent(agent_name, prompt, agent_version)

    async def _run_prompt_agent(self, agent_name: str, prompt: str) -> str:
        try:
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as exc:
            raise RuntimeError(
                "Prompt-agent orchestration requires azure-identity. "
                "Install dependencies with: pip install -e ."
            ) from exc

        trace_headers = inject_trace_context()
        payload = {"input": prompt, "stream": False}
        endpoint = _responses_endpoint(self.settings.foundry_project_endpoint, agent_name)
        async with DefaultAzureCredential() as credential:
            token = await credential.get_token(self.settings.foundry_token_scope)

        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
        }
        if trace_headers:
            headers.update(trace_headers)

        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            return _responses_text(response.json())

    async def _run_foundry_agent(
        self, agent_name: str, prompt: str, agent_version: str | None
    ) -> str:
        try:
            from agent_framework.foundry import FoundryAgent
            from azure.ai.projects.aio import AIProjectClient
            from azure.ai.projects.models import VersionRefIndicator
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as exc:
            raise RuntimeError(
                "Hosted orchestration requires agent-framework-foundry, azure-ai-projects, "
                "and azure-identity. Install dependencies with: pip install -e ."
            ) from exc

        # Forward the active W3C trace context so the hosted agent (and the
        # workers it calls) continue the caller's trace instead of starting a
        # new one. The headers are applied to the OpenAI Responses call the
        # FoundryAgent makes under the hood.
        trace_headers = inject_trace_context()

        credential = DefaultAzureCredential()
        async with (
            AIProjectClient(
                endpoint=self.settings.foundry_project_endpoint,
                credential=credential,
                allow_preview=True,
            ) as project_client,
            FoundryAgent(
                project_client=project_client,
                agent_name=agent_name,
                agent_version=agent_version,
                allow_preview=True,
                default_headers=trace_headers or None,
                default_options={"store": False},
            ) as agent,
        ):
            resolved_version = await _resolve_agent_version(project_client, agent_name, agent_version)
            service_session = await project_client.beta.agents.create_session(
                agent_name=agent_name,
                version_indicator=VersionRefIndicator(agent_version=resolved_version),
            )
            service_session_id = getattr(service_session, "agent_session_id", None)
            if not isinstance(service_session_id, str) or not service_session_id:
                raise RuntimeError(f"Hosted agent {agent_name!r} did not return a session id.")

            session: AgentSession = agent.get_session(service_session_id)
            try:
                parts: list[str] = []
                async for chunk in agent.run(prompt, session=session, stream=True):
                    text = getattr(chunk, "text", "")
                    if text:
                        parts.append(text)
                return "".join(parts)
            finally:
                await project_client.beta.agents.delete_session(
                    agent_name=agent_name,
                    session_id=service_session_id,
                )


async def run_hosted_workflow(
    report: str, settings: Settings | None = None
) -> IncidentWorkflowResult:
    active_settings = settings or get_settings()
    if not report.strip():
        raise ValueError("Incident report text is required.")

    client = HostedAgentResponsesClient(active_settings)
    orchestrator_text = await client.run(
        active_settings.orchestrator_agent_name,
        report.strip(),
        active_settings.orchestrator_agent_version,
    )
    return IncidentWorkflowResult.from_mapping(
        extract_json_object(orchestrator_text), correlation_id=f"inc-{uuid4().hex[:12]}"
    )


async def _resolve_agent_version(
    project_client: Any, agent_name: str, agent_version: str | None
) -> str:
    if agent_version:
        return agent_version

    agent_details = await project_client.agents.get(agent_name=agent_name)
    versions = getattr(agent_details, "versions", None)
    latest = (
        versions.get("latest")
        if isinstance(versions, Mapping)
        else getattr(versions, "latest", None)
    )
    resolved = getattr(latest, "version", None)
    if not isinstance(resolved, str) or not resolved:
        raise RuntimeError(f"Hosted agent {agent_name!r} did not include a latest version.")
    return resolved


async def run_local_responses_workflow(
    report: str, settings: Settings | None = None
) -> IncidentWorkflowResult:
    active_settings = settings or get_settings()
    if not report.strip():
        raise ValueError("Incident report text is required.")

    payload = {"input": report.strip(), "stream": False}
    timeout = httpx.Timeout(active_settings.request_timeout_seconds)
    with trace_span(
        "orchestrator.call_local_responses",
        {
            "http.url": active_settings.local_orchestrator_responses_url,
        },
    ):
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                active_settings.local_orchestrator_responses_url,
                json=payload,
                headers=inject_trace_context(),
            )
            response.raise_for_status()

    return IncidentWorkflowResult.from_mapping(
        extract_json_object(_responses_text(response.json())),
        correlation_id=f"inc-{uuid4().hex[:12]}",
    )


def _responses_endpoint(project_endpoint: str, agent_name: str) -> str:
    return (
        project_endpoint.rstrip("/")
        + f"/agents/{agent_name}/endpoint/protocols/openai/responses?api-version=v1"
    )


def _responses_text(payload: dict[str, Any]) -> str:
    if payload.get("status") == "failed":
        raise RuntimeError(f"Hosted agent response failed: {payload.get('error') or payload}")

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output = payload.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if isinstance(content_item, dict):
                    text = content_item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        if parts:
            return "\n".join(parts)

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message", {})
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    return str(payload)
