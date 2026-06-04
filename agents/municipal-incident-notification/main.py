from orchestrator.hosting import run_hosted_agent
from prompt import NOTIFICATION_AGENT_INSTRUCTIONS


def main() -> None:
    run_hosted_agent("Notification Agent", NOTIFICATION_AGENT_INSTRUCTIONS)


if __name__ == "__main__":
    main()
