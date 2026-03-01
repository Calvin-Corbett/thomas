#!/usr/bin/env python3
"""Task-manager automation for WORKBOARD execution protocol.

This script provides seven operations:
1) Ensure every active/up-for-grabs task has durable PLAN.md and PROBLEM.md scaffolds.
2) Detect stale/offline agents and move their work to a recoverable state.
3) Reactivate a parked task for an agent.
4) Sync visible agent session registry (alias + session id lifecycle).
5) Capture task-orchestration preferences with summary+verbatim weighting.
6) Sync task-to-specialist routing rows on the board.
7) Resolve the specialist route for a specific task or ad-hoc task description.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from scripts import check_workboard_claim_freshness as freshness_gate
    from scripts import check_workboard_claims as claims_gate
    from scripts import (
        task_specialists,
        workboard_brainstorm,
        workboard_claim,
        workboard_issue,
        workboard_message,
        workboard_swarm,
    )
except Exception:  # pragma: no cover
    import check_workboard_claim_freshness as freshness_gate  # type: ignore
    import check_workboard_claims as claims_gate  # type: ignore
    import task_specialists  # type: ignore
    import workboard_brainstorm  # type: ignore
    import workboard_claim  # type: ignore
    import workboard_issue  # type: ignore
    import workboard_message  # type: ignore
    import workboard_swarm  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
DEFAULT_PLAN_ROOT = "plans/thomas/tasks"
DEFAULT_PROBLEM_ROOT = "plans/thomas/problems"
DEFAULT_TASK_MANAGER_AGENT = "thomas"
DEFAULT_ORCHESTRATOR_AGENTS = ("thomas", "task-manager-agent", "task-manager")
DEFAULT_ORCHESTRATOR_ERROR = "auto-start is disabled for orchestrator agents"
MODEL_ALIAS_OWNER_SUFFIX_RE = re.compile(r"^[\s_-]+\d+$")
DEFAULT_MAX_IDLE_MINUTES = 1.0
DEFAULT_MONITOR_INTERVAL_SECONDS = 30.0
DEFAULT_MONITOR_CYCLES = 1
DEFAULT_MAX_AGENT_SILENCE_MINUTES = 5.0
DEFAULT_MAX_DISPATCH_PER_CYCLE = 2
DEFAULT_SESSION_LEASE_MINUTES = 5.0
TASK_PLANS_HEADING = "Task Plans"
TASK_PROBLEMS_HEADING = "Task Problems"
INACTIVE_AGENTS_HEADING = "Inactive Agents"
AGENT_SESSIONS_HEADING = "Agent Sessions"
TASK_SPECIALIST_HEADING = "Task Specialist Routing"
TASK_ECOSYSTEM_WEIGHTS = {"summary": 0.8, "verbatim": 0.2}
BACKGROUND_TASK_TYPES = {"task_ecosystem_ops"}
BRAINSTORM_TASK_TYPES = {"brainstorm_orchestration"}


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _canonical_model_alias_owner(owner_agent: str) -> str:
    return re.sub(r"[\s_-]*\d+$", "", _norm(owner_agent))


def _model_alias_owner_suffix(owner_norm: str) -> str:
    normalized = _norm(owner_norm)
    owner_base = _canonical_model_alias_owner(normalized)
    if not owner_base:
        return ""
    suffix = normalized[len(owner_base) :]
    if MODEL_ALIAS_OWNER_SUFFIX_RE.fullmatch(suffix):
        return suffix
    return ""


def _is_orchestrator_agent(agent: str | None) -> bool:
    return _norm(agent) in {_norm(name) for name in DEFAULT_ORCHESTRATOR_AGENTS}


def _is_authorized_model_alias(preferred_alias: str, owner_agent: str) -> bool:
    alias_norm = _norm(preferred_alias)
    owner_norm = _norm(owner_agent)
    if not alias_norm or not owner_norm:
        return False
    if alias_norm == owner_norm:
        return True
    owner_base = _canonical_model_alias_owner(owner_norm)
    if not owner_base:
        return False
    if alias_norm == owner_base:
        return True
    if not alias_norm.startswith(owner_base):
        return False
    suffix = alias_norm[len(owner_base) :]
    if not suffix:
        return False
    owner_suffix = _model_alias_owner_suffix(owner_norm)
    if not MODEL_ALIAS_OWNER_SUFFIX_RE.fullmatch(suffix):
        return False
    return suffix == owner_suffix


def _sanitize(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if ";" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} cannot include ';' or newline characters")
    return cleaned


def _parse_now(raw: str | None) -> datetime:
    return freshness_gate._parse_now(raw)  # type: ignore[attr-defined]


def _line_commit_unix(workboard_path: Path, line_no: int) -> int | None:
    return freshness_gate._line_commit_unix(workboard_path, line_no)  # type: ignore[attr-defined]


def _parse_iso_utc(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _task_priority_rank(summary: str) -> tuple[int, int, str]:
    text = _norm(summary)
    priority = 1
    if "[p0]" in text:
        priority = 0
    elif "[p2]" in text:
        priority = 2

    urgency = 1
    if "[now]" in text:
        urgency = 0
    elif "[later]" in text:
        urgency = 2
    return priority, urgency, text


TASK_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"claimed"},
    "claimed": {"in_progress", "blocked"},
    "in_progress": {"blocked", "review"},
    "blocked": {"in_progress", "review", "done"},
    "review": {"done", "blocked", "in_progress"},
    "done": {"queued", "claimed"},
}


def _normalize_task_status(status: str) -> str:
    normalized, err = claims_gate.normalize_active_task_status(status)
    if err or normalized is None:
        raise ValueError(err or f"invalid status `{status}`")
    return normalized


def _replace_status_field(line: str, *, status: str) -> str:
    stripped = str(line).strip()
    if not stripped.startswith("- "):
        raise ValueError("expected bullet line")
    token = stripped[2:].strip()
    if not token:
        raise ValueError("empty bullet payload")
    parts = [part.strip() for part in token.split(";") if part.strip()]
    updated: list[str] = []
    seen = False
    for part in parts:
        if "=" not in part:
            updated.append(part)
            continue
        key, value = part.split("=", 1)
        key_clean = key.strip().lower()
        if key_clean == "status":
            updated.append(f"status={status}")
            seen = True
            continue
        updated.append(f"{key.strip()}={value.strip()}")
    if not seen:
        updated.append(f"status={status}")
    return "- " + "; ".join(updated)


def set_task_status(
    workboard_path: Path,
    *,
    task_id: str,
    status: str,
    actor: str,
    enforce_transition: bool = True,
) -> tuple[bool, dict[str, object]]:
    task_clean = str(task_id or "").strip()
    actor_clean = str(actor or "").strip() or DEFAULT_TASK_MANAGER_AGENT
    if not task_clean:
        return False, {"error": "task_id is required"}
    try:
        target_status = _normalize_task_status(status)
    except ValueError as exc:
        return False, {"error": str(exc)}

    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    target_idx: int | None = None
    current_status = ""
    for idx in workboard_claim._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_claim._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, {"error": err}
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        if _norm(fields.get("task_id", "")) != _norm(task_clean):
            continue
        if target_idx is not None:
            return False, {"error": f"duplicate active task entries found for `{task_clean}`"}
        target_idx = idx
        current_status = _normalize_task_status(str(fields.get("status", "")))
    if target_idx is None:
        return False, {"error": f"active task `{task_clean}` not found"}

    if current_status == target_status:
        return True, {
            "task_id": task_clean,
            "from_status": current_status,
            "to_status": target_status,
            "updated": False,
        }

    if enforce_transition:
        allowed_next = TASK_STATUS_TRANSITIONS.get(current_status, set())
        if target_status not in allowed_next:
            return False, {
                "error": (
                    f"invalid task status transition `{current_status}` -> `{target_status}` for task `{task_clean}`"
                ),
                "allowed_next": sorted(allowed_next),
            }

    try:
        lines[target_idx] = _replace_status_field(lines[target_idx], status=target_status)
    except ValueError as exc:
        return False, {"error": str(exc)}
    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    ok_write, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path,
        original_text,
        new_text,
    )
    if not ok_write:
        return False, {
            "error": "task status update rejected by gate",
            "violations": list(violations),
        }
    return True, {
        "task_id": task_clean,
        "from_status": current_status,
        "to_status": target_status,
        "updated": True,
        "updated_by": actor_clean,
    }


def _task_priority_source(*, summary: str, task_type: str) -> str:
    text = _norm(summary)
    if "[user]" in text or "user requested" in text or "from user" in text:
        return "user"
    if task_type in BACKGROUND_TASK_TYPES:
        return "background"
    return "user"


def _priority_from_summary(summary: str) -> str:
    text = _norm(summary)
    if "[p0]" in text:
        return "p0"
    if "[p2]" in text:
        return "p2"
    return "p1"


def _task_type_by_task_id(workboard_path: Path) -> dict[str, str]:
    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section = _find_section(lines, heading_prefix=TASK_SPECIALIST_HEADING)
    if section is None:
        return {}
    out: dict[str, str] = {}
    for idx in _bullet_indices(lines, section[0], section[1]):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        task_id = str(fields.get("task_id", "")).strip()
        task_type = str(fields.get("task_type", "")).strip()
        if not task_id or not task_type:
            continue
        out[_norm(task_id)] = task_type
    return out


def _ensure_brainstorm_started(
    *,
    workboard_path: Path,
    task: claims_gate.UpForGrabTask,
    task_manager_agent: str,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    task_id = str(task.task_id).strip()
    if not task_id:
        return False, {"error": "brainstorm task missing task_id"}
    ok_sessions, payload_sessions = workboard_brainstorm.list_sessions(workboard_path, state="")
    if not ok_sessions:
        return False, {
            "error": "unable to list brainstorm sessions",
            **payload_sessions,
        }
    sessions = list(payload_sessions.get("sessions") or [])
    for row in sessions:
        if _norm(str(row.get("task_id", ""))) != _norm(task_id):
            continue
        if _norm(str(row.get("state", ""))) in {"resolved", "cancelled"}:
            continue
        return True, {
            "task_id": task_id,
            "started": False,
            "session_id": str(row.get("session_id", "")).strip(),
            "state": str(row.get("state", "")).strip() or "active",
        }

    if not apply:
        return True, {
            "task_id": task_id,
            "started": False,
            "state": "dry_run",
        }
    ok_start, payload_start = workboard_brainstorm.start_session(
        workboard_path,
        task_id=task_id,
        summary=str(task.summary).strip(),
        objective=f"All-hands brainstorm for `{task_id}` before execution split",
        initiator=task_manager_agent,
        facilitator=task_manager_agent,
        all_hands=True,
        invite_agents=[],
        priority=_priority_from_summary(str(task.summary)),
        send_summons=True,
    )
    if not ok_start:
        return False, {
            "error": f"failed to start brainstorm for `{task_id}`",
            **payload_start,
        }
    session_row = dict(payload_start.get("session") or {})
    return True, {
        "task_id": task_id,
        "started": True,
        "session_id": str(session_row.get("session_id", "")).strip(),
        "state": str(session_row.get("state", "")).strip() or "active",
        "invited_count": int(payload_start.get("invited_count", 0) or 0),
        "sent_message_count": int(payload_start.get("sent_message_count", 0) or 0),
    }


def _latest_message_timestamp_by_sender(
    *,
    messages: Sequence[dict[str, str]],
    kinds: Sequence[str] | None = None,
) -> dict[str, datetime]:
    allowed = {_norm(item) for item in list(kinds or []) if _norm(item)}
    out: dict[str, datetime] = {}
    for row in messages:
        sender = str(row.get("from", "")).strip()
        sender_key = _norm(sender)
        if not sender_key:
            continue
        kind = _norm(str(row.get("kind", "")))
        if allowed and kind not in allowed:
            continue
        stamp = _parse_iso_utc(str(row.get("updated_at", "")).strip() or str(row.get("created_at", "")).strip())
        if stamp is None:
            continue
        prior = out.get(sender_key)
        if prior is None or stamp > prior:
            out[sender_key] = stamp
    return out


def _recent_online_agents(
    *,
    messages: Sequence[dict[str, str]],
    now: datetime,
    task_manager_agent: str,
    lookback_minutes: float,
) -> list[str]:
    threshold = now.astimezone(timezone.utc) - timedelta(minutes=max(0.0, float(lookback_minutes)))
    manager_key = _norm(task_manager_agent)
    active_kinds = {
        "status",
        "handoff",
        "blocker",
        "coordination",
        "decision",
        "scope_change",
        "brainstorm_call",
        "brainstorm_note",
        "brainstorm_decision",
        "ping",
    }
    seen: dict[str, str] = {}
    for row in messages:
        sender = str(row.get("from", "")).strip()
        sender_key = _norm(sender)
        if not sender or sender_key == manager_key:
            continue
        kind = _norm(str(row.get("kind", "")))
        if kind not in active_kinds:
            continue
        stamp = _parse_iso_utc(str(row.get("updated_at", "")).strip() or str(row.get("created_at", "")).strip())
        if stamp is not None and stamp < threshold:
            continue
        seen.setdefault(sender_key, sender)
    return [seen[key] for key in sorted(seen.keys())]


def _next_split_task_id(lines: Sequence[str], *, base_task_id: str) -> str:
    used_ids: set[str] = set()
    active_section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    for idx in workboard_claim._bullet_indices(lines, active_section[0], active_section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_claim._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if fields:
            used_ids.add(_norm(fields.get("task_id", "")))

    grabs_section = workboard_issue._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]
    for idx in workboard_issue._bullet_indices(lines, grabs_section[0], grabs_section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue._parse_up_for_grabs_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            continue
        if entry is not None and workboard_issue._is_none_entry(entry):  # type: ignore[attr-defined]
            continue
        if fields:
            used_ids.add(_norm(fields.get("task_id", "")))

    safe_base = re.sub(r"[^A-Za-z0-9._-]+", "-", str(base_task_id or "").strip()).strip("-") or "task"
    stem = f"{safe_base}-split"
    counter = 1
    while True:
        candidate = f"{stem}-{counter}"
        if _norm(candidate) not in used_ids:
            return candidate
        counter += 1


def _split_up_for_grabs_task_for_dispatch(
    *,
    workboard_path: Path,
    task_id: str,
    dispatch_scopes: Sequence[str],
    task_manager_agent: str,
) -> tuple[bool, dict[str, object]]:
    source_task_id = str(task_id or "").strip()
    if not source_task_id:
        return False, {"error": "task_id is required for split"}
    requested_scopes: list[str] = []
    for scope in list(dispatch_scopes):
        normalized = workboard_issue._normalize_scope_token(str(scope))  # type: ignore[attr-defined]
        if normalized and normalized not in requested_scopes:
            requested_scopes.append(normalized)
    if not requested_scopes:
        return False, {"error": "dispatch_scopes must include at least one scope token"}

    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    section = workboard_issue._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]

    target_idx: int | None = None
    target_fields: dict[str, str] | None = None
    task_key = _norm(source_task_id)
    for idx in workboard_issue._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue._parse_up_for_grabs_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, {"error": err}
        if entry is not None and workboard_issue._is_none_entry(entry):  # type: ignore[attr-defined]
            continue
        if fields and _norm(fields.get("task_id", "")) == task_key:
            target_idx = idx
            target_fields = dict(fields)
            break
    if target_idx is None or target_fields is None:
        return False, {"error": f"up-for-grabs task `{source_task_id}` not found"}

    source_scopes: list[str] = []
    for token in str(target_fields.get("scope", "")).split(","):
        normalized = workboard_issue._normalize_scope_token(token)  # type: ignore[attr-defined]
        if normalized:
            source_scopes.append(normalized)
    if not source_scopes:
        return False, {"error": f"task `{source_task_id}` has no usable scopes to split"}

    source_set = {_norm(scope) for scope in source_scopes}
    dispatch_final = [scope for scope in requested_scopes if _norm(scope) in source_set]
    if not dispatch_final:
        return False, {"error": f"task `{source_task_id}` has no overlap with requested split scopes"}

    dispatch_key = {_norm(scope) for scope in dispatch_final}
    remainder = [scope for scope in source_scopes if _norm(scope) not in dispatch_key]
    if not remainder:
        return False, {"error": "split requires at least one remainder scope token"}

    split_task_id = _next_split_task_id(lines, base_task_id=source_task_id)
    source_summary = str(target_fields.get("summary", "")).strip() or source_task_id
    split_summary = f"{source_summary} [AUTO-SPLIT {source_task_id}]"
    source_depends_on = str(target_fields.get("depends_on", "")).strip()
    if not source_depends_on and "[p0]" in _norm(source_summary):
        source_depends_on = "none"
    split_depends_on = source_depends_on or ("none" if "[p0]" in _norm(split_summary) else "")
    reporter = (
        str(target_fields.get("reported_by", "")).strip() or str(task_manager_agent).strip() or "thomas"
    )

    lines[target_idx] = workboard_issue._format_up_for_grabs(  # type: ignore[attr-defined]
        task_id=source_task_id,
        scope=",".join(remainder),
        summary=source_summary,
        reported_by=reporter,
        depends_on=source_depends_on,
    )
    lines.insert(
        target_idx + 1,
        workboard_issue._format_up_for_grabs(  # type: ignore[attr-defined]
            task_id=split_task_id,
            scope=",".join(dispatch_final),
            summary=split_summary,
            reported_by=reporter,
            depends_on=split_depends_on,
        ),
    )

    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    ok_write, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path,
        original_text,
        new_text,
    )
    if not ok_write:
        return False, {
            "error": "auto-split update rejected by gate",
            "violations": list(violations),
        }
    return True, {
        "source_task_id": source_task_id,
        "split_task_id": split_task_id,
        "dispatch_scope": ",".join(dispatch_final),
        "remainder_scope": ",".join(remainder),
        "reported_by": reporter,
    }


def _ping_silent_active_agents(
    *,
    workboard_path: Path,
    now: datetime,
    task_manager_agent: str,
    max_agent_silence_minutes: float,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, _claims, active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    ok_messages, payload_messages = workboard_message.list_messages(workboard_path)
    if not ok_messages:
        return False, {
            "error": "unable to load message traffic for silence monitor",
            **payload_messages,
        }
    messages = list(payload_messages.get("messages") or [])

    manager_key = _norm(task_manager_agent)
    threshold = now.astimezone(timezone.utc) - timedelta(minutes=float(max_agent_silence_minutes))
    active_kinds = {"status", "handoff", "blocker", "coordination", "decision", "scope_change", "brainstorm_note"}
    last_agent_update: dict[tuple[str, str], datetime] = {}
    recent_pings: set[tuple[str, str]] = set()

    for row in messages:
        sender_key = _norm(str(row.get("from", "")))
        recipient_key = _norm(str(row.get("to", "")))
        task_key = _norm(str(row.get("task_id", "")))
        if task_key in {"", "none"}:
            continue
        stamp = _parse_iso_utc(str(row.get("updated_at", "")).strip() or str(row.get("created_at", "")).strip())
        if stamp is None:
            continue
        kind = _norm(str(row.get("kind", "")))
        if sender_key == manager_key and kind == "ping" and stamp >= threshold:
            recent_pings.add((recipient_key, task_key))
        if recipient_key != manager_key:
            continue
        if kind not in active_kinds:
            continue
        key = (sender_key, task_key)
        prior = last_agent_update.get(key)
        if prior is None or stamp > prior:
            last_agent_update[key] = stamp

    silent_rows: list[dict[str, str]] = []
    sent_message_ids: list[str] = []
    errors: list[str] = []
    for task in active_tasks:
        key = (_norm(task.agent), _norm(task.task_id))
        last_update = last_agent_update.get(key)
        is_silent = last_update is None or last_update < threshold
        if not is_silent:
            continue
        if key in recent_pings:
            continue
        silent_rows.append(
            {
                "agent": task.agent,
                "task_id": task.task_id,
                "last_update_at": last_update.isoformat() if last_update is not None else "none",
            }
        )
        if not apply:
            continue
        ok_send, payload_send = workboard_message.send_message(
            workboard_path,
            sender=task_manager_agent,
            recipient=task.agent,
            summary=(
                f"idle monitor: no status update for `{task.task_id}` in {float(max_agent_silence_minutes):.2f} minutes"
            ),
            task_id=task.task_id,
            kind="ping",
            priority="p0",
            requested_action="send status update with progress or blocker details",
            decision="pending",
        )
        if ok_send:
            msg_id = str(dict(payload_send.get("message") or {}).get("msg_id") or "").strip()
            if msg_id:
                sent_message_ids.append(msg_id)
        else:
            errors.append(
                f"silence ping failed for task `{task.task_id}` agent `{task.agent}`: "
                + str(payload_send.get("error", "unknown error"))
            )

    payload: dict[str, object] = {
        "silent_task_count": len(silent_rows),
        "silent_tasks": silent_rows,
        "sent_message_count": len(sent_message_ids),
        "sent_message_ids": sorted(set(sent_message_ids), key=str.lower),
        "threshold_minutes": float(max_agent_silence_minutes),
        "applied": bool(apply),
    }
    if errors:
        payload["errors"] = errors
        return False, payload
    return True, payload


def _dispatch_up_for_grabs_to_idle_agents(
    *,
    workboard_path: Path,
    now: datetime,
    task_manager_agent: str,
    max_dispatch_per_cycle: int,
    online_lookback_minutes: float,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    if int(max_dispatch_per_cycle) <= 0:
        return True, {
            "online_idle_agent_count": 0,
            "online_idle_agents": [],
            "candidate_task_count": 0,
            "assigned_count": 0,
            "assignments": [],
            "applied": bool(apply),
        }

    violations, claims, _active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    ok_messages, payload_messages = workboard_message.list_messages(workboard_path)
    if not ok_messages:
        return False, {
            "error": "unable to load message traffic for idle-agent dispatch",
            **payload_messages,
        }
    messages = list(payload_messages.get("messages") or [])
    manager_key = _norm(task_manager_agent)
    notice_threshold = now.astimezone(timezone.utc) - timedelta(minutes=max(10.0, float(online_lookback_minutes)))
    recent_block_notices: set[str] = set()
    for row in messages:
        if _norm(str(row.get("from", ""))) != manager_key:
            continue
        if _norm(str(row.get("kind", ""))) != "coordination":
            continue
        summary = _norm(str(row.get("summary", "")))
        if "dispatch blocked" not in summary:
            continue
        stamp = _parse_iso_utc(str(row.get("updated_at", "")).strip() or str(row.get("created_at", "")).strip())
        if stamp is not None and stamp < notice_threshold:
            continue
        recent_block_notices.add(_norm(str(row.get("to", ""))))

    online_agents = _recent_online_agents(
        messages=messages,
        now=now,
        task_manager_agent=task_manager_agent,
        lookback_minutes=float(online_lookback_minutes),
    )
    claimed_agents = {_norm(row.agent) for row in claims}
    idle_agents = [
        agent for agent in online_agents if _norm(agent) not in claimed_agents and _norm(agent) != manager_key
    ]

    task_type_map = _task_type_by_task_id(workboard_path)

    def _dispatch_sort_key(task: claims_gate.UpForGrabTask) -> tuple[int, int, int, str]:
        task_type = task_type_map.get(_norm(task.task_id), "generalist_engineering")
        source = _task_priority_source(summary=str(task.summary), task_type=task_type)
        source_rank = 0 if source == "user" else 1
        priority, urgency, text = _task_priority_rank(task.summary)
        return source_rank, priority, urgency, text

    pending_tasks = sorted(list(up_for_grabs), key=_dispatch_sort_key)
    claimed_scopes: list[tuple[str, str]] = []
    for row in claims:
        for scope in list(row.scopes):
            claimed_scopes.append((str(row.agent), str(scope)))

    def _partition_task_scopes(task: claims_gate.UpForGrabTask) -> tuple[list[str], list[str], list[str]]:
        dispatch_scopes: list[str] = []
        blocked_scopes: list[str] = []
        conflict_agents: list[str] = []
        for task_scope in list(task.scopes):
            overlaps: list[str] = []
            for claim_agent, claim_scope in claimed_scopes:
                if claims_gate._scope_overlaps(str(task_scope), str(claim_scope)):  # type: ignore[attr-defined]
                    overlaps.append(claim_agent)
            if overlaps:
                blocked_scopes.append(str(task_scope))
                conflict_agents.extend(overlaps)
            else:
                dispatch_scopes.append(str(task_scope))
        deduped_agents = sorted(set(conflict_agents), key=str.lower)
        return dispatch_scopes, blocked_scopes, deduped_agents

    assignments: list[dict[str, str]] = []
    errors: list[str] = []
    blocked_candidates: list[dict[str, object]] = []
    blocked_notice_ids: list[str] = []
    blocked_notice_count = 0
    split_task_ids: list[str] = []
    assignment_notice_ids: list[str] = []
    brainstorm_rows: list[dict[str, object]] = []
    cap = max(0, int(max_dispatch_per_cycle))

    for agent in idle_agents:
        if len(assignments) >= cap or not pending_tasks:
            break
        task: claims_gate.UpForGrabTask | None = None
        task_dispatch_scopes: list[str] = []
        task_requires_split = False
        blocked_for_agent: list[dict[str, object]] = []
        keep: list[claims_gate.UpForGrabTask] = []
        for candidate in pending_tasks:
            candidate_task_type = task_type_map.get(_norm(candidate.task_id), "generalist_engineering")
            if candidate_task_type in BRAINSTORM_TASK_TYPES:
                ok_brainstorm, payload_brainstorm = _ensure_brainstorm_started(
                    workboard_path=workboard_path,
                    task=candidate,
                    task_manager_agent=task_manager_agent,
                    apply=apply,
                )
                if ok_brainstorm:
                    brainstorm_rows.append(
                        {
                            "task_id": str(candidate.task_id),
                            "task_type": candidate_task_type,
                            **payload_brainstorm,
                        }
                    )
                else:
                    errors.append(
                        f"brainstorm start failed for task `{candidate.task_id}`: "
                        + str(payload_brainstorm.get("error", "unknown error"))
                    )
                keep.append(candidate)
                continue
            dispatch_scopes, blocked_scopes, conflict_agents = _partition_task_scopes(candidate)
            if not dispatch_scopes:
                blocked_for_agent.append(
                    {
                        "agent": agent,
                        "task_id": candidate.task_id,
                        "task_type": candidate_task_type,
                        "blocked_scopes": list(blocked_scopes),
                        "conflicts_with": list(conflict_agents),
                    }
                )
                keep.append(candidate)
                continue
            if task is None:
                task = candidate
                task_dispatch_scopes = list(dispatch_scopes)
                task_requires_split = bool(blocked_scopes)
            else:
                keep.append(candidate)
        pending_tasks = keep
        blocked_candidates.extend(blocked_for_agent)
        if task is None:
            if blocked_for_agent:
                blocked_notice_count += 1
            if apply and blocked_for_agent and _norm(agent) not in recent_block_notices:
                task_ids = (
                    ",".join(
                        [
                            str(item.get("task_id", "")).strip()
                            for item in blocked_for_agent[:5]
                            if str(item.get("task_id", "")).strip()
                        ]
                    )
                    or "none"
                )
                ok_notice, payload_notice = workboard_message.send_message(
                    workboard_path,
                    sender=task_manager_agent,
                    recipient=agent,
                    summary=f"dispatch blocked for {agent}: no non-overlap queued task",
                    task_id="none",
                    kind="coordination",
                    priority="p1",
                    requested_action=f"propose scope split for queued tasks: {task_ids}",
                    decision="pending",
                )
                if ok_notice:
                    msg_id = str(dict(payload_notice.get("message") or {}).get("msg_id") or "").strip()
                    if msg_id:
                        blocked_notice_ids.append(msg_id)
                else:
                    errors.append(
                        f"blocked-dispatch notice failed for `{agent}`: "
                        + str(payload_notice.get("error", "unknown error"))
                    )
            continue

        dispatch_scope_value = ",".join(task_dispatch_scopes)
        dispatch_task_id = str(task.task_id)
        dispatch_task_type = task_type_map.get(_norm(task.task_id), "generalist_engineering")
        dispatch_source = _task_priority_source(summary=str(task.summary), task_type=dispatch_task_type)
        assignment_mode = "dry_run"
        if task_requires_split:
            assignment_mode = "dry_run_split"
            if apply:
                ok_split, payload_split = _split_up_for_grabs_task_for_dispatch(
                    workboard_path=workboard_path,
                    task_id=task.task_id,
                    dispatch_scopes=task_dispatch_scopes,
                    task_manager_agent=task_manager_agent,
                )
                if not ok_split:
                    errors.append(
                        f"auto-split failed for task `{task.task_id}` before dispatch to `{agent}`: "
                        + str(payload_split.get("error", "unknown error"))
                    )
                    continue
                dispatch_task_id = str(payload_split.get("split_task_id", "")).strip() or dispatch_task_id
                dispatch_scope_value = str(payload_split.get("dispatch_scope", "")).strip() or dispatch_scope_value
                split_task_ids.append(dispatch_task_id)
                assignment_mode = "applied_split"
        elif apply:
            assignment_mode = "applied"

        if not apply:
            assignments.append(
                {
                    "agent": agent,
                    "task_id": dispatch_task_id,
                    "task_type": dispatch_task_type,
                    "priority_source": dispatch_source,
                    "mode": assignment_mode,
                    "scope": dispatch_scope_value,
                }
            )
            for scope in list(task_dispatch_scopes):
                claimed_scopes.append((agent, str(scope)))
            continue
        ok_assign, payload_assign = _reactivate_task(
            workboard_path=workboard_path,
            task_id=dispatch_task_id,
            agent=agent,
            task_summary=None,
            scope_override=None,
            name=agent,
            role="solo",
            parent="none",
        )
        if ok_assign:
            assignments.append(
                {
                    "agent": agent,
                    "task_id": dispatch_task_id,
                    "task_type": dispatch_task_type,
                    "priority_source": dispatch_source,
                    "mode": assignment_mode,
                    "scope": dispatch_scope_value,
                }
            )
            ok_notice, payload_notice = workboard_message.send_message(
                workboard_path,
                sender=task_manager_agent,
                recipient=agent,
                summary=f"assigned `{dispatch_task_id}` ({dispatch_task_type})",
                task_id=dispatch_task_id,
                kind="coordination",
                priority=_priority_from_summary(str(task.summary)),
                requested_action="start task and send status updates against this task_id",
                decision="pending",
            )
            if ok_notice:
                msg_id = str(dict(payload_notice.get("message") or {}).get("msg_id") or "").strip()
                if msg_id:
                    assignment_notice_ids.append(msg_id)
            else:
                errors.append(
                    f"dispatch notice failed for task `{dispatch_task_id}` -> `{agent}`: "
                    + str(payload_notice.get("error", "unknown error"))
                )
            for scope in list(task_dispatch_scopes):
                claimed_scopes.append((agent, str(scope)))
            continue
        errors.append(
            f"dispatch failed for task `{dispatch_task_id}` -> `{agent}`: "
            + str(payload_assign.get("error", "unknown error"))
        )

    payload: dict[str, object] = {
        "online_idle_agent_count": len(idle_agents),
        "online_idle_agents": idle_agents,
        "candidate_task_count": len(up_for_grabs),
        "assigned_count": len(assignments),
        "assignments": assignments,
        "blocked_candidate_count": len(blocked_candidates),
        "blocked_candidates": blocked_candidates[:50],
        "blocked_notice_count": int(blocked_notice_count),
        "blocked_notice_message_count": len(blocked_notice_ids),
        "blocked_notice_message_ids": sorted(set(blocked_notice_ids), key=str.lower),
        "assignment_notice_count": len(assignment_notice_ids),
        "assignment_notice_message_ids": sorted(set(assignment_notice_ids), key=str.lower),
        "brainstorm_task_count": len(brainstorm_rows),
        "brainstorm_tasks": brainstorm_rows[:50],
        "split_task_count": len(sorted(set(split_task_ids))),
        "split_task_ids": sorted(set(split_task_ids), key=str.lower),
        "max_dispatch_per_cycle": cap,
        "online_lookback_minutes": float(online_lookback_minutes),
        "applied": bool(apply),
    }
    if errors:
        payload["errors"] = errors
        return False, payload
    return True, payload


def dispatch_idle_agents_once(
    *,
    workboard_path: Path,
    task_manager_agent: str = DEFAULT_TASK_MANAGER_AGENT,
    max_dispatch_per_cycle: int = DEFAULT_MAX_DISPATCH_PER_CYCLE,
    online_lookback_minutes: float = 30.0,
    apply: bool = True,
    now: datetime | None = None,
) -> tuple[bool, dict[str, object]]:
    stamp = now if now is not None else datetime.now(timezone.utc)
    ok_specialists, payload_specialists = _sync_task_specialists(
        workboard_path=workboard_path,
        now=stamp,
        apply=bool(apply),
    )
    if not ok_specialists:
        return False, {
            "error": "sync_specialists failed before dispatch",
            "sync_specialists": payload_specialists,
        }
    ok_dispatch, payload_dispatch = _dispatch_up_for_grabs_to_idle_agents(
        workboard_path=workboard_path,
        now=stamp,
        task_manager_agent=task_manager_agent,
        max_dispatch_per_cycle=max_dispatch_per_cycle,
        online_lookback_minutes=online_lookback_minutes,
        apply=apply,
    )
    payload_dispatch["sync_specialists"] = payload_specialists
    return ok_dispatch, payload_dispatch


def _recover_swarms(
    *,
    workboard_path: Path,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    ok_list, payload_list = workboard_swarm.list_swarms(workboard_path, state="")
    if not ok_list:
        return False, {
            "error": "unable to list swarms for recovery",
            **payload_list,
        }
    sessions = list(payload_list.get("sessions") or [])
    results: list[dict[str, object]] = []
    errors: list[str] = []

    for row in sessions:
        swarm_id = str(row.get("swarm_id", "")).strip()
        state = _norm(str(row.get("state", "")))
        if not swarm_id or state in {"completed", "cancelled"}:
            continue
        ok_launch, payload_launch = workboard_swarm.launch_missing_swarm(
            workboard_path,
            swarm_id=swarm_id,
            dry_run=not bool(apply),
            limit=0,
        )
        result_row: dict[str, object] = {
            "swarm_id": swarm_id,
            "state": state or "planned",
            "ok": bool(ok_launch),
            "launched_count": int(payload_launch.get("launched_count", 0) or 0),
            "missing_count": int(payload_launch.get("missing_count", 0) or 0),
            "online_count": int(payload_launch.get("online_count", 0) or 0),
        }
        results.append(result_row)
        if not ok_launch:
            errors.append(
                f"swarm recovery failed for `{swarm_id}`: " + str(payload_launch.get("error", "unknown error"))
            )

    relaunched = sum(int(row.get("launched_count", 0) or 0) for row in results)
    payload: dict[str, object] = {
        "checked_swarm_count": len(results),
        "relaunched_count": int(relaunched),
        "results": results,
        "applied": bool(apply),
    }
    if errors:
        payload["errors"] = errors
        return False, payload
    return True, payload


def _run_monitor_cycle(
    *,
    workboard_path: Path,
    plan_root: str,
    problem_root: str,
    task_manager_agent: str,
    max_idle_minutes: float,
    max_agent_silence_minutes: float,
    session_lease_minutes: float,
    max_dispatch_per_cycle: int,
    online_lookback_minutes: float,
    run_swarm_recovery: bool,
    run_auto_start: bool,
    run_idle_dispatch: bool,
    now: datetime,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    checks: dict[str, dict[str, object]] = {}
    errors: list[str] = []

    ok_sessions, payload_sessions = _sync_agent_sessions(
        workboard_path=workboard_path,
        now=now,
        session_lease_minutes=session_lease_minutes,
        apply=apply,
    )
    checks["sync_sessions"] = payload_sessions
    if not ok_sessions:
        errors.append(str(payload_sessions.get("error", "sync_sessions failed")))

    ok_specialists, payload_specialists = _sync_task_specialists(
        workboard_path=workboard_path,
        now=now,
        apply=apply,
    )
    checks["sync_specialists"] = payload_specialists
    if not ok_specialists:
        errors.append(str(payload_specialists.get("error", "sync_specialists failed")))

    if run_swarm_recovery:
        ok_swarms, payload_swarms = _recover_swarms(
            workboard_path=workboard_path,
            apply=apply,
        )
        checks["swarm_recovery"] = payload_swarms
        if not ok_swarms:
            errors.append(str(payload_swarms.get("error", "swarm_recovery failed")))

    ok_ping, payload_ping = _ping_silent_active_agents(
        workboard_path=workboard_path,
        now=now,
        task_manager_agent=task_manager_agent,
        max_agent_silence_minutes=max_agent_silence_minutes,
        apply=apply,
    )
    checks["silence_ping"] = payload_ping
    if not ok_ping:
        errors.extend(
            [str(item) for item in list(payload_ping.get("errors") or [])] or [str(payload_ping.get("error", ""))]
        )

    ok_sweep, payload_sweep = _sweep_inactive(
        workboard_path=workboard_path,
        max_idle_minutes=max_idle_minutes,
        task_manager_agent=task_manager_agent,
        now=now,
        apply=apply,
    )
    checks["sweep_inactive"] = payload_sweep
    if not ok_sweep:
        errors.extend(
            [str(item) for item in list(payload_sweep.get("errors") or [])] or [str(payload_sweep.get("error", ""))]
        )

    if run_auto_start:
        ok_auto_start, payload_auto_start = _auto_start_all_claimed_agents(
            workboard_path=workboard_path,
            task_manager_agent=task_manager_agent,
            apply=apply,
        )
        checks["auto_start"] = payload_auto_start
        if not ok_auto_start:
            errors.extend(
                [str(item) for item in list(payload_auto_start.get("errors") or [])]
                or [str(payload_auto_start.get("error", ""))]
            )

    if run_idle_dispatch:
        ok_dispatch, payload_dispatch = _dispatch_up_for_grabs_to_idle_agents(
            workboard_path=workboard_path,
            now=now,
            task_manager_agent=task_manager_agent,
            max_dispatch_per_cycle=max_dispatch_per_cycle,
            online_lookback_minutes=online_lookback_minutes,
            apply=apply,
        )
        checks["idle_dispatch"] = payload_dispatch
        if not ok_dispatch:
            errors.extend(
                [str(item) for item in list(payload_dispatch.get("errors") or [])]
                or [str(payload_dispatch.get("error", ""))]
            )

    ok_plans, payload_plans = _sync_task_plans(
        workboard_path=workboard_path,
        plan_root=plan_root,
        problem_root=problem_root,
        apply=apply,
        now=now,
    )
    checks["sync_plans"] = payload_plans
    if not ok_plans:
        errors.append(str(payload_plans.get("error", "sync_plans failed")))

    payload: dict[str, object] = {
        "cycle_started_at": now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "checks": checks,
        "applied": bool(apply),
    }
    if errors:
        payload["errors"] = [item for item in errors if item]
        return False, payload
    return True, payload


def _monitor_loop(
    *,
    workboard_path: Path,
    plan_root: str,
    problem_root: str,
    task_manager_agent: str,
    max_idle_minutes: float,
    max_agent_silence_minutes: float,
    session_lease_minutes: float,
    max_dispatch_per_cycle: int,
    online_lookback_minutes: float,
    run_swarm_recovery: bool,
    run_auto_start: bool,
    run_idle_dispatch: bool,
    cycles: int,
    interval_seconds: float,
    now_seed: datetime | None,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    if cycles < 0:
        return False, {"error": "--cycles must be >= 0"}
    if interval_seconds < 0:
        return False, {"error": "--interval-seconds must be >= 0"}

    cycle_reports: list[dict[str, object]] = []
    cycle_index = 0
    overall_ok = True

    while cycles == 0 or cycle_index < cycles:
        if now_seed is None:
            cycle_now = datetime.now(timezone.utc)
        else:
            cycle_now = now_seed + timedelta(seconds=float(interval_seconds) * cycle_index)
        ok_cycle, payload_cycle = _run_monitor_cycle(
            workboard_path=workboard_path,
            plan_root=plan_root,
            problem_root=problem_root,
            task_manager_agent=task_manager_agent,
            max_idle_minutes=max_idle_minutes,
            max_agent_silence_minutes=max_agent_silence_minutes,
            session_lease_minutes=session_lease_minutes,
            max_dispatch_per_cycle=max_dispatch_per_cycle,
            online_lookback_minutes=online_lookback_minutes,
            run_swarm_recovery=run_swarm_recovery,
            run_auto_start=run_auto_start,
            run_idle_dispatch=run_idle_dispatch,
            now=cycle_now,
            apply=apply,
        )
        cycle_reports.append(
            {
                "cycle": cycle_index + 1,
                "ok": bool(ok_cycle),
                **payload_cycle,
            }
        )
        if not ok_cycle:
            overall_ok = False

        cycle_index += 1
        if cycles != 0 and cycle_index >= cycles:
            break
        if float(interval_seconds) > 0:
            time.sleep(float(interval_seconds))

    return overall_ok, {
        "cycle_count": cycle_index,
        "cycles": cycle_reports,
        "run_swarm_recovery": bool(run_swarm_recovery),
        "run_auto_start": bool(run_auto_start),
        "run_idle_dispatch": bool(run_idle_dispatch),
        "max_idle_minutes": float(max_idle_minutes),
        "max_agent_silence_minutes": float(max_agent_silence_minutes),
        "session_lease_minutes": float(session_lease_minutes),
        "max_dispatch_per_cycle": int(max_dispatch_per_cycle),
        "online_lookback_minutes": float(online_lookback_minutes),
        "interval_seconds": float(interval_seconds),
        "applied": bool(apply),
    }


def _find_section(lines: Sequence[str], *, heading_prefix: str) -> tuple[int, int] | None:
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
        return None
    return start, end


def _ensure_section(lines: list[str], *, heading: str) -> tuple[int, int]:
    existing = _find_section(lines, heading_prefix=heading)
    if existing is not None:
        return existing

    insert_idx = len(lines)
    supporting = _find_section(lines, heading_prefix="supporting docs")
    if supporting is not None:
        insert_idx = max(0, supporting[0] - 1)

    payload = [f"## {heading}", "", "- none", ""]
    if insert_idx > 0 and lines[insert_idx - 1].strip():
        payload.insert(0, "")
    lines[insert_idx:insert_idx] = payload
    ensured = _find_section(lines, heading_prefix=heading)
    if ensured is None:
        raise ValueError(f"failed to create `## {heading}` section")
    return ensured


def _bullet_indices(lines: Sequence[str], start: int, end: int) -> list[int]:
    out: list[int] = []
    for idx in range(start, end):
        if lines[idx].strip().startswith("- "):
            out.append(idx)
    return out


def _parse_kv_entry(line_no: int, line: str) -> tuple[str | None, dict[str, str] | None, str | None]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected bullet entry"
    token = stripped[2:].strip()
    if token.lower() in claims_gate.NONE_TOKENS:
        return token, None, None
    fields: dict[str, str] = {}
    for part in [x.strip() for x in token.split(";") if x.strip()]:
        if "=" not in part:
            return token, None, f"line {line_no}: invalid field `{part}`"
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if not key or not value:
            return token, None, f"line {line_no}: invalid key/value field `{part}`"
        fields[key] = value
    return token, fields, None


def _write_section_entries(lines: list[str], *, section_start: int, section_end: int, entries: list[str]) -> None:
    for idx in sorted(_bullet_indices(lines, section_start, section_end), reverse=True):
        del lines[idx]
        if idx < section_end:
            section_end -= 1
    if not entries:
        lines.insert(section_end, "- none")
        return
    for entry in entries:
        lines.insert(section_end, entry)
        section_end += 1


def _new_session_id(agent: str, now: datetime, used_ids: set[str]) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", _norm(agent)).strip("-") or "agent"
    candidate = f"sess-{stamp}-{slug}"
    if _norm(candidate) not in used_ids:
        return candidate
    suffix = 2
    while True:
        variant = f"{candidate}-{suffix}"
        if _norm(variant) not in used_ids:
            return variant
        suffix += 1


def _new_model_alias(preferred_alias: str, *, fallback_agent: str, used_aliases: set[str]) -> str:
    base = str(preferred_alias or "").strip()
    if not _is_authorized_model_alias(base, fallback_agent):
        base = str(fallback_agent or "").strip() or "agent"
    if not base:
        base = "agent"
    candidate = base
    if _norm(candidate) not in used_aliases:
        return candidate
    suffix = 2
    while True:
        variant = f"{base}-{suffix}"
        if _norm(variant) not in used_aliases:
            return variant
        suffix += 1


def _sync_agent_sessions(
    *,
    workboard_path: Path,
    now: datetime,
    session_lease_minutes: float,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, claims, active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _ensure_section(lines, heading=AGENT_SESSIONS_HEADING)

    existing: dict[str, dict[str, str]] = {}
    parse_errors: list[str] = []
    alias_violations: list[str] = []
    for idx in _bullet_indices(lines, section_start, section_end):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            parse_errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        agent = str(fields.get("agent", "")).strip()
        if not agent:
            parse_errors.append(f"line {idx + 1}: missing agent")
            continue
        model_alias = str(fields.get("model_alias", "")).strip()
        if model_alias and not _is_authorized_model_alias(model_alias, agent):
            alias_violations.append(
                f"line {idx + 1}: unauthorized model_alias `{model_alias}` for agent `{agent}`"
            )
        existing[_norm(agent)] = dict(fields)
    if parse_errors:
        return False, {"error": "agent sessions section parse failed", "violations": parse_errors}
    if alias_violations:
        return False, {
            "error": "agent sessions contains unauthorized model_alias swap attempts",
            "violations": alias_violations,
        }

    task_by_agent: dict[str, str] = {}
    for row in active_tasks:
        key = _norm(row.agent)
        task_by_agent.setdefault(key, str(row.task_id).strip() or "none")

    ok_messages, payload_messages = workboard_message.list_messages(workboard_path)
    if not ok_messages:
        return False, {"error": "message traffic parse failed for session sync", **payload_messages}
    messages = list(payload_messages.get("messages") or [])
    activity_kinds = (
        "status",
        "handoff",
        "blocker",
        "coordination",
        "decision",
        "scope_change",
        "brainstorm_call",
        "brainstorm_note",
        "brainstorm_decision",
        "ping",
    )
    sender_last_seen = _latest_message_timestamp_by_sender(messages=messages, kinds=activity_kinds)

    now_iso = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    lease_delta = timedelta(minutes=max(0.1, float(session_lease_minutes)))
    used_session_ids: set[str] = set()
    used_aliases: set[str] = set()
    updated: dict[str, dict[str, str]] = {}
    created_session_count = 0

    for claim in sorted(claims, key=lambda row: _norm(row.agent)):
        key = _norm(claim.agent)
        prior = dict(existing.get(key, {}))
        session_id = str(prior.get("session_id", "")).strip()
        if not session_id or _norm(session_id) in used_session_ids:
            session_id = _new_session_id(claim.agent, now, used_session_ids)
            created_session_count += 1
        used_session_ids.add(_norm(session_id))
        model_alias = _new_model_alias(
            str(prior.get("model_alias", "")).strip(),
            fallback_agent=str(claim.agent).strip(),
            used_aliases=used_aliases,
        )
        used_aliases.add(_norm(model_alias))
        parent = str(getattr(claim, "parent", "") or "none").strip() or "none"
        active_task = str(task_by_agent.get(key, "none")).strip() or "none"
        prior_seen = _parse_iso_utc(str(prior.get("last_seen", "")).strip())
        message_seen = sender_last_seen.get(key)
        effective_seen = prior_seen
        if message_seen is not None and (effective_seen is None or message_seen > effective_seen):
            effective_seen = message_seen
        if effective_seen is None:
            effective_seen = now.astimezone(timezone.utc)
        lease_expires = effective_seen + lease_delta
        updated[key] = {
            "agent": claim.agent,
            "model_alias": model_alias,
            "session_id": session_id,
            "parent": parent,
            "state": "active",
            "active_task": active_task,
            "last_seen": _to_iso_utc(effective_seen),
            "lease_expires": _to_iso_utc(lease_expires),
        }

    for key, row in existing.items():
        if key in updated:
            continue
        prior_seen = _parse_iso_utc(str(row.get("last_seen", "")).strip())
        message_seen = sender_last_seen.get(key)
        effective_seen = prior_seen
        if message_seen is not None and (effective_seen is None or message_seen > effective_seen):
            effective_seen = message_seen
        inactive_last_seen = _to_iso_utc(effective_seen) if effective_seen is not None else now_iso
        inactive_seen = effective_seen if effective_seen is not None else now.astimezone(timezone.utc)
        inactive_lease_expires = _to_iso_utc(inactive_seen + lease_delta)
        inactive_session_id = str(row.get("session_id", "")).strip()
        if not inactive_session_id or _norm(inactive_session_id) in used_session_ids:
            inactive_session_id = _new_session_id(str(row.get("agent", key)), now, used_session_ids)
            created_session_count += 1
        used_session_ids.add(_norm(inactive_session_id))
        inactive_alias = _new_model_alias(
            str(row.get("model_alias", "")).strip(),
            fallback_agent=str(row.get("agent", "")).strip() or key,
            used_aliases=used_aliases,
        )
        used_aliases.add(_norm(inactive_alias))
        updated[key] = {
            "agent": str(row.get("agent", "")).strip() or key,
            "model_alias": inactive_alias,
            "session_id": inactive_session_id,
            "parent": str(row.get("parent", "none")).strip() or "none",
            "state": "inactive",
            "active_task": "none",
            "last_seen": inactive_last_seen,
            "lease_expires": inactive_lease_expires,
        }

    entries: list[str] = []
    for _, row in sorted(updated.items(), key=lambda item: item[0]):
        entries.append(
            f"- agent={_sanitize('agent', row['agent'])}; "
            f"model_alias={_sanitize('model_alias', row['model_alias'])}; "
            f"session_id={_sanitize('session_id', row['session_id'])}; "
            f"parent={_sanitize('parent', row['parent'])}; "
            f"state={_sanitize('state', row['state'])}; "
            f"active_task={_sanitize('active_task', row['active_task'])}; "
            f"last_seen={_sanitize('last_seen', row['last_seen'])}; "
            f"lease_expires={_sanitize('lease_expires', row['lease_expires'])}"
        )

    if apply:
        _write_section_entries(lines, section_start=section_start, section_end=section_end, entries=entries)
        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        ok_write, write_violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
            workboard_path,
            text,
            new_text,
        )
        if not ok_write:
            return False, {"error": "session sync rejected by gate", "violations": list(write_violations)}

    return True, {
        "session_entry_count": len(entries),
        "created_session_count": int(created_session_count),
        "active_session_count": len(claims),
        "inactive_session_count": max(0, len(entries) - len(claims)),
        "session_lease_minutes": float(session_lease_minutes),
        "applied": bool(apply),
    }


def _capture_task_ecosystem_preference(
    *,
    user_id: str,
    summary: str,
    verbatim: str,
    now: datetime,
) -> tuple[bool, dict[str, object]]:
    summary_clean = str(summary or "").strip()
    verbatim_clean = str(verbatim or "").strip()
    if not summary_clean:
        return False, {"error": "--preference-summary is required"}
    if not verbatim_clean:
        return False, {"error": "--preference-verbatim is required"}

    try:
        from thomas.preferences.store import OnboardingPatch, PreferencesPatch, PreferencesStore
    except Exception as exc:  # pragma: no cover
        return False, {"error": f"unable to import preferences store: {exc}"}

    store = PreferencesStore()
    current = store.get(user_id=user_id)
    answers = dict(current.onboarding.answers or {})
    ecosystem = dict(answers.get("task_ecosystem") or {})
    rows = list(ecosystem.get("conduct_preferences") or [])
    now_iso = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    rows.append(
        {
            "captured_at": now_iso,
            "source": "user",
            "summary": summary_clean,
            "verbatim": verbatim_clean,
            "summary_weight": float(TASK_ECOSYSTEM_WEIGHTS["summary"]),
            "verbatim_weight": float(TASK_ECOSYSTEM_WEIGHTS["verbatim"]),
        }
    )
    rows = rows[-50:]

    ecosystem["conduct_preferences"] = rows
    ecosystem["current_preference_summary"] = summary_clean
    ecosystem["weights"] = dict(TASK_ECOSYSTEM_WEIGHTS)
    ecosystem["last_updated_at"] = now_iso
    answers["task_ecosystem"] = ecosystem

    patch = PreferencesPatch(onboarding=OnboardingPatch(answers=answers))
    store.patch(patch, user_id=user_id)
    return True, {
        "user_id": user_id,
        "saved_preference_count": len(rows),
        "current_preference_summary": summary_clean,
        "weights": dict(TASK_ECOSYSTEM_WEIGHTS),
    }


def _task_rows_for_specialist_routing(
    *,
    active_tasks: Sequence[claims_gate.ActiveTask],
    up_for_grabs: Sequence[claims_gate.UpForGrabTask],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for row in active_tasks:
        key = _norm(row.task_id)
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "task_id": str(row.task_id).strip(),
                "scope": ",".join(row.scopes),
                "summary": str(row.summary).strip(),
                "status": str(row.status).strip() or "in_progress",
            }
        )

    for row in up_for_grabs:
        key = _norm(row.task_id)
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "task_id": str(row.task_id).strip(),
                "scope": ",".join(row.scopes),
                "summary": str(row.summary).strip(),
                "status": "up_for_grabs",
            }
        )
    return rows


def _sync_task_specialists(
    *,
    workboard_path: Path,
    now: datetime,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    task_rows = _task_rows_for_specialist_routing(
        active_tasks=active_tasks,
        up_for_grabs=up_for_grabs,
    )

    now_iso = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    entries: list[str] = []
    for row in sorted(task_rows, key=lambda item: _norm(item.get("task_id", ""))):
        route = task_specialists.infer_specialist(
            task_id=row["task_id"],
            scope=row["scope"],
            summary=row["summary"],
        )
        matched = ",".join([str(v) for v in list(route.get("matched_keywords") or [])]) or "none"
        reason = str(route.get("reason") or "rule-based specialist route").strip().replace(";", ",")
        entries.append(
            f"- task_id={_sanitize('task_id', row['task_id'])}; "
            f"task_type={_sanitize('task_type', str(route.get('task_type') or 'generalist_engineering'))}; "
            f"specialist={_sanitize('specialist', str(route.get('specialist') or 'specialist-generalist-engineering'))}; "
            f"status={_sanitize('status', row['status'])}; "
            f"matched_keywords={_sanitize('matched_keywords', matched)}; "
            f"reason={_sanitize('reason', reason)}; "
            f"updated_at={_sanitize('updated_at', now_iso)}"
        )

    if apply:
        text = workboard_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        section_start, section_end = _ensure_section(lines, heading=TASK_SPECIALIST_HEADING)
        _write_section_entries(lines, section_start=section_start, section_end=section_end, entries=entries)
        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        ok_write, violations_after = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
            workboard_path,
            text,
            new_text,
        )
        if not ok_write:
            return False, {"error": "specialist route sync rejected by gate", "violations": list(violations_after)}

    return True, {
        "routed_task_count": len(entries),
        "tracked_task_count": len(task_rows),
        "applied": bool(apply),
    }


def _specialist_for_task(
    *,
    workboard_path: Path,
    task_id: str,
    task_scope: str,
    task_summary: str,
) -> tuple[bool, dict[str, object]]:
    task_id_clean = str(task_id or "").strip()
    task_scope_clean = str(task_scope or "").strip()
    task_summary_clean = str(task_summary or "").strip()

    if not task_id_clean and not task_scope_clean and not task_summary_clean:
        return False, {"error": "provide --task-id or --task-scope/--task-summary"}

    if task_id_clean:
        violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
        if violations:
            return False, {"error": "workboard invalid", "violations": list(violations)}
        matches = _task_rows_for_specialist_routing(active_tasks=active_tasks, up_for_grabs=up_for_grabs)
        selected = next((row for row in matches if _norm(row.get("task_id", "")) == _norm(task_id_clean)), None)
        if selected is None:
            return False, {"error": f"task `{task_id_clean}` not found in active/up-for-grabs lanes"}
        task_scope_clean = selected.get("scope", "")
        task_summary_clean = selected.get("summary", "")
        task_id_clean = selected.get("task_id", task_id_clean)

    route = task_specialists.infer_specialist(
        task_id=task_id_clean or "adhoc-task",
        scope=task_scope_clean,
        summary=task_summary_clean,
    )
    payload = {
        "task_id": task_id_clean or "adhoc-task",
        "task_scope": task_scope_clean,
        "task_summary": task_summary_clean,
        "task_type": route.get("task_type"),
        "specialist": route.get("specialist"),
        "matched_keywords": list(route.get("matched_keywords") or []),
        "reason": route.get("reason"),
        "score": int(route.get("score") or 0),
    }
    return True, payload


def _default_plan_path(task_id: str, plan_root: str) -> str:
    safe_task_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(task_id or "").strip()).strip("-") or "task"
    rel = Path(plan_root) / safe_task_id / "PLAN.md"
    return str(rel).replace("\\", "/")


def _default_problem_path(task_id: str, problem_root: str) -> str:
    safe_task_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(task_id or "").strip()).strip("-") or "task"
    rel = Path(problem_root) / safe_task_id / "PROBLEM.md"
    return str(rel).replace("\\", "/")


def _build_plan_template(
    *,
    task_id: str,
    owner: str,
    summary: str,
    scope: str,
    status: str,
    now_iso: str,
) -> str:
    return (
        f"# Task Plan: {task_id}\n\n"
        f"- task_id: `{task_id}`\n"
        f"- owner: `{owner}`\n"
        f"- status: `{status}`\n"
        f"- scope: `{scope}`\n"
        f"- summary: {summary}\n"
        f"- created_at_utc: `{now_iso}`\n\n"
        "## Objective\n\n"
        "- Define the desired end state for this task.\n\n"
        "## Constraints\n\n"
        "- List hard constraints and guardrails before implementation.\n\n"
        "## Plan\n\n"
        "1. Gather current context and failure signals.\n"
        "2. Implement the smallest complete change that resolves root cause.\n"
        "3. Validate with focused tests and runtime checks.\n\n"
        "## Progress Log\n\n"
        f"- {now_iso} check-in: PLAN scaffold generated by task manager.\n\n"
        "## Handoff Notes\n\n"
        "- Record what is done, what remains, and exact resume commands.\n"
    )


def _build_problem_template(
    *,
    task_id: str,
    owner: str,
    summary: str,
    scope: str,
    status: str,
    now_iso: str,
) -> str:
    return (
        f"# Task Problem Record: {task_id}\n\n"
        f"- task_id: `{task_id}`\n"
        f"- owner: `{owner}`\n"
        f"- status: `{status}`\n"
        f"- scope: `{scope}`\n"
        f"- summary: {summary}\n"
        f"- created_at_utc: `{now_iso}`\n"
        f"- last_synced_at_utc: `{now_iso}`\n\n"
        "## Problem Statement\n\n"
        "- Describe what is broken, missing, or risky.\n\n"
        "## Evidence\n\n"
        "- Link logs, failing tests, screenshots, or message ids.\n\n"
        "## Root Cause Hypothesis\n\n"
        "- Capture the current best explanation before coding.\n\n"
        "## Fix Plan\n\n"
        "1. Implement the smallest root-cause fix.\n"
        "2. Validate using focused tests and runtime checks.\n"
        "3. Record final outcome and residual risk.\n\n"
        "## Outcome\n\n"
        "- Pending implementation.\n"
    )


def _sync_task_plans(
    *,
    workboard_path: Path,
    plan_root: str,
    problem_root: str,
    apply: bool,
    now: datetime,
) -> tuple[bool, dict[str, object]]:
    violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    owner_by_task: dict[str, str] = {}
    summary_by_task: dict[str, str] = {}
    scope_by_task: dict[str, str] = {}
    status_by_task: dict[str, str] = {}

    for row in active_tasks:
        key = str(row.task_id).strip()
        owner_by_task[key] = row.agent
        summary_by_task[key] = row.summary
        scope_by_task[key] = ",".join(row.scopes)
        status_by_task[key] = row.status

    for row in up_for_grabs:
        key = str(row.task_id).strip()
        owner_by_task.setdefault(key, "unassigned")
        summary_by_task.setdefault(key, row.summary)
        scope_by_task.setdefault(key, ",".join(row.scopes))
        status_by_task.setdefault(key, "up_for_grabs")

    tracked_task_ids = sorted(owner_by_task.keys(), key=str.lower)

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _ensure_section(lines, heading=TASK_PLANS_HEADING)
    problems_start, problems_end = _ensure_section(lines, heading=TASK_PROBLEMS_HEADING)

    existing_plans: dict[str, dict[str, str]] = {}
    existing_problems: dict[str, dict[str, str]] = {}
    parse_errors: list[str] = []
    for idx in _bullet_indices(lines, section_start, section_end):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            parse_errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        task_id = str(fields.get("task_id", "")).strip()
        if not task_id:
            parse_errors.append(f"line {idx + 1}: missing task_id")
            continue
        existing_plans[_norm(task_id)] = fields

    for idx in _bullet_indices(lines, problems_start, problems_end):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            parse_errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        task_id = str(fields.get("task_id", "")).strip()
        if not task_id:
            parse_errors.append(f"line {idx + 1}: missing task_id")
            continue
        existing_problems[_norm(task_id)] = fields

    if parse_errors:
        return False, {"error": "task artifact section parse failed", "violations": parse_errors}

    created_plans: list[str] = []
    missing_plans: list[str] = []
    created_problems: list[str] = []
    missing_problems: list[str] = []
    updated_plan_entries: list[str] = []
    updated_problem_entries: list[str] = []
    now_iso = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    for task_id in tracked_task_ids:
        plan_row = existing_plans.get(_norm(task_id), {})
        problem_row = existing_problems.get(_norm(task_id), {})
        plan_path = str(plan_row.get("plan", "")).strip() or _default_plan_path(task_id, plan_root)
        problem_path = str(problem_row.get("problem", "")).strip() or _default_problem_path(task_id, problem_root)
        owner = owner_by_task[task_id]
        summary = summary_by_task[task_id]
        scope = scope_by_task[task_id]
        status = status_by_task[task_id]

        plan_abs = (ROOT / plan_path).resolve()
        if not plan_abs.exists():
            missing_plans.append(plan_path)
            if apply:
                plan_abs.parent.mkdir(parents=True, exist_ok=True)
                plan_abs.write_text(
                    _build_plan_template(
                        task_id=task_id,
                        owner=owner,
                        summary=summary,
                        scope=scope,
                        status=status,
                        now_iso=now_iso,
                    ),
                    encoding="utf-8",
                )
                created_plans.append(plan_path)
        updated_plan_entries.append(
            f"- task_id={_sanitize('task_id', task_id)}; plan={_sanitize('plan', plan_path)}; "
            f"owner={_sanitize('owner', owner)}; status={_sanitize('status', status)}; "
            f"updated_at={_sanitize('updated_at', now_iso)}; "
            f"summary={_sanitize('summary', summary)}"
        )

        problem_abs = (ROOT / problem_path).resolve()
        if not problem_abs.exists():
            missing_problems.append(problem_path)
            if apply:
                problem_abs.parent.mkdir(parents=True, exist_ok=True)
                problem_abs.write_text(
                    _build_problem_template(
                        task_id=task_id,
                        owner=owner,
                        summary=summary,
                        scope=scope,
                        status=status,
                        now_iso=now_iso,
                    ),
                    encoding="utf-8",
                )
                created_problems.append(problem_path)
        updated_problem_entries.append(
            f"- task_id={_sanitize('task_id', task_id)}; problem={_sanitize('problem', problem_path)}; "
            f"owner={_sanitize('owner', owner)}; status={_sanitize('status', status)}; "
            f"updated_at={_sanitize('updated_at', now_iso)}; "
            f"summary={_sanitize('summary', summary)}"
        )

    if (missing_plans or missing_problems) and not apply:
        return False, {
            "error": "missing task artifact files",
            "missing_plan_count": len(missing_plans),
            "missing_plans": missing_plans,
            "missing_problem_count": len(missing_problems),
            "missing_problems": missing_problems,
            "tracked_task_count": len(tracked_task_ids),
        }

    if apply:
        _write_section_entries(
            lines, section_start=section_start, section_end=section_end, entries=updated_plan_entries
        )
        refreshed_problems = _find_section(lines, heading_prefix=TASK_PROBLEMS_HEADING)
        if refreshed_problems is None:
            return False, {"error": f"missing `## {TASK_PROBLEMS_HEADING}` section after sync update"}
        _write_section_entries(
            lines,
            section_start=refreshed_problems[0],
            section_end=refreshed_problems[1],
            entries=updated_problem_entries,
        )
        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        ok, violations_after = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
            workboard_path, text, new_text
        )
        if not ok:
            return False, {"error": "workboard update rejected by gate", "violations": list(violations_after)}

    return True, {
        "tracked_task_count": len(tracked_task_ids),
        "plan_entry_count": len(updated_plan_entries),
        "created_plan_count": len(created_plans),
        "created_plans": created_plans,
        "missing_plan_count": len(missing_plans),
        "missing_plans": missing_plans,
        "problem_entry_count": len(updated_problem_entries),
        "created_problem_count": len(created_problems),
        "created_problems": created_problems,
        "missing_problem_count": len(missing_problems),
        "missing_problems": missing_problems,
        "applied": bool(apply),
    }


def _reassign_owned_open_issues(
    *,
    workboard_path: Path,
    from_owner: str,
    to_owner: str,
) -> tuple[bool, list[str], str | None]:
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    section = workboard_issue._find_issues_section(lines)  # type: ignore[attr-defined]
    issue_ids: list[str] = []

    for idx in workboard_issue._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue._parse_issue_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, [], err
        if entry is not None and workboard_issue._is_none_entry(entry):  # type: ignore[attr-defined]
            continue
        if not fields:
            continue
        if _norm(fields.get("owner", "")) != _norm(from_owner):
            continue
        if _norm(fields.get("state", "")) == "resolved":
            continue
        fields["owner"] = to_owner
        lines[idx] = workboard_issue._format_issue(  # type: ignore[attr-defined]
            issue_id=fields["issue_id"],
            task_id=fields["task_id"],
            reporter=fields["reporter"],
            owner=fields["owner"],
            state=fields["state"],
            summary=fields["summary"],
        )
        issue_ids.append(fields["issue_id"])

    if not issue_ids:
        return True, [], None
    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    ok, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path, original_text, new_text
    )
    if not ok:
        return False, [], "; ".join(violations)
    return True, issue_ids, None


def _stale_claims(
    *,
    workboard_path: Path,
    now: datetime,
    max_idle_minutes: float,
) -> tuple[list[str], list[dict[str, object]], dict[str, list[claims_gate.ActiveTask]]]:
    violations, claims, active_tasks, _grab, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return list(violations), [], {}

    ok_messages, payload_messages = workboard_message.list_messages(workboard_path)
    if not ok_messages:
        return [str(payload_messages.get("error", "message section parse failed"))], [], {}
    messages = list(payload_messages.get("messages") or [])
    activity_kinds = (
        "status",
        "handoff",
        "blocker",
        "coordination",
        "decision",
        "scope_change",
        "brainstorm_call",
        "brainstorm_note",
        "brainstorm_decision",
        "ping",
    )
    sender_last_seen = _latest_message_timestamp_by_sender(messages=messages, kinds=activity_kinds)

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    sessions: dict[str, datetime] = {}
    session_lease_expires: dict[str, datetime] = {}
    section = _find_section(lines, heading_prefix=AGENT_SESSIONS_HEADING)
    if section is not None:
        for idx in _bullet_indices(lines, section[0], section[1]):
            entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
            if err:
                return [f"agent sessions parse failed: {err}"], [], {}
            if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                continue
            if not fields:
                continue
            agent = str(fields.get("agent", "")).strip()
            stamp = _parse_iso_utc(str(fields.get("last_seen", "")).strip())
            lease_stamp = _parse_iso_utc(str(fields.get("lease_expires", "")).strip())
            if agent and stamp is not None:
                sessions[_norm(agent)] = stamp
            if agent and lease_stamp is not None:
                session_lease_expires[_norm(agent)] = lease_stamp

    max_age_seconds = float(max_idle_minutes) * 60.0
    now_ts = now.timestamp()
    tasks_by_agent: dict[str, list[claims_gate.ActiveTask]] = {}
    for task in active_tasks:
        tasks_by_agent.setdefault(_norm(task.agent), []).append(task)

    stale: list[dict[str, object]] = []
    for claim in claims:
        claim_ts = _line_commit_unix(workboard_path, int(claim.line_no))
        stale_item: dict[str, object] = {
            "agent": claim.agent,
            "line_no": int(claim.line_no),
            "task": claim.task,
            "scope": ",".join(claim.scopes),
        }
        agent_key = _norm(claim.agent)
        session_seen = sessions.get(agent_key)
        lease_expires = session_lease_expires.get(agent_key)
        message_seen = sender_last_seen.get(agent_key)
        freshest_seen = session_seen
        if message_seen is not None and (freshest_seen is None or message_seen > freshest_seen):
            freshest_seen = message_seen
        is_stale = False
        if lease_expires is not None and now.astimezone(timezone.utc) > lease_expires:
            age_seconds = max(0.0, now_ts - float(lease_expires.timestamp()))
            stale_item["age_minutes"] = round(age_seconds / 60.0, 2)
            stale_item["last_update_utc"] = _to_iso_utc(lease_expires)
            stale_item["issue"] = "session_lease_expired"
            is_stale = True
        elif freshest_seen is not None:
            seen_ts = float(freshest_seen.timestamp())
            age_seconds = max(0.0, now_ts - seen_ts)
            if age_seconds > max_age_seconds:
                stale_item["age_minutes"] = round(age_seconds / 60.0, 2)
                stale_item["last_update_utc"] = _to_iso_utc(freshest_seen)
                stale_item["issue"] = "agent_activity_timeout"
                is_stale = True
        elif claim_ts is None:
            stale_item["issue"] = "missing_blame_timestamp_and_activity"
            is_stale = True
        else:
            age_seconds = max(0.0, now_ts - float(claim_ts))
            if age_seconds > max_age_seconds:
                stale_item["age_minutes"] = round(age_seconds / 60.0, 2)
                stale_item["last_update_utc"] = datetime.fromtimestamp(claim_ts, tz=timezone.utc).isoformat()
                stale_item["issue"] = "claim_line_age_timeout"
                is_stale = True
        if not is_stale:
            continue
        task_rows = tasks_by_agent.get(agent_key, [])
        stale_item["task_ids"] = [row.task_id for row in task_rows]
        stale.append(stale_item)

    return [], stale, tasks_by_agent


def _update_inactive_agents_section(
    *,
    workboard_path: Path,
    stale_claims: list[dict[str, object]],
    task_manager_agent: str,
    now: datetime,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    if not stale_claims and not apply:
        return True, {"inactive_agent_count": 0, "updated": False}
    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _ensure_section(lines, heading=INACTIVE_AGENTS_HEADING)

    existing: dict[str, dict[str, str]] = {}
    parse_errors: list[str] = []
    for idx in _bullet_indices(lines, section_start, section_end):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            parse_errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        agent = str(fields.get("agent", "")).strip()
        if not agent:
            parse_errors.append(f"line {idx + 1}: missing agent")
            continue
        existing[_norm(agent)] = fields
    if parse_errors:
        return False, {"error": "inactive agents section parse failed", "violations": parse_errors}

    now_iso = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    updated: dict[str, dict[str, str]] = dict(existing)
    for item in stale_claims:
        agent = str(item.get("agent", "")).strip()
        if not agent:
            continue
        task_ids = ",".join(str(x).strip() for x in (item.get("task_ids") or []) if str(x).strip()) or "none"
        idle = str(item.get("age_minutes", "unknown"))
        updated[_norm(agent)] = {
            "agent": agent,
            "state": "inactive",
            "detected_at": now_iso,
            "idle_minutes": idle,
            "task_ids": task_ids,
            "notify": task_manager_agent,
            "action": "reactivate_or_reassign",
        }

    entries = [
        (
            f"- agent={_sanitize('agent', row['agent'])}; state={_sanitize('state', row['state'])}; "
            f"detected_at={_sanitize('detected_at', row['detected_at'])}; "
            f"idle_minutes={_sanitize('idle_minutes', row['idle_minutes'])}; "
            f"task_ids={_sanitize('task_ids', row['task_ids'])}; "
            f"notify={_sanitize('notify', row['notify'])}; "
            f"action={_sanitize('action', row['action'])}"
        )
        for _, row in sorted(updated.items(), key=lambda item: item[0])
    ]

    if apply:
        _write_section_entries(lines, section_start=section_start, section_end=section_end, entries=entries)
        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        ok, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
            workboard_path, text, new_text
        )
        if not ok:
            return False, {"error": "inactive section update rejected by gate", "violations": list(violations)}

    return True, {"inactive_agent_count": len(entries), "updated": bool(apply)}


def _sweep_inactive(
    *,
    workboard_path: Path,
    max_idle_minutes: float,
    task_manager_agent: str,
    now: datetime,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, stale_claims, tasks_by_agent = _stale_claims(
        workboard_path=workboard_path,
        now=now,
        max_idle_minutes=max_idle_minutes,
    )
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    blocked_task_ids: list[str] = []
    moved_task_ids: list[str] = []
    released_agents: list[str] = []
    reassigned_issue_ids: list[str] = []
    sent_message_ids: list[str] = []
    errors: list[str] = []

    if apply:
        for stale in stale_claims:
            agent = str(stale.get("agent", "")).strip()
            if not agent:
                continue
            ok_message, message_payload = workboard_message.send_message(
                workboard_path,
                sender=task_manager_agent,
                recipient=agent,
                summary=(f"inactivity detected for `{agent}`, confirm active status or allow task reassignment"),
                task_id="none",
                kind="ping",
                priority="p0",
                requested_action=("ack message if still active, or let task manager reassign blocked work"),
                decision="pending",
            )
            if ok_message:
                sent_message_ids.append(str(dict(message_payload.get("message") or {}).get("msg_id") or ""))
            else:
                errors.append("inactive ping message failed: " + str(message_payload.get("error") or "unknown error"))

            for task in sorted(tasks_by_agent.get(_norm(agent), []), key=lambda row: str(row.task_id).lower()):
                summary = (
                    f"agent `{agent}` marked inactive (> {max_idle_minutes:.2f} minutes idle), "
                    "task manager should reactivate or reassign"
                )
                ok_block, _msg_block, _issue_id = workboard_issue.block_task(
                    workboard_path,
                    task_id=task.task_id,
                    reporter=task_manager_agent,
                    owner=task_manager_agent,
                    summary=summary,
                    issue_id=f"{task.task_id}-inactive",
                )
                if ok_block:
                    blocked_task_ids.append(task.task_id)

                ok_move, msg_move = workboard_issue.move_task_to_up_for_grabs(
                    workboard_path,
                    task_id=task.task_id,
                    reported_by=task_manager_agent,
                    summary=task.summary,
                )
                if ok_move:
                    moved_task_ids.append(task.task_id)
                else:
                    errors.append(f"move task `{task.task_id}` failed: {msg_move}")

            stale_issue = str(stale.get("issue", "")).strip() or "agent_activity_timeout"
            dirty_release_reason = f"inactivity reclaim by {task_manager_agent} for {agent}: {stale_issue}"
            ok_release, msg_release = workboard_claim.release(
                workboard_path,
                agent=agent,
                allow_dirty=True,
                dirty_reason=dirty_release_reason,
            )
            if ok_release:
                released_agents.append(agent)
            elif "no active claim found" not in _norm(msg_release):
                errors.append(f"release claim `{agent}` failed: {msg_release}")

            ok_reassign, issue_ids, reassign_err = _reassign_owned_open_issues(
                workboard_path=workboard_path,
                from_owner=agent,
                to_owner=task_manager_agent,
            )
            if ok_reassign:
                reassigned_issue_ids.extend(issue_ids)
            else:
                errors.append(f"reassign issues for `{agent}` failed: {reassign_err or 'unknown error'}")

        ok_inactive, inactive_payload = _update_inactive_agents_section(
            workboard_path=workboard_path,
            stale_claims=stale_claims,
            task_manager_agent=task_manager_agent,
            now=now,
            apply=True,
        )
        if not ok_inactive:
            errors.append(str(inactive_payload.get("error", "inactive section update failed")))
    else:
        _update_inactive_agents_section(
            workboard_path=workboard_path,
            stale_claims=stale_claims,
            task_manager_agent=task_manager_agent,
            now=now,
            apply=False,
        )

    payload = {
        "stale_claim_count": len(stale_claims),
        "stale_claims": stale_claims,
        "blocked_task_count": len(sorted(set(blocked_task_ids))),
        "blocked_task_ids": sorted(set(blocked_task_ids), key=str.lower),
        "moved_task_count": len(sorted(set(moved_task_ids))),
        "moved_task_ids": sorted(set(moved_task_ids), key=str.lower),
        "released_agent_count": len(sorted(set(released_agents))),
        "released_agents": sorted(set(released_agents), key=str.lower),
        "reassigned_issue_count": len(sorted(set(reassigned_issue_ids))),
        "reassigned_issue_ids": sorted(set(reassigned_issue_ids), key=str.lower),
        "sent_message_count": len([item for item in sent_message_ids if item]),
        "sent_message_ids": sorted({item for item in sent_message_ids if item}, key=str.lower),
        "task_manager_agent": task_manager_agent,
        "max_idle_minutes": float(max_idle_minutes),
        "applied": bool(apply),
    }
    if errors:
        payload["errors"] = errors
        return False, payload
    return True, payload


def _remove_up_for_grabs_task(lines: list[str], *, task_id: str) -> tuple[bool, str]:
    section = workboard_issue._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]
    remove_idx: int | None = None
    key = _norm(task_id)
    for idx in workboard_issue._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue._parse_up_for_grabs_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, err
        if entry is not None and workboard_issue._is_none_entry(entry):  # type: ignore[attr-defined]
            continue
        if fields and _norm(fields.get("task_id", "")) == key:
            remove_idx = idx
            break
    if remove_idx is None:
        return False, f"up-for-grabs task `{task_id}` not found"
    del lines[remove_idx]
    section = workboard_issue._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]
    workboard_issue._ensure_none_if_empty(lines, section_start=section[0], section_end=section[1])  # type: ignore[attr-defined]
    return True, "removed up-for-grabs task"


def _get_up_for_grabs_task(workboard_path: Path, task_id: str) -> tuple[bool, dict[str, str] | None, str]:
    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = workboard_issue._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]
    key = _norm(task_id)
    for idx in workboard_issue._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue._parse_up_for_grabs_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, None, err
        if entry is not None and workboard_issue._is_none_entry(entry):  # type: ignore[attr-defined]
            continue
        if fields and _norm(fields.get("task_id", "")) == key:
            return True, fields, "ok"
    return False, None, f"up-for-grabs task `{task_id}` not found"


def _remove_inactive_agent(lines: list[str], *, agent: str) -> tuple[bool, str]:
    section = _find_section(lines, heading_prefix=INACTIVE_AGENTS_HEADING)
    if section is None:
        return True, "inactive section not present"
    removed = False
    for idx in sorted(_bullet_indices(lines, section[0], section[1]), reverse=True):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if fields and _norm(fields.get("agent", "")) == _norm(agent):
            del lines[idx]
            removed = True
    section = _find_section(lines, heading_prefix=INACTIVE_AGENTS_HEADING)
    if section is not None:
        entries: list[str] = []
        for idx in _bullet_indices(lines, section[0], section[1]):
            text = lines[idx].strip()
            if text.lower() in {f"- {token}" for token in claims_gate.NONE_TOKENS}:
                continue
            entries.append(text)
        _write_section_entries(lines, section_start=section[0], section_end=section[1], entries=entries)
    return True, "removed inactive agent entry" if removed else "inactive agent entry not found"


def _reactivate_task(
    *,
    workboard_path: Path,
    task_id: str,
    agent: str,
    task_summary: str | None,
    scope_override: str | None,
    name: str | None,
    role: str | None,
    parent: str | None,
) -> tuple[bool, dict[str, object]]:
    found, row, message = _get_up_for_grabs_task(workboard_path, task_id)
    if not found or row is None:
        return False, {"error": message}
    auto_task_id = workboard_claim._task_id_from_agent(agent)  # type: ignore[attr-defined]

    scope = str(scope_override or row.get("scope") or "").strip()
    summary = str(task_summary or row.get("summary") or "").strip()
    if not scope:
        return False, {"error": f"task `{task_id}` has empty scope and no --scope override was provided"}
    if not summary:
        return False, {"error": f"task `{task_id}` has empty summary and no --summary override was provided"}

    claim_kwargs: dict[str, object] = {}
    if name is not None:
        claim_kwargs["name"] = name
    if role is not None:
        claim_kwargs["role"] = role
    if parent is not None:
        claim_kwargs["parent"] = parent

    removed_up_for_grabs_before_claim = False

    def _attempt_claim() -> tuple[bool, str]:
        try:
            return workboard_claim.claim(
                workboard_path,
                agent=agent,
                scope=scope,
                task=f"[WIP] {summary}",
                **claim_kwargs,
            )
        except TypeError:
            # Backward compatibility: older claim helpers may not support identity fields.
            return workboard_claim.claim(
                workboard_path,
                agent=agent,
                scope=scope,
                task=f"[WIP] {summary}",
            )

    ok_claim, msg_claim = _attempt_claim()
    if not ok_claim:
        duplicate_task_id_conflict = _norm(task_id) == _norm(
            auto_task_id
        ) and "task_id appears in both active tasks and up-for-grabs" in _norm(str(msg_claim))
        if not duplicate_task_id_conflict:
            return False, {"error": msg_claim}

        preclaim_text = workboard_path.read_text(encoding="utf-8")
        preclaim_lines = preclaim_text.splitlines()
        ok_remove_preclaim, msg_remove_preclaim = _remove_up_for_grabs_task(
            preclaim_lines,
            task_id=task_id,
        )
        if not ok_remove_preclaim:
            return False, {"error": msg_remove_preclaim}
        preclaim_next = "\n".join(preclaim_lines) + ("\n" if preclaim_text.endswith("\n") else "")
        ok_preclaim_write, preclaim_violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
            workboard_path,
            preclaim_text,
            preclaim_next,
        )
        if not ok_preclaim_write:
            return False, {
                "error": "preclaim up-for-grabs removal rejected by gate",
                "violations": list(preclaim_violations),
            }
        removed_up_for_grabs_before_claim = True
        ok_claim, msg_claim = _attempt_claim()
        if not ok_claim:
            workboard_path.write_text(preclaim_text, encoding="utf-8")
            return False, {"error": msg_claim}

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    if not removed_up_for_grabs_before_claim:
        ok_remove_grab, msg_remove_grab = _remove_up_for_grabs_task(lines, task_id=task_id)
        if not ok_remove_grab:
            return False, {"error": msg_remove_grab}

    claim_section = workboard_claim._find_claim_section(lines)  # type: ignore[attr-defined]
    claim_name = agent
    claim_role = "solo"
    claim_parent = "none"
    for idx in workboard_claim._bullet_indices(lines, claim_section[0], claim_section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_claim._parse_claim_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, {"error": err}
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        if _norm(fields.get("agent", "")) != _norm(agent):
            continue
        claim_name = str(fields.get("name") or agent).strip() or agent
        claim_role = str(fields.get("role") or claim_role).strip() or claim_role
        claim_parent = str(fields.get("parent") or claim_parent).strip() or claim_parent
        break

    active_section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    target_idx: int | None = None
    auto_idx: int | None = None

    for idx in workboard_claim._bullet_indices(lines, active_section[0], active_section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_claim._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, {"error": err}
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        if _norm(fields.get("task_id", "")) == _norm(task_id):
            target_idx = idx
        if _norm(fields.get("task_id", "")) == _norm(auto_task_id):
            auto_idx = idx

    replacement = workboard_claim._format_active_task(  # type: ignore[attr-defined]
        task_id=task_id,
        agent=agent,
        scope=scope,
        summary=f"[WIP] {summary}",
        status="claimed",
        name=claim_name,
        role=claim_role,
        parent=claim_parent,
    )

    if target_idx is not None:
        lines[target_idx] = replacement
    elif auto_idx is not None:
        lines[auto_idx] = replacement
    else:
        for idx in sorted(workboard_claim._bullet_indices(lines, active_section[0], active_section[1]), reverse=True):  # type: ignore[attr-defined]
            entry = lines[idx].strip()[2:].strip()
            if entry.lower() in claims_gate.NONE_TOKENS:
                del lines[idx]
        active_section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
        lines.insert(active_section[1], replacement)

    active_section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    seen_target = False
    for idx in sorted(workboard_claim._bullet_indices(lines, active_section[0], active_section[1]), reverse=True):  # type: ignore[attr-defined]
        entry, fields, err = workboard_claim._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, {"error": err}
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        if _norm(fields.get("task_id", "")) == _norm(task_id):
            if seen_target:
                del lines[idx]
            else:
                seen_target = True
        elif _norm(fields.get("task_id", "")) == _norm(auto_task_id):
            del lines[idx]

    ok_inactive, inactive_msg = _remove_inactive_agent(lines, agent=agent)
    if not ok_inactive:
        return False, {"error": inactive_msg}

    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    ok_write, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path,
        text,
        new_text,
    )
    if not ok_write:
        return False, {"error": "reactivation update rejected by gate", "violations": list(violations)}

    return True, {
        "task_id": task_id,
        "agent": agent,
        "scope": scope,
        "summary": f"[WIP] {summary}",
        "reactivated": True,
    }


def _resolve_auto_start_agent(explicit_agent: str | None) -> tuple[bool, str, str]:
    explicit = str(explicit_agent or "").strip()
    if _is_orchestrator_agent(explicit):
        return (
            False,
            "",
            DEFAULT_ORCHESTRATOR_ERROR,
        )
    if explicit:
        return True, explicit, ""

    resolver = getattr(workboard_claim, "_resolve_agent", None)
    if not callable(resolver):
        return (
            False,
            "",
            "agent id is required for auto-start; set --agent or configure agent identity env.",
        )
    try:
        resolved = str(resolver(None))
    except Exception as exc:  # pragma: no cover
        return False, "", str(exc)
    if not resolved.strip():
        return (
            False,
            "",
            "agent id is required for auto-start; pass --agent or configure agent identity env.",
        )
    return True, resolved.strip(), ""


def _pick_auto_start_up_for_grabs_task(
    workboard_path: Path,
) -> tuple[bool, claims_gate.UpForGrabTask | None, str]:
    violations, _claims, _active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, None, "workboard invalid: " + "; ".join(violations)
    if not up_for_grabs:
        return False, None, "no up-for-grabs tasks available"

    task_type_map = _task_type_by_task_id(workboard_path)

    def _sort_key(task: claims_gate.UpForGrabTask) -> tuple[int, int, int, str]:
        task_type = task_type_map.get(_norm(task.task_id), "generalist_engineering")
        source = _task_priority_source(summary=str(task.summary), task_type=task_type)
        source_rank = 0 if source == "user" else 1
        priority, urgency, text = _task_priority_rank(task.summary)
        return (source_rank, priority, urgency, text)

    selected = sorted(list(up_for_grabs), key=_sort_key)[0]
    return True, selected, "ok"


def _auto_start_task_for_agent(
    *,
    workboard_path: Path,
    agent: str,
    task_manager_agent: str,
) -> tuple[bool, dict[str, object]]:
    if not str(agent).strip():
        return False, {"error": "agent id is required for auto-start"}
    if _is_orchestrator_agent(agent):
        return False, {"error": DEFAULT_ORCHESTRATOR_ERROR}

    violations, _claims, active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    agent_key = _norm(agent)
    agent_active = [item for item in active_tasks if _norm(item.agent) == agent_key]
    if agent_active:
        def _active_status_rank(status: str) -> int:
            normalized_status = _normalize_task_status(status)
            if normalized_status == "in_progress":
                return 0
            if normalized_status == "claimed":
                return 1
            if normalized_status == "queued":
                return 2
            return 9

        def _active_sort_key(item: claims_gate.ActiveTask) -> tuple[int, int, int, str]:
            priority, urgency, text = _task_priority_rank(item.summary)
            return (_active_status_rank(item.status), priority, urgency, text)

        working_tasks = [
            item
            for item in agent_active
            if _normalize_task_status(item.status) in {"in_progress", "claimed", "queued"}
        ]
        if working_tasks:
            target_task = sorted(working_tasks, key=_active_sort_key)[0]
            current_status = _normalize_task_status(target_task.status)
            if current_status == "in_progress":
                return True, {
                    "agent": agent,
                    "task_id": target_task.task_id,
                    "status": "in_progress",
                    "started": True,
                    "source": "existing",
                }

            if current_status == "queued":
                ok_claimed, payload_claimed = set_task_status(
                    workboard_path,
                    task_id=target_task.task_id,
                    status="claimed",
                    actor=agent,
                    enforce_transition=True,
                )
                if not ok_claimed:
                    return False, {
                        "error": f"failed to move `{target_task.task_id}` from queued to claimed",
                        "details": payload_claimed,
                    }

            ok_in_progress, payload_in_progress = set_task_status(
                workboard_path,
                task_id=target_task.task_id,
                status="in_progress",
                actor=agent,
                enforce_transition=True,
            )
            if not ok_in_progress:
                return False, {
                    "error": f"unable to move `{target_task.task_id}` to in_progress",
                    "details": payload_in_progress,
                }

            return True, {
                "agent": agent,
                "task_id": target_task.task_id,
                "status": "in_progress",
                "started": True,
                "source": "existing",
                "previous_status": current_status,
            }

        non_startable = sorted(
            [
                {
                    "task_id": item.task_id,
                    "status": _normalize_task_status(item.status),
                }
                for item in agent_active
            ],
            key=lambda item: item["task_id"],
        )
        return False, {
            "error": f"agent `{agent}` has non-startable active task state(s)",
            "active_tasks": non_startable,
            "status_note": "resolve blockers/review/done flow before auto-starting a new task",
        }

    ok_pick, pick, pick_error = _pick_auto_start_up_for_grabs_task(workboard_path)
    if not ok_pick or pick is None:
        return False, {"error": pick_error}

    ok_reactivate, payload_reactivate = _reactivate_task(
        workboard_path=workboard_path,
        task_id=str(pick.task_id),
        agent=agent,
        task_summary=str(pick.summary),
        scope_override=",".join(pick.scopes),
        name=None,
        role=None,
        parent=None,
    )
    if not ok_reactivate:
        return False, {"error": f"reactivation failed for `{pick.task_id}`", "details": payload_reactivate}

    task_id = str(payload_reactivate.get("task_id") or pick.task_id)
    ok_start, payload_start = set_task_status(
        workboard_path,
        task_id=task_id,
        status="in_progress",
        actor=agent,
        enforce_transition=True,
    )
    if not ok_start:
        return False, {
            "error": f"reactivated `{task_id}` but failed to move to in_progress",
            "details": payload_start,
            "reactivation": payload_reactivate,
        }

    return True, {
        "agent": agent,
        "task_id": task_id,
        "status": "in_progress",
        "started": True,
        "source": "up_for_grabs",
        "reactivation": payload_reactivate,
    }


def _auto_start_all_claimed_agents(
    *,
    workboard_path: Path,
    task_manager_agent: str,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, claims, active_tasks, up_for_grabs, _ = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    active_by_agent: dict[str, set[str]] = {}
    for row in active_tasks:
        agent_key = _norm(row.agent)
        if not agent_key:
            continue
        active_by_agent.setdefault(agent_key, set()).add(_normalize_task_status(row.status))

    target_agents: list[str] = []
    seen_targets: set[str] = set()
    skipped_non_startable_agents: list[str] = []
    for claim in claims:
        claim_agent_key = _norm(claim.agent)
        claim_agent = str(claim.agent).strip()
        if not claim_agent or _is_orchestrator_agent(claim_agent):
            continue
        if claim_agent_key in seen_targets:
            continue
        claim_rows = active_by_agent.get(claim_agent_key, set())
        if claim_rows and not any(item in {"in_progress", "claimed", "queued"} for item in claim_rows):
            skipped_non_startable_agents.append(claim_agent)
            continue
        target_agents.append(claim_agent)
        seen_targets.add(claim_agent_key)

    up_for_grabs_available = len(up_for_grabs)
    if not target_agents:
        return True, {
            "candidate_agent_count": 0,
            "attempted_count": 0,
            "already_in_progress_count": 0,
            "auto_started_count": 0,
            "assigned_count": 0,
            "up_for_grabs_available": int(up_for_grabs_available),
            "skipped_non_startable_count": len(skipped_non_startable_agents),
            "skipped_non_startable_agents": sorted(set(skipped_non_startable_agents), key=str.lower),
            "no_work_available_count": 0,
            "failed_agent_count": 0,
            "results": [],
            "applied": bool(apply),
        }

    assignments: list[dict[str, object]] = []
    attempted_count = 0
    auto_started_count = 0
    already_in_progress_count = 0
    no_work_agents: list[str] = []
    failed_agents: list[dict[str, object]] = []
    skipped_non_startable_agents: list[str] = list(skipped_non_startable_agents)

    for agent in target_agents:
        attempted_count += 1
        ok_start, payload_start = _auto_start_task_for_agent(
            workboard_path=workboard_path,
            agent=agent,
            task_manager_agent=task_manager_agent,
        )
        if ok_start:
            status = str(payload_start.get("status") or "").strip().lower()
            source = str(payload_start.get("source") or "").strip().lower()
            if status == "in_progress" and source == "existing":
                already_in_progress_count += 1
            else:
                auto_started_count += 1
            assignments.append({"agent": agent, **payload_start})
            continue

        error_text = str(payload_start.get("error", "")).strip().lower()
        if (
            error_text.startswith("agent `")
            and "non-startable active task state(s)" in error_text
        ):
            skipped_non_startable_agents.append(agent)
            continue

        if (
            str(payload_start.get("error", ""))
            .strip()
            .lower()
            .startswith("no up-for-grabs tasks available")
        ):
            no_work_agents.append(agent)
            continue

        failed_agents.append({"agent": agent, "error": payload_start.get("error")})

    payload: dict[str, object] = {
        "candidate_agent_count": len(target_agents),
        "attempted_count": attempted_count,
        "already_in_progress_count": already_in_progress_count,
        "auto_started_count": auto_started_count,
        "assigned_count": len(assignments),
        "up_for_grabs_available": int(up_for_grabs_available),
        "skipped_non_startable_count": len(set(skipped_non_startable_agents)),
        "skipped_non_startable_agents": sorted(set(skipped_non_startable_agents), key=str.lower),
        "no_work_available_count": len(no_work_agents),
        "no_work_available_agents": sorted(set(no_work_agents), key=str.lower),
        "failed_agent_count": len(failed_agents),
        "failed_agents": failed_agents,
        "results": assignments,
        "applied": bool(apply),
    }
    if failed_agents:
        payload["errors"] = [str(item.get("error") or item) for item in failed_agents]
        return False, payload
    return True, payload


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Task-manager automation for WORKBOARD protocols.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--auto-start",
        action="store_true",
        help="Auto-claim and move a task to in_progress for --agent when no working task is active.",
    )
    actions.add_argument("--sync-plans", action="store_true", help="Ensure per-task plan entries/files exist.")
    actions.add_argument("--sweep-inactive", action="store_true", help="Detect and process inactive agents.")
    actions.add_argument("--reactivate", action="store_true", help="Reactivate a task from Up For Grabs.")
    actions.add_argument("--sync-sessions", action="store_true", help="Sync active/inactive agent sessions.")
    actions.add_argument(
        "--monitor",
        action="store_true",
        help=(
            "Run monitor loop: sync board, recover swarms, auto-start claimed agents, "
            "ping silence, sweep inactive, and dispatch idle agents."
        ),
    )
    actions.add_argument(
        "--sync-specialists",
        action="store_true",
        help="Sync task-type specialist routes for active/up-for-grabs tasks.",
    )
    actions.add_argument(
        "--specialist-for-task",
        action="store_true",
        help="Return specialist route for one board task id or ad-hoc scope/summary text.",
    )
    actions.add_argument(
        "--capture-preference",
        action="store_true",
        help="Store task-orchestration preference (summary + verbatim) in preferences.",
    )

    parser.add_argument("--apply", action="store_true", help="Apply mutations instead of dry-run checks.")
    parser.add_argument("--now", default="", help="Optional ISO now override for deterministic checks.")

    parser.add_argument("--plan-root", default=DEFAULT_PLAN_ROOT, help="Plan root path for generated PLAN.md files.")
    parser.add_argument(
        "--problem-root",
        default=DEFAULT_PROBLEM_ROOT,
        help="Problem root path for generated PROBLEM.md files.",
    )

    parser.add_argument(
        "--max-idle-minutes",
        type=float,
        default=DEFAULT_MAX_IDLE_MINUTES,
        help="Idle threshold in minutes for inactive-agent detection (default: 1).",
    )
    parser.add_argument(
        "--task-manager-agent",
        default=DEFAULT_TASK_MANAGER_AGENT,
        help="Agent id assigned as issue owner/notification target.",
    )
    parser.add_argument(
        "--max-agent-silence-minutes",
        type=float,
        default=DEFAULT_MAX_AGENT_SILENCE_MINUTES,
        help="Silence threshold before pinging active-task agents (default: 5).",
    )
    parser.add_argument(
        "--session-lease-minutes",
        type=float,
        default=DEFAULT_SESSION_LEASE_MINUTES,
        help="Lease TTL for active sessions before they are considered expired (default: 5).",
    )
    parser.add_argument(
        "--max-dispatch-per-cycle",
        type=int,
        default=DEFAULT_MAX_DISPATCH_PER_CYCLE,
        help="Maximum up-for-grabs tasks to auto-dispatch per monitor cycle (default: 2).",
    )
    parser.add_argument(
        "--online-lookback-minutes",
        type=float,
        default=30.0,
        help="Lookback window used to consider an agent online via message traffic (default: 30).",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=DEFAULT_MONITOR_CYCLES,
        help="Monitor cycle count (0 means run continuously; default: 1).",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_MONITOR_INTERVAL_SECONDS,
        help="Delay between monitor cycles (default: 30).",
    )
    parser.add_argument(
        "--no-swarm-recovery",
        action="store_true",
        help="Disable automatic swarm missing-agent relaunch in --monitor mode.",
    )
    parser.add_argument(
        "--no-idle-dispatch",
        action="store_true",
        help="Disable automatic up-for-grabs dispatch to online idle agents in --monitor mode.",
    )
    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        help="Disable automatic claimed-agent auto-start in --monitor mode.",
    )

    parser.add_argument("--task-id", default="", help="Task id for --reactivate or --specialist-for-task.")
    parser.add_argument("--agent", default="", help="Agent id for --reactivate.")
    parser.add_argument("--summary", default="", help="Optional summary override for --reactivate.")
    parser.add_argument("--scope", default="", help="Optional scope override for --reactivate.")
    parser.add_argument("--task-scope", default="", help="Scope text for ad-hoc --specialist-for-task routing.")
    parser.add_argument("--task-summary", default="", help="Summary text for ad-hoc --specialist-for-task routing.")
    parser.add_argument("--name", default="", help="Optional claim display name for --reactivate.")
    parser.add_argument("--role", default="", help="Optional role for --reactivate (solo|parent|worker).")
    parser.add_argument("--parent", default="", help="Optional parent id for --reactivate worker role.")
    parser.add_argument("--user-id", default="default", help="Preferences user id for --capture-preference.")
    parser.add_argument(
        "--preference-summary",
        default="",
        help="Preference summary used as primary weighted instruction for --capture-preference.",
    )
    parser.add_argument(
        "--preference-verbatim",
        default="",
        help="Verbatim user instruction to retain for audit context with --capture-preference.",
    )

    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()
    if not workboard_path.exists():
        payload = {
            "action": "workboard_task_manager",
            "ok": False,
            "error": f"missing workboard file: {workboard_path}",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1

    try:
        now = _parse_now(args.now)
    except Exception as exc:
        payload = {"action": "workboard_task_manager", "ok": False, "error": f"invalid --now value: {exc}"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1

    if args.max_idle_minutes <= 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--max-idle-minutes must be > 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.max_agent_silence_minutes <= 0:
        payload = {
            "action": "workboard_task_manager",
            "ok": False,
            "error": "--max-agent-silence-minutes must be > 0",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.max_dispatch_per_cycle < 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--max-dispatch-per-cycle must be >= 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.session_lease_minutes <= 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--session-lease-minutes must be > 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.online_lookback_minutes <= 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--online-lookback-minutes must be > 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.cycles < 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--cycles must be >= 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.interval_seconds < 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--interval-seconds must be >= 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1

    if args.monitor:
        now_seed = now if str(args.now).strip() else None
        ok_plan_sync, plan_sync_details = _sync_task_plans(
            workboard_path=workboard_path,
            plan_root=str(args.plan_root),
            problem_root=str(args.problem_root),
            apply=bool(args.apply),
            now=now,
        )
        if not ok_plan_sync:
            payload = {
                "action": "monitor",
                "ok": False,
                "workboard": str(workboard_path),
                "plan_sync": plan_sync_details,
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- plan sync failed: {payload.get('error', plan_sync_details.get('error', 'unknown'))}")
            return 1
        ok, details = _monitor_loop(
            workboard_path=workboard_path,
            plan_root=str(args.plan_root),
            problem_root=str(args.problem_root),
            task_manager_agent=str(args.task_manager_agent),
            max_idle_minutes=float(args.max_idle_minutes),
            max_agent_silence_minutes=float(args.max_agent_silence_minutes),
            session_lease_minutes=float(args.session_lease_minutes),
            max_dispatch_per_cycle=int(args.max_dispatch_per_cycle),
            online_lookback_minutes=float(args.online_lookback_minutes),
            run_swarm_recovery=not bool(args.no_swarm_recovery),
            run_auto_start=not bool(args.no_auto_start),
            run_idle_dispatch=not bool(args.no_idle_dispatch),
            cycles=int(args.cycles),
            interval_seconds=float(args.interval_seconds),
            now_seed=now_seed,
            apply=bool(args.apply),
        )
        payload = {
            "action": "monitor",
            "ok": bool(ok),
            "workboard": str(workboard_path),
            "plan_sync": plan_sync_details,
            **details,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            print(
                f"- cycles run: {payload.get('cycle_count', 0)}; "
                f"swarm recovery: {payload.get('run_swarm_recovery')}; "
                f"auto-start: {payload.get('run_auto_start')}; "
                f"idle dispatch: {payload.get('run_idle_dispatch')}"
            )
            if ok_plan_sync:
                print(
                    "- plan sync: "
                    f"tracked={payload.get('plan_sync', {}).get('tracked_task_count', 0)}; "
                    f"created plans={payload.get('plan_sync', {}).get('created_plan_count', 0)}; "
                    f"created problems={payload.get('plan_sync', {}).get('created_problem_count', 0)}; "
                    f"missing plans={payload.get('plan_sync', {}).get('missing_plan_count', 0)}; "
                    f"missing problems={payload.get('plan_sync', {}).get('missing_problem_count', 0)}"
                )
        return 0 if ok else 1

    if args.sync_plans:
        ok, details = _sync_task_plans(
            workboard_path=workboard_path,
            plan_root=str(args.plan_root),
            problem_root=str(args.problem_root),
            apply=bool(args.apply),
            now=now,
        )
        payload = {"action": "sync_plans", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- tracked tasks: {payload.get('tracked_task_count', 0)}; "
                    f"plan entries: {payload.get('plan_entry_count', 0)}; "
                    f"created plans: {payload.get('created_plan_count', 0)}; "
                    f"problem entries: {payload.get('problem_entry_count', 0)}; "
                    f"created problems: {payload.get('created_problem_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync plans failed')}")
        return 0 if ok else 1

    if args.sync_sessions:
        ok, details = _sync_agent_sessions(
            workboard_path=workboard_path,
            now=now,
            session_lease_minutes=float(args.session_lease_minutes),
            apply=bool(args.apply),
        )
        payload = {"action": "sync_sessions", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- session entries: {payload.get('session_entry_count', 0)}; "
                    f"created session ids: {payload.get('created_session_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync sessions failed')}")
        return 0 if ok else 1

    if args.sync_specialists:
        ok, details = _sync_task_specialists(
            workboard_path=workboard_path,
            now=now,
            apply=bool(args.apply),
        )
        payload = {"action": "sync_specialists", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- routed tasks: {payload.get('routed_task_count', 0)}; "
                    f"tracked tasks: {payload.get('tracked_task_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync specialists failed')}")
        return 0 if ok else 1

    if args.specialist_for_task:
        ok, details = _specialist_for_task(
            workboard_path=workboard_path,
            task_id=str(args.task_id).strip(),
            task_scope=str(args.task_scope).strip(),
            task_summary=str(args.task_summary).strip(),
        )
        payload = {"action": "specialist_for_task", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(f"- task `{payload.get('task_id')}` -> {payload.get('task_type')} / {payload.get('specialist')}")
            else:
                print(f"- {payload.get('error', 'specialist resolution failed')}")
        return 0 if ok else 1

    if args.sweep_inactive:
        ok, details = _sweep_inactive(
            workboard_path=workboard_path,
            max_idle_minutes=float(args.max_idle_minutes),
            task_manager_agent=str(args.task_manager_agent),
            now=now,
            apply=bool(args.apply),
        )
        payload = {"action": "sweep_inactive", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            print(
                f"- stale claims: {payload.get('stale_claim_count', 0)} (threshold {float(args.max_idle_minutes):.2f}m)"
            )
            if args.apply:
                print(
                    f"- moved tasks: {payload.get('moved_task_count', 0)}; "
                    f"released agents: {payload.get('released_agent_count', 0)}"
                )
                print(f"- coordination pings: {payload.get('sent_message_count', 0)}")
            if not ok:
                for item in payload.get("errors", []):
                    print(f"- {item}")
        return 0 if ok else 1

    if args.auto_start:
        ok_agent, resolved_agent, agent_error = _resolve_auto_start_agent(args.agent)
        if not ok_agent:
            payload = {"action": "auto_start", "ok": False, "error": agent_error}
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- {payload['error']}")
            return 1

        ok, details = _auto_start_task_for_agent(
            workboard_path=workboard_path,
            agent=resolved_agent,
            task_manager_agent=str(args.task_manager_agent),
        )
        payload = {"action": "auto_start", "ok": bool(ok), "workboard": str(workboard_path), "agent": resolved_agent, **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                source = str(details.get("source") or "unknown")
                print(f"- started task `{details.get('task_id')}` for `{resolved_agent}` (source: {source})")
            else:
                print(f"- {details.get('error', 'auto-start failed')}")
        return 0 if ok else 1

    if args.reactivate:
        if _is_orchestrator_agent(str(args.agent)):
            payload = {
                "action": "reactivate",
                "ok": False,
                "error": "reactivate is disabled for orchestrator agents",
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- {payload['error']}")
            return 1
        if not str(args.task_id).strip() or not str(args.agent).strip():
            payload = {
                "action": "reactivate",
                "ok": False,
                "error": "--task-id and --agent are required for --reactivate",
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- {payload['error']}")
            return 1
        ok, details = _reactivate_task(
            workboard_path=workboard_path,
            task_id=str(args.task_id).strip(),
            agent=str(args.agent).strip(),
            task_summary=str(args.summary).strip() or None,
            scope_override=str(args.scope).strip() or None,
            name=str(args.name).strip() or None,
            role=str(args.role).strip() or None,
            parent=str(args.parent).strip() or None,
        )
        if ok:
            task_id = str(details.get("task_id") or args.task_id).strip()
            ok_status, payload_status = set_task_status(
                workboard_path,
                task_id=task_id,
                status="in_progress",
                actor=str(args.agent).strip(),
                enforce_transition=True,
            )
            if not ok_status:
                details = {
                    "error": "reactivation succeeded but transition to in_progress failed",
                    "reactivation": details,
                    "status_error": payload_status,
                }
                ok = False

        payload = {"action": "reactivate", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(f"- reactivated task `{payload.get('task_id')}` for `{payload.get('agent')}`")
            else:
                print(f"- {payload.get('error', 'reactivation failed')}")
        return 0 if ok else 1

    if args.capture_preference:
        ok, details = _capture_task_ecosystem_preference(
            user_id=str(args.user_id).strip() or "default",
            summary=str(args.preference_summary).strip(),
            verbatim=str(args.preference_verbatim).strip(),
            now=now,
        )
        payload = {
            "action": "capture_preference",
            "ok": bool(ok),
            "workboard": str(workboard_path),
            **details,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- captured preference for user `{payload.get('user_id')}` "
                    f"(total stored: {payload.get('saved_preference_count', 0)})"
                )
            else:
                print(f"- {payload.get('error', 'capture preference failed')}")
        return 0 if ok else 1

    payload = {"action": "workboard_task_manager", "ok": False, "error": "no action selected"}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Workboard task manager: FAIL")
        print(f"- {payload['error']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
