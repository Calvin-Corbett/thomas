"""Run threat-model cadence checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from thomas.marketplace.security.incident_drill import _validate_scoped_path
from thomas.marketplace.security.threat_model_cadence import evaluate_threat_model_cadence

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _scope_violation_report(path: str, *, error: str) -> dict[str, object]:
    return {
        "ok": False,
        "path": str(path),
        "errors": [
            {
                "code": "threat_model.scope_violation",
                "message": str(error),
                "remediation": "Use the scoped plan artifact path, for example docs/THREAT_MODEL_WEB_API.md.",
            }
        ],
        "warnings": [],
        "summary": {"error_count": 1, "warning_count": 0},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate threat-model review cadence.")
    parser.add_argument("--path", default="docs/THREAT_MODEL_WEB_API.md", help="Threat model file path.")
    parser.add_argument("--max-age-days", type=int, default=14, help="Maximum allowed age in days.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON output.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on cadence errors.")
    args = parser.parse_args(argv)

    requested_path = Path(args.path)
    if not requested_path.is_absolute():
        requested_path = (_REPO_ROOT / requested_path).resolve()
    try:
        threat_model_path = _validate_scoped_path(_REPO_ROOT, str(args.path), scope="plan")
    except ValueError as exc:
        report = _scope_violation_report(str(requested_path), error=str(exc))
    else:
        report = evaluate_threat_model_cadence(
            threat_model_path,
            max_age_days=max(1, int(args.max_age_days)),
        )

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
