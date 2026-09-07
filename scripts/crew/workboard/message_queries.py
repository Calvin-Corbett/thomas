"""Read-only query helpers for the Thomas workboard message lane."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core import agent_session_identity


def validate_message_choice(value: str, *, label: str, allowed: set[str], normalize: Any) -> str:
    normalized = normalize(value)
    if normalized not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(sorted(allowed))}")
    return normalized


def empty_audit_payload(*, agent: str, peer: str, task_id: str, diagnosis: str, marker: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "agent": agent,
        "peer": peer,
        "task_id": task_id,
        "canonical_inbox_count": 0,
        "canonical_current_count": 0,
        "awaiting_me": 0,
        "awaiting_peer": 0,
        "awaiting_peer_oldest_seconds": 0,
        "awaiting_peer_msg_id": "",
        "parse_error_count": 0,
        "candidate_mention_count": 0,
        "identity_mismatch_count": 0,
        "stale_identity_mismatch_count": 0,
        "cross_task_open_p0_count": 0,
        "problem_count": 0,
        "parse_errors": [],
        "candidate_mentions": [],
        "identity_mismatches": [],
        "stale_identity_mismatches": [],
        "cross_task_open_p0": [],
        "diagnosis": diagnosis,
        marker: True,
    }
    return payload


def _parse_authorization_time(value: object) -> datetime | None:
    token = str(value or "").strip()
    if token.endswith("Z"):
        token = token[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(token)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def evaluate_takeover_authorization(
    *,
    authorization_id: str,
    audit_path: Path,
    workboard_path: Path,
    repo_root: Path,
    board_sha: str,
    taker: str,
    holders: dict[str, dict[str, str]],
    requested_task: str,
    requested_scope: str,
    reason: str,
    now: datetime,
    agent_key: Any,
    coordinators: set[str],
    repo_owners: set[str],
    authorization_ttl_seconds: int,
) -> tuple[bool, str, dict[str, object]]:
    if not authorization_id:
        return False, "", {}
    events: list[dict[str, Any]] = []
    try:
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict) and row.get("authorization_id") == authorization_id:
                    events.append(row)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"takeover authorization audit is unreadable: {exc}", {}
    if len(events) != 1:
        return False, f"takeover authorization `{authorization_id}` must resolve to exactly one durable record", {}
    row = events[0]
    holder_names = sorted(fields.get("agent", key) for key, fields in holders.items())
    expected_holder = holder_names[0] if len(holder_names) == 1 else ",".join(holder_names)
    authority = str(row.get("authority") or "").strip().casefold()
    authorized_by = str(row.get("authorized_by") or "").strip()
    authorizer_session_id = str(row.get("authorizer_session_id") or "").strip()
    allowed = (
        (authority == "holder" and agent_key(authorized_by) in holders)
        or (authority == "coordinator" and agent_key(authorized_by) in coordinators)
        or (authority == "repo_owner" and agent_key(authorized_by) in repo_owners)
    )
    expected = {
        "event": "takeover_authorization",
        "holder": expected_holder,
        "taker": taker,
        "task": requested_task,
        "scope": requested_scope,
        "reason": reason,
        "expected_board_sha": board_sha,
    }
    mismatches = [key for key, value in expected.items() if str(row.get(key) or "") != str(value)]
    if not allowed or mismatches:
        detail = ", ".join(mismatches) or "authority"
        return False, f"takeover authorization `{authorization_id}` is not bound to exact {detail}", {}
    issued = _parse_authorization_time(row.get("issued_at"))
    expires = _parse_authorization_time(row.get("expires_at"))
    if (
        issued is None
        or expires is None
        or issued > now
        or expires <= now
        or (expires - issued).total_seconds() > max(1, int(authorization_ttl_seconds))
    ):
        return False, f"takeover authorization `{authorization_id}` is outside its verified time window", {}
    try:
        binding = agent_session_identity.validate_recorded_binding(
            repo_root,
            agent_id=authorized_by,
            session_id=authorizer_session_id,
            now=now,
        )
    except (OSError, ValueError) as exc:
        return False, f"takeover authorization `{authorization_id}` has no valid live session binding: {exc}", {}
    actor = row.get("actor")
    if (
        not str(row.get("event_id") or "").strip()
        or not isinstance(actor, dict)
        or agent_key(str(actor.get("agent") or "")) != agent_key(binding.agent_id)
        or str(actor.get("session_id") or "") != binding.session_id
    ):
        return False, f"takeover authorization `{authorization_id}` lacks exact bound actor evidence", {}
    target_ids = row.get("target_message_ids")
    if not isinstance(target_ids, list) or any(not str(item or "").strip() for item in target_ids):
        return False, f"takeover authorization `{authorization_id}` has invalid target message ids", {}
    normalized_ids = [str(item).strip() for item in target_ids]
    if len(set(normalized_ids)) != len(normalized_ids):
        return False, f"takeover authorization `{authorization_id}` has duplicate target message ids", {}
    return (
        True,
        "durable exact takeover authorization verified",
        {
            "mode": "authorization",
            "authorization_id": authorization_id,
            "authorized_by": authorized_by,
            "authority": authority,
            "authorizer_session_id": binding.session_id,
            "target_message_ids": normalized_ids,
            "audit_path": str(audit_path),
            "workboard": str(workboard_path),
        },
    )


def current_messages(
    workboard_path: Path,
    *,
    agent: str,
    peer: str = "",
    task_id: str = "",
    limit: int = 20,
    core: Any,
) -> tuple[bool, dict[str, object]]:
    agent_clean = str(agent or "").strip()
    if not agent_clean:
        return False, {"error": "agent identity is required for current-thread checks"}
    ok, payload = core.list_messages(workboard_path)
    if not ok:
        return False, payload

    agent_key = core._norm(agent_clean)
    peer_key = core._norm(peer)
    task_key = core._norm(task_id)
    agent_is_tm = core._is_task_manager_agent(agent_clean)
    peer_is_tm = core._is_task_manager_agent(peer)

    def _matches_identity(value: str, key: str, is_task_manager: bool) -> bool:
        return (is_task_manager and core._is_task_manager_agent(value)) or core._norm(value) == key

    rows: list[dict[str, str]] = []
    for row in list(payload.get("messages") or []):
        if core._norm(str(row.get("state", ""))) == "resolved":
            continue
        if task_key and core._norm(str(row.get("task_id", ""))) != task_key:
            continue
        sender = str(row.get("from") or "")
        recipient = str(row.get("to") or "")
        from_agent = _matches_identity(sender, agent_key, agent_is_tm)
        to_agent = _matches_identity(recipient, agent_key, agent_is_tm)
        if not (from_agent or to_agent):
            continue
        if peer_key:
            from_peer = _matches_identity(sender, peer_key, peer_is_tm)
            to_peer = _matches_identity(recipient, peer_key, peer_is_tm)
            if not (from_peer or to_peer):
                continue
        next_row = dict(row)
        if to_agent:
            next_row["direction"] = "incoming"
            next_row["awaiting"] = "me" if core._norm(str(row.get("state", ""))) == "open" else "thread"
        else:
            next_row["direction"] = "outgoing"
            next_row["awaiting"] = "peer" if core._norm(str(row.get("state", ""))) == "open" else "thread"
        rows.append(next_row)

    def _stamp(row: dict[str, str]) -> datetime:
        return core._parse_iso_utc(str(row.get("updated_at") or row.get("created_at") or "")) or datetime.min.replace(
            tzinfo=timezone.utc
        )

    rows.sort(
        key=lambda row: (
            _stamp(row),
            -core.PRIORITY_SORT.get(core._norm(row.get("priority", "")), 99),
            str(row.get("msg_id") or ""),
        ),
        reverse=True,
    )
    max_rows = max(1, int(limit or 20))
    rows = rows[:max_rows]
    result = {
        "messages": rows,
        "message_count": len(rows),
        "agent": agent_clean,
        "peer": str(peer or "").strip(),
        "task_id": str(task_id or "").strip(),
    }
    if payload.get("missing_workboard"):
        result["missing_workboard"] = True
    return True, result


def wait_for_messages(
    workboard_path: Path,
    *,
    agent: str = "",
    peer: str = "",
    task_id: str = "",
    limit: int = 20,
    timeout_seconds: float = 60.0,
    poll_interval_seconds: float = 5.0,
    core: Any,
) -> tuple[bool, dict[str, object]]:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds or 0.0))
    poll_interval = max(0.05, float(poll_interval_seconds or 0.0))
    attempts = 0
    while True:
        attempts += 1
        ok, payload = core.audit_messages(
            workboard_path,
            agent=agent,
            peer=peer,
            task_id=task_id,
            limit=limit,
        )
        payload["wait_attempts"] = attempts
        payload["timeout_seconds"] = float(timeout_seconds or 0.0)
        payload["poll_interval_seconds"] = poll_interval
        if not ok:
            payload["wait_status"] = "problem"
            return False, payload
        if int(payload.get("awaiting_me") or 0) > 0:
            payload["wait_status"] = "ready"
            payload["timed_out"] = False
            return True, payload
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            payload["wait_status"] = "timeout"
            payload["timed_out"] = True
            return True, payload
        time.sleep(min(poll_interval, remaining))


def latest_activity_by_task(
    workboard_path: Path,
    *,
    kinds: Sequence[str] | None = None,
    core: Any,
) -> tuple[bool, dict[str, object]]:
    ok, payload = core.list_messages(workboard_path)
    if not ok:
        return False, payload
    allowed = {core._norm(item) for item in list(kinds or []) if core._norm(item)}
    latest: dict[str, datetime] = {}
    for row in list(payload.get("messages") or []):
        task_key = core._norm(str(row.get("task_id", "")))
        if task_key in {"", "none", "_none_"}:
            continue
        kind = core._norm(str(row.get("kind", "")))
        if allowed and kind not in allowed:
            continue
        stamp = core._parse_iso_utc(str(row.get("updated_at", "")).strip() or str(row.get("created_at", "")).strip())
        if stamp is None:
            continue
        prior = latest.get(task_key)
        if prior is None or stamp > prior:
            latest[task_key] = stamp
    return True, {
        "task_count": len(latest),
        "latest_by_task": {task_id: stamp.isoformat() for task_id, stamp in sorted(latest.items())},
    }
