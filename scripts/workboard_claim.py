#!/usr/bin/env python3
"""Manage active agent claims in plans/thomas/WORKBOARD.md."""

from __future__ import annotations

import argparse
import fnmatch
import getpass
import json
import os
import re
import subprocess
import time
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts import agent_identity
    from scripts import check_workboard_claims as claims_gate
except Exception:  # pragma: no cover
    import agent_identity  # type: ignore
    import check_workboard_claims as claims_gate  # type: ignore

try:
    from scripts import workboard_message as workboard_message_mod
except Exception:  # pragma: no cover
    try:
        import workboard_message as workboard_message_mod  # type: ignore
    except Exception:  # pragma: no cover
        workboard_message_mod = None  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
COORDINATION_DIR = ROOT / "runtime" / "coordination"
LOCK_FILE = COORDINATION_DIR / "workboard_claim.lock"
RELEASE_OVERRIDE_AUDIT_LOG = COORDINATION_DIR / "workboard_release_override_audit.jsonl"
LOCK_TIMEOUT_SECONDS = 10.0
LOCK_STALE_SECONDS = 60.0
NONE_ENTRY = "- none"
ACTIVE_TASK_HEADING_PREFIX = "active tasks"
ACTIVE_TASK_HEADING_LABEL = "Active Tasks"
CLAIM_ROLE_VALUES = ("solo", "parent", "worker")
DEFAULT_DISPATCH_TARGET_WORKERS = 2
DEFAULT_DISPATCH_MAX_SUGGESTIONS = 5
DEFAULT_DIRTY_RELEASE_REASON_MIN_LEN = 12
DEFAULT_TASK_MANAGER_AGENT = "task-manager-agent"
TEMP_TASK_CREATOR_TASK_TAG = "[temp-task-creator]"
TEMP_TASK_CREATOR_SCOPE = "runtime/coordination/temp-task-creator"
TEMP_TASK_CREATOR_AGENT_PREFIX = "temp-task-creator"
TEMP_TASK_CREATOR_NAME_PREFIX = "Temp-Task-Creator"
TEMP_TASK_CREATOR_RELEASE_REASON = "task manager ended temporary task creator assignment"
_TEMP_TASK_CREATOR_OWNER_PATTERN = re.compile(r"owner=`([^`]+)`", re.IGNORECASE)
_TEMP_TASK_CREATOR_MANAGER_PATTERN = re.compile(r"manager=`([^`]+)`", re.IGNORECASE)


def _agent_key(agent: str) -> str:
    return str(agent or "").strip().lower()


def _normalize_scope_token(scope: str) -> str:
    token = str(scope or "").strip().replace("\\", "/")
    if token.startswith("./"):
        token = token[2:]
    while "//" in token:
        token = token.replace("//", "/")
    return token.rstrip("/")


def _normalize_repo_path(value: str) -> str:
    token = str(value or "").strip().replace("\\", "/")
    while token.startswith("./"):
        token = token[2:]
    while "//" in token:
        token = token.replace("//", "/")
    return token.strip("/")


def _normalize_task_id(value: str) -> str:
    return str(value or "").strip().lower()


def _scope_matches_path(scope: str, rel_path: str) -> bool:
    scope_norm = _normalize_repo_path(scope).lower()
    path_norm = _normalize_repo_path(rel_path).lower()
    if not scope_norm or not path_norm:
        return False
    if scope_norm in {".", "*", "**"}:
        return True
    if any(ch in scope_norm for ch in "*?["):
        if fnmatch.fnmatchcase(path_norm, scope_norm):
            return True
        if scope_norm.endswith("/**"):
            base = scope_norm[:-3].rstrip("/")
            return bool(base) and (path_norm == base or path_norm.startswith(base + "/"))
        return False
    return path_norm == scope_norm or path_norm.startswith(scope_norm + "/")


def _porcelain_path(line: str) -> str:
    raw = str(line or "")
    if len(raw) <= 3:
        return _normalize_repo_path(raw)
    token = raw[3:].strip()
    if " -> " in token:
        token = token.split(" -> ", 1)[1].strip()
    return _normalize_repo_path(token)


def _git_status_porcelain(repo_root: Path = ROOT) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    rows: list[str] = []
    for raw in str(proc.stdout or "").splitlines():
        line = str(raw or "").rstrip()
        if line:
            rows.append(line)
    return rows


def _claimed_scope_dirty_paths(scopes: Sequence[str]) -> dict[str, list[str]]:
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    normalized_scopes = [scope for scope in scopes if _normalize_scope_token(scope)]
    if not normalized_scopes:
        return {"staged": [], "unstaged": [], "untracked": []}

    for line in _git_status_porcelain(ROOT):
        rel_path = _porcelain_path(line)
        if not rel_path:
            continue
        if not any(_scope_matches_path(scope, rel_path) for scope in normalized_scopes):
            continue

        if line.startswith("??"):
            untracked.append(rel_path)
            continue
        if line.startswith("!!"):
            continue

        index_status = line[0] if len(line) > 0 else " "
        worktree_status = line[1] if len(line) > 1 else " "
        if index_status not in (" ", "?", "!"):
            staged.append(rel_path)
        if worktree_status not in (" ", "?", "!"):
            unstaged.append(rel_path)

    return {
        "staged": sorted(set(staged)),
        "unstaged": sorted(set(unstaged)),
        "untracked": sorted(set(untracked)),
    }


def _sample_paths(paths: Sequence[str], *, limit: int = 5) -> str:
    if not paths:
        return ""
    cap = max(1, int(limit))
    sample = ", ".join(str(item) for item in list(paths)[:cap])
    if len(paths) > cap:
        sample += f", ... (+{len(paths) - cap} more)"
    return sample


def _validate_dirty_release_reason(reason: str) -> str:
    token = str(reason or "").strip()
    if not token:
        raise ValueError("dirty release reason is required when --allow-dirty-release is set")
    if len(token) < DEFAULT_DIRTY_RELEASE_REASON_MIN_LEN:
        raise ValueError(f"dirty release reason must be at least {DEFAULT_DIRTY_RELEASE_REASON_MIN_LEN} characters")
    if any(ch in token for ch in ("\n", "\r")):
        raise ValueError("dirty release reason cannot contain newlines")
    return token


def _append_release_override_audit(
    *,
    agent: str,
    reason: str,
    scopes: Sequence[str],
    dirty_paths: dict[str, list[str]],
) -> None:
    payload = {
        "action": "workboard_release_override",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "agent": str(agent),
        "reason": str(reason),
        "scopes": list(scopes),
        "dirty_paths": {
            "staged": list(dirty_paths.get("staged") or []),
            "unstaged": list(dirty_paths.get("unstaged") or []),
            "untracked": list(dirty_paths.get("untracked") or []),
        },
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"]) or "",
        "head": _run_git(["rev-parse", "HEAD"]) or "",
    }
    RELEASE_OVERRIDE_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RELEASE_OVERRIDE_AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _scope_guard_supported(workboard_path: Path) -> bool:
    try:
        workboard_path.resolve().relative_to(ROOT.resolve())
        return True
    except Exception:
        return False


def _task_id_from_agent(agent: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(agent or "").strip().lower()).strip("-")
    if not slug:
        slug = "agent"
    return f"{slug}-task"


def _is_ready_task(task: str) -> bool:
    return "[ready]" in str(task or "").strip().lower()


def _slug_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return token or "agent"


def _temp_task_creator_agent(owner_agent: str) -> str:
    return f"{TEMP_TASK_CREATOR_AGENT_PREFIX}-{_slug_token(owner_agent)}"


