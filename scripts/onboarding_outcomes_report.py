"""Generate onboarding outcomes report from run/event telemetry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from thomas.observability.onboarding_outcomes import build_onboarding_outcome_report
from thomas.observability.run_db import resolve_runs_db_path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build onboarding funnel outcome report from telemetry events.")
    parser.add_argument("--days", type=int, default=7, help="Window size in days (default: 7).")
    parser.add_argument("--db", default="", help="Optional runs DB path override.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve() if str(args.db or "").strip() else resolve_runs_db_path()
    report = build_onboarding_outcome_report(db_path, since_days=max(1, int(args.days)))

    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = dict(report.get("summary") or {})
        print("Onboarding outcomes")
        print(f"- db: {db_path}")
        print(f"- window days: {report.get('window_days', 0)}")
        print(f"- events: {summary.get('events', 0)}")
        print(f"- runs: {summary.get('runs', 0)}")
        print(f"- unique users: {summary.get('unique_users', 0)}")
        print(f"- wizard opened: {summary.get('wizard_opened', 0)}")
        print(f"- completed: {summary.get('onboarding_completed', 0)}")
        print(f"- completion rate: {summary.get('completion_rate', 0.0):.4f}")
        print(f"- recovery attempts: {summary.get('recovery_attempts', 0)}")
        print(f"- recovery succeeded: {summary.get('recovery_succeeded', 0)}")
        print(f"- recovery success rate: {summary.get('recovery_success_rate', 0.0):.4f}")
        reasons = list(report.get("top_failure_reasons") or [])
        if reasons:
            lead = dict(reasons[0] or {})
            print(f"- top failure reason: {lead.get('reason', 'unknown')} ({lead.get('count', 0)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
