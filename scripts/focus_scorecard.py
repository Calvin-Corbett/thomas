"""Generate a telemetry-driven weekly focus scorecard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from thomas.observability.focus_scorecard import build_focus_scorecard
from thomas.observability.run_db import resolve_runs_db_path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a weekly focus scorecard for outcome-based prioritization.")
    parser.add_argument("--days", type=int, default=7, help="Window size in days (default: 7).")
    parser.add_argument("--db", default="", help="Optional runs DB path override.")
    parser.add_argument("--config", default="", help="Optional thomas.toml path override.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve() if str(args.db or "").strip() else resolve_runs_db_path()
    cfg_path = Path(args.config).resolve() if str(args.config or "").strip() else None

    report = build_focus_scorecard(
        runs_db_path=db_path,
        config_path=cfg_path,
        window_days=max(1, min(90, int(args.days))),
    )

    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Weekly focus scorecard")
        print(f"- generated: {report.get('generated_at', '')}")
        print(f"- health score: {report.get('health_score', 0)}")
        print(f"- window days: {report.get('window_days', 0)}")
        actions = list(report.get("priority_actions") or [])
        if actions:
            print("- top action:")
            first = dict(actions[0])
            print(f"  [{first.get('severity', 'n/a')}] {first.get('id', 'unknown')}: {first.get('reason', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