def _temp_task_creator_name(owner_name: str) -> str:
    return f"{TEMP_TASK_CREATOR_NAME_PREFIX}-{_slug_token(owner_name)}"


def _temp_task_creator_task(owner_agent: str, task_manager_agent: str) -> str:
    owner_clean = _sanitize_field("owner_agent", owner_agent)
    manager_clean = _sanitize_field("task_manager_agent", task_manager_agent)
    return (
        "[WIP][TEMP-TASK-CREATOR] "
        f"owner=`{owner_clean}` manager=`{manager_clean}` "
        "reseed-up-for-grabs while manager is busy"
    )


def _is_temp_task_creator_task(task: str) -> bool:
    return TEMP_TASK_CREATOR_TASK_TAG in str(task or "").strip().lower()


def _temp_task_creator_owner(task: str, fallback: str = "") -> str:
    raw = str(task or "")
    match = _TEMP_TASK_CREATOR_OWNER_PATTERN.search(raw)
    if match:
        candidate = str(match.group(1) or "").strip()
        if candidate:
            return candidate
    return str(fallback or "").strip()


def _temp_task_creator_manager(task: str, fallback: str = DEFAULT_TASK_MANAGER_AGENT) -> str:
    raw = str(task or "")
    match = _TEMP_TASK_CREATOR_MANAGER_PATTERN.search(raw)
    if match:
        candidate = str(match.group(1) or "").strip()
        if candidate:
            return candidate
    return str(fallback or DEFAULT_TASK_MANAGER_AGENT).strip()


def _find_temp_task_creator_claims(claims: Sequence[claims_gate.Claim]) -> list[claims_gate.Claim]:
    out: list[claims_gate.Claim] = []
    for claim_row in claims:
        if _is_temp_task_creator_task(claim_row.task):
            out.append(claim_row)
    return sorted(out, key=lambda row: row.line_no)


def _send_temp_task_creator_notice(
    workboard_path: Path,
    *,
    sender: str,
    recipient: str,
    summary: str,
    requested_action: str,
) -> tuple[bool, str]:
    if workboard_message_mod is None:
        return False, "workboard_message module unavailable"
    try:
        ok_send, payload_send = workboard_message_mod.send_message(
            workboard_path,
            sender=sender,
            recipient=recipient,
            summary=summary,
            task_id="none",
            kind="coordination",
            priority="p1",
            requested_action=requested_action,
            decision="pending",
        )
    except Exception as exc:  # pragma: no cover
        return False, str(exc)
    if not ok_send:
        if isinstance(payload_send, dict):
            return False, str(payload_send.get("error") or "message send failed")
        return False, str(payload_send)
    if not isinstance(payload_send, dict):
        return True, ""
    message = dict(payload_send.get("message") or {})
    return True, str(message.get("msg_id") or "")


def _worker_index_for_agent(agent: str, parent_agent: str) -> int | None:
    normalized_agent = _agent_key(agent)
    prefix = f"{_agent_key(parent_agent)}-worker-"
    if not normalized_agent.startswith(prefix):
        return None
    suffix = normalized_agent[len(prefix) :]
    if not suffix.isdigit():
        return None
    value = int(suffix)
    if value <= 0:
        return None
    return value


def _next_worker_index(parent_agent: str, claims: Sequence[claims_gate.Claim]) -> int:
    used: set[int] = set()
    for claim_row in claims:
        index = _worker_index_for_agent(claim_row.agent, parent_agent)
        if index is not None:
            used.add(index)
    candidate = 1
    while candidate in used:
        candidate += 1
    return candidate


def _sanitize_field(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if ";" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} cannot include ';' or newline characters")
    return cleaned


def _resolve_display_name(name: str | None, agent: str) -> str:
    candidate = str(name or "").strip()
    if candidate:
        return _sanitize_field("name", candidate)
    return _sanitize_field("name", agent)


def _normalize_parent_token(parent: str | None) -> str:
    raw = str(parent or "").strip()
    if not raw:
        return "none"
    if raw.lower() in claims_gate.PARENT_NONE_TOKENS:
        return "none"
    return _sanitize_field("parent", raw)


def _resolve_claim_role(role: str | None, parent: str) -> str:
    raw = str(role or "").strip().lower()
    parent_value = _normalize_parent_token(parent)
    if not raw:
        return "worker" if parent_value != "none" else "solo"
    if raw not in CLAIM_ROLE_VALUES:
        allowed = ", ".join(CLAIM_ROLE_VALUES)
        raise ValueError(f"role must be one of: {allowed}")
    if raw == "worker" and parent_value == "none":
        raise ValueError("worker role requires --parent")
    if raw in {"solo", "parent"} and parent_value != "none":
        raise ValueError(f"role `{raw}` cannot include parent `{parent_value}`")
    return raw


def _run_git(args: Sequence[str]) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip()
    return out or None


def _detect_agent_default() -> str | None:
    explicit_env = agent_identity.resolve_agent(None, include_name_fallback=True)
    if explicit_env:
        return explicit_env
    git_name = _run_git(["config", "user.name"])
    if git_name:
        return git_name
    user = str(getpass.getuser() or "").strip()
    return user or None


def _detect_branch_name() -> str | None:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if not branch or branch.upper() == "HEAD":
        return None
    return branch


def _resolve_agent(agent: str | None) -> str:
    if agent:
        return _sanitize_field("agent", agent)
    detected = _detect_agent_default()
    if detected:
        return _sanitize_field("agent", detected)
    raise ValueError("agent is required (pass --agent or set THOMAS_AGENT_ID/AGENT_ID or THOMAS_AGENT_NAME)")


def _resolve_task(task: str | None) -> str:
    if task:
        return _sanitize_field("task", task)
    branch = _detect_branch_name()
    if branch:
        return f"branch {branch}"
    return "active claim"


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


def _format_claim(
    agent: str,
    scope: str,
    task: str,
    *,
    name: str,
    role: str,
    parent: str,
) -> str:
    agent_clean = _sanitize_field("agent", agent)
    name_clean = _sanitize_field("name", name)
    role_clean = _sanitize_field("role", role).lower()
    parent_clean = _normalize_parent_token(parent)
    scope_clean = _normalize_scope_value(scope)
    task_clean = _sanitize_field("task", task)
    return (
        f"- agent={agent_clean}; name={name_clean}; role={role_clean}; parent={parent_clean}; "
        f"scope={scope_clean}; task={task_clean}"
    )


def _format_active_task(
    *,
    task_id: str,
    agent: str,
    scope: str,
    summary: str,
    status: str,
    name: str | None = None,
    role: str | None = None,
    parent: str | None = None,
) -> str:
    task_id_clean = _sanitize_field("task_id", task_id)
    agent_clean = _sanitize_field("agent", agent)
    scope_clean = _normalize_scope_value(scope)
    summary_clean = _sanitize_field("summary", summary)
    status_input = _sanitize_field("status", status).lower()
    status_clean, status_err = claims_gate.normalize_active_task_status(status_input)
    if status_err or status_clean is None:
        raise ValueError(status_err or f"invalid status `{status_input}`")
    line = (
        f"- task_id={task_id_clean}; agent={agent_clean}; scope={scope_clean}; "
        f"summary={summary_clean}; status={status_clean}"
    )
    if name:
        line += f"; name={_sanitize_field('name', name)}"
    if role:
        line += f"; role={_sanitize_field('role', role).lower()}"
    if parent:
        line += f"; parent={_normalize_parent_token(parent)}"
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
    return _find_section(
        lines,
        heading_prefix=ACTIVE_TASK_HEADING_PREFIX,
        heading_label=ACTIVE_TASK_HEADING_LABEL,
    )


