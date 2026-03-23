"""Enforce onboarding telemetry contract and KPI thresholds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from thomas.marketplace.observability.onboarding_outcomes import build_onboarding_outcome_report
from thomas.marketplace.observability.onboarding_outcomes_gate import evaluate_onboarding_outcomes_gate
from thomas.marketplace.observability.run_db import resolve_runs_db_path

_LOW_SAMPLE_WARNING_PREFIX = "insufficient onboarding telemetry sample"


def _is_low_sample_warning(message: str) -> bool:
    return str(message or "").strip().lower().startswith(_LOW_SAMPLE_WARNING_PREFIX)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate onboarding outcomes telemetry contract and enforce KPI thresholds "
            "when telemetry sample size is sufficient."
        )
    )
    parser.add_argument("--days", type=int, default=7, help="Window size in days (default: 7).")
    parser.add_argument("--db", default="", help="Optional runs DB path override.")
    parser.add_argument(
        "--min-events-for-quality-thresholds",
        type=int,
        default=20,
        help="Only apply KPI thresholds when events in window are at least this value.",
    )
    parser.add_argument(
        "--min-completion-rate",
        type=float,
        default=0.9,
        help="Minimum onboarding completion rate once quality thresholds are active.",
    )
    parser.add_argument(
        "--min-recovery-success-rate",
        type=float,
        default=0.8,
        help="Minimum recovery success rate once quality thresholds are active.",
    )
    parser.add_argument(
        "--max-median-time-to-ready-seconds",
        type=float,
        default=480.0,
        help="Maximum allowed median onboarding time-to-ready once quality thresholds are active.",
    )
    parser.add_argument(
        "--ignore-low-sample-warning",
        action="store_true",
        help="When strict mode is enabled, do not fail on low-sample telemetry warnings.",
    )
    parser.add_argument("--strict", action="store_true", help="Fail when warnings are present.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve() if str(args.db or "").strip() else resolve_runs_db_path()
    report = build_onboarding_outcome_report(db_path, since_days=max(1, int(args.days)))
    gate = evaluate_onboarding_outcomes_gate(
        report,
        min_events_for_quality_thresholds=max(0, int(args.min_events_for_quality_thresholds)),
        min_completion_rate=max(0.0, min(1.0, float(args.min_completion_rate))),
        min_recovery_success_rate=max(0.0, min(1.0, float(args.min_recovery_success_rate))),
        max_median_time_to_ready_seconds=max(1.0, float(args.max_median_time_to_ready_seconds)),
    )

    ok = bool(gate.get("ok", False))
    warnings = list(gate.get("warnings") or [])
    errors = list(gate.get("errors") or [])
    ignored_warnings = [
        msg for msg in warnings if bool(args.ignore_low_sample_warning) and _is_low_sample_warning(str(msg))
    ]
    effective_strict_warnings = [msg for msg in warnings if msg not in ignored_warnings]
    if bool(args.strict) and effective_strict_warnings:
        ok = False
        errors.append("strict mode enabled and warnings were present")

    payload = {
        "ok": bool(ok),
        "db_path": str(db_path),
        "window_days": int(max(1, int(args.days))),
        "errors": errors,
        "warnings": warnings,
        "ignored_warnings": ignored_warnings,
        "gate": gate,
        "onboarding_summary": dict(report.get("summary") or {}),
    }

    if bool(args.as_json):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("Onboarding outcomes gate")
        print(f"- db: {payload['db_path']}")
        print(f"- window days: {payload['window_days']}")
        print(f"- ok: {payload['ok']}")
        print(f"- errors: {len(errors)}")
        print(f"- warnings: {len(warnings)}")
        for msg in errors:
            print(f"  ERROR: {msg}")
        for msg in warnings:
            print(f"  WARN: {msg}")

    return 0 if bool(ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
