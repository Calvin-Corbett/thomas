#!/usr/bin/env python3
"""Print a concise environment report for local debugging."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _git_value(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def build_report() -> dict[str, Any]:
    cwd = Path.cwd()
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "workspace": {
            "cwd": str(cwd),
            "git_root": _git_value(["rev-parse", "--show-toplevel"]),
            "git_branch": _git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
            "git_commit": _git_value(["rev-parse", "--short", "HEAD"]),
            "dirty": bool(_git_value(["status", "--porcelain"])),
        },
        "environment": {
            "venv": os.environ.get("VIRTUAL_ENV"),
            "thomas_config": os.environ.get("THOMAS_CONFIG"),
            "path_entries": len(os.environ.get("PATH", "").split(os.pathsep)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Print local environment diagnostics.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"Timestamp (UTC): {report['timestamp_utc']}")
    print(f"Python: {report['python']['version']} ({report['python']['executable']})")
    print(f"Platform: {report['platform']['system']} {report['platform']['release']} ({report['platform']['machine']})")
    print(f"CWD: {report['workspace']['cwd']}")
    print(f"Git root: {report['workspace']['git_root'] or 'n/a'}")
    print(f"Git branch: {report['workspace']['git_branch'] or 'n/a'}")
    print(f"Git commit: {report['workspace']['git_commit'] or 'n/a'}")
    print(f"Git dirty: {'yes' if report['workspace']['dirty'] else 'no'}")
    print(f"Virtual env: {report['environment']['venv'] or 'n/a'}")
    print(f"THOMAS_CONFIG: {report['environment']['thomas_config'] or 'n/a'}")
    print(f"PATH entries: {report['environment']['path_entries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