def _find_issues_section(lines: Sequence[str]) -> tuple[int, int]:
    return _find_section(lines, heading_prefix="issues / blockers", heading_label="Issues / Blockers")


def _ensure_active_tasks_section(lines: list[str]) -> tuple[int, int]:
    try:
        return _find_active_tasks_section(lines)
    except ValueError:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"## {ACTIVE_TASK_HEADING_LABEL}")
        lines.append("")
        lines.append(NONE_ENTRY)
        return _find_active_tasks_section(lines)


def _bullet_indices(lines: Sequence[str], start: int, end: int) -> list[int]:
    out: list[int] = []
    for idx in range(start, end):
        if lines[idx].strip().startswith("- "):
            out.append(idx)
    return out


def _parse_claim_line(line_no: int, line: str) -> tuple[str | None, dict[str, str] | None, str | None]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected claim bullet entry"
    entry = stripped[2:].strip()
    if entry.lower() in claims_gate.NONE_TOKENS:
        return entry, None, None
    claim, err = claims_gate._parse_claim_entry(line_no, entry)  # type: ignore[attr-defined]
    if err:
        return entry, None, err
    if claim is None:
        return entry, None, None

    fields: dict[str, str] = {
        "agent": claim.agent,
        "name": claim.name,
        "role": claim.role,
        "parent": claim.parent or "none",
        "scope": ",".join(claim.scopes),
        "task": claim.task,
    }
    return entry, fields, None


def _parse_active_task_line(line_no: int, line: str) -> tuple[str | None, dict[str, str] | None, str | None]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected active task bullet entry"
    entry = stripped[2:].strip()
    if entry.lower() in claims_gate.NONE_TOKENS:
        return entry, None, None
    task, err = claims_gate._parse_active_task_entry(line_no, entry)  # type: ignore[attr-defined]
    if err:
        return entry, None, err
    if task is None:
        return entry, None, None

    fields: dict[str, str] = {
        "task_id": task.task_id,
        "agent": task.agent,
        "scope": ",".join(task.scopes),
        "summary": task.summary,
        "status": task.status,
    }
    return entry, fields, None


def _parse_issue_line(line_no: int, line: str) -> tuple[str | None, dict[str, str] | None, str | None]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected issue bullet entry"
    entry = stripped[2:].strip()
    if entry.lower() in claims_gate.NONE_TOKENS:
        return entry, None, None
    issue, err = claims_gate._parse_issue_entry(line_no, entry)  # type: ignore[attr-defined]
    if err:
        return entry, None, err
    if issue is None:
        return entry, None, None

    fields: dict[str, str] = {
        "issue_id": issue.issue_id,
        "task_id": issue.task_id,
        "reporter": issue.reporter,
        "owner": issue.owner,
        "state": issue.state,
        "summary": issue.summary,
    }
    return entry, fields, None


def _upsert_active_task(
    lines: list[str],
    *,
    agent: str,
    scope: str,
    task: str,
    name: str,
    role: str,
    parent: str,
) -> tuple[bool, str]:
    section_start, section_end = _ensure_active_tasks_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)

    existing_idx: int | None = None
    duplicate_idx: int | None = None
    none_idxs: list[int] = []
    existing_task_id = _task_id_from_agent(agent)
    existing_status = "claimed"
    agent_norm = _agent_key(agent)

    for idx in bullet_idxs:
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            none_idxs.append(idx)
            continue
        if not fields:
            continue
        current_agent = _agent_key(fields.get("agent", ""))
        if current_agent == agent_norm:
            if existing_idx is None:
                existing_idx = idx
                existing_task_id = fields.get("task_id", existing_task_id) or existing_task_id
                existing_status = fields.get("status", existing_status) or existing_status
            else:
                duplicate_idx = idx

    if duplicate_idx is not None:
        return (
            False,
            f"duplicate existing active-task entries for `{agent}` at lines "
            f"{existing_idx + 1} and {duplicate_idx + 1}",
        )

    normalized_status, _ = claims_gate.normalize_active_task_status(existing_status)
    if normalized_status is None:
        normalized_status = "claimed"

    formatted = _format_active_task(
        task_id=existing_task_id,
        agent=agent,
        scope=scope,
        summary=task,
        status=normalized_status,
        name=name,
        role=role,
        parent=parent,
    )
    if existing_idx is not None:
        lines[existing_idx] = formatted
        return True, "updated active task entry"

    for idx in sorted(none_idxs, reverse=True):
        del lines[idx]
        if idx < section_end:
            section_end -= 1
    lines.insert(section_end, formatted)
    return True, "added active task entry"


def _release_active_task(lines: list[str], *, agent: str) -> tuple[bool, str]:
    section_start, section_end = _ensure_active_tasks_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)
    remove_idxs: list[int] = []
    keep_active = 0
    agent_norm = _agent_key(agent)

    for idx in bullet_idxs:
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        current_agent = _agent_key(fields.get("agent", ""))
        if current_agent == agent_norm:
            remove_idxs.append(idx)
        else:
            keep_active += 1

    for idx in sorted(remove_idxs, reverse=True):
        del lines[idx]
        if idx < section_end:
            section_end -= 1

    if keep_active == 0:
        lines.insert(section_end, NONE_ENTRY)
    return True, "released active task entry"


def _task_ids_for_agent(lines: Sequence[str], *, agent: str) -> tuple[bool, list[str] | str]:
    try:
        section_start, section_end = _find_active_tasks_section(lines)
    except ValueError:
        return True, []
    bullet_idxs = _bullet_indices(lines, section_start, section_end)
    out: list[str] = []
    agent_norm = _agent_key(agent)
    for idx in bullet_idxs:
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        if _agent_key(fields.get("agent", "")) != agent_norm:
            continue
        task_id = str(fields.get("task_id", "")).strip()
        if task_id:
            out.append(task_id)
    return True, sorted(set(out), key=str.lower)


def _is_auto_inactive_issue(fields: dict[str, str]) -> bool:
    issue_id = _normalize_task_id(fields.get("issue_id", ""))
    summary = str(fields.get("summary", "")).strip().lower()
    if issue_id.endswith("-inactive"):
        return True
    if "marked inactive" in summary:
        return True
    if "reactivate or reassign" in summary:
        return True
    if "reactivate_or_reassign" in summary:
        return True
    return False


def _cleanup_auto_inactive_issues_for_tasks(
    lines: list[str],
    *,
    task_ids: Sequence[str],
) -> tuple[bool, str, int]:
    wanted = {_normalize_task_id(task_id) for task_id in list(task_ids) if str(task_id).strip()}
    if not wanted:
        return True, "no released task ids", 0
    try:
        section_start, section_end = _find_issues_section(lines)
    except ValueError:
        return True, "issues section missing", 0

    remove_idxs: list[int] = []
    for idx in _bullet_indices(lines, section_start, section_end):
        entry, fields, err = _parse_issue_line(idx + 1, lines[idx])
        if err:
            return False, err, 0
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        if _normalize_task_id(fields.get("task_id", "")) not in wanted:
            continue
        if not _is_auto_inactive_issue(fields):
            continue
        remove_idxs.append(idx)

    if not remove_idxs:
        return True, "no auto inactive issues to remove", 0

    for idx in sorted(remove_idxs, reverse=True):
        del lines[idx]

    section_start, section_end = _find_issues_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)
    non_none_idxs: list[int] = []
    none_idxs: list[int] = []
    for idx in bullet_idxs:
        token = lines[idx].strip()[2:].strip().lower()
        if token in claims_gate.NONE_TOKENS:
            none_idxs.append(idx)
        else:
            non_none_idxs.append(idx)
    if non_none_idxs:
        for idx in sorted(none_idxs, reverse=True):
            del lines[idx]
    else:
        for idx in sorted(bullet_idxs, reverse=True):
            del lines[idx]
        _, section_end = _find_issues_section(lines)
        lines.insert(section_end, NONE_ENTRY)

    return True, "removed auto inactive issues", len(remove_idxs)


