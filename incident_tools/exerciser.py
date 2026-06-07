from __future__ import annotations

import argparse
import json
import os
import random
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from incident_core.config import get_settings, load_dotenv_if_available

DEFAULT_ORCHESTRATOR_AGENT = "municipal-incident-orchestrator"

INCIDENT_REPORTS = [
    "Water main burst at Central Avenue and 4th Street, road is flooding and cars are swerving.",
    "Small water leak from a curb valve outside 12 Oak Street, no flooding yet.",
    "Sewage smell and water backing up from a storm drain near Riverside Market.",
    "Fire hydrant knocked over near City Hospital, water is spraying into the road.",
    "Large pothole on Bridge Road damaged two tires this morning.",
    "Several shallow potholes on Pine Street between 2nd and 3rd Avenue.",
    "Road surface is cracked and sinking near the bus stop on Harbor Lane.",
    "Loose manhole cover banging loudly on King Street.",
    "Traffic light stuck red at Main Street and 1st Avenue causing a long backup.",
    "Pedestrian crossing signal is dark outside Westside Elementary School.",
    "Stop sign knocked down at Elm Street and Lake Road.",
    "Temporary roadwork sign has fallen into a traffic lane on Market Street.",
    "Streetlight out near Pine Street school crossing and it is very dark.",
    "Three streetlights flickering in the park entrance parking lot.",
    "Exposed wires at the base of a streetlight on North Plaza.",
    "Decorative lights on the city square are off after last night's storm.",
    "Large fallen tree blocking both lanes on Hillcrest Drive.",
    "Tree branch hanging low over the sidewalk near 44 Cedar Avenue.",
    "Fallen branch blocking the bike lane on River Trail.",
    "Tree roots have lifted the sidewalk outside the library.",
    "Overflowing public trash bins at the downtown bus terminal.",
    "Illegal dumping of furniture and bags behind the community center.",
    "Broken glass and scattered trash around the playground entrance.",
    "Public recycling container is full and bags are stacked beside it.",
    "Graffiti sprayed on the wall of the public library overnight.",
    "Bus shelter glass shattered on Maple Avenue.",
    "Public restroom door at Memorial Park is broken and will not close.",
    "Bench in the town square has loose metal pieces sticking out.",
    "Construction barrier blocking the accessible sidewalk ramp near City Hall.",
    "Scooters and signs blocking the sidewalk outside the train station.",
    "Ice on the pedestrian bridge has not been treated and people are slipping.",
    "Sidewalk slab missing near the senior center entrance.",
    "Noise complaint about loud construction work after midnight near 18 Walnut Street.",
    "Repeated loud music from the public plaza after permitted hours.",
    "Generator noise from roadwork equipment left running overnight on Mill Road.",
    "Loose metal plate in the road makes a loud bang every time vehicles pass.",
    "Flooded underpass on South Road, water is nearly covering the curb.",
    "Blocked storm drain at Willow Street causing water to pool after rain.",
    "Mud and debris washed onto the roadway near the hillside trail.",
    "Park footpath washed out after heavy rain near the pond.",
    "Playground swing chain is broken and hanging loose.",
    "Damaged fence around the sports field has sharp edges.",
    "Irrigation leak flooding the grass near the park pavilion.",
    "Public drinking fountain in the park is running continuously.",
    "Dead animal on the shoulder of County Road near the city boundary.",
    "Aggressive stray dogs reported near the public playground.",
    "Bee swarm inside a public bus shelter downtown.",
    "Overflowing creek near Greenway Trail is close to the walking path.",
    "Public elevator at the transit station is out of service.",
    "Broken escalator at the civic center entrance.",
    "Bus stop sign missing from the northbound stop near 7th Avenue.",
    "Damaged bike rack blocking part of the sidewalk at the library.",
    "Abandoned shopping cart in the middle of the bike lane on Lake Street.",
    "Sinkhole opening near the curb on East Road.",
    "Oil spill across one lane near the municipal garage entrance.",
    "Loose bricks falling from a public retaining wall near the river walk.",
    "Public fountain overflowing into the plaza walkway.",
    "Snow pile blocking visibility at the corner of Ash Street and Main Street.",
    "Missing cover on an irrigation control box in the park lawn.",
    "Damaged public notice board leaning over the sidewalk.",
]


@dataclass(frozen=True)
class ExerciserConfig:
    project_endpoint: str
    agent_name: str
    token_scope: str
    min_seconds: float
    max_seconds: float
    threads: int
    timeout_seconds: float


class TokenProvider:
    def __init__(self, scope: str):
        try:
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:
            raise RuntimeError("Install azure-identity before running the exerciser.") from exc
        self.scope = scope
        self.credential = DefaultAzureCredential()
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_on = 0

    def get(self) -> str:
        now = int(time.time())
        with self._lock:
            if self._token and self._expires_on - now > 300:
                return self._token
            access_token = self.credential.get_token(self.scope)
            self._token = access_token.token
            self._expires_on = access_token.expires_on
            return self._token


