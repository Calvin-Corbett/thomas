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

import re
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from scripts import check_workboard_claim_freshness as freshness_gate
    from scripts import check_workboard_claims as claims_gate
    from scripts import (
        workboard_brainstorm,
        workboard_claim,
        workboard_issue,
        workboard_message,
    )
    from thomas.core import task_bot_runtime
except Exception:  # pragma: no cover
    import check_workboard_claim_freshness as freshness_gate  # type: ignore
    import check_workboard_claims as claims_gate  # type: ignore
    import workboard_brainstorm  # type: ignore
    import workboard_claim  # type: ignore
    import workboard_issue  # type: ignore
    import workboard_message  # type: ignore

    from thomas.core import task_bot_runtime  # type: ignore


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
DEFAULT_INFERRED_EXPIRY_MINUTES = 10.0
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


def _strip_blocked_task_violations(
    violations: list[str] | tuple[str, ...],
    *,
    allow_blocked_without_issue: bool,
) -> list[str]:
    if not allow_blocked_without_issue:
        return list(violations)
    normalized_suffix = "must have an open/triaged entry in `## Issues / Blockers`"
    return [
        item
        for item in violations
        if not (item.startswith("blocked task `") and normalized_suffix in str(item).strip())
    ]


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
    require_claims_to_have_active_task: bool = True,
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
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    if not ok_write:
        return False, {
            "error": "task status update rejected by gate",
            "violations": list(violations),
        }
    try:
        task_bot_runtime.sync_task_state(
            task_id=task_clean,
            workboard_status=target_status,
            actor=actor_clean,
            summary=f"Task `{task_clean}` is now `{target_status}`.",
            claimed_owner=actor_clean,
            repo_root=ROOT,
        )
    except Exception:
        pass
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
    reporter = str(target_fields.get("reported_by", "")).strip() or str(task_manager_agent).strip() or "thomas"

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
    require_claims_to_have_active_task: bool,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, _claims, active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(
        workboard_path,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    violations = _strip_blocked_task_violations(
        violations,
        allow_blocked_without_issue=not bool(require_claims_to_have_active_task),
    )
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
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
