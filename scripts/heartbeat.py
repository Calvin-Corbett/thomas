"""Thomas heartbeat — standalone entry point.

Run automated project health checks (all token-free, pure Python). Also
exposes Crew.Brief Layer 1 auto-checkpoint via ``--checkpoint``.

Usage::

    python scripts/heartbeat.py
    python scripts/heartbeat.py --fix
    python scripts/heartbeat.py changelog_sync version_consistency
    python scripts/heartbeat.py --list
    python scripts/heartbeat.py --json
    python scripts/heartbeat.py --tags git,syntax
    python scripts/heartbeat.py --checkpoint
    python scripts/heartbeat.py --checkpoint --agent claude --force
"""

from __future__ import annotations

import argparse
import json
import logging
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
    parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="Auto-checkpoint dirty worktree via agent_commit.py (Crew.Brief Layer 1).",
    )
    parser.add_argument(
        "--agent",
        default="",
        help="Agent identifier for checkpoint (defaults to env: THOMAS_AGENT_ID etc.).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the checkpoint interval throttle.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --checkpoint: ask agent_commit.py to dry-run (no commit).",
    )
    args = parser.parse_args(argv)

    if args.checkpoint:
        return _run_checkpoint_cli(args)

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


def _run_checkpoint_cli(args) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from thomas.system.heartbeat_checkpoint import run_checkpoint

    result = run_checkpoint(
        agent=args.agent or None,
        force=args.force,
        dry_run=args.dry_run,
    )
    if args.as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"heartbeat-checkpoint: {result.status} -- {result.message}")
        if result.commit_sha:
            print(f"  commit: {result.commit_sha[:12]} on {result.branch}")
        if result.record_path:
            print(f"  record: {result.record_path}")
    # Heartbeat must not exit non-zero just because we recorded a dirty state;
    # only return failure for hard configuration issues, never reached here.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
