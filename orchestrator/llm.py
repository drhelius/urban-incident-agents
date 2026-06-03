from __future__ import annotations

from typing import Any

from orchestrator.config import Settings


def build_foundry_agent(name: str, instructions: str, settings: Settings) -> Any:
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError(
            "Foundry model mode requires agent-framework-foundry and azure-identity. "
            "Install dependencies with: pip install -e ."
        ) from exc

    credential = DefaultAzureCredential()
    client = build_foundry_chat_client(settings, credential=credential)
    return client.as_agent(name=name, instructions=instructions)


def build_foundry_chat_client(settings: Settings, credential: Any | None = None) -> Any:
    from agent_framework.foundry import FoundryChatClient
    from azure.identity import DefaultAzureCredential

    return FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.model_deployment_name,
        credential=credential or DefaultAzureCredential(),
    )


def _result_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text
    value = getattr(result, "value", None)
    if isinstance(value, str):
        return value
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    return str(result)


def agent_result_text(result: Any) -> str:
    return _result_text(result)
