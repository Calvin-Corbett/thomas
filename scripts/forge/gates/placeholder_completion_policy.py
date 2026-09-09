#!/usr/bin/env python3
"""Fail when placeholder-backed source files are missing completion annotations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from typing import Any

from thomas.core.placeholder_policy import (
    placeholder_policy_report,
    repo_relative_placeholder_path,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCAN_PREFIXES = ("thomas/", "scripts/")


def _scan_paths(*, repo_root: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for prefix in DEFAULT_SCAN_PREFIXES:
        base = repo_root / prefix.rstrip("/")
        if not base.exists():
            continue
        for full_path in sorted(base.rglob("*.py")):
            report = placeholder_policy_report(full_path)
            if not report.get("is_placeholder"):
                continue
            report["path"] = repo_relative_placeholder_path(full_path, repo_root=repo_root)
            reports.append(report)
    return reports


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check placeholder-backed files for required completion notes.")
    parser.add_argument("--repo-root", default=".", help="Repository root (default: current repo).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    try:
        reports = _scan_paths(repo_root=repo_root)
    except Exception as exc:
        payload = {"ok": False, "error": f"placeholder completion policy failed: {exc}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(payload["error"])
        return 1

    offenders = [
        {
            "path": str(report.get("path") or ""),
            "missing_fields": list(report.get("missing_fields") or []),
        }
        for report in reports
        if not bool(report.get("ok", False))
    ]
    payload = {
        "ok": len(offenders) == 0,
        "placeholder_file_count": len(reports),
        "offenders": offenders,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if payload["ok"]:
            print(f"placeholder completion policy: PASS ({len(reports)} placeholder-backed files checked)")
        else:
            print("placeholder completion policy: FAIL")
            for item in offenders:
                missing = ", ".join(item["missing_fields"])
                print(f"- {item['path']}: missing {missing}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
