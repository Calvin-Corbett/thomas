#!/usr/bin/env python3
"""
Rollback script for observability.run_replay_debugger

Restores any backed-up modified files, and removes newly added files if present.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

FEATURE_ID = "observability.run_replay_debugger"

NEW_FILES = [
    "thomas/observability/redaction.py",
    "thomas/observability/run_db.py",
    "thomas/observability/event_recorder.py",
    "thomas/observability/auto_instrument.py",
    "thomas/observability/run_store_replay.py",
    "thomas/server/routes/replay_debugger.py",
    "thomas/server/middleware/replay_observability.py",
    "thomas/server/web/replay_debugger.html",
    "thomas/server/web/css/replay_debugger.css",
    "thomas/server/web/js/replay_debugger.js",
    "docs/ops/run_replay_debugger.md",
    "tests/_replay_test_db.py",
    "tests/test_replay_debugger_redaction.py",
    "tests/test_replay_debugger_determinism.py",
    "tests/test_replay_debugger_api.py",
    "tests/test_event_recorder_persistence.py",
    "tests/test_replay_middleware_records_run.py",
    "docs/FEATURE_CATALOG.md.append",
]

def restore_backups(repo: Path) -> None:
    backup_root = repo / ".feature_backups" / FEATURE_ID
    if not backup_root.exists():
        return
    for p in backup_root.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(backup_root)
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)

def remove_new_files(repo: Path) -> None:
    for rel in NEW_FILES:
        p = repo / rel
        if p.exists():
            try:
                p.unlink()
            except IsADirectoryError:
                shutil.rmtree(p, ignore_errors=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        raise SystemExit(f"Repo path does not exist: {repo}")

    restore_backups(repo)
    remove_new_files(repo)
    print("✅ Rolled back feature pack:", FEATURE_ID)

if __name__ == "__main__":
    main()
