from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_PROJECT_ENDPOINT = (
    "https://<YOUR-RESOURCE>.services.ai.azure.com/api/projects/<YOUR-PROJECT>"
)
DEFAULT_MODEL_DEPLOYMENT = "gpt-5.4"


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)


@dataclass(frozen=True)
class Settings:
    foundry_project_endpoint: str = DEFAULT_PROJECT_ENDPOINT
    model_deployment_name: str = DEFAULT_MODEL_DEPLOYMENT
    orchestration_backend: str = "local"
    orchestrator_agent_name: str = "municipal-incident-orchestrator"
    intake_agent_name: str = "municipal-incident-intake"
    routing_agent_name: str = "municipal-incident-routing"
    notification_agent_name: str = "municipal-incident-notification"
    orchestrator_agent_version: str | None = None
    intake_agent_version: str | None = None
    routing_agent_version: str | None = None
    notification_agent_version: str | None = None
    local_orchestrator_responses_url: str = "http://localhost:8088/responses"
    foundry_token_scope: str = "https://ai.azure.com/.default"
    request_timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv_if_available()
        return cls(
            foundry_project_endpoint=os.getenv(
                "FOUNDRY_PROJECT_ENDPOINT", DEFAULT_PROJECT_ENDPOINT
            ),
            model_deployment_name=os.getenv(
                "AZURE_AI_MODEL_DEPLOYMENT_NAME", DEFAULT_MODEL_DEPLOYMENT
            ),
            orchestration_backend=os.getenv("ORCHESTRATION_BACKEND", "local").strip().lower(),
            orchestrator_agent_name=os.getenv(
                "ORCHESTRATOR_AGENT_NAME", "municipal-incident-orchestrator"
            ),
            intake_agent_name=os.getenv("INTAKE_AGENT_NAME", "municipal-incident-intake"),
            routing_agent_name=os.getenv("ROUTING_AGENT_NAME", "municipal-incident-routing"),
            notification_agent_name=os.getenv(
                "NOTIFICATION_AGENT_NAME", "municipal-incident-notification"
            ),
            orchestrator_agent_version=_optional_env("ORCHESTRATOR_AGENT_VERSION"),
            intake_agent_version=_optional_env("INTAKE_AGENT_VERSION"),
            routing_agent_version=_optional_env("ROUTING_AGENT_VERSION"),
            notification_agent_version=_optional_env("NOTIFICATION_AGENT_VERSION"),
            local_orchestrator_responses_url=os.getenv(
                "LOCAL_ORCHESTRATOR_RESPONSES_URL", "http://localhost:8088/responses"
            ),
            foundry_token_scope=os.getenv("FOUNDRY_TOKEN_SCOPE", "https://ai.azure.com/.default"),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "120")),
        )

    @property
    def hosted_agent_names(self) -> dict[str, str]:
        return {
            "intake": self.intake_agent_name,
            "routing": self.routing_agent_name,
            "notification": self.notification_agent_name,
        }

    @property
    def hosted_agent_versions(self) -> dict[str, str | None]:
        return {
            "intake": self.intake_agent_version,
            "routing": self.routing_agent_version,
            "notification": self.notification_agent_version,
        }

    def sanitized(self) -> dict[str, str | float | None]:
        return {
            "foundry_project_endpoint": self.foundry_project_endpoint,
            "model_deployment_name": self.model_deployment_name,
            "orchestration_backend": self.orchestration_backend,
            "orchestrator_agent_name": self.orchestrator_agent_name,
            "orchestrator_agent_version": self.orchestrator_agent_version,
            "intake_agent_name": self.intake_agent_name,
            "routing_agent_name": self.routing_agent_name,
            "notification_agent_name": self.notification_agent_name,
            "intake_agent_version": self.intake_agent_version,
            "routing_agent_version": self.routing_agent_version,
            "notification_agent_version": self.notification_agent_version,
            "local_orchestrator_responses_url": self.local_orchestrator_responses_url,
            "request_timeout_seconds": self.request_timeout_seconds,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip()
