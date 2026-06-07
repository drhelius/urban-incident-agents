from incident_core.hosting import run_hosted_agent
from prompt import ROUTING_AGENT_INSTRUCTIONS


def main() -> None:
    run_hosted_agent("Routing Agent", ROUTING_AGENT_INSTRUCTIONS)


if __name__ == "__main__":
    main()
