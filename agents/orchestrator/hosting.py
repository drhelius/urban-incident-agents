from __future__ import annotations

from orchestrator.config import get_settings, load_dotenv_if_available
from orchestrator.llm import build_foundry_agent
from orchestrator.observability import configure_observability


def run_hosted_agent(name: str, instructions: str) -> None:
    load_dotenv_if_available()
    configure_observability()

    from agent_framework_foundry_hosting import ResponsesHostServer

    agent = build_foundry_agent(
        name=name,
        instructions=instructions,
        settings=get_settings(),
    )
    ResponsesHostServer(agent).run()
