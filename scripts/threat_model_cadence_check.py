"""Run threat-model cadence checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from thomas.security.threat_model_cadence import evaluate_threat_model_cadence


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate threat-model review cadence.")
    parser.add_argument("--path", default="docs/THREAT_MODEL_WEB_API.md", help="Threat model file path.")
    parser.add_argument("--max-age-days", type=int, default=14, help="Maximum allowed age in days.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON output.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on cadence errors.")
    args = parser.parse_args(argv)

    report = evaluate_threat_model_cadence(Path(args.path).resolve(), max_age_days=max(1, int(args.max_age_days)))

    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = dict(report.get("summary") or {})
        print("Threat model cadence check")
        print(f"- file: {report.get('path', '')}")
        print(f"- errors: {summary.get('error_count', 0)}")
        print(f"- warnings: {summary.get('warning_count', 0)}")

    if bool(args.strict) and not bool(report.get("ok")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
