#!/usr/bin/env python3
"""Manage active agent claims in plans/thomas/WORKBOARD.md."""

from __future__ import annotations

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
    from scripts import agent_identity, virtual_office_identity
    from scripts import check_workboard_claims as claims_gate
except Exception:  # pragma: no cover
    import agent_identity  # type: ignore
    import check_workboard_claims as claims_gate  # type: ignore
    import virtual_office_identity  # type: ignore

try:
    from scripts import workboard_message as workboard_message_mod
except Exception:  # pragma: no cover
    try:
        import workboard_message as workboard_message_mod  # type: ignore
    except Exception:  # pragma: no cover
        workboard_message_mod = None  # type: ignore
try:
    from scripts import workboard_issue as workboard_issue_mod
except Exception:  # pragma: no cover
    try:
        import workboard_issue as workboard_issue_mod  # type: ignore
    except Exception:  # pragma: no cover
        workboard_issue_mod = None  # type: ignore

try:
    from thomas.core import agent_presence
except Exception:  # pragma: no cover
    agent_presence = None  # type: ignore[assignment]


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
DEFAULT_MIN_DISPATCH_TARGET_WORKERS = 2
DEFAULT_DISPATCH_MAX_SUGGESTIONS = 5
DEFAULT_DIRTY_RELEASE_REASON_MIN_LEN = 12
DEFAULT_DIRTY_CLAIM_REASON_MIN_LEN = 12
CLAIM_OVERRIDE_AUDIT_LOG = COORDINATION_DIR / "workboard_claim_override_audit.jsonl"
DEFAULT_TASK_MANAGER_AGENT = "thomas"
TEMP_TASK_CREATOR_TASK_TAG = "[temp-task-creator]"
TEMP_TASK_CREATOR_SCOPE = "runtime/coordination/temp-task-creator"
TEMP_TASK_CREATOR_AGENT_PREFIX = "temp-task-creator"
TEMP_TASK_CREATOR_NAME_PREFIX = "Temp-Task-Creator"
TEMP_TASK_CREATOR_RELEASE_REASON = "task manager ended temporary task creator assignment"
TASK_MANAGER_AGENT_ALIASES = {"thomas", "task-manager-agent", "task-manager"}
_TEMP_TASK_CREATOR_OWNER_PATTERN = re.compile(r"owner=`([^`]+)`", re.IGNORECASE)
_TEMP_TASK_CREATOR_MANAGER_PATTERN = re.compile(r"manager=`([^`]+)`", re.IGNORECASE)


def _agent_key(agent: str) -> str:
    return str(agent or "").strip().lower()


def _task_manager_agent_keys(manager_agent: str) -> set[str]:
    manager_key = _agent_key(manager_agent)
    if not manager_key:
        return set(TASK_MANAGER_AGENT_ALIASES)
    if manager_key in TASK_MANAGER_AGENT_ALIASES:
        return set(TASK_MANAGER_AGENT_ALIASES)
    return {manager_key}


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


def _worktree_dirty_paths(repo_root: Path = ROOT) -> dict[str, list[str]]:
    return _claimed_scope_dirty_paths(["."])


def _validate_dirty_claim_reason(reason: str) -> str:
    token = str(reason or "").strip()
    if not token:
        raise ValueError("dirty claim reason is required when --allow-dirty-claim is set")
    if len(token) < DEFAULT_DIRTY_CLAIM_REASON_MIN_LEN:
        raise ValueError(f"dirty claim reason must be at least {DEFAULT_DIRTY_CLAIM_REASON_MIN_LEN} characters")
    if any(ch in token for ch in ("\n", "\r")):
        raise ValueError("dirty claim reason cannot contain newlines")
    return token


def _append_claim_override_audit(
    *,
    agent: str,
    reason: str,
    scope: str,
    dirty_paths: dict[str, list[str]],
) -> None:
    payload = {
        "action": "workboard_claim_override",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "agent": str(agent),
        "reason": str(reason),
        "scope": str(scope),
        "dirty_paths": {
            "staged": list(dirty_paths.get("staged") or []),
            "unstaged": list(dirty_paths.get("unstaged") or []),
            "untracked": list(dirty_paths.get("untracked") or []),
        },
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"]) or "",
        "head": _run_git(["rev-parse", "HEAD"]) or "",
    }
    CLAIM_OVERRIDE_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CLAIM_OVERRIDE_AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _presence_repo_root(workboard_path: Path) -> Path:
    candidate = workboard_path.resolve()
    try:
        candidate.relative_to(ROOT)
    except Exception:
        return candidate.parent
    return ROOT


def _presence_gate(
    *,
    workboard_path: Path,
    purpose: str,
    agent: str,
    requested_scope: str | Sequence[str] | None,
    allow_override: bool,
    override_reason: str,
) -> tuple[bool, str]:
    if agent_presence is None:
        return True, ""
    try:
        result = agent_presence.evaluate_soft_gate(
            purpose=purpose,
            repo_root=_presence_repo_root(workboard_path),
            workboard_path=workboard_path,
            actor_agent=agent,
            requested_scope=requested_scope,
            allow_override=allow_override,
            override_reason=override_reason,
        )
    except ValueError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"presence gate failed: {exc}"
    if bool(result.get("ok", False)):
        return True, ""
    return False, str(result.get("message") or "presence gate requires override")


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
    return _sanitize_field("name", virtual_office_identity.default_display_name(agent))


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


def _validate_and_write(
    workboard_path: Path,
    original_text: str,
    new_text: str,
    *,
    require_claims_to_have_active_task: bool = True,
    allow_blocked_without_issue: bool = False,
) -> tuple[bool, list[str]]:
    _atomic_write(workboard_path, new_text)
    violations, _claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(
        workboard_path,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    if allow_blocked_without_issue:
        blocked_violation_pattern = "must have an open/triaged entry in `## issues / blockers`"
        violations = [item for item in violations if blocked_violation_pattern not in str(item).lower()]
    if violations:
        _atomic_write(workboard_path, original_text)
        return False, violations
    return True, []
