#!/usr/bin/env python3
"""Aggregated security audit command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from thomas.security.security_audit import run_security_audit


def _render_text(payload: dict) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        f"Repo root: {payload.get('repo_root', '')}",
        f"Result: {'OK' if payload.get('ok') else 'FAILED'}",
        f"Checks: {summary.get('check_count', 0)}",
        f"Failing checks: {', '.join(summary.get('failing_checks') or []) if summary.get('failing_checks') else 'none'}",
        f"Error count: {summary.get('error_count', 0)}",
        f"Warning count: {summary.get('warning_count', 0)}",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run aggregated Thomas security audit.")
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    parser.add_argument("--threat-max-age-days", type=int, default=30, help="Maximum threat model age in days.")
    parser.add_argument("--min-extension-pass-rate", type=float, default=0.95, help="Minimum extension certification pass rate.")
    parser.add_argument("--include-incident-drill", action="store_true", help="Run the incident drill artifact checks.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on failing checks.")
    args = parser.parse_args(argv)

    payload = run_security_audit(
        Path(args.repo_root).resolve(),
        max_threat_model_age_days=max(1, int(args.threat_max_age_days)),
        min_extension_pass_rate=float(args.min_extension_pass_rate),
        include_incident_drill=bool(args.include_incident_drill),
    )

    if bool(args.as_json):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_text(payload))

    if bool(args.strict) and not bool(payload.get("ok")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
