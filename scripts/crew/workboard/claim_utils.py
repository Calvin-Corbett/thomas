#!/usr/bin/env python3
"""Utilities for managing workboard claims."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts import virtual_office_identity
    from scripts.crew.brief import identity as agent_identity
    from scripts.forge.gates import workboard_claims as claims_gate
except Exception:  # pragma: no cover
    import virtual_office_identity  # type: ignore
    from crew.brief import identity as agent_identity  # type: ignore
    from forge.gates import workboard_claims as claims_gate  # type: ignore

try:
    from scripts.crew.workboard import message as workboard_message_mod
except Exception:  # pragma: no cover
    try:
        from crew.workboard import message as workboard_message_mod  # type: ignore
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


ROOT = Path(__file__).resolve().parents[3]
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
    if path_norm == scope_norm or path_norm.startswith(scope_norm + "/"):
        return True
    if any(ch in scope_norm for ch in "*?["):
        if fnmatch.fnmatchcase(path_norm, scope_norm):
            return True
        if scope_norm.endswith("/**"):
            base = scope_norm[:-3].rstrip("/")
            return bool(base) and (path_norm == base or path_norm.startswith(base + "/"))
        return False
    return False


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
    reason = str(reason or "").strip()
    if len(reason) < DEFAULT_DIRTY_RELEASE_REASON_MIN_LEN:
        raise ValueError(
            f"--dirty-release-reason must be at least "
            f"{DEFAULT_DIRTY_RELEASE_REASON_MIN_LEN} characters (got {len(reason)})"
        )
    return reason


def _worktree_dirty_paths(repo_root: Path = ROOT) -> dict[str, list[str]]:
    return _claimed_scope_dirty_paths(["**"])


def _validate_dirty_claim_reason(reason: str) -> str:
    reason = str(reason or "").strip()
    if len(reason) < DEFAULT_DIRTY_CLAIM_REASON_MIN_LEN:
        raise ValueError(
            f"--dirty-claim-reason must be at least "
            f"{DEFAULT_DIRTY_CLAIM_REASON_MIN_LEN} characters (got {len(reason)})"
        )
    return reason


def _append_claim_override_audit(
    agent: str,
    reason: str,
    scope: str,
    dirty_paths: dict[str, list[str]],
) -> None:
    if agent_identity is None:
        return
    try:
        actor = agent_identity.identity_with_env(agent)
    except Exception:
        actor = {"agent": agent}
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "reason": reason,
        "scope": scope,
        "dirty_paths_count": {k: len(v) for k, v in dirty_paths.items()},
    }
    CLAIM_OVERRIDE_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(CLAIM_OVERRIDE_AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _presence_repo_root(workboard_path: Path) -> Path:
    if agent_presence is None:
        return ROOT
    try:
        return agent_presence.repo_root()
    except Exception:
        return ROOT


def _presence_gate(
    workboard_path: Path,
    purpose: str,
    agent: str,
    requested_scope: str,
    allow_override: bool = False,
    override_reason: str = "",
) -> tuple[bool, str]:
    if agent_presence is None:
        return False, "presence gate unavailable: agent_presence backend is not loaded"
    repo_root = _presence_repo_root(workboard_path)
    try:
        result = agent_presence.evaluate_soft_gate(
            purpose=purpose,
            repo_root=repo_root,
            workboard_path=workboard_path,
            actor_agent=agent,
            requested_scope=requested_scope,
            allow_override=bool(allow_override),
            override_reason=str(override_reason or ""),
        )
    except Exception as exc:
        return False, f"presence gate failed: {exc}"
    if bool(result.get("ok", False)):
        return True, ""
    return False, str(result.get("message") or "presence gate requires override")


def _append_release_override_audit(
    agent: str,
    reason: str,
    scope: str,
) -> None:
    if agent_identity is None:
        return
    try:
        actor = agent_identity.identity_with_env(agent)
    except Exception:
        actor = {"agent": agent}
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "reason": reason,
        "scope": scope,
    }
    RELEASE_OVERRIDE_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RELEASE_OVERRIDE_AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _scope_guard_supported(workboard_path: Path) -> bool:
    if virtual_office_identity is None:
        return False
    try:
        guard = virtual_office_identity.scope_guard(workboard_path)
        return guard is not None
    except Exception:
        return False


def _task_id_from_agent(agent: str) -> str:
    token = str(agent or "").strip().lower()
    return token.replace(" ", "-").replace("_", "-")


def _is_ready_task(task: str) -> bool:
    token = str(task or "").strip()
    return str(token).startswith("[ready]")


def _slug_token(value: str) -> str:
    token = str(value or "").strip().lower()
    return token.replace(" ", "-").replace("_", "-")


def _temp_task_creator_agent(owner_agent: str) -> str:
    return f"{TEMP_TASK_CREATOR_AGENT_PREFIX}-{_slug_token(owner_agent)}"


def _temp_task_creator_name(owner_name: str) -> str:
    return f"{TEMP_TASK_CREATOR_NAME_PREFIX}-{_slug_token(owner_name)}"


def _temp_task_creator_task(owner_agent: str, task_manager_agent: str) -> str:
    return f"{TEMP_TASK_CREATOR_TASK_TAG} " f"owner=`{owner_agent}`; manager=`{task_manager_agent}`"


def _is_temp_task_creator_task(task: str) -> bool:
    token = str(task or "").strip()
    return token.startswith(TEMP_TASK_CREATOR_TASK_TAG)


def _temp_task_creator_owner(task: str, fallback: str = "") -> str:
    match = _TEMP_TASK_CREATOR_OWNER_PATTERN.search(str(task or ""))
    if match:
        return match.group(1)
    return str(fallback or "")


def _temp_task_creator_manager(task: str, fallback: str = DEFAULT_TASK_MANAGER_AGENT) -> str:
    match = _TEMP_TASK_CREATOR_MANAGER_PATTERN.search(str(task or ""))
    if match:
        return match.group(1)
    return str(fallback or DEFAULT_TASK_MANAGER_AGENT)


def _find_temp_task_creator_claims(claims: Sequence[claims_gate.Claim]) -> list[claims_gate.Claim]:
    return [c for c in claims if _is_temp_task_creator_task(c.task)]


def _send_temp_task_creator_notice(
    workboard_path: Path,
    temp_agent: str,
    owner_agent: str,
    manager_agent: str,
    task_manager_agent: str,
    task_id: str,
) -> tuple[bool, str]:
    if workboard_message_mod is None:
        return False, "workboard_message module unavailable"
    try:
        ok, msg = workboard_message_mod.send_message(
            workboard_path=workboard_path,
            recipient_agent=task_manager_agent,
            sender_agent="workboard-claim-tool",
            subject=f"temp-task-creator acquired: {temp_agent}",
            body=(
                f"A temporary task-creator assignment has been acquired:\n"
                f"- agent: {temp_agent}\n"
                f"- owner: {owner_agent}\n"
                f"- manager: {manager_agent}\n"
                f"- task: {task_id}\n"
            ),
        )
        return ok, msg
    except Exception as exc:
        return False, f"Failed to send message: {exc}"


def _worker_index_for_agent(agent: str, parent_agent: str) -> int | None:
    agent_key = _agent_key(agent)
    parent_key = _agent_key(parent_agent)
    if agent_key == parent_key:
        return None
    if agent_key.startswith(f"{parent_key}-worker-"):
        try:
            return int(agent_key.split("-")[-1])
        except ValueError:
            return None
    return None


def _next_worker_index(parent_agent: str, claims: Sequence[claims_gate.Claim]) -> int:
    indices = []
    for claim in claims:
        if _agent_key(claim.parent) == _agent_key(parent_agent):
            idx = _worker_index_for_agent(claim.agent, parent_agent)
            if idx is not None:
                indices.append(idx)
    if not indices:
        return 1
    return max(indices) + 1


def _sanitize_field(label: str, value: str) -> str:
    label = str(label or "").strip()
    value = str(value or "").strip()
    if not label:
        return ""
    if not value:
        return ""
    if "`" in value or ";" in value:
        return ""
    return value


def _resolve_display_name(name: str | None, agent: str) -> str:
    if name:
        return str(name).strip()
    if virtual_office_identity is not None:
        return str(virtual_office_identity.default_display_name(agent)).strip()
    return str(agent or "").strip()


def _normalize_parent_token(parent: str | None) -> str:
    parent = str(parent or "").strip()
    if not parent:
        return ""
    return parent


def _resolve_claim_role(role: str | None, parent: str) -> str:
    role = str(role or "").strip().lower()
    if parent:
        if not role:
            return "worker"
        if role in CLAIM_ROLE_VALUES:
            return role
        raise ValueError(f"Invalid role: {role}")
    if not role:
        return "solo"
    if role in CLAIM_ROLE_VALUES:
        return role
    raise ValueError(f"Invalid role: {role}")


def _run_git(args: Sequence[str]) -> str | None:
    try:
        proc = subprocess.run(
            ["git"] + list(args),
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return str(proc.stdout or "").strip()


def _detect_agent_default() -> str | None:
    branch = _detect_branch_name()
    if not branch or branch == "main":
        return None
    token = branch.split("/")[-1]
    if token:
        return token
    return None


def _detect_branch_name() -> str | None:
    rev = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if rev and rev != "HEAD":
        return rev
    return None


def _resolve_agent(agent: str | None) -> str:
    agent = str(agent or "").strip()
    if not agent:
        detected = _detect_agent_default()
        if detected:
            return detected
        raise ValueError("unable to auto-detect agent; pass --agent")
    return agent


def _resolve_task(task: str | None) -> str:
    task = str(task or "").strip()
    if not task:
        agent = _resolve_agent(None)
        task = _task_id_from_agent(agent)
    return task


def _normalize_scope_value(scope_value: str) -> str:
    scope = _normalize_scope_token(scope_value)
    if not scope:
        raise ValueError(f"invalid scope: {scope_value}")
    return scope


def _format_claim(
    agent: str,
    scope: str,
    task: str,
    name: str | None = None,
    role: str | None = None,
    parent: str | None = None,
) -> str:
    claim_name = _sanitize_field("name", name or "") or _sanitize_field("name", agent) or "unknown-agent"
    claim_role = _sanitize_field("role", role or "") or "solo"
    claim_parent = _sanitize_field("parent", parent or "") or "none"

    fields: list[str] = [
        f"agent={agent}",
        f"name={claim_name}",
        f"role={claim_role}",
        f"parent={claim_parent}",
    ]
    fields.append(f"scope={scope}")
    fields.append(f"task={task}")
    return "- " + "; ".join(fields)


def _format_active_task(
    task_id: str,
    *,
    agent: str,
    scope: str,
    summary: str = "",
    status: str = "active",
) -> str:
    summary_value = _sanitize_field("summary", summary) or str(task_id or "").strip()
    status_value = _sanitize_field("status", status) or "active"
    fields: list[str] = [
        f"task_id={task_id}",
        f"agent={agent}",
        f"scope={scope}",
        f"summary={summary_value}",
        f"status={status_value}",
    ]
    return "- " + "; ".join(fields)


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


def _upsert_active_task(
    lines: list[str],
    task_id: str,
    *,
    agent: str,
    scope: str,
    summary: str = "",
    status: str = "active",
) -> tuple[bool, str]:
    task_id_key = _normalize_task_id(task_id)
    if not task_id_key:
        return False, "task_id is required"
    section = _find_active_tasks_section(lines)
    if section[0] >= section[1]:
        section = _ensure_active_tasks_section(lines)
    existing_idx: int | None = None
    for idx in _bullet_indices(lines, section[0], section[1]):
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry and _normalize_task_id(entry) == task_id_key:
            existing_idx = idx
            break
    formatted = _format_active_task(task_id, agent=agent, scope=scope, summary=summary, status=status)
    if existing_idx is not None:
        lines[existing_idx] = formatted + "\n"
    else:
        none_idx: int | None = None
        for idx in _bullet_indices(lines, section[0], section[1]):
            if lines[idx].strip() == NONE_ENTRY:
                none_idx = idx
                break
        if none_idx is not None:
            lines[none_idx] = formatted + "\n"
        else:
            insert_idx = section[1]
            if insert_idx <= len(lines):
                lines.insert(insert_idx, formatted + "\n")
            else:
                lines.append(formatted + "\n")
    return True, f"upserted active task `{task_id}`"


def _release_active_task(lines: list[str], *, agent: str) -> tuple[bool, str]:
    section = _find_active_tasks_section(lines)
    matching: list[tuple[int, str]] = []
    for idx in _bullet_indices(lines, section[0], section[1]):
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is None:
            continue
        entry_agent = str(fields.get("agent", "") or "")
        if entry_agent and _agent_key(entry_agent) != _agent_key(agent):
            continue
        matching.append((idx, entry))
    if not matching:
        return False, "no active tasks found"
    if len(matching) > 1:
        return False, f"multiple active tasks found for agent {agent}: {[task_id for _, task_id in matching]}"
    idx, task_id = matching[0]
    del lines[idx]
    section = _find_active_tasks_section(lines)
    bullets = range(section[0], min(section[1], len(lines)))
    if not any(lines[bullet_idx].strip().startswith("-") for bullet_idx in bullets):
        lines.insert(section[0], NONE_ENTRY + "\n")
    return True, f"released active task `{task_id}`"


def _task_ids_for_agent(lines: Sequence[str], *, agent: str) -> tuple[bool, list[str]]:
    section = _find_claim_section(lines)
    task_ids: list[str] = []
    for idx in _bullet_indices(lines, section[0], section[1]):
        entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
        if err:
            return False, []
        if entry and _agent_key(entry) == _agent_key(agent):
            task_id = fields.get("task", "")
            if task_id:
                task_ids.append(task_id)
    return True, task_ids


def _is_auto_inactive_issue(fields: dict[str, str]) -> bool:
    status = fields.get("status", "").lower()
    return status == "auto-inactive"


def _cleanup_auto_inactive_issues_for_tasks(
    lines: list[str],
    task_ids: Sequence[str],
) -> tuple[bool, str]:
    if workboard_issue_mod is None:
        return True, ""
    section = workboard_issue_mod._find_issues_section(lines)  # type: ignore[attr-defined]
    if section[0] >= section[1]:
        return True, ""
    task_id_keys = {_normalize_task_id(tid) for tid in task_ids}
    indices_to_remove: list[int] = []
    for idx in workboard_issue_mod._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue_mod._parse_issue_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            continue
        if entry is not None and _normalize_task_id(entry) in task_id_keys and _is_auto_inactive_issue(fields):
            indices_to_remove.append(idx)
    for idx in reversed(indices_to_remove):
        del lines[idx]
    if indices_to_remove:
        section = workboard_issue_mod._find_issues_section(lines)  # type: ignore[attr-defined]
        workboard_issue_mod._ensure_none_if_empty(lines, section_start=section[0], section_end=section[1])  # type: ignore[attr-defined]
    return True, ""


@contextmanager
def _file_lock(lock_file: Path, timeout: float = LOCK_TIMEOUT_SECONDS):
    from contextlib import suppress

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - lock_file.stat().st_mtime
            except FileNotFoundError:
                age = 0.0
            if age > LOCK_STALE_SECONDS:
                with suppress(FileNotFoundError):
                    lock_file.unlink()
                continue
            if time.time() >= deadline:
                msg = f"timed out waiting for lock: {lock_file}"
                raise TimeoutError(msg) from None
            time.sleep(0.1)

    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        with suppress(FileNotFoundError):
            lock_file.unlink()


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
