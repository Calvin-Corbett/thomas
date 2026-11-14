#!/usr/bin/env python3
"""Keep the audit backstop task the last entry of `## Up For Grabs`.

The merge-readiness check (`audit_backstop.py`) fails when the recurring
`audit-24h-backstop` task is anywhere but last in `## Up For Grabs`. Every
board tool that appended a task did so at the end of the section, which put the
new task after the backstop and broke the check on the next push. The tools now
insert before the backstop (`insert_index`), and a tool that cannot be changed
in place (the protected `issue.py`) is called through `move_task_to_up_for_grabs`
here, which restores the order after it returns.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.workboard import issue as workboard_issue

BACKSTOP_TASK_ID = "audit-24h-backstop"


def _is_backstop(lines: Sequence[str], idx: int) -> bool:
    entry, fields, err = workboard_issue._parse_up_for_grabs_line(idx + 1, lines[idx])
    if err or entry is None or not fields:
        return False
    return str(fields.get("task_id", "")).strip().lower() == BACKSTOP_TASK_ID


def _backstop_bullet(lines: Sequence[str], start: int, end: int) -> int | None:
    for idx in workboard_issue._bullet_indices(lines, start, end):
        if _is_backstop(lines, idx):
            return idx
    return None


def insert_index(lines: Sequence[str], start: int, end: int) -> int:
    """Where a new Up For Grabs bullet goes: before the backstop, else at `end`."""
    found = _backstop_bullet(lines, start, end)
    return end if found is None else found


def move_backstop_last(lines: list[str]) -> bool:
    """Move the backstop bullet after every other bullet; True if lines changed."""
    start, end = workboard_issue._find_up_for_grabs_section(lines)
    bullets = workboard_issue._bullet_indices(lines, start, end)
    found = _backstop_bullet(lines, start, end)
    if found is None or not bullets or found == bullets[-1]:
        return False
    row = lines.pop(found)
    # Popping shifted every later line up by one: the last bullet is now at bullets[-1] - 1.
    lines.insert(bullets[-1], row)
    return True


def keep_backstop_last(workboard_path: Path) -> tuple[bool, str]:
    """Restore the backstop-last order in a board file. Adds nothing if it has no backstop."""
    original = workboard_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    if not move_backstop_last(lines):
        return True, "backstop already last"
    new_text = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
    ok, violations = workboard_issue._validate_and_write(workboard_path, original, new_text)
    if not ok:
        return False, "; ".join(violations)
    return True, "backstop moved last"


def move_task_to_up_for_grabs(workboard_path: Path, **kwargs) -> tuple[bool, str]:
    """`issue.move_task_to_up_for_grabs`, then keep the backstop last."""
    ok, message = workboard_issue.move_task_to_up_for_grabs(workboard_path, **kwargs)
    if not ok:
        return ok, message
    ok_order, order_message = keep_backstop_last(workboard_path)
    if not ok_order:
        return False, f"{message}; backstop order not restored: {order_message}"
    return True, message
