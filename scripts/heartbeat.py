"""Thomas heartbeat — standalone entry point.

Run automated project health checks (all token-free, pure Python).

Usage::

    python scripts/heartbeat.py
    python scripts/heartbeat.py --fix
    python scripts/heartbeat.py changelog_sync version_consistency
    python scripts/heartbeat.py --list
    python scripts/heartbeat.py --json
    python scripts/heartbeat.py --tags git,syntax
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure thomas package is importable when running standalone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Thomas heartbeat health checks (all token-free).",
    )
    parser.add_argument(
        "checks",
        nargs="*",
        help="Run only these named checks (default: all).",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output JSON.")
    parser.add_argument("--fix", action="store_true", help="Auto-fix fixable failures.")
    parser.add_argument("--list", action="store_true", dest="list_checks", help="List checks.")
    parser.add_argument(
        "--tags",
        default="",
        help="Filter by tag (comma-separated, e.g. 'git,syntax').",
    )
    args = parser.parse_args(argv)

    from thomas.system.heartbeat import (
        format_text_report,
        list_checks,
        run_heartbeat,
    )

    if args.list_checks:
        checks = list_checks()
        if args.as_json:
            print(json.dumps(checks, ensure_ascii=False, indent=2))
        else:
            for c in checks:
                fix = " [fixable]" if c["has_fix"] else ""
                tags = f" ({', '.join(c['tags'])})" if c["tags"] else ""
                print(f"  {c['name']}{fix}{tags}")
                print(f"    {c['description']}")
        return 0

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    check_names = args.checks or None

    report = run_heartbeat(checks=check_names, fix=args.fix, tags=tags)

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_text_report(report))

    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
