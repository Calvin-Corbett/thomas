#!/usr/bin/env python3
"""Manage WORKBOARD blocker issues and up-for-grabs task transitions."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

try:
    from scripts import check_workboard_claims as claims_gate
except Exception:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
NONE_ENTRY = "- none"


def _normalize_key(value: str) -> str:
    return str(value or "").strip().lower()


def _sanitize_field(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if ";" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} cannot include ';' or newline characters")
    return cleaned


def _normalize_scope_token(scope: str) -> str:
    token = str(scope or "").strip().replace("\\", "/")
    if token.startswith("./"):
        token = token[2:]
    while "//" in token:
        token = token.replace("//", "/")
    return token.rstrip("/")


def _normalize_scope_value(scope_value: str) -> str:
    raw = _sanitize_field("scope", scope_value)
    scopes: list[str] = []
    for token in raw.split(","):
        normalized = _normalize_scope_token(token)
        if normalized:
            scopes.append(normalized)
    if not scopes:
        raise ValueError("scope must contain at least one non-empty path")
    return ",".join(scopes)


def _default_issue_id(task_id: str, existing_issue_ids: list[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", str(task_id or "").strip().lower()).strip("-")
    if not base:
        base = "task"
    candidate = f"{base}-issue"
    seen = {_normalize_key(item) for item in existing_issue_ids}
    if _normalize_key(candidate) not in seen:
        return candidate
    suffix = 2
    while True:
        candidate = f"{base}-issue-{suffix}"
        if _normalize_key(candidate) not in seen:
            return candidate
        suffix += 1


def _format_issue(
    *,
    issue_id: str,
    task_id: str,
    reporter: str,
    owner: str,
    state: str,
    summary: str,
) -> str:
    issue_id_clean = _sanitize_field("issue_id", issue_id)
    task_id_clean = _sanitize_field("task_id", task_id)
    reporter_clean = _sanitize_field("reporter", reporter)
    owner_clean = _sanitize_field("owner", owner)
    state_clean = _sanitize_field("state", state).lower()
    if state_clean not in claims_gate.ISSUE_STATES:
        allowed = ", ".join(claims_gate.ISSUE_STATES)
        raise ValueError(f"state must be one of: {allowed}")
    summary_clean = _sanitize_field("summary", summary)
    return (
        f"- issue_id={issue_id_clean}; task_id={task_id_clean}; reporter={reporter_clean}; "
        f"owner={owner_clean}; state={state_clean}; summary={summary_clean}"
    )


def _format_active_task(
    *,
    task_id: str,
    agent: str,
    scope: str,
    summary: str,
    status: str,
) -> str:
    task_id_clean = _sanitize_field("task_id", task_id)
    agent_clean = _sanitize_field("agent", agent)
    scope_clean = _normalize_scope_value(scope)
    summary_clean = _sanitize_field("summary", summary)
    status_clean = _sanitize_field("status", status).lower()
    if status_clean not in claims_gate.ACTIVE_TASK_STATES:
        allowed = ", ".join(claims_gate.ACTIVE_TASK_STATES)
        raise ValueError(f"status must be one of: {allowed}")
    return (
        f"- task_id={task_id_clean}; agent={agent_clean}; scope={scope_clean}; "
        f"summary={summary_clean}; status={status_clean}"
    )


def _format_up_for_grabs(
    *,
    task_id: str,
    scope: str,
    summary: str,
    reported_by: str,
    depends_on: str = "",
) -> str:
    task_id_clean = _sanitize_field("task_id", task_id)
    scope_clean = _normalize_scope_value(scope)
    summary_clean = _sanitize_field("summary", summary)
    reporter_clean = _sanitize_field("reported_by", reported_by)
    line = f"- task_id={task_id_clean}; scope={scope_clean}; " f"summary={summary_clean}; reported_by={reporter_clean}"
    depends_clean = str(depends_on or "").strip()
    if depends_clean:
        line += f"; depends_on={_sanitize_field('depends_on', depends_clean)}"
    return line


def _find_section(lines: Sequence[str], *, heading_prefix: str, heading_label: str) -> tuple[int, int]:
    start: int | None = None
    end = len(lines)
    wanted = str(heading_prefix or "").strip().lower()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if start is None:
                if heading.startswith(wanted):
                    start = idx + 1
            else:
                end = idx
                break
    if start is None:
        raise ValueError(f"missing `## {heading_label}` section in workboard")
    return start, end


def _find_claim_section(lines: Sequence[str]) -> tuple[int, int]:
    return _find_section(lines, heading_prefix="agent claims", heading_label="Agent Claims")


def _find_active_tasks_section(lines: Sequence[str]) -> tuple[int, int]:
    return _find_section(lines, heading_prefix="active tasks", heading_label="Active Tasks")


def _find_issues_section(lines: Sequence[str]) -> tuple[int, int]:
    return _find_section(lines, heading_prefix="issues / blockers", heading_label="Issues / Blockers")


def _find_up_for_grabs_section(lines: Sequence[str]) -> tuple[int, int]:
    return _find_section(lines, heading_prefix="up for grabs", heading_label="Up For Grabs")


def _bullet_indices(lines: Sequence[str], start: int, end: int) -> list[int]:
    out: list[int] = []
    for idx in range(start, end):
        if lines[idx].strip().startswith("- "):
            out.append(idx)
    return out


def _is_none_entry(entry: str) -> bool:
    return str(entry or "").strip().lower() in claims_gate.NONE_TOKENS


def _parse_claim_line(line_no: int, line: str) -> tuple[str | None, dict[str, str] | None, str | None]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected claim bullet entry"
    entry = stripped[2:].strip()
    if _is_none_entry(entry):
        return entry, None, None
    claim, err = claims_gate._parse_claim_entry(line_no, entry)  # type: ignore[attr-defined]
    if err:
        return entry, None, err
    if claim is None:
        return entry, None, None
    return (
        entry,
        {
            "agent": claim.agent,
            "scope": ",".join(claim.scopes),
            "task": claim.task,
        },
        None,
    )


def _parse_active_task_line(line_no: int, line: str) -> tuple[str | None, dict[str, str] | None, str | None]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected active task bullet entry"
    entry = stripped[2:].strip()
    if _is_none_entry(entry):
        return entry, None, None
    task, err = claims_gate._parse_active_task_entry(line_no, entry)  # type: ignore[attr-defined]
    if err:
        return entry, None, err
    if task is None:
        return entry, None, None
    return (
        entry,
        {
            "task_id": task.task_id,
            "agent": task.agent,
            "scope": ",".join(task.scopes),
            "summary": task.summary,
            "status": task.status,
        },
        None,
    )


def _parse_issue_line(line_no: int, line: str) -> tuple[str | None, dict[str, str] | None, str | None]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected issue bullet entry"
    entry = stripped[2:].strip()
    if _is_none_entry(entry):
        return entry, None, None
    issue, err = claims_gate._parse_issue_entry(line_no, entry)  # type: ignore[attr-defined]
    if err:
        return entry, None, err
    if issue is None:
        return entry, None, None
    return (
        entry,
        {
            "issue_id": issue.issue_id,
            "task_id": issue.task_id,
            "reporter": issue.reporter,
            "owner": issue.owner,
            "state": issue.state,
            "summary": issue.summary,
        },
        None,
    )


def _parse_up_for_grabs_line(line_no: int, line: str) -> tuple[str | None, dict[str, str] | None, str | None]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected up-for-grabs bullet entry"
    entry = stripped[2:].strip()
    if _is_none_entry(entry):
        return entry, None, None
    task, err = claims_gate._parse_up_for_grabs_entry(line_no, entry)  # type: ignore[attr-defined]
    if err:
        return entry, None, err
    if task is None:
        return entry, None, None
    return (
        entry,
        {
            "task_id": task.task_id,
            "scope": ",".join(task.scopes),
            "summary": task.summary,
            "reported_by": task.reported_by,
            "depends_on": ",".join(task.depends_on) if task.has_explicit_depends_on else "",
        },
        None,
    )


def _ensure_none_if_empty(lines: list[str], *, section_start: int, section_end: int) -> None:
    bullet_idxs = _bullet_indices(lines, section_start, section_end)
    has_non_none = False
    for idx in bullet_idxs:
        entry = lines[idx].strip()[2:].strip()
        if not _is_none_entry(entry):
            has_non_none = True
            break
    if has_non_none:
        for idx in sorted(bullet_idxs, reverse=True):
            entry = lines[idx].strip()[2:].strip()
            if _is_none_entry(entry):
                del lines[idx]
        return

    for idx in sorted(bullet_idxs, reverse=True):
        del lines[idx]
    lines.insert(section_end - len(bullet_idxs), NONE_ENTRY)


def _validate_and_write(
    workboard_path: Path,
    original_text: str,
    new_text: str,
    *,
    require_claims_to_have_active_task: bool = True,
) -> tuple[bool, list[str]]:
    def _is_blocked_task_issue_violation(message: str) -> bool:
        return str(message).strip().startswith(
            "blocked task `"
        ) and "must have an open/triaged entry in `## Issues / Blockers`" in str(message)

    workboard_path.write_text(new_text, encoding="utf-8")
    violations, _ = claims_gate.evaluate_claims(
        workboard_path,
        require_claims_to_have_active_task=require_claims_to_have_active_task,
    )
    if not require_claims_to_have_active_task:
        violations = [item for item in violations if not _is_blocked_task_issue_violation(item)]
    if violations:
        workboard_path.write_text(original_text, encoding="utf-8")
        return False, violations
    return True, []


def _set_task_status(lines: list[str], *, task_id: str, status: str) -> tuple[bool, str, dict[str, str] | None]:
    section_start, section_end = _find_active_tasks_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)
    task_idx: int | None = None
    task_fields: dict[str, str] | None = None
    task_key = _normalize_key(task_id)
    for idx in bullet_idxs:
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err, None
        if entry is not None and _is_none_entry(entry):
            continue
        if not fields:
            continue
        if _normalize_key(fields.get("task_id", "")) == task_key:
            if task_idx is not None:
                return False, f"duplicate active task entries found for `{task_id}`", None
            task_idx = idx
            task_fields = dict(fields)

    if task_idx is None or task_fields is None:
        return False, f"active task `{task_id}` not found", None

    task_fields["status"] = status
    lines[task_idx] = _format_active_task(
        task_id=task_fields["task_id"],
        agent=task_fields["agent"],
        scope=task_fields["scope"],
        summary=task_fields["summary"],
        status=task_fields["status"],
    )
    return True, "updated task status", task_fields


def _upsert_issue(
    lines: list[str],
    *,
    task_id: str,
    reporter: str,
    owner: str,
    summary: str,
    issue_id: str | None,
    state: str,
) -> tuple[bool, str, str]:
    section_start, section_end = _find_issues_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)
    none_idxs: list[int] = []
    existing_ids: list[str] = []
    target_idx: int | None = None
    target_fields: dict[str, str] | None = None
    task_key = _normalize_key(task_id)
    issue_key = _normalize_key(issue_id or "")

    for idx in bullet_idxs:
        entry, fields, err = _parse_issue_line(idx + 1, lines[idx])
        if err:
            return False, err, ""
        if entry is not None and _is_none_entry(entry):
            none_idxs.append(idx)
            continue
        if not fields:
            continue
        existing_ids.append(fields["issue_id"])
        if issue_key and _normalize_key(fields["issue_id"]) == issue_key:
            target_idx = idx
            target_fields = dict(fields)
            continue
        if not issue_key and _normalize_key(fields["task_id"]) == task_key and target_idx is None:
            target_idx = idx
            target_fields = dict(fields)

    chosen_issue_id = issue_id or _default_issue_id(task_id, existing_ids)
    if target_idx is not None and target_fields is not None:
        target_fields["issue_id"] = chosen_issue_id
        target_fields["task_id"] = _sanitize_field("task_id", task_id)
        target_fields["reporter"] = _sanitize_field("reporter", reporter)
        target_fields["owner"] = _sanitize_field("owner", owner)
        target_fields["summary"] = _sanitize_field("summary", summary)
        target_fields["state"] = _sanitize_field("state", state).lower()
        lines[target_idx] = _format_issue(
            issue_id=target_fields["issue_id"],
            task_id=target_fields["task_id"],
            reporter=target_fields["reporter"],
            owner=target_fields["owner"],
            state=target_fields["state"],
            summary=target_fields["summary"],
        )
        return True, "updated issue entry", chosen_issue_id

    for idx in sorted(none_idxs, reverse=True):
        del lines[idx]
        if idx < section_end:
            section_end -= 1
    lines.insert(
        section_end,
        _format_issue(
            issue_id=chosen_issue_id,
            task_id=task_id,
            reporter=reporter,
            owner=owner,
            state=state,
            summary=summary,
        ),
    )
    return True, "added issue entry", chosen_issue_id


def block_task(
    workboard_path: Path,
    *,
    task_id: str,
    reporter: str,
    summary: str,
    owner: str,
    issue_id: str | None,
) -> tuple[bool, str, str]:
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()

    ok, msg, _ = _set_task_status(lines, task_id=task_id, status="blocked")
    if not ok:
        return False, msg, ""
    issue_ok, issue_msg, chosen_issue_id = _upsert_issue(
        lines,
        task_id=task_id,
        reporter=reporter,
        owner=owner,
        summary=summary,
        issue_id=issue_id,
        state="open",
    )
    if not issue_ok:
        return False, issue_msg, ""

    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    write_ok, violations = _validate_and_write(workboard_path, original_text, new_text)
    if not write_ok:
        return False, f"issue update rejected by gate: {'; '.join(violations)}", ""
    return True, f"{msg}; {issue_msg}", chosen_issue_id


def triage_issue(
    workboard_path: Path,
    *,
    issue_id: str,
    owner: str | None,
    summary: str | None,
) -> tuple[bool, str]:
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()

    section_start, section_end = _find_issues_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)
    issue_idx: int | None = None
    issue_fields: dict[str, str] | None = None
    issue_key = _normalize_key(issue_id)
    for idx in bullet_idxs:
        entry, fields, err = _parse_issue_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and _is_none_entry(entry):
            continue
        if not fields:
            continue
        if _normalize_key(fields["issue_id"]) == issue_key:
            issue_idx = idx
            issue_fields = dict(fields)
            break

    if issue_idx is None or issue_fields is None:
        return False, f"issue `{issue_id}` not found"

    issue_fields["state"] = "triaged"
    if owner:
        issue_fields["owner"] = _sanitize_field("owner", owner)
    if summary:
        issue_fields["summary"] = _sanitize_field("summary", summary)
    lines[issue_idx] = _format_issue(
        issue_id=issue_fields["issue_id"],
        task_id=issue_fields["task_id"],
        reporter=issue_fields["reporter"],
        owner=issue_fields["owner"],
        state=issue_fields["state"],
        summary=issue_fields["summary"],
    )

    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    write_ok, violations = _validate_and_write(workboard_path, original_text, new_text)
    if not write_ok:
        return False, f"issue update rejected by gate: {'; '.join(violations)}"
    return True, f"triaged issue `{issue_fields['issue_id']}`"


def _find_issue_by_selector(
    lines: list[str],
    *,
    issue_id: str | None,
    task_id: str | None,
) -> tuple[int | None, dict[str, str] | None, str | None]:
    section_start, section_end = _find_issues_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)
    issue_key = _normalize_key(issue_id or "")
    task_key = _normalize_key(task_id or "")

    candidates: list[tuple[int, dict[str, str]]] = []
    for idx in bullet_idxs:
        entry, fields, err = _parse_issue_line(idx + 1, lines[idx])
        if err:
            return None, None, err
        if entry is not None and _is_none_entry(entry):
            continue
        if not fields:
            continue
        if issue_key:
            if _normalize_key(fields["issue_id"]) == issue_key:
                return idx, dict(fields), None
            continue
        if task_key and _normalize_key(fields["task_id"]) == task_key:
            candidates.append((idx, dict(fields)))

    if issue_key:
        return None, None, f"issue `{issue_id}` not found"
    if task_key:
        if not candidates:
            return None, None, f"no issue found for task `{task_id}`"
        for idx, fields in candidates:
            if fields.get("state") in {"open", "triaged"}:
                return idx, fields, None
        return candidates[0][0], candidates[0][1], None
    return None, None, "issue selector is required"


def resolve_issue(
    workboard_path: Path,
    *,
    issue_id: str | None,
    task_id: str | None,
) -> tuple[bool, str]:
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()

    issue_idx, issue_fields, err = _find_issue_by_selector(lines, issue_id=issue_id, task_id=task_id)
    if err:
        return False, err
    if issue_idx is None or issue_fields is None:
        return False, "issue not found"

    issue_fields["state"] = "resolved"
    lines[issue_idx] = _format_issue(
        issue_id=issue_fields["issue_id"],
        task_id=issue_fields["task_id"],
        reporter=issue_fields["reporter"],
        owner=issue_fields["owner"],
        state=issue_fields["state"],
        summary=issue_fields["summary"],
    )

    _set_task_status(lines, task_id=issue_fields["task_id"], status="in_progress")

    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    write_ok, violations = _validate_and_write(workboard_path, original_text, new_text)
    if not write_ok:
        return False, f"issue update rejected by gate: {'; '.join(violations)}"
    return True, f"resolved issue `{issue_fields['issue_id']}`"


def move_task_to_up_for_grabs(
    workboard_path: Path,
    *,
    task_id: str,
    reported_by: str,
    summary: str | None,
) -> tuple[bool, str]:
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()

    task_section_start, task_section_end = _find_active_tasks_section(lines)
    bullet_idxs = _bullet_indices(lines, task_section_start, task_section_end)
    task_idx: int | None = None
    task_fields: dict[str, str] | None = None
    task_key = _normalize_key(task_id)
    for idx in bullet_idxs:
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and _is_none_entry(entry):
            continue
        if not fields:
            continue
        if _normalize_key(fields["task_id"]) == task_key:
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

    task_section_start, task_section_end = _find_active_tasks_section(lines)
    _ensure_none_if_empty(lines, section_start=task_section_start, section_end=task_section_end)

    remaining_tasks_for_agent = 0
    task_section_start, task_section_end = _find_active_tasks_section(lines)
    for idx in _bullet_indices(lines, task_section_start, task_section_end):
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and _is_none_entry(entry):
            continue
        if fields and _normalize_key(fields["agent"]) == _normalize_key(moved_agent):
            remaining_tasks_for_agent += 1

    if remaining_tasks_for_agent == 0:
        claim_section_start, claim_section_end = _find_claim_section(lines)
        claim_remove: list[int] = []
        for idx in _bullet_indices(lines, claim_section_start, claim_section_end):
            entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
            if err:
                return False, err
            if entry is not None and _is_none_entry(entry):
                continue
            if fields and _normalize_key(fields["agent"]) == _normalize_key(moved_agent):
                claim_remove.append(idx)
        for idx in sorted(claim_remove, reverse=True):
            del lines[idx]
        claim_section_start, claim_section_end = _find_claim_section(lines)
        _ensure_none_if_empty(lines, section_start=claim_section_start, section_end=claim_section_end)

    grabs_section_start, grabs_section_end = _find_up_for_grabs_section(lines)
    grab_idx: int | None = None
    none_idxs: list[int] = []
    for idx in _bullet_indices(lines, grabs_section_start, grabs_section_end):
        entry, fields, err = _parse_up_for_grabs_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and _is_none_entry(entry):
            none_idxs.append(idx)
            continue
        if fields and _normalize_key(fields["task_id"]) == task_key:
            grab_idx = idx
            break

    grab_line = _format_up_for_grabs(
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
    write_ok, violations = _validate_and_write(workboard_path, original_text, new_text)
    if not write_ok:
        return False, f"issue update rejected by gate: {'; '.join(violations)}"
    return True, f"moved task `{moved_task_id}` to up-for-grabs"


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage blocked-task issues and up-for-grabs transitions in WORKBOARD.md."
    )
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help="Path to workboard markdown file (default: plans/thomas/WORKBOARD.md)",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--block", action="store_true", help="Mark active task blocked and open/update issue.")
    action.add_argument("--triage", action="store_true", help="Set issue state to triaged.")
    action.add_argument("--resolve", action="store_true", help="Set issue state to resolved and reactivate task.")
    action.add_argument(
        "--up-for-grabs",
        action="store_true",
        help="Move active task into `## Up For Grabs` and release agent claim if it has no remaining tasks.",
    )

    parser.add_argument("--task-id", default="", help="Task identifier.")
    parser.add_argument("--issue-id", default="", help="Issue identifier.")
    parser.add_argument("--reporter", default="", help="Issue reporter.")
    parser.add_argument("--owner", default="", help="Issue owner (defaults to unassigned for --block).")
    parser.add_argument("--summary", default="", help="Issue/task summary override.")
    parser.add_argument("--reported-by", default="", help="Reporter for --up-for-grabs.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    if not workboard_path.exists():
        message = f"missing workboard file: {workboard_path}"
        if args.json:
            print(
                json.dumps(
                    {"action": "workboard_issue", "ok": False, "workboard": str(workboard_path), "error": message},
                    sort_keys=True,
                )
            )
        else:
            print("Workboard issue tool: FAIL")
            print(f"- {message}")
        return 1

    try:
        if args.block:
            task_id = _sanitize_field("task_id", args.task_id)
            reporter = _sanitize_field("reporter", args.reporter)
            summary = _sanitize_field("summary", args.summary)
            owner = _sanitize_field("owner", args.owner or "unassigned")
            issue_id = str(args.issue_id or "").strip() or None
            ok, message, chosen_issue_id = block_task(
                workboard_path,
                task_id=task_id,
                reporter=reporter,
                summary=summary,
                owner=owner,
                issue_id=issue_id,
            )
            payload = {
                "action": "block",
                "ok": ok,
                "workboard": str(workboard_path),
                "task_id": task_id,
                "issue_id": chosen_issue_id or issue_id or "",
            }
            if ok:
                payload["message"] = message
            else:
                payload["error"] = message

        elif args.triage:
            issue_id = _sanitize_field("issue_id", args.issue_id)
            owner = str(args.owner or "").strip() or None
            summary = str(args.summary or "").strip() or None
            ok, message = triage_issue(workboard_path, issue_id=issue_id, owner=owner, summary=summary)
            payload = {
                "action": "triage",
                "ok": ok,
                "workboard": str(workboard_path),
                "issue_id": issue_id,
            }
            if ok:
                payload["message"] = message
            else:
                payload["error"] = message

        elif args.resolve:
            issue_id = str(args.issue_id or "").strip() or None
            task_id = str(args.task_id or "").strip() or None
            if not issue_id and not task_id:
                raise ValueError("issue_id or task_id is required for --resolve")
            ok, message = resolve_issue(workboard_path, issue_id=issue_id, task_id=task_id)
            payload = {
                "action": "resolve",
                "ok": ok,
                "workboard": str(workboard_path),
                "issue_id": issue_id or "",
                "task_id": task_id or "",
            }
            if ok:
                payload["message"] = message
            else:
                payload["error"] = message

        else:
            task_id = _sanitize_field("task_id", args.task_id)
            reported_by = _sanitize_field("reported_by", args.reported_by)
            summary = str(args.summary or "").strip() or None
            ok, message = move_task_to_up_for_grabs(
                workboard_path,
                task_id=task_id,
                reported_by=reported_by,
                summary=summary,
            )
            payload = {
                "action": "up_for_grabs",
                "ok": ok,
                "workboard": str(workboard_path),
                "task_id": task_id,
            }
            if ok:
                payload["message"] = message
            else:
                payload["error"] = message

    except ValueError as exc:
        payload = {
            "action": "workboard_issue",
            "ok": False,
            "workboard": str(workboard_path),
            "error": str(exc),
        }

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        if payload.get("ok"):
            print("Workboard issue tool: PASS")
            print(f"- {payload.get('message', '')}")
        else:
            print("Workboard issue tool: FAIL")
            print(f"- {payload.get('error', 'unknown error')}")

    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(run())