def main() -> None:
    load_dotenv_if_available()
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Continuously exercise a Foundry hosted orchestrator.")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--min-seconds", type=float, default=5.0)
    parser.add_argument("--max-seconds", type=float, default=30.0)
    parser.add_argument(
        "--agent-name",
        default=os.getenv("ORCHESTRATOR_AGENT_NAME", DEFAULT_ORCHESTRATOR_AGENT),
    )
    parser.add_argument("--project-endpoint", default=settings.foundry_project_endpoint)
    parser.add_argument("--token-scope", default=settings.foundry_token_scope)
    parser.add_argument("--timeout-seconds", type=float, default=settings.request_timeout_seconds)
    args = parser.parse_args()

    config = ExerciserConfig(
        project_endpoint=args.project_endpoint,
        agent_name=args.agent_name,
        token_scope=args.token_scope,
        min_seconds=args.min_seconds,
        max_seconds=args.max_seconds,
        threads=args.threads,
        timeout_seconds=args.timeout_seconds,
    )
    _validate_config(config)

    stop_event = threading.Event()
    output_lock = threading.Lock()
    token_provider = TokenProvider(config.token_scope)
    workers = [
        threading.Thread(
            target=_worker_loop,
            args=(index + 1, config, token_provider, stop_event, output_lock),
            daemon=True,
        )
        for index in range(config.threads)
    ]

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    _write(
        output_lock,
        f"starting threads={config.threads} delay={config.min_seconds}-{config.max_seconds}s "
        f"agent={config.agent_name}",
    )
    for worker in workers:
        worker.start()

    while not stop_event.is_set():
        time.sleep(0.2)

    _write(output_lock, "stopping")
    for worker in workers:
        worker.join(timeout=config.max_seconds + config.timeout_seconds + 5)


def _worker_loop(
    worker_id: int,
    config: ExerciserConfig,
    token_provider: TokenProvider,
    stop_event: threading.Event,
    output_lock: threading.Lock,
) -> None:
    random_source = random.Random(time.time_ns() + worker_id)
    endpoint = _responses_endpoint(config.project_endpoint, config.agent_name)
    while not stop_event.is_set():
        delay = random_source.uniform(config.min_seconds, config.max_seconds)
        if stop_event.wait(delay):
            return

        report = random_source.choice(INCIDENT_REPORTS)
        started = time.monotonic()
        try:
            status, response_id, text = _invoke(
                endpoint=endpoint,
                report=report,
                timeout_seconds=config.timeout_seconds,
                token_provider=token_provider,
            )
            elapsed = time.monotonic() - started
            _write(
                output_lock,
                f"worker={worker_id} status={status} elapsed={elapsed:.2f}s "
                f"response={response_id} report={_shorten(report)} result={_shorten(text)}",
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            _write(
                output_lock,
                f"worker={worker_id} status=error elapsed={elapsed:.2f}s "
                f"report={_shorten(report)} error={_shorten(str(exc), 500)}",
            )


def _invoke(
    *,
    endpoint: str,
    report: str,
    timeout_seconds: float,
    token_provider: TokenProvider,
) -> tuple[str, str, str]:
    headers = {
        "Authorization": f"Bearer {token_provider.get()}",
        "Content-Type": "application/json",
    }
    payload = {"input": report, "stream": False, "store": False}
    response = httpx.post(endpoint, headers=headers, json=payload, timeout=timeout_seconds)
    response.raise_for_status()
    body = response.json()
    status = str(body.get("status") or "unknown")
    response_id = str(body.get("response_id") or body.get("id") or "")
    if status == "failed":
        raise RuntimeError(f"response failed: {body.get('error') or body}")
    return status, response_id, _responses_text(body)


def _responses_endpoint(project_endpoint: str, agent_name: str) -> str:
    return (
        project_endpoint.rstrip("/")
        + f"/agents/{agent_name}/endpoint/protocols/openai/responses?api-version=v1"
    )


def _responses_text(payload: dict[str, Any]) -> str:
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
            return " ".join(parts)

    return json.dumps(payload, ensure_ascii=True)


def _validate_config(config: ExerciserConfig) -> None:
    if config.threads < 1:
        raise ValueError("--threads must be at least 1")
    if config.min_seconds < 0:
        raise ValueError("--min-seconds must be 0 or greater")
    if config.max_seconds < config.min_seconds:
        raise ValueError("--max-seconds must be greater than or equal to --min-seconds")
    if config.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than 0")
    if "<" in config.project_endpoint or not config.project_endpoint.startswith("https://"):
        raise ValueError("Set FOUNDRY_PROJECT_ENDPOINT or pass --project-endpoint")


def _write(lock: threading.Lock, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with lock:
        print(f"{timestamp} {message}", flush=True)


def _shorten(value: str, limit: int = 220) -> str:
    clean = " ".join(value.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


if __name__ == "__main__":
    main()
