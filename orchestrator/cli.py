from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import replace

from orchestrator.config import get_settings
from orchestrator.service import process_incident_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the municipal incident workflow.")
    parser.add_argument("report", nargs="?", help="Citizen incident report text.")
    parser.add_argument("--hosted", action="store_true", help="Call deployed hosted agents.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    report = args.report or input("Incident report: ").strip()
    settings = get_settings()
    if args.hosted:
        settings = replace(settings, orchestration_backend="hosted")
    result = asyncio.run(process_incident_report(report, settings))
    indent = 2 if args.pretty or os.getenv("PRETTY_JSON") else None
    print(json.dumps(result.to_dict(), indent=indent, ensure_ascii=True))


if __name__ == "__main__":
    main()