@contextmanager
def _file_lock(lock_file: Path, timeout: float = LOCK_TIMEOUT_SECONDS):
    COORDINATION_DIR.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + max(0.1, float(timeout))
    fd: int | None = None

    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()} ts={time.time():.3f}".encode("utf-8", errors="ignore"))
            break
        except FileExistsError:
            try:
                age = time.time() - lock_file.stat().st_mtime
            except FileNotFoundError:
                age = 0.0
            if age > LOCK_STALE_SECONDS:
                try:
                    lock_file.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.time() >= deadline:
                raise TimeoutError(f"timed out waiting for lock: {lock_file}")
            time.sleep(0.1)

    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_file.unlink()
        except FileNotFoundError:
            pass


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _validate_and_write(workboard_path: Path, original_text: str, new_text: str) -> tuple[bool, list[str]]:
    _atomic_write(workboard_path, new_text)
    violations = claims_gate.evaluate(workboard_path)
    if violations:
        _atomic_write(workboard_path, original_text)
        return False, violations
    return True, []


def claim(
    workboard_path: Path,
    *,
    agent: str,
    scope: str,
    task: str,
    name: str | None = None,
    role: str | None = None,
    parent: str | None = None,
) -> tuple[bool, str]:
    with _file_lock(LOCK_FILE):
        claim_name = _resolve_display_name(name, agent)
        claim_parent = _normalize_parent_token(parent)
        claim_role = _resolve_claim_role(role, claim_parent)
        formatted = _format_claim(
            agent,
            scope,
            task,
            name=claim_name,
            role=claim_role,
            parent=claim_parent,
        )
        agent_norm = _agent_key(agent)
        original_text = workboard_path.read_text(encoding="utf-8")
        lines = original_text.splitlines()

        section_start, section_end = _find_claim_section(lines)
        bullet_idxs = _bullet_indices(lines, section_start, section_end)

        existing_idx: int | None = None
        duplicate_idx: int | None = None
        none_idxs: list[int] = []

        for idx in bullet_idxs:
            entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
            if err:
                return False, err
            if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                none_idxs.append(idx)
                continue
            if not fields:
                continue
            current_agent = _agent_key(fields.get("agent", ""))
            if current_agent == agent_norm:
                if existing_idx is None:
                    existing_idx = idx
                else:
                    duplicate_idx = idx

        if duplicate_idx is not None:
            return (
                False,
                f"duplicate existing claim entries for `{agent}` at lines {existing_idx + 1} and {duplicate_idx + 1}",
            )

        if existing_idx is not None:
            lines[existing_idx] = formatted
            action = f"updated claim for `{agent}`"
        else:
            for idx in sorted(none_idxs, reverse=True):
                del lines[idx]
                if idx < section_end:
                    section_end -= 1
            insert_at = section_end
            lines.insert(insert_at, formatted)
            action = f"added claim for `{agent}`"

        task_ok, task_msg = _upsert_active_task(
            lines,
            agent=agent,
            scope=scope,
            task=task,
            name=claim_name,
            role=claim_role,
            parent=claim_parent,
        )
        if not task_ok:
            return False, task_msg

        new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
        ok, violations = _validate_and_write(workboard_path, original_text, new_text)
        if not ok:
            joined = "; ".join(violations)
            return False, f"claim update rejected by gate: {joined}"
        return True, f"{action}; {task_msg}"


def release(
    workboard_path: Path,
    *,
    agent: str,
    allow_dirty: bool = False,
    dirty_reason: str = "",
    require_done_state: bool = False,
) -> tuple[bool, str]:
    with _file_lock(LOCK_FILE):
        agent_norm = _agent_key(agent)
        original_text = workboard_path.read_text(encoding="utf-8")
        lines = original_text.splitlines()
        section_start, section_end = _find_claim_section(lines)
        bullet_idxs = _bullet_indices(lines, section_start, section_end)

        remove_idxs: list[int] = []
        remove_scopes: list[str] = []
        keep_active = 0
        for idx in bullet_idxs:
            entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
            if err:
                return False, err
            if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                continue
            if not fields:
                continue
            current_agent = _agent_key(fields.get("agent", ""))
            if current_agent == agent_norm:
                remove_idxs.append(idx)
                remove_scopes.extend(
                    [
                        _normalize_scope_token(token)
                        for token in str(fields.get("scope", "")).split(",")
                        if _normalize_scope_token(token)
                    ]
                )
            else:
                keep_active += 1

        if not remove_idxs:
            return False, f"no active claim found for `{agent}`"

        ok_task_ids, task_payload = _task_ids_for_agent(lines, agent=agent)
        if not ok_task_ids:
            return False, str(task_payload)
        released_task_ids = [item for item in list(task_payload) if str(item).strip()]

        if require_done_state:
            active_section_start, active_section_end = _ensure_active_tasks_section(lines)
            not_ready: list[str] = []
            for idx in _bullet_indices(lines, active_section_start, active_section_end):
                entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
                if err:
                    return False, err
                if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                    continue
                if not fields:
                    continue
                if _agent_key(fields.get("agent", "")) != agent_norm:
                    continue
                task_id = str(fields.get("task_id", "")).strip() or "unknown-task"
                status_raw = str(fields.get("status", "")).strip()
                status, _status_err = claims_gate.normalize_active_task_status(status_raw)
                status = status or status_raw.lower() or "unknown"
                if status not in {"done", "blocked"}:
                    not_ready.append(f"{task_id}:{status}")
            if not_ready:
                return (
                    False,
                    (
                        f"agent `{agent}` cannot release claim because task statuses are not close-ready: "
                        + ", ".join(not_ready)
                        + " (expected done or blocked)"
                    ),
                )

        clean_scopes = sorted(set(remove_scopes), key=str.lower)
        dirty_paths = {"staged": [], "unstaged": [], "untracked": []}
        if clean_scopes and _scope_guard_supported(workboard_path):
            dirty_paths = _claimed_scope_dirty_paths(clean_scopes)
            offenders = sorted(
                set(
                    list(dirty_paths.get("staged") or [])
                    + list(dirty_paths.get("unstaged") or [])
                    + list(dirty_paths.get("untracked") or [])
                )
            )
            if offenders and not allow_dirty:
                sample = _sample_paths(offenders)
                return (
                    False,
                    (
                        f"agent `{agent}` has dirty files in claimed scope ({len(offenders)}): {sample}. "
                        "Commit or stash these files before release, or pass "
                        "--allow-dirty-release with --dirty-release-reason."
                    ),
                )
            if offenders and allow_dirty:
                try:
                    reason = _validate_dirty_release_reason(dirty_reason)
                except ValueError as exc:
                    return False, str(exc)
                try:
                    _append_release_override_audit(
                        agent=agent,
                        reason=reason,
                        scopes=clean_scopes,
                        dirty_paths=dirty_paths,
                    )
                except Exception as exc:
                    return False, f"failed to write release override audit: {exc}"
        elif allow_dirty and _scope_guard_supported(workboard_path):
            try:
                _validate_dirty_release_reason(dirty_reason)
            except ValueError as exc:
                return False, str(exc)

        for idx in sorted(remove_idxs, reverse=True):
            del lines[idx]
            if idx < section_end:
                section_end -= 1

        if keep_active == 0:
            lines.insert(section_end, NONE_ENTRY)

        task_ok, task_msg = _release_active_task(lines, agent=agent)
        if not task_ok:
            return False, task_msg

        issues_ok, issues_msg, removed_issue_count = _cleanup_auto_inactive_issues_for_tasks(
            lines,
            task_ids=released_task_ids,
        )
        if not issues_ok:
            return False, issues_msg

        new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
        ok, violations = _validate_and_write(workboard_path, original_text, new_text)
        if not ok:
            joined = "; ".join(violations)
            return False, f"claim release rejected by gate: {joined}"
        return (
            True,
            f"released claim for `{agent}`; {task_msg}; " f"cleaned_auto_inactive_issues={removed_issue_count}",
        )


