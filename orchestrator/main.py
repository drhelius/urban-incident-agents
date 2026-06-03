from __future__ import annotations

import asyncio

from orchestrator.config import get_settings, load_dotenv_if_available
from orchestrator.observability import configure_observability


async def main() -> None:
    load_dotenv_if_available()
    configure_observability()

    from agent_framework_foundry_hosting import ResponsesHostServer
    from orchestrator.workflow import build_remote_orchestrator_agent

    server = ResponsesHostServer(build_remote_orchestrator_agent(get_settings()))
    await server.run_async()


if __name__ == "__main__":
    asyncio.run(main())
