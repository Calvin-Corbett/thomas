"""Refusing to claim a scope another agent already holds.

A claim row is the repo's only statement of ownership. `claim()` historically
looked only for the CALLING agent's own row, so a scope somebody else held
could be claimed without a word; the board gate noticed the overlap only once
two rows coexisted, which is after the edits have already happened.

This module answers one question at the moment of the act - whose work would
this claim reach into - and records the answer when a handover really is
intended.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from scripts.crew.workboard.claim_utils import (
    CLAIM_OVERRIDE_AUDIT_LOG,
    _agent_key,
    _file_lock,
    _find_claim_section,
    _normalize_scope_token,
    _parse_claim_line,
    _resolve_audit_log,
    agent_identity,
    agent_presence,
    claims_gate,
)
from scripts.crew.workboard.message_queries import evaluate_takeover_authorization
from thomas.core.agent_presence_sessions import evaluate_inactive_takeover_holder

TAKEOVER_REASON_MIN_LEN = 12
TAKEOVER_AUTHORIZATION_TTL_SECONDS = 15 * 60
TAKEOVER_COORDINATORS = {"codex-integrator", "task-manager-agent", "task-manager", "thomas"}
TAKEOVER_REPO_OWNERS = {"codex-integrator", "thomas"}


def _takeover_repo_root(workboard_path: Path) -> Path:
    resolved = workboard_path.resolve()
    if resolved.name.casefold() == "workboard.md" and resolved.parent.name.casefold() == "thomas":
        return resolved.parents[2]
    return resolved.parent


def _takeover_pid_alive(pid: int) -> bool:
    return bool(agent_presence and agent_presence._is_pid_alive(int(pid)))  # type: ignore[attr-defined]


def _takeover_process_rows(repo_root: Path) -> list[dict[str, Any]]:
    if agent_presence is None:
        return []
    return list(agent_presence._list_processes(repo_root))  # type: ignore[attr-defined]


def _scope_value(value: object) -> str:
    items = value if isinstance(value, list) else str(value or "").split(",")
    return ",".join(token for token in (_normalize_scope_token(str(item)) for item in items) if token)


def _holder_claims(lines: Sequence[str], agents: Sequence[str]) -> tuple[dict[str, dict[str, str]], str]:
    wanted = {_agent_key(agent) for agent in agents}
    found: dict[str, dict[str, str]] = {}
    start, end = _find_claim_section(lines)
    for idx in range(start, min(end, len(lines))):
        if not lines[idx].strip().startswith("-"):
            continue
        entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
        if err:
            return {}, err
        if entry and fields and _agent_key(entry) in wanted:
            found[_agent_key(entry)] = dict(fields)
    if set(found) != wanted:
        return {}, "takeover holder claim disappeared before eligibility verification"
    return found, ""


def evaluate_takeover_eligibility(
    *,
    workboard_path: Path,
    lines: Sequence[str],
    taker: str,
    requested_task: str,
    requested_scope: str,
    conflicting_agents: Sequence[str],
    takeover_reason: str,
    authorization_id: str = "",
    now: datetime | None = None,
) -> tuple[bool, str, dict[str, object]]:
    holders, error = _holder_claims(lines, conflicting_agents)
    if error:
        return False, error, {}
    scope = _scope_value(requested_scope)
    holder_tasks = {str(fields.get("task") or "").strip() for fields in holders.values()}
    holder_scopes = {_scope_value(fields.get("scope")) for fields in holders.values()}
    if holder_tasks != {str(requested_task or "").strip()} or holder_scopes != {scope}:
        return False, "strict takeover must preserve the exact holder task and scope", {}
    board_sha = hashlib.sha256(workboard_path.read_bytes()).hexdigest()
    auth_ok, auth_message, auth_evidence = evaluate_takeover_authorization(
        authorization_id=authorization_id,
        audit_path=_resolve_audit_log(CLAIM_OVERRIDE_AUDIT_LOG, "CLAIM_OVERRIDE_AUDIT_LOG"),
        workboard_path=workboard_path,
        repo_root=_takeover_repo_root(workboard_path),
        board_sha=board_sha,
        taker=taker,
        holders=holders,
        requested_task=requested_task,
        requested_scope=scope,
        reason=takeover_reason,
        now=now or datetime.now(timezone.utc),
        agent_key=_agent_key,
        coordinators=TAKEOVER_COORDINATORS,
        repo_owners=TAKEOVER_REPO_OWNERS,
        authorization_ttl_seconds=TAKEOVER_AUTHORIZATION_TTL_SECONDS,
    )
    if authorization_id:
        return auth_ok, auth_message, auth_evidence
    repo_root = _takeover_repo_root(workboard_path)
    evidence: list[dict[str, object]] = []
    for holder_key, fields in holders.items():
        if agent_presence is None:
            return False, "agent presence backend is unavailable", {}
        ok, message, row = evaluate_inactive_takeover_holder(
            repo_root=repo_root,
            holder=str(fields.get("agent") or holder_key),
            holder_task=str(fields.get("task") or ""),
            scope=scope,
            now=now or datetime.now(timezone.utc),
            active_folders_path=agent_presence.active_folders_state_path,
            session_path_for=agent_presence.session_file_path,
            process_rows=_takeover_process_rows,
            pid_alive=_takeover_pid_alive,
            stale_seconds=int(getattr(agent_presence, "DEFAULT_STALE_SECONDS", 120)),
            agent_key=_agent_key,
        )
        if not ok:
            return False, message + "; provide a durable exact takeover authorization", {}
        evidence.append(row)
    return True, "all foreign holders are verifiably stale/dead", {"mode": "automatic_stale_dead", "holders": evidence}


def validate_takeover_reason(reason: str) -> str:
    """A handover has to say who agreed to it, so an empty flag is not enough."""
    text = str(reason or "").strip()
    if len(text) < TAKEOVER_REASON_MIN_LEN:
        raise ValueError(
            f"--allow-scope-takeover requires --takeover-reason with at least "
            f"{TAKEOVER_REASON_MIN_LEN} characters saying who agreed to the handover and where."
        )
    return text


def foreign_scope_conflicts(
    lines: Sequence[str],
    *,
    agent: str,
    scope: str,
) -> dict[str, list[str]]:
    """Which other agents' claims this scope would reach into, and where.

    Returns a mapping of the other agent's claim entry to the human-readable
    `mine vs theirs` path collisions, so a refusal can name both.
    """
    wanted = [token for token in (_normalize_scope_token(part) for part in str(scope or "").split(",")) if token]
    if not wanted:
        return {}
    start, end = _find_claim_section(lines)
    conflicts: dict[str, list[str]] = {}
    for idx in range(start, min(end, len(lines))):
        if not lines[idx].strip().startswith("-"):
            continue
        entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
        if err or not entry or _agent_key(entry) == _agent_key(agent):
            continue
        held = [
            token
            for token in (_normalize_scope_token(part) for part in str(fields.get("scope", "")).split(","))
            if token
        ]
        hits = sorted(
            {f"{mine} vs {theirs}" for mine in wanted for theirs in held if claims_gate._scope_overlaps(mine, theirs)}
        )
        if hits:
            conflicts[entry] = hits
    return conflicts


def refusal_message(scope: str, conflicts: dict[str, list[str]]) -> str:
    held = "; ".join(f"`{other}` ({', '.join(hits)})" for other, hits in sorted(conflicts.items()))
    return (
        f"scope `{scope}` is held by {held}. Ask them to release it, or pass "
        "--allow-scope-takeover with --takeover-reason saying who agreed to the handover."
    )


def _append_durable_event(event: dict[str, object]) -> dict[str, object]:
    log_path = _resolve_audit_log(CLAIM_OVERRIDE_AUDIT_LOG, "CLAIM_OVERRIDE_AUDIT_LOG")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(log_path.with_suffix(log_path.suffix + ".lock")):
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    matches = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict) and row.get("event_id") == event["event_id"]:
                matches.append(row)
    if len(matches) != 1 or matches[0] != event:
        raise RuntimeError("takeover audit durability readback failed")
    return event


def record_takeover_authorization(
    *,
    workboard_path: Path,
    authorized_by: str,
    authority: str,
    holder: str,
    taker: str,
    task: str,
    scope: str,
    reason: str,
    target_message_ids: Sequence[str] = (),
    now: datetime | None = None,
) -> dict[str, object]:
    from scripts.crew.brief.coordination_barrier import require_clear_p0

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    require_clear_p0(workboard_path, bound_agent=authorized_by)
    if agent_identity is None:
        raise RuntimeError("takeover authorization requires the bound identity backend")
    binding = agent_identity.require_bound_identity(authorized_by, repo_root=_takeover_repo_root(workboard_path))
    authority_key = str(authority or "").strip().casefold()
    allowed = (
        (authority_key == "holder" and _agent_key(binding.agent_id) == _agent_key(holder))
        or (authority_key == "coordinator" and _agent_key(binding.agent_id) in TAKEOVER_COORDINATORS)
        or (authority_key == "repo_owner" and _agent_key(binding.agent_id) in TAKEOVER_REPO_OWNERS)
    )
    if not allowed:
        raise ValueError("bound authorizer does not hold the requested takeover authority")
    normalized_scope = _scope_value(scope)
    normalized_targets = [str(item).strip() for item in target_message_ids if str(item).strip()]
    if not holder.strip() or not taker.strip() or not task.strip() or not normalized_scope:
        raise ValueError("takeover authorization requires exact holder, taker, task, and scope")
    if len(set(normalized_targets)) != len(normalized_targets):
        raise ValueError("takeover authorization target message ids must be unique")
    event = {
        "event_id": str(uuid.uuid4()),
        "event": "takeover_authorization",
        "authorization_id": str(uuid.uuid4()),
        "authorized_by": binding.agent_id,
        "authorizer_session_id": binding.session_id,
        "actor": {"agent": binding.agent_id, "session_id": binding.session_id, "pid": binding.pid},
        "authority": authority_key,
        "holder": holder.strip(),
        "taker": taker.strip(),
        "task": task.strip(),
        "scope": normalized_scope,
        "reason": validate_takeover_reason(reason),
        "expected_board_sha": hashlib.sha256(workboard_path.read_bytes()).hexdigest(),
        "target_message_ids": normalized_targets,
        "issued_at": current.isoformat(),
        "expires_at": (current + timedelta(seconds=TAKEOVER_AUTHORIZATION_TTL_SECONDS)).isoformat(),
    }
    return _append_durable_event(event)


def append_takeover_audit(
    *,
    agent: str,
    reason: str,
    scope: str,
    takeover_from: Sequence[str],
    stage: str = "takeover_committed",
    task: str = "",
    authorization_id: str = "",
    before_sha: str = "",
    board_sha: str = "",
    evidence: dict[str, object] | None = None,
    rollback_reason: str = "",
    workboard_path: Path,
) -> dict[str, object]:
    """Record who was holding this scope when it changed hands.

    Without this the board shows only the new owner and the handover leaves no
    trace at all.
    """
    if agent_identity is None:
        raise RuntimeError("takeover audit requires the bound identity backend")
    binding = agent_identity.require_bound_identity(agent, repo_root=_takeover_repo_root(workboard_path))
    actor = {"agent": binding.agent_id, "session_id": binding.session_id, "pid": binding.pid}
    event = {
        "event_id": str(uuid.uuid4()),
        "event": str(stage or "takeover_committed"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "actor": actor,
        "reason": reason,
        "scope": scope,
        "task": str(task or ""),
        "holder_agents": sorted(set(takeover_from)),
        "authorization_id": str(authorization_id or ""),
        "expected_before_sha": str(before_sha or ""),
        "board_sha": str(board_sha or ""),
        "evidence": dict(evidence or {}),
    }
    if str(stage or "") == "takeover_committed":
        event["takeover_from"] = sorted(set(takeover_from))
    if rollback_reason:
        event["rollback_reason"] = str(rollback_reason)
    return _append_durable_event(event)