def list_claims(workboard_path: Path) -> tuple[bool, list[str] | str]:
    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _find_claim_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)

    claims: list[str] = []
    for idx in bullet_idxs:
        entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if fields:
            claims.append(lines[idx].strip())
    return True, claims


def suggest_delegation(
    workboard_path: Path,
    *,
    parent_agent: str,
    max_suggestions: int = 3,
) -> tuple[bool, dict[str, object] | str]:
    violations, claims, _active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, "workboard invalid: " + "; ".join(violations)

    parent_key = _agent_key(parent_agent)
    parent_claims = [claim for claim in claims if _agent_key(claim.agent) == parent_key]
    if not parent_claims:
        return False, f"no active claim found for parent agent `{parent_agent}`"

    parent_name = str(parent_claims[0].name or parent_agent).strip()
    workers = [claim for claim in claims if _agent_key(claim.parent) == parent_key]

    max_items = max(1, int(max_suggestions))
    ready: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []

    for item in up_for_grabs:
        overlaps: list[str] = []
        for claim_row in claims:
            has_overlap = False
            for source_scope in item.scopes:
                for claimed_scope in claim_row.scopes:
                    if claims_gate._scope_overlaps(source_scope, claimed_scope):  # type: ignore[attr-defined]
                        has_overlap = True
                        break
                if has_overlap:
                    break
            if has_overlap:
                overlaps.append(claim_row.agent)

        payload: dict[str, object] = {
            "task_id": item.task_id,
            "scope": ",".join(item.scopes),
            "summary": item.summary,
            "reported_by": item.reported_by,
            "overlaps": sorted(set(overlaps), key=str.lower),
        }
        if overlaps:
            blocked.append(payload)
            continue
        ready.append(payload)

    ready = ready[:max_items]
    commands: list[str] = []
    for idx, item in enumerate(ready, start=1):
        child_agent = f"{parent_agent}-Worker-{idx}"
        child_name = f"{parent_name}-worker-{idx}"
        task_label = f"[WIP][AUTO-{idx:02d}] {item['task_id']}: {item['summary']}"
        command = (
            "python scripts/workboard_claim.py --claim "
            f"--agent \"{child_agent}\" --name \"{child_name}\" --role worker "
            f"--parent \"{parent_agent}\" --scope \"{item['scope']}\" --task \"{task_label}\""
        )
        commands.append(command)
        item["suggested_agent"] = child_agent
        item["suggested_name"] = child_name
        item["claim_command"] = command

    result: dict[str, object] = {
        "parent_agent": parent_agent,
        "parent_name": parent_name,
        "parent_claim_count": len(parent_claims),
        "active_worker_count": len(workers),
        "ready_suggestions": ready,
        "blocked_candidates": blocked,
        "generated_claim_commands": commands,
    }
    if not ready and blocked:
        overlap_counts: dict[str, int] = {}
        for item in blocked:
            for overlap_agent in [str(v) for v in (item.get("overlaps") or [])]:
                overlap_counts[overlap_agent] = int(overlap_counts.get(overlap_agent, 0)) + 1
        if overlap_counts:
            crowded = sorted(overlap_counts.items(), key=lambda pair: (-pair[1], pair[0]))
            hot = ", ".join([f"{agent}({count})" for agent, count in crowded[:5]])
            result["guidance"] = (
                "No non-overlapping delegation candidates. Narrow broad claim scopes first; "
                f"most frequent blockers: {hot}."
            )
    return True, result


def acquire_temp_task_creator(
    workboard_path: Path,
    *,
    owner_agent: str,
    owner_name: str,
    task_manager_agent: str = DEFAULT_TASK_MANAGER_AGENT,
    notify_task_manager: bool = True,
) -> tuple[bool, dict[str, object] | str]:
    owner_agent_clean = _sanitize_field("owner_agent", owner_agent)
    owner_name_clean = _resolve_display_name(owner_name, owner_agent_clean)
    manager_clean = _sanitize_field("task_manager_agent", task_manager_agent or DEFAULT_TASK_MANAGER_AGENT)
    lease_agent = _temp_task_creator_agent(owner_agent_clean)
    lease_name = _temp_task_creator_name(owner_name_clean)

    violations, claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, "workboard invalid: " + "; ".join(violations)

    existing = _find_temp_task_creator_claims(claims)
    if existing:
        row = existing[0]
        holder_agent = _temp_task_creator_owner(row.task, fallback=row.agent)
        holder_name = str(row.name or holder_agent).strip() or holder_agent
        holder_manager = _temp_task_creator_manager(row.task, fallback=manager_clean)
        if _agent_key(holder_agent) == _agent_key(owner_agent_clean):
            return True, {
                "status": "already_holder",
                "can_create_tasks": True,
                "holder_agent": holder_agent,
                "holder_name": holder_name,
                "manager_agent": holder_manager,
                "lease_agent": row.agent,
                "lease_scope": ",".join(list(row.scopes) or [TEMP_TASK_CREATOR_SCOPE]),
                "claim_message": "temp task creator lease already active for caller",
            }
        return True, {
            "status": "held_by_other",
            "can_create_tasks": False,
            "holder_agent": holder_agent,
            "holder_name": holder_name,
            "manager_agent": holder_manager,
            "lease_agent": row.agent,
            "lease_scope": ",".join(list(row.scopes) or [TEMP_TASK_CREATOR_SCOPE]),
            "claim_message": f"temp task creator lease already held by `{holder_agent}`",
        }

    ok_claim, msg_claim = claim(
        workboard_path,
        agent=lease_agent,
        scope=TEMP_TASK_CREATOR_SCOPE,
        task=_temp_task_creator_task(owner_agent_clean, manager_clean),
        name=lease_name,
        role="solo",
        parent="none",
    )
    if not ok_claim:
        # Recover gracefully from race conditions where another agent wins the lease.
        violations_retry, claims_retry, _active_retry, _grabs_retry, _issues_retry = claims_gate.evaluate_board(
            workboard_path
        )
        if not violations_retry:
            existing_retry = _find_temp_task_creator_claims(claims_retry)
            if existing_retry:
                row = existing_retry[0]
                holder_agent = _temp_task_creator_owner(row.task, fallback=row.agent)
                holder_name = str(row.name or holder_agent).strip() or holder_agent
                holder_manager = _temp_task_creator_manager(row.task, fallback=manager_clean)
                if _agent_key(holder_agent) == _agent_key(owner_agent_clean):
                    return True, {
                        "status": "already_holder",
                        "can_create_tasks": True,
                        "holder_agent": holder_agent,
                        "holder_name": holder_name,
                        "manager_agent": holder_manager,
                        "lease_agent": row.agent,
                        "lease_scope": ",".join(list(row.scopes) or [TEMP_TASK_CREATOR_SCOPE]),
                        "claim_message": str(msg_claim),
                    }
                return True, {
                    "status": "held_by_other",
                    "can_create_tasks": False,
                    "holder_agent": holder_agent,
                    "holder_name": holder_name,
                    "manager_agent": holder_manager,
                    "lease_agent": row.agent,
                    "lease_scope": ",".join(list(row.scopes) or [TEMP_TASK_CREATOR_SCOPE]),
                    "claim_message": str(msg_claim),
                }
        return False, f"temp task creator claim failed: {msg_claim}"

    payload: dict[str, object] = {
        "status": "acquired",
        "can_create_tasks": True,
        "holder_agent": owner_agent_clean,
        "holder_name": owner_name_clean,
        "manager_agent": manager_clean,
        "lease_agent": lease_agent,
        "lease_scope": TEMP_TASK_CREATOR_SCOPE,
        "claim_message": str(msg_claim),
    }

    if notify_task_manager:
        ok_notice, notice_value = _send_temp_task_creator_notice(
            workboard_path,
            sender=owner_agent_clean,
            recipient=manager_clean,
            summary=(f"no tasks available; {owner_agent_clean} claimed temporary task-creator lease"),
            requested_action=("confirm backup task creator assignment and send release when backlog is healthy"),
        )
        payload["notice_status"] = "sent" if ok_notice else "failed"
        if ok_notice and notice_value:
            payload["notice_msg_id"] = notice_value
        if not ok_notice:
            payload["notice_error"] = notice_value
    else:
        payload["notice_status"] = "skipped"
    return True, payload


