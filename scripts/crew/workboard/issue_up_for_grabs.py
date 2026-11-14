#!/usr/bin/env python3
"""Move an active workboard task to `## Up For Grabs`.

Moved out of ``issue.py`` unchanged (it calls the same helpers through the ``issue`` module, so a stand-in for one of
them still takes effect); ``issue.move_task_to_up_for_grabs`` forwards here. ``issue.py`` was over the 800-line soft
limit, which refuses every edit to a file that is not on the baseline."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.workboard import issue as _issue  # noqa: E402


def move_task_to_up_for_grabs(
    workboard_path: Path,
    *,
    task_id: str,
    reported_by: str,
    summary: str | None,
) -> tuple[bool, str]:
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()

    task_section_start, task_section_end = _issue._find_active_tasks_section(lines)
    bullet_idxs = _issue._bullet_indices(lines, task_section_start, task_section_end)
    task_idx: int | None = None
    task_fields: dict[str, str] | None = None
    task_key = _issue._normalize_key(task_id)
    for idx in bullet_idxs:
        entry, fields, err = _issue._parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and _issue._is_none_entry(entry):
            continue
        if not fields:
            continue
        if _issue._normalize_key(fields["task_id"]) == task_key:
            task_idx = idx
            task_fields = dict(fields)
            break

    if task_idx is None or task_fields is None:
        return False, f"active task `{task_id}` not found"

    moved_task_id = task_fields["task_id"]
    moved_agent = task_fields["agent"]
    moved_scope = task_fields["scope"]
    moved_summary = summary if summary else task_fields["summary"]
    del lines[task_idx]

    task_section_start, task_section_end = _issue._find_active_tasks_section(lines)
    _issue._ensure_none_if_empty(lines, section_start=task_section_start, section_end=task_section_end)

    remaining_tasks_for_agent = 0
    task_section_start, task_section_end = _issue._find_active_tasks_section(lines)
    for idx in _issue._bullet_indices(lines, task_section_start, task_section_end):
        entry, fields, err = _issue._parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and _issue._is_none_entry(entry):
            continue
        if fields and _issue._normalize_key(fields["agent"]) == _issue._normalize_key(moved_agent):
            remaining_tasks_for_agent += 1

    if remaining_tasks_for_agent == 0:
        claim_section_start, claim_section_end = _issue._find_claim_section(lines)
        claim_remove: list[int] = []
        for idx in _issue._bullet_indices(lines, claim_section_start, claim_section_end):
            entry, fields, err = _issue._parse_claim_line(idx + 1, lines[idx])
            if err:
                return False, err
            if entry is not None and _issue._is_none_entry(entry):
                continue
            if fields and _issue._normalize_key(fields["agent"]) == _issue._normalize_key(moved_agent):
                claim_remove.append(idx)
        for idx in sorted(claim_remove, reverse=True):
            del lines[idx]
        claim_section_start, claim_section_end = _issue._find_claim_section(lines)
        _issue._ensure_none_if_empty(lines, section_start=claim_section_start, section_end=claim_section_end)

    grabs_section_start, grabs_section_end = _issue._find_up_for_grabs_section(lines)
    grab_idx: int | None = None
    none_idxs: list[int] = []
    for idx in _issue._bullet_indices(lines, grabs_section_start, grabs_section_end):
        entry, fields, err = _issue._parse_up_for_grabs_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and _issue._is_none_entry(entry):
            none_idxs.append(idx)
            continue
        if fields and _issue._normalize_key(fields["task_id"]) == task_key:
            grab_idx = idx
            break

    grab_line = _issue._format_up_for_grabs(
        task_id=moved_task_id,
        scope=moved_scope,
        summary=moved_summary,
        reported_by=reported_by,
        depends_on="none",
    )
    if grab_idx is not None:
        lines[grab_idx] = grab_line
    else:
        for idx in sorted(none_idxs, reverse=True):
            del lines[idx]
            if idx < grabs_section_end:
                grabs_section_end -= 1
        lines.insert(grabs_section_end, grab_line)

    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    write_ok, violations = _issue._validate_and_write(workboard_path, original_text, new_text)
    if not write_ok:
        return False, f"issue update rejected by gate: {'; '.join(violations)}"
    return True, f"moved task `{moved_task_id}` to up-for-grabs"


def backstop_last(text: str) -> str:
    """`text` with the recurring audit backstop task moved after every other Up For Grabs entry (audit_backstop.py checks it).

    Every board write goes through issue._validate_and_write, so the order holds whichever tool added the task, the issue
    command and brainstorm --dispatch included. Anything else (no backstop, already last, no Up For Grabs section) comes
    back unchanged."""
    lines = text.split("\n")
    try:
        start, end = _issue._find_up_for_grabs_section(lines)
    except ValueError:
        return text
    bullets = _issue._bullet_indices(lines, start, end)
    for idx in bullets:
        _entry, fields, _err = _issue._parse_up_for_grabs_line(idx + 1, lines[idx])
        if fields and _issue._normalize_key(fields.get("task_id", "")) == "audit-24h-backstop":
            if idx != bullets[-1]:
                lines.insert(bullets[-1], lines.pop(idx))  # popping shifted the last bullet up to bullets[-1] - 1
            break
    return "\n".join(lines)
