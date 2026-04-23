"""Run a lightweight incident response drill and emit machine-readable report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from thomas.marketplace.security.incident_drill import run_security_incident_drill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a security incident response drill.")
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    parser.add_argument("--scenario", default="web_api", help="Drill scenario id.")
    parser.add_argument(
        "--no-command-checks",
        action="store_true",
        help="Skip command execution checks and run artifact-only drill.",
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    report = run_security_incident_drill(
        Path(args.repo_root).resolve(),
        scenario=str(args.scenario),
        include_command_checks=not bool(args.no_command_checks),
    )

    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = dict(report.get("summary") or {})
        print("Security incident drill")
        print(f"- scenario: {report.get('scenario', '')}")
        print(f"- passed: {summary.get('passed', 0)}")
        print(f"- failed: {summary.get('failed', 0)}")

    return 0 if bool(report.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
