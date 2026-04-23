#!/usr/bin/env python3
"""Workboard Markdown section parsing helpers."""

from __future__ import annotations

from collections.abc import Sequence

NONE_ENTRY = "- none"
ACTIVE_TASK_HEADING_PREFIX = "active tasks"
ACTIVE_TASK_HEADING_LABEL = "Active Tasks"


def _find_section(
    lines: Sequence[str],
    *,
    heading_prefix: str,
    heading_label: str,
) -> tuple[int, int]:
    start = 0
    end = len(lines)
    for idx, line in enumerate(lines):
        normalized = line.strip().lower()
        if normalized.startswith(f"## {heading_prefix}"):
            start = idx + 1
            break
    for idx in range(start, len(lines)):
        normalized = lines[idx].strip().lower()
        if normalized.startswith("## ") and not normalized.startswith(f"## {heading_prefix}"):
            end = idx
            break
    return start, end


def _find_claim_section(lines: Sequence[str]) -> tuple[int, int]:
    for idx, line in enumerate(lines):
        normalized = line.strip().lower()
        if normalized.startswith("## agent claims") or normalized.startswith("## active claims"):
            end = len(lines)
            for follow_idx in range(idx + 1, len(lines)):
                next_line = lines[follow_idx].strip().lower()
                if (
                    next_line.startswith("## ")
                    and not next_line.startswith("## agent claims")
                    and not next_line.startswith("## active claims")
                ):
                    end = follow_idx
                    break
            return idx + 1, end
    return _find_section(lines, heading_prefix="active claims", heading_label="Active Claims")


def _find_active_tasks_section(lines: Sequence[str]) -> tuple[int, int]:
    return _find_section(lines, heading_prefix=ACTIVE_TASK_HEADING_PREFIX, heading_label=ACTIVE_TASK_HEADING_LABEL)


def _find_issues_section(lines: Sequence[str]) -> tuple[int, int]:
    return _find_section(lines, heading_prefix="issues", heading_label="Issues / Blockers")


def _ensure_active_tasks_section(lines: list[str]) -> tuple[int, int]:
    section = _find_active_tasks_section(lines)
    if section[0] > 0 and section[0] < len(lines):
        return section
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith("## issues"):
            lines.insert(idx, f"## {ACTIVE_TASK_HEADING_LABEL}\n")
            lines.insert(idx + 1, NONE_ENTRY + "\n")
            return idx + 1, idx + 2
    lines.append(f"## {ACTIVE_TASK_HEADING_LABEL}\n")
    lines.append(NONE_ENTRY + "\n")
    return len(lines) - 1, len(lines)


def _bullet_indices(lines: Sequence[str], start: int, end: int) -> list[int]:
    indices: list[int] = []
    for idx in range(start, min(end, len(lines))):
        if lines[idx].strip().startswith("-"):
            indices.append(idx)
    return indices


def _parse_claim_line(line_no: int, line: str) -> tuple[str | None, dict[str, str], str]:
    line = line.strip()
    if not line.startswith("-"):
        return None, {}, ""
    line = line[1:].strip()
    if line == NONE_ENTRY.split("-", 1)[1].strip():
        return None, {}, ""
    fields = {}
    for segment in line.split(";"):
        segment = segment.strip()
        if "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        key = key.strip()
        value = value.strip().strip("`").strip("'").strip('"')
        fields[key] = value
    agent = fields.get("agent", "")
    if not agent:
        return None, {}, f"claim line {line_no} is missing agent"
    return agent, fields, ""


def _parse_active_task_line(line_no: int, line: str) -> tuple[str | None, dict[str, str], str]:
    line = line.strip()
    if not line.startswith("-"):
        return None, {}, ""
    line = line[1:].strip()
    if line == NONE_ENTRY.split("-", 1)[1].strip():
        return None, {}, ""
    fields = {}
    for segment in line.split(";"):
        segment = segment.strip()
        if "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        key = key.strip()
        value = value.strip().strip("`").strip("'").strip('"')
        fields[key] = value
    task_id = fields.get("task_id", "") or fields.get("task", "")
    if not task_id:
        return None, {}, f"active task line {line_no} is missing task_id"
    return task_id, fields, ""


def _parse_issue_line(line_no: int, line: str) -> tuple[str | None, dict[str, str], str]:
    line = line.strip()
    if not line.startswith("-"):
        return None, {}, ""
    line = line[1:].strip()
    if line == NONE_ENTRY.split("-", 1)[1].strip():
        return None, {}, ""
    fields = {}
    for segment in line.split(";"):
        segment = segment.strip()
        if "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        key = key.strip()
        value = value.strip().strip("`").strip("'").strip('"')
        fields[key] = value
    task_id = fields.get("task", "")
    if not task_id:
        return None, {}, f"issue line {line_no} is missing task"
    return task_id, fields, ""
