#!/usr/bin/env python3
"""Create a simple reminder note in Thomas's research library."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

from thomas.library.store import ResearchLibrary

ROOT = Path(__file__).resolve().parent.parent
_MAKE_NOTE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(?:please\s+)?make(?:\s+me)?\s+a\s+note\s+that\s+says\s+(.+?)\s*$", re.I),
    re.compile(r"^\s*(?:please\s+)?make(?:\s+me)?\s+a\s+note\s+saying\s+(.+?)\s*$", re.I),
    re.compile(r"^\s*(?:please\s+)?make(?:\s+me)?\s+a\s+note\s+(.+?)\s*$", re.I),
)


def _clean_note_text(text: str) -> str:
    note = str(text or "").strip()
    if not note:
        return ""
    if note[-1:] in {".", "!", "?"}:
        note = note[:-1].rstrip()
    if len(note) >= 2 and note[0] == note[-1] and note[0] in {'"', "'"}:
        note = note[1:-1].strip()
    return note.strip()


def extract_note_text(summary: str) -> str:
    prompt = str(summary or "").strip()
    for pattern in _MAKE_NOTE_PATTERNS:
        match = pattern.match(prompt)
        if match:
            return _clean_note_text(match.group(1))
    return ""


def save_note(
    *,
    note_text: str,
    query: str,
    task_id: str = "",
    repo_root: Path = ROOT,
) -> dict[str, object]:
    library = ResearchLibrary((Path(repo_root).resolve() / "library"))
    source = "thomas:task-bot"
    if str(task_id or "").strip():
        source = f"{source}:{str(task_id).strip()}"
    return library.add_entry(
        title=note_text,
        category="research-notes",
        content=note_text,
        summary="Reminder note saved.",
        source=source,
        tags=["note", "reminder", "task-bot"],
        query=str(query or "").strip(),
        auto_captured=False,
        dedupe=True,
    )


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a reminder note from a chat task summary.")
    parser.add_argument("--summary", default="", help="Original chat task summary.")
    parser.add_argument("--content", default="", help="Exact note content override.")
    parser.add_argument("--task-id", default="", help="Optional task id for provenance.")
    parser.add_argument("--repo-root", default=str(ROOT), help="Thomas repo root.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    note_text = _clean_note_text(str(args.content or "").strip()) or extract_note_text(str(args.summary or ""))
    if not note_text:
        payload = {
            "ok": False,
            "error": "unable to extract note content from summary",
            "summary": str(args.summary or ""),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(payload["error"])
        return 1

    row = save_note(
        note_text=note_text,
        query=str(args.summary or note_text),
        task_id=str(args.task_id or ""),
        repo_root=Path(str(args.repo_root or ROOT)),
    )
    payload = {"ok": True, "note_text": note_text, "entry": row}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"Saved note: {row.get('id')} -> {row.get('path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