def release_temp_task_creator(
    workboard_path: Path,
    *,
    actor_agent: str,
    task_manager_agent: str = DEFAULT_TASK_MANAGER_AGENT,
    notify_holder: bool = True,
) -> tuple[bool, dict[str, object] | str]:
    actor_clean = _sanitize_field("agent", actor_agent)
    manager_clean = _sanitize_field("task_manager_agent", task_manager_agent or DEFAULT_TASK_MANAGER_AGENT)
    if _agent_key(actor_clean) != _agent_key(manager_clean):
        return False, f"only `{manager_clean}` can release temporary task creator assignment"

    violations, claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, "workboard invalid: " + "; ".join(violations)

    temp_claims = _find_temp_task_creator_claims(claims)
    if not temp_claims:
        return True, {
            "task_manager_agent": manager_clean,
            "released_count": 0,
            "released": [],
            "release_errors": [],
            "notice_count": 0,
            "notice_errors": [],
        }

    released: list[dict[str, str]] = []
    release_errors: list[dict[str, str]] = []
    notice_ids: list[str] = []
    notice_errors: list[str] = []
    for row in temp_claims:
        holder_agent = _temp_task_creator_owner(row.task, fallback=row.agent)
        holder_name = str(row.name or holder_agent).strip() or holder_agent
        ok_release, msg_release = release(
            workboard_path,
            agent=row.agent,
            allow_dirty=True,
            dirty_reason=TEMP_TASK_CREATOR_RELEASE_REASON,
        )
        if not ok_release:
            release_errors.append(
                {
                    "lease_agent": row.agent,
                    "holder_agent": holder_agent,
                    "error": str(msg_release),
                }
            )
            continue
        released.append(
            {
                "lease_agent": row.agent,
                "holder_agent": holder_agent,
                "holder_name": holder_name,
            }
        )
        if notify_holder:
            ok_notice, notice_value = _send_temp_task_creator_notice(
                workboard_path,
                sender=manager_clean,
                recipient=holder_agent,
                summary=(f"temporary task creator lease released for {holder_agent}; backlog is covered"),
                requested_action="stop creating backup tasks and return to normal task dispatch",
            )
            if ok_notice and notice_value:
                notice_ids.append(notice_value)
            if not ok_notice:
                notice_errors.append(f"notice to `{holder_agent}` failed: {notice_value}")

    payload: dict[str, object] = {
        "task_manager_agent": manager_clean,
        "released_count": len(released),
        "released": released,
        "release_errors": release_errors,
        "notice_count": len(notice_ids),
        "notice_msg_ids": sorted(set(notice_ids), key=str.lower),
        "notice_errors": notice_errors,
    }
    if release_errors:
        return False, payload
    return True, payload


