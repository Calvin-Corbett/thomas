"""Fit one tool result into the model's context without losing its end.

A test run prints its verdict and its error last, so a cap that keeps only the
start hides exactly the part the model needed. This keeps the start and the end,
says in the middle how much was left out, and saves the whole output to a file in
Thomas's own folder of the project (``.thomas/tool-output/<run>/``, never tracked
by git) so the model can read the rest with ``fs.read_file`` and a line range.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

SPILL_DIR = Path(".thomas") / "tool-output"
# Of the budget left after the marker: the end gets more, since that is where errors are.
_HEAD_SHARE = 0.4
_READ_TOOLS = frozenset({"fs.read_file", "fs_read_file"})
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe(part: str, fallback: str) -> str:
    return (_UNSAFE.sub("_", str(part or "")).strip("._") or fallback)[:80]


def spill_full_output(sandbox_root: Path, run_id: str, call_id: str, text: str) -> str:
    """Write *text* under the sandbox's Thomas folder; the relative path, or "" if it could not be saved."""
    rel = SPILL_DIR / _safe(run_id, "run") / f"{_safe(call_id, 'call')}.txt"
    try:
        base = Path(sandbox_root) / SPILL_DIR
        base.mkdir(parents=True, exist_ok=True)
        ignore = base / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")
        target = Path(sandbox_root) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("Could not save the full tool output to %s: %s", rel, exc)
        return ""
    return rel.as_posix()


def cap_tool_result(
    text: str,
    limit: int,
    *,
    tool_name: str = "",
    sandbox_root: Path | None = None,
    run_id: str = "",
    call_id: str = "",
) -> str:
    """*text* unchanged when it fits; otherwise its head and tail around a marker, never over *limit*."""
    if len(text) <= limit:
        return text
    total_lines = text.count("\n") + 1
    is_read = tool_name in _READ_TOOLS
    saved = "" if is_read or sandbox_root is None else spill_full_output(sandbox_root, run_id, call_id, text)

    def marker(omitted_chars: int, first: int, last: int) -> str:
        lines = f"lines {first}-{last} of {total_lines}" if last >= first else "part of one line"
        head = f"\n\n[... {omitted_chars:,} of {len(text):,} chars omitted ({lines}). "
        if is_read:
            return head + "Read them with fs.read_file on the same path with start_line/end_line. ...]\n\n"
        if saved:
            return head + (
                f"Full output saved to {saved}: read it with fs.read_file "
                f"path={saved} start_line={first} end_line={last}. ...]\n\n"
            )
        return head + "The full output could not be saved. ...]\n\n"

    # Size the marker with the widest numbers it can hold, then split what is left.
    room = max(0, limit - len(marker(len(text), total_lines, total_lines)))
    head_len = int(room * _HEAD_SHARE)
    tail_len = room - head_len
    head, tail = text[:head_len], text[len(text) - tail_len :] if tail_len else ""
    first = head.count("\n") + 1
    last = total_lines - tail.count("\n")
    if not head.endswith("\n"):
        first += 1  # the head's last line is cut off, so it counts as omitted from the next whole one
    out = head + marker(len(text) - head_len - tail_len, first, last) + tail
    return out[:limit]


def sandbox_root_of(loop: object) -> Path | None:
    """The loop's sandbox folder, or None for a loop built without tool config (nothing is then saved)."""
    try:
        return Path(loop.config.tools.sandbox_path)  # type: ignore[attr-defined]
    except (AttributeError, TypeError, OSError, ValueError):
        return None
