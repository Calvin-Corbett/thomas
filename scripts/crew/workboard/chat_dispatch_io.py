#!/usr/bin/env python3
"""Transactional WORKBOARD APIs used by the protected chat dispatcher."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.workboard import board_io
from scripts.crew.workboard import issue as workboard_issue
from scripts.crew.workboard import message as workboard_message


@board_io.transaction
def queue_task(
    workboard_path: Path,
    *,
    task_id: str,
    summary: str,
    scope: str = "chat",
    reported_by: str = "thomas",
) -> tuple[bool, str]:
    """Insert or update one canonical up-for-grabs task atomically."""
    task_clean = workboard_issue._sanitize_field("task_id", task_id)  # type: ignore[attr-defined]
    scope_clean = workboard_issue._normalize_scope_value(scope or "chat")  # type: ignore[attr-defined]
    summary_clean = workboard_issue._sanitize_field("summary", summary)  # type: ignore[attr-defined]
    reporter_clean = workboard_issue._sanitize_field("reported_by", reported_by)  # type: ignore[attr-defined]

    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    section_start, section_end = workboard_issue._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]
    matching_idx: int | None = None
    none_idxs: list[int] = []
    for idx in workboard_issue._bullet_indices(lines, section_start, section_end):  # type: ignore[attr-defined]
        entry, fields, error = workboard_issue._parse_up_for_grabs_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if error:
            return False, error
        if entry is not None and workboard_issue._is_none_entry(entry):  # type: ignore[attr-defined]
            none_idxs.append(idx)
            continue
        if fields and workboard_issue._normalize_key(fields.get("task_id", "")) == workboard_issue._normalize_key(  # type: ignore[attr-defined]
            task_clean
        ):
            matching_idx = idx

    row = workboard_issue._format_up_for_grabs(  # type: ignore[attr-defined]
        task_id=task_clean,
        scope=scope_clean,
        summary=summary_clean,
        reported_by=reporter_clean,
    )
    if matching_idx is not None:
        lines[matching_idx] = row
    else:
        for idx in sorted(none_idxs, reverse=True):
            del lines[idx]
            if idx < section_end:
                section_end -= 1
        lines.insert(section_end, row)

    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    ok, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path,
        original_text,
        new_text,
    )
    if not ok:
        return False, "chat task queue rejected by gate: " + "; ".join(violations)
    return True, f"queued task `{task_clean}`"


def send_dispatch_message(
    workboard_path: Path,
    *,
    task_id: str,
    summary: str,
    sender: str = "thomas",
    recipient: str = "task-manager-agent",
) -> tuple[bool, dict[str, object]]:
    """Send the chat dispatch notice through the shared message transaction."""
    return workboard_message.send_message(
        workboard_path,
        sender=sender,
        recipient=recipient,
        task_id=task_id,
        kind="coordination",
        priority="p1",
        summary=f"New task from chat: {summary}",
        requested_action="dispatch",
        decision="pending",
    )
