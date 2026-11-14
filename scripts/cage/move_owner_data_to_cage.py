"""Move your chats, memory and settings into the caged Thomas's own data.

You chose (2026-09-23) to make the caged server your everyday Thomas once your
things were moved. Each account can reach only its own side: the cage account
cannot read your %LOCALAPPDATA%, and you cannot write its profile. So this runs
twice:

* ``stage`` (as you): copy the stores into ``runtime\\cage-move`` in the repo --
  a folder the cage account can read -- taking SQLite files through SQLite's own
  backup, so writes still sitting in a WAL file are not lost.
* ``install`` (as the cage account, through the caged shell): copy from there into
  its own data folder and memory root, after backing up anything it replaces into
  ``pre-move-backup``. Chats it already has are kept; yours are added beside them.

``clean`` (as you) removes the staging folder afterwards.

What moves, from the map of Thomas's stores: chat history (sessions_v2, legacy
chats, budget, attachments), long-term memory, preferences (thomas.db), the
guardrails policy, goals and schedules, workspaces, channels, feedback, and the
list of linked projects. What does not: locks (serve.lock would make the caged
server kill your server's process), the Praxis run store (it would resume your
unfinished runs), browser profiles, green copies, caches, logs, and secrets (DPAPI
ties them to your account; the Codex sign-in is shared through .codex already).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGING = REPO_ROOT / "runtime" / "cage-move"

MEMORY_FILES = ("chat_budget.json", "schedules.json", "channels.json", "feedback.jsonl")
MEMORY_DIRS = ("sessions_v2", "chats")
MEMORY_DBS = ("memory_fabric_v2.sqlite3", "workspaces.sqlite3")
DATA_FILES = ("guardrails_policy.json", "thomas_state.json", ".thomas/linked_projects.json")
DATA_DBS = ("thomas.db", "runtime/chat-attachments.sqlite3")


def _backup_db(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def stage(data_dir: Path, memory_dir: Path, staging: Path = STAGING) -> dict[str, int]:
    """Copy your stores into *staging*: ``data/...`` and ``memory/...``. Returns counts."""
    counts = {"files": 0, "databases": 0}
    for rel in DATA_FILES:
        if (data_dir / rel).is_file():
            (staging / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(data_dir / rel, staging / "data" / rel)
            counts["files"] += 1
    for rel in DATA_DBS:
        if (data_dir / rel).is_file():
            _backup_db(data_dir / rel, staging / "data" / rel)
            counts["databases"] += 1
    for rel in MEMORY_FILES:
        if (memory_dir / rel).is_file():
            (staging / "memory").mkdir(parents=True, exist_ok=True)
            shutil.copy2(memory_dir / rel, staging / "memory" / rel)
            counts["files"] += 1
    for rel in MEMORY_DIRS:
        for item in sorted((memory_dir / rel).glob("*.json")) if (memory_dir / rel).is_dir() else []:
            (staging / "memory" / rel).mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, staging / "memory" / rel / item.name)
            counts["files"] += 1
    for rel in MEMORY_DBS:
        if (memory_dir / rel).is_file():
            _backup_db(memory_dir / rel, staging / "memory" / rel)
            counts["databases"] += 1
    return counts


def _place(source: Path, target: Path, backup: Path, *, keep_existing: bool) -> str:
    if target.exists():
        if keep_existing:
            return "kept"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return "placed"


def install(data_dir: Path, memory_dir: Path, staging: Path = STAGING) -> dict[str, int]:
    """Copy *staging* into this account's own stores. Chats it already has win."""
    counts = {"placed": 0, "kept": 0}
    backup = data_dir / "pre-move-backup"
    for side, root in (("data", data_dir), ("memory", memory_dir)):
        base = staging / side
        for source in sorted(p for p in base.rglob("*") if p.is_file()) if base.is_dir() else []:
            rel = source.relative_to(base)
            chat = rel.parts[0] in MEMORY_DIRS
            outcome = _place(source, root / rel, backup / side / rel, keep_existing=chat)
            counts[outcome] += 1
    return counts


def _roots_for_this_account() -> tuple[Path, Path]:
    sys.path.insert(0, str(REPO_ROOT))
    from thomas.core.config import resolve_thomas_data_dir

    data = resolve_thomas_data_dir()
    memory = Path(os.environ.get("THOMAS_MEMORY_ROOT") or data / "runtime") / ".thomas"
    return data, memory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Move your Thomas data into the caged Thomas.")
    parser.add_argument("step", choices=("stage", "install", "clean"))
    parser.add_argument("--data-dir", default="", help="default: this account's Thomas data folder")
    parser.add_argument("--memory-dir", default="", help="stage: your memory (repo runtime/.thomas)")
    args = parser.parse_args(argv)
    if args.step == "clean":
        shutil.rmtree(STAGING, ignore_errors=True)
        print(json.dumps({"cleaned": not STAGING.exists()}))
        return 0
    data, memory = _roots_for_this_account()
    data = Path(args.data_dir) if args.data_dir else data
    if args.step == "stage":
        memory = Path(args.memory_dir) if args.memory_dir else REPO_ROOT / "runtime" / ".thomas"
        print(json.dumps(stage(data, memory)))
    else:
        memory = Path(args.memory_dir) if args.memory_dir else memory
        print(json.dumps(install(data, memory)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
