from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from orchestrator.models import IntakeResult, RoutingResult

AGENTS_ROOT = Path(__file__).resolve().parent.parent / "agents"


@lru_cache(maxsize=3)
def _load_prompt_module(agent_folder: str) -> ModuleType:
    prompt_path = AGENTS_ROOT / agent_folder / "prompt.py"
    module_name = f"urban_incident_{agent_folder.replace('-', '_')}_prompt"
    spec = importlib.util.spec_from_file_location(module_name, prompt_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load prompt module from {prompt_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def intake_agent_instructions() -> str:
    return str(_load_prompt_module("intake-agent").INTAKE_AGENT_INSTRUCTIONS)


def routing_agent_instructions() -> str:
    return str(_load_prompt_module("routing-agent").ROUTING_AGENT_INSTRUCTIONS)


def notification_agent_instructions() -> str:
    return str(_load_prompt_module("notification-agent").NOTIFICATION_AGENT_INSTRUCTIONS)


def build_intake_prompt(report: str) -> str:
    return str(_load_prompt_module("intake-agent").build_intake_prompt(report))


def build_routing_prompt(report: str, intake: IntakeResult) -> str:
    return str(_load_prompt_module("routing-agent").build_routing_prompt(report, intake))


def build_notification_prompt(report: str, intake: IntakeResult, routing: RoutingResult) -> str:
    return str(
        _load_prompt_module("notification-agent").build_notification_prompt(report, intake, routing)
    )
