from __future__ import annotations

from incident_core.config import get_settings, load_dotenv_if_available
from incident_core.llm import build_foundry_agent
from incident_core.observability import configure_observability


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


def run_hosted_orchestrator() -> None:
    """Serve the orchestrator as a Foundry hosted agent.

    Builds the remote orchestrator workflow agent (which coordinates the
    separately deployed Intake, Routing, and Notification hosted agents) and
    exposes it over the Responses protocol.
    """
    import asyncio

    load_dotenv_if_available()
    configure_observability()

    from agent_framework_foundry_hosting import ResponsesHostServer

    from incident_core.workflow import build_remote_orchestrator_agent

    async def _serve() -> None:
        server = ResponsesHostServer(build_remote_orchestrator_agent(get_settings()))
        await server.run_async()

    asyncio.run(_serve())