def dispatch_workers(
    workboard_path: Path,
    *,
    parent_agent: str,
    target_workers: int = DEFAULT_DISPATCH_TARGET_WORKERS,
    max_suggestions: int = DEFAULT_DISPATCH_MAX_SUGGESTIONS,
    release_ready: bool = False,
    enable_temp_creator: bool = True,
    task_manager_agent: str = DEFAULT_TASK_MANAGER_AGENT,
    notify_task_manager: bool = True,
) -> tuple[bool, dict[str, object] | str]:
    target = max(1, int(target_workers or 1))
    max_items = max(1, int(max_suggestions or 1))
    parent_key = _agent_key(parent_agent)

    released_workers: list[str] = []
    release_errors: list[dict[str, str]] = []
    claimed_workers: list[dict[str, str]] = []
    claim_errors: list[dict[str, str]] = []
    parent_name = parent_agent
    temp_task_creator: dict[str, object] | None = None

    if release_ready:
        violations, claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
        if violations:
            return False, "workboard invalid: " + "; ".join(violations)

        parent_claims = [claim_row for claim_row in claims if _agent_key(claim_row.agent) == parent_key]
        if not parent_claims:
            return False, f"no active claim found for parent agent `{parent_agent}`"
        parent_name = str(parent_claims[0].name or parent_agent).strip() or parent_agent

        ready_workers = [
            claim_row
            for claim_row in claims
            if _agent_key(claim_row.parent) == parent_key and _is_ready_task(claim_row.task)
        ]
        for claim_row in sorted(ready_workers, key=lambda row: row.agent.lower()):
            ok_release, msg_release = release(workboard_path, agent=claim_row.agent)
            if ok_release:
                released_workers.append(claim_row.agent)
            else:
                release_errors.append({"agent": claim_row.agent, "error": str(msg_release)})

    rounds = 0
    max_rounds = max(1, target * 4)
    while rounds < max_rounds:
        rounds += 1
        violations, claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
        if violations:
            return False, "workboard invalid: " + "; ".join(violations)

        parent_claims = [claim_row for claim_row in claims if _agent_key(claim_row.agent) == parent_key]
        if not parent_claims:
            return False, f"no active claim found for parent agent `{parent_agent}`"
        parent_name = str(parent_claims[0].name or parent_agent).strip() or parent_agent

        workers = [claim_row for claim_row in claims if _agent_key(claim_row.parent) == parent_key]
        if len(workers) >= target:
            break

        ok_suggest, suggest_result = suggest_delegation(
            workboard_path,
            parent_agent=parent_agent,
            max_suggestions=max_items,
        )
        if not ok_suggest:
            return False, str(suggest_result)
        payload = dict(suggest_result) if isinstance(suggest_result, dict) else {}
        ready = list(payload.get("ready_suggestions") or [])
        if not ready:
            if enable_temp_creator and temp_task_creator is None:
                ok_temp, temp_result = acquire_temp_task_creator(
                    workboard_path,
                    owner_agent=parent_agent,
                    owner_name=parent_name,
                    task_manager_agent=task_manager_agent,
                    notify_task_manager=notify_task_manager,
                )
                if ok_temp and isinstance(temp_result, dict):
                    temp_task_creator = dict(temp_result)
                elif not ok_temp:
                    claim_errors.append(
                        {
                            "agent": parent_agent,
                            "task_id": "temp-task-creator",
                            "error": str(temp_result),
                        }
                    )
            break

        claimed_this_round = False
        attempted_this_round = False
        active_worker_keys = {_agent_key(worker.agent) for worker in workers}
        for item in ready:
            task_id = str(item.get("task_id") or "").strip()
            scope = str(item.get("scope") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not task_id or not scope or not summary:
                continue

            suggested_agent = str(item.get("suggested_agent") or "").strip()
            suggested_name = str(item.get("suggested_name") or "").strip()
            if suggested_agent and _agent_key(suggested_agent) in active_worker_keys:
                continue

            worker_index = _worker_index_for_agent(suggested_agent, parent_agent)
            if worker_index is None:
                worker_index = _next_worker_index(parent_agent, claims)
            child_agent = suggested_agent or f"{parent_agent}-Worker-{worker_index}"
            child_name = suggested_name or f"{parent_name}-worker-{worker_index}"
            task_label = f"[WIP][AUTO-{worker_index:02d}] {task_id}: {summary}"

            attempted_this_round = True
            ok_claim, msg_claim = claim(
                workboard_path,
                agent=child_agent,
                scope=scope,
                task=task_label,
                name=child_name,
                role="worker",
                parent=parent_agent,
            )
            if ok_claim:
                claimed_workers.append(
                    {
                        "agent": child_agent,
                        "name": child_name,
                        "task_id": task_id,
                        "scope": scope,
                    }
                )
                claimed_this_round = True
                break
            claim_errors.append({"agent": child_agent, "task_id": task_id, "error": str(msg_claim)})

        if claimed_this_round:
            continue
        if attempted_this_round:
            continue
        break

    violations, claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, "workboard invalid: " + "; ".join(violations)
    workers = [claim_row for claim_row in claims if _agent_key(claim_row.parent) == parent_key]

    ready_suggestion_count = 0
    guidance = ""
    generated_claim_commands: list[str] = []
    ok_final, final_result = suggest_delegation(
        workboard_path,
        parent_agent=parent_agent,
        max_suggestions=max_items,
    )
    if ok_final and isinstance(final_result, dict):
        ready_suggestion_count = len(list(final_result.get("ready_suggestions") or []))
        guidance = str(final_result.get("guidance") or "").strip()
        generated_claim_commands = [str(cmd) for cmd in list(final_result.get("generated_claim_commands") or [])]

    result: dict[str, object] = {
        "parent_agent": parent_agent,
        "parent_name": parent_name,
        "target_workers": target,
        "max_suggestions": max_items,
        "release_ready": bool(release_ready),
        "temp_creator_enabled": bool(enable_temp_creator),
        "rounds": rounds,
        "active_worker_count": len(workers),
        "released_workers": released_workers,
        "release_errors": release_errors,
        "claimed_workers": claimed_workers,
        "claim_errors": claim_errors,
        "ready_suggestion_count": ready_suggestion_count,
        "generated_claim_commands": generated_claim_commands,
    }
    if enable_temp_creator:
        if temp_task_creator is not None:
            result["temp_task_creator"] = temp_task_creator
        else:
            result["temp_task_creator"] = {
                "status": "not_needed",
                "can_create_tasks": False,
                "holder_agent": "",
                "manager_agent": task_manager_agent,
            }
    else:
        result["temp_task_creator"] = {
            "status": "disabled",
            "can_create_tasks": False,
            "holder_agent": "",
            "manager_agent": task_manager_agent,
        }
    if guidance:
        result["guidance"] = guidance
    return True, result


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add/list/release active agent claims in WORKBOARD.md.")
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help="Path to workboard markdown file (default: plans/thomas/WORKBOARD.md)",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--claim", action="store_true", help="Add or update an active claim for --agent.")
    action.add_argument("--release", action="store_true", help="Release active claim for --agent.")
    action.add_argument("--list", action="store_true", help="List active claims.")
    action.add_argument(
        "--suggest-delegation",
        action="store_true",
        help="Suggest non-overlapping `## Up For Grabs` tasks to delegate to child workers.",
    )
    action.add_argument(
        "--dispatch-workers",
        action="store_true",
        help="Release READY workers (optional) and claim suggested worker tasks for a parent agent.",
    )
    action.add_argument(
        "--release-temp-task-creator",
        action="store_true",
        help="Manager-only: release active temporary task-creator lease(s).",
    )
    parser.add_argument("--agent", help="Agent identifier (defaults to env/git user when omitted).")
    parser.add_argument(
        "--name",
        help="Human-readable claim name/callsign (defaults to --agent when omitted).",
    )
    parser.add_argument(
        "--role",
        choices=list(CLAIM_ROLE_VALUES),
        help="Claim role: solo, parent, or worker (auto-derived when omitted).",
    )
    parser.add_argument(
        "--parent",
        help="Parent agent id for worker claims (use `none` to clear).",
    )
    parser.add_argument("--scope", help="Claim scope path(s), comma separated.")
    parser.add_argument("--task", help="Short task description (defaults to current git branch).")
    parser.add_argument(
        "--max-suggestions",
        type=int,
        default=3,
        help="Maximum delegation suggestions to emit with --suggest-delegation (default: 3).",
    )
    parser.add_argument(
        "--dispatch-target-workers",
        type=int,
        default=DEFAULT_DISPATCH_TARGET_WORKERS,
        help=("Target active workers for --dispatch-workers " f"(default: {DEFAULT_DISPATCH_TARGET_WORKERS})."),
    )
    parser.add_argument(
        "--dispatch-max-suggestions",
        type=int,
        default=DEFAULT_DISPATCH_MAX_SUGGESTIONS,
        help=(
            "Maximum suggestions inspected during --dispatch-workers " f"(default: {DEFAULT_DISPATCH_MAX_SUGGESTIONS})."
        ),
    )
    parser.add_argument(
        "--dispatch-release-ready",
        action="store_true",
        help="With --dispatch-workers, release READY worker claims before claiming new work.",
    )
    parser.add_argument(
        "--dispatch-no-temp-creator",
        action="store_true",
        help="With --dispatch-workers, disable automatic temporary task-creator fallback when no tasks are available.",
    )
    parser.add_argument(
        "--dispatch-no-temp-creator-notice",
        action="store_true",
        help="With --dispatch-workers, skip coordination notice to task-manager when temp-task-creator is acquired.",
    )
    parser.add_argument(
        "--task-manager-agent",
        default=DEFAULT_TASK_MANAGER_AGENT,
        help=(
            "Task-manager agent id used by temporary task-creator fallback " f"(default: {DEFAULT_TASK_MANAGER_AGENT})."
        ),
    )
    parser.add_argument(
        "--allow-dirty-release",
        action="store_true",
        help=(
            "Allow --release to proceed even when claimed scope has dirty files. " "Requires --dirty-release-reason."
        ),
    )
    parser.add_argument(
        "--dirty-release-reason",
        default="",
        help="Required reason (>=12 chars) when --allow-dirty-release is used.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON for suggestion output.")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    if not workboard_path.exists():
        print(f"Workboard claim tool: FAIL\n- missing workboard file: {workboard_path}")
        return 1

    try:
        if args.list:
            ok, result = list_claims(workboard_path)
            if not ok:
                print(f"Workboard claim tool: FAIL\n- {result}")
                return 1
            claims = result if isinstance(result, list) else []
            if args.json:
                violations, rows, _tasks, _grab, _issues = claims_gate.evaluate_board(workboard_path)
                if violations:
                    out = {
                        "ok": False,
                        "action": "list",
                        "error": "workboard invalid",
                        "violations": list(violations),
                    }
                else:
                    out = {
                        "ok": True,
                        "action": "list",
                        "active_claim_count": len(rows),
                        "active_claims": [
                            {
                                "agent": claim.agent,
                                "name": claim.name or claim.agent,
                                "role": claim.role or ("worker" if claim.parent else "solo"),
                                "parent": claim.parent or "none",
                                "scope": list(claim.scopes),
                                "task": claim.task,
                                "line_no": int(claim.line_no),
                            }
                            for claim in rows
                        ],
                    }
                print(json.dumps(out, sort_keys=True))
                return 0 if out.get("ok") else 1
            print("Workboard claim tool: PASS")
            if claims:
                for line in claims:
                    print(line)
            else:
                print("- no active claims")
            return 0

        if args.suggest_delegation:
            agent = _resolve_agent(args.agent)
            ok, result = suggest_delegation(
                workboard_path,
                parent_agent=agent,
                max_suggestions=int(args.max_suggestions),
            )
            if not ok:
                if args.json:
                    print('{"ok": false, "action": "suggest_delegation", "error": ' + json.dumps(str(result)) + "}")
                else:
                    print(f"Workboard claim tool: FAIL\n- {result}")
                return 1
            payload = result if isinstance(result, dict) else {}
            if args.json:
                out = {"ok": True, "action": "suggest_delegation", **payload}
                print(json.dumps(out, sort_keys=True))
            else:
                print("Workboard claim tool: PASS")
                print(
                    f"- parent={payload.get('parent_agent')}; name={payload.get('parent_name')}; "
                    f"active_workers={payload.get('active_worker_count')}"
                )
                ready = list(payload.get("ready_suggestions") or [])
                blocked = list(payload.get("blocked_candidates") or [])
                if ready:
                    print("- ready delegation suggestions:")
                    for item in ready:
                        print(f"  - {item.get('task_id')}: {item.get('summary')} " f"(scope={item.get('scope')})")
                        print(f"    {item.get('claim_command')}")
                else:
                    print("- no non-overlapping delegation suggestions available")
                if blocked:
                    print("- blocked candidates:")
                    for item in blocked[:5]:
                        overlaps = ", ".join([str(v) for v in (item.get("overlaps") or [])])
                        print(f"  - {item.get('task_id')} overlaps with: {overlaps}")
                guidance = str(payload.get("guidance") or "").strip()
                if guidance:
                    print(f"- guidance: {guidance}")
            return 0

        if args.dispatch_workers:
            agent = _resolve_agent(args.agent)
            ok, result = dispatch_workers(
                workboard_path,
                parent_agent=agent,
                target_workers=int(args.dispatch_target_workers),
                max_suggestions=int(args.dispatch_max_suggestions),
                release_ready=bool(args.dispatch_release_ready),
                enable_temp_creator=not bool(args.dispatch_no_temp_creator),
                task_manager_agent=str(args.task_manager_agent or DEFAULT_TASK_MANAGER_AGENT),
                notify_task_manager=not bool(args.dispatch_no_temp_creator_notice),
            )
            if not ok:
                if args.json:
                    print('{"ok": false, "action": "dispatch_workers", "error": ' + json.dumps(str(result)) + "}")
                else:
                    print(f"Workboard claim tool: FAIL\n- {result}")
                return 1
            payload = result if isinstance(result, dict) else {}
            if args.json:
                out = {"ok": True, "action": "dispatch_workers", **payload}
                print(json.dumps(out, sort_keys=True))
            else:
                print("Workboard claim tool: PASS")
                print(
                    f"- parent={payload.get('parent_agent')}; name={payload.get('parent_name')}; "
                    f"active_workers={payload.get('active_worker_count')}/{payload.get('target_workers')}"
                )
                released = list(payload.get("released_workers") or [])
                if released:
                    print("- released READY workers:")
                    for worker in released:
                        print(f"  - {worker}")
                claimed = list(payload.get("claimed_workers") or [])
                if claimed:
                    print("- claimed worker lanes:")
                    for item in claimed:
                        print(f"  - {item.get('agent')} => {item.get('task_id')} " f"(scope={item.get('scope')})")
                else:
                    print("- no worker claims created in this dispatch pass")
                temp_payload = payload.get("temp_task_creator")
                if isinstance(temp_payload, dict):
                    temp_status = str(temp_payload.get("status") or "").strip()
                    holder = str(temp_payload.get("holder_agent") or "").strip()
                    manager = str(temp_payload.get("manager_agent") or "").strip()
                    if temp_status and temp_status != "disabled":
                        print(
                            f"- temp-task-creator={temp_status}; holder={holder or 'none'}; "
                            f"manager={manager or 'none'}"
                        )
                guidance = str(payload.get("guidance") or "").strip()
                if guidance:
                    print(f"- guidance: {guidance}")
            return 0

        if args.release_temp_task_creator:
            agent = _resolve_agent(args.agent)
            ok, result = release_temp_task_creator(
                workboard_path,
                actor_agent=agent,
                task_manager_agent=str(args.task_manager_agent or DEFAULT_TASK_MANAGER_AGENT),
            )
            if args.json:
                if ok:
                    out = {"ok": True, "action": "release_temp_task_creator", **(result or {})}
                else:
                    if isinstance(result, dict):
                        out = {"ok": False, "action": "release_temp_task_creator", **result}
                    else:
                        out = {
                            "ok": False,
                            "action": "release_temp_task_creator",
                            "error": str(result),
                        }
                print(json.dumps(out, sort_keys=True))
                return 0 if ok else 1

            if not ok:
                if isinstance(result, dict):
                    err = str(result.get("error") or json.dumps(result, sort_keys=True))
                else:
                    err = str(result)
                print(f"Workboard claim tool: FAIL\n- {err}")
                return 1

            payload = result if isinstance(result, dict) else {}
            print("Workboard claim tool: PASS")
            print(
                f"- task-manager={payload.get('task_manager_agent')}; " f"released={payload.get('released_count', 0)}"
            )
            released_rows = list(payload.get("released") or [])
            if released_rows:
                for row in released_rows:
                    print(f"  - {row.get('holder_agent')} " f"(lease={row.get('lease_agent')})")
            return 0

        if args.claim:
            if not args.scope:
                print("Workboard claim tool: FAIL\n- --scope is required for --claim")
                return 1
            agent = _resolve_agent(args.agent)
            task = _resolve_task(args.task)
            ok, msg = claim(
                workboard_path,
                agent=agent,
                scope=args.scope,
                task=task,
                name=args.name,
                role=args.role,
                parent=args.parent,
            )
            if not ok:
                print(f"Workboard claim tool: FAIL\n- {msg}")
                return 1
            print("Workboard claim tool: PASS")
            print(f"- {msg}")
            return 0

        agent = _resolve_agent(args.agent)
        ok, msg = release(
            workboard_path,
            agent=agent,
            allow_dirty=bool(args.allow_dirty_release),
            dirty_reason=str(args.dirty_release_reason or ""),
        )
        if not ok:
            print(f"Workboard claim tool: FAIL\n- {msg}")
            return 1
        print("Workboard claim tool: PASS")
        print(f"- {msg}")
        return 0
    except ValueError as exc:
        print(f"Workboard claim tool: FAIL\n- {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
