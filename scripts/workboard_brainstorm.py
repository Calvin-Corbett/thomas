#!/usr/bin/env python3
"""Manage all-hands brainstorm sessions on WORKBOARD.md.

Brainstorm sessions are task-manager-led coordination loops:
1) Start a brainstorm session (optionally all-hands).
2) Summon participants through agent message traffic.
3) Collect structured contributions from agents.
4) Resolve with a decision and optional dispatch tasks.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.workboard_paths import default_workboard_path, resolve_workboard_path
except ImportError:  # pragma: no cover
    from workboard_paths import default_workboard_path, resolve_workboard_path  # type: ignore

try:
    from scripts import check_workboard_claims as claims_gate
    from scripts import workboard_issue, workboard_message
except Exception:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore
    import workboard_issue  # type: ignore
    import workboard_message  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = default_workboard_path(ROOT)
DEFAULT_FACILITATOR = "thomas"
NONE_ENTRY = "- none"

SESSIONS_HEADING = "Brainstorm Sessions"
NOTES_HEADING = "Brainstorm Notes"

SESSION_STATES = {"active", "decision_ready", "resolved", "cancelled"}
SESSION_MODES = {"all_hands", "targeted"}
NOTE_KINDS = {"proposal", "risk", "question", "vote", "decision"}
PRIORITIES = {"p0", "p1", "p2"}


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sanitize(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if ";" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} cannot include ';' or newline characters")
    return cleaned


def _validate_priority(priority: str) -> str:
    normalized = _norm(priority)
    if normalized not in PRIORITIES:
        allowed = ", ".join(sorted(PRIORITIES))
        raise ValueError(f"priority must be one of: {allowed}")
    return normalized


def _validate_session_state(state: str) -> str:
    normalized = _norm(state)
    if normalized not in SESSION_STATES:
        allowed = ", ".join(sorted(SESSION_STATES))
        raise ValueError(f"state must be one of: {allowed}")
    return normalized


def _validate_session_mode(mode: str) -> str:
    normalized = _norm(mode)
    if normalized not in SESSION_MODES:
        allowed = ", ".join(sorted(SESSION_MODES))
        raise ValueError(f"mode must be one of: {allowed}")
    return normalized


def _validate_note_kind(kind: str) -> str:
    normalized = _norm(kind)
    if normalized not in NOTE_KINDS:
        allowed = ", ".join(sorted(NOTE_KINDS))
        raise ValueError(f"kind must be one of: {allowed}")
    return normalized


def _split_agents(raw: str) -> list[str]:
    rows: list[str] = []
    for token in str(raw or "").split(","):
        clean = str(token or "").strip()
        if clean:
            rows.append(clean)
    return rows


def _format_agents(values: Sequence[str]) -> str:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        clean = str(item or "").strip()
        key = _norm(clean)
        if not clean or key in seen:
            continue
        _sanitize("agent", clean)
        seen.add(key)
        deduped.append(clean)
    return ",".join(deduped) if deduped else "none"


def _split_dispatch(raw: str) -> tuple[str, str, str]:
    parts = [str(part or "").strip() for part in str(raw or "").split("|", 2)]
    if len(parts) != 3:
        raise ValueError("dispatch item must be `task_id|scope|summary`")
    task_id = _sanitize("dispatch task_id", parts[0])
    scope = _sanitize("dispatch scope", parts[1])
    summary = _sanitize("dispatch summary", parts[2])
    return task_id, scope, summary


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

    payload = [f"## {heading}", "", NONE_ENTRY, ""]
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


def _write_entries(lines: list[str], *, section_start: int, section_end: int, entries: list[str]) -> None:
    for idx in sorted(_bullet_indices(lines, section_start, section_end), reverse=True):
        del lines[idx]
        if idx < section_end:
            section_end -= 1
    if not entries:
        lines.insert(section_end, NONE_ENTRY)
        return
    for entry in entries:
        lines.insert(section_end, entry)
        section_end += 1


def _normalize_session_fields(fields: dict[str, str]) -> dict[str, str]:
    now_iso = _now_iso()
    out = {
        "session_id": str(fields.get("session_id", "")).strip(),
        "task_id": str(fields.get("task_id", "")).strip(),
        "initiator": str(fields.get("initiator", "")).strip(),
        "facilitator": str(fields.get("facilitator", DEFAULT_FACILITATOR)).strip() or DEFAULT_FACILITATOR,
        "mode": str(fields.get("mode", "targeted")).strip() or "targeted",
        "state": str(fields.get("state", "active")).strip() or "active",
        "priority": str(fields.get("priority", "p1")).strip() or "p1",
        "summary": str(fields.get("summary", "")).strip(),
        "objective": str(fields.get("objective", "")).strip(),
        "invited_agents": _format_agents(_split_agents(str(fields.get("invited_agents", "none")))),
        "responded_agents": _format_agents(_split_agents(str(fields.get("responded_agents", "none")))),
        "decision": str(fields.get("decision", "none")).strip() or "none",
        "resolution_task_ids": str(fields.get("resolution_task_ids", "none")).strip() or "none",
        "created_at": str(fields.get("created_at", now_iso)).strip() or now_iso,
        "updated_at": str(fields.get("updated_at", now_iso)).strip() or now_iso,
    }
    _format_session(out)
    return out


def _normalize_note_fields(fields: dict[str, str]) -> dict[str, str]:
    now_iso = _now_iso()
    out = {
        "entry_id": str(fields.get("entry_id", "")).strip(),
        "session_id": str(fields.get("session_id", "")).strip(),
        "agent": str(fields.get("agent", "")).strip(),
        "kind": str(fields.get("kind", "proposal")).strip() or "proposal",
        "summary": str(fields.get("summary", "")).strip(),
        "created_at": str(fields.get("created_at", now_iso)).strip() or now_iso,
    }
    _format_note(out)
    return out


def _format_session(fields: dict[str, str]) -> str:
    session_id = _sanitize("session_id", fields.get("session_id", ""))
    task_id = _sanitize("task_id", fields.get("task_id", ""))
    initiator = _sanitize("initiator", fields.get("initiator", ""))
    facilitator = _sanitize("facilitator", fields.get("facilitator", DEFAULT_FACILITATOR))
    mode = _validate_session_mode(fields.get("mode", "targeted"))
    state = _validate_session_state(fields.get("state", "active"))
    priority = _validate_priority(fields.get("priority", "p1"))
    summary = _sanitize("summary", fields.get("summary", ""))
    objective = _sanitize("objective", fields.get("objective", ""))
    invited_agents = _sanitize("invited_agents", fields.get("invited_agents", "none"))
    responded_agents = _sanitize("responded_agents", fields.get("responded_agents", "none"))
    decision = _sanitize("decision", fields.get("decision", "none"))
    resolution_task_ids = _sanitize("resolution_task_ids", fields.get("resolution_task_ids", "none"))
    created_at = _sanitize("created_at", fields.get("created_at", ""))
    updated_at = _sanitize("updated_at", fields.get("updated_at", created_at))
    return (
        f"- session_id={session_id}; task_id={task_id}; initiator={initiator}; facilitator={facilitator}; "
        f"mode={mode}; state={state}; priority={priority}; summary={summary}; objective={objective}; "
        f"invited_agents={invited_agents}; responded_agents={responded_agents}; decision={decision}; "
        f"resolution_task_ids={resolution_task_ids}; created_at={created_at}; updated_at={updated_at}"
    )


def _format_note(fields: dict[str, str]) -> str:
    entry_id = _sanitize("entry_id", fields.get("entry_id", ""))
    session_id = _sanitize("session_id", fields.get("session_id", ""))
    agent = _sanitize("agent", fields.get("agent", ""))
    kind = _validate_note_kind(fields.get("kind", "proposal"))
    summary = _sanitize("summary", fields.get("summary", ""))
    created_at = _sanitize("created_at", fields.get("created_at", ""))
    return (
        f"- entry_id={entry_id}; session_id={session_id}; agent={agent}; kind={kind}; "
        f"summary={summary}; created_at={created_at}"
    )


def _load_sessions(lines: Sequence[str], section: tuple[int, int]) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for idx in _bullet_indices(lines, section[0], section[1]):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        try:
            rows.append(_normalize_session_fields(fields))
        except Exception as exc:
            errors.append(f"line {idx + 1}: {exc}")
    return rows, errors


def _load_notes(lines: Sequence[str], section: tuple[int, int]) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for idx in _bullet_indices(lines, section[0], section[1]):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        try:
            rows.append(_normalize_note_fields(fields))
        except Exception as exc:
            errors.append(f"line {idx + 1}: {exc}")
    return rows, errors


def _next_session_id(rows: Sequence[dict[str, str]], task_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", _norm(task_id)).strip("-") or "task"
    candidate = f"brainstorm-{stamp}-{slug}"
    seen = {_norm(row.get("session_id", "")) for row in rows}
    if _norm(candidate) not in seen:
        return candidate
    suffix = 2
    while True:
        variant = f"{candidate}-{suffix}"
        if _norm(variant) not in seen:
            return variant
        suffix += 1


def _next_note_id(rows: Sequence[dict[str, str]], agent: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", _norm(agent)).strip("-") or "agent"
    candidate = f"note-{stamp}-{slug}"
    seen = {_norm(row.get("entry_id", "")) for row in rows}
    if _norm(candidate) not in seen:
        return candidate
    suffix = 2
    while True:
        variant = f"{candidate}-{suffix}"
        if _norm(variant) not in seen:
            return variant
        suffix += 1


def _session_lookup(rows: Sequence[dict[str, str]], session_id: str) -> dict[str, str] | None:
    wanted = _norm(session_id)
    for row in rows:
        if _norm(row.get("session_id", "")) == wanted:
            return row
    return None


def _agent_set(raw: str) -> set[str]:
    out: set[str] = set()
    for token in _split_agents(raw):
        out.add(_norm(token))
    out.discard("none")
    out.discard("")
    return out


def _upsert_up_for_grabs(
    lines: list[str],
    *,
    new_rows: Sequence[str],
) -> None:
    section = _find_section(lines, heading_prefix="up for grabs")
    if section is None:
        raise ValueError("missing `## Up For Grabs` section in workboard")
    bullet_idxs = _bullet_indices(lines, section[0], section[1])
    for idx in sorted(bullet_idxs, reverse=True):
        entry = lines[idx].strip()[2:].strip()
        if entry.lower() in claims_gate.NONE_TOKENS:
            del lines[idx]
    section = _find_section(lines, heading_prefix="up for grabs")
    if section is None:
        raise ValueError("missing `## Up For Grabs` section in workboard")
    insert_at = section[1]
    for row in new_rows:
        lines.insert(insert_at, row)
        insert_at += 1


def _write_all(
    workboard_path: Path,
    *,
    sessions: Sequence[dict[str, str]],
    notes: Sequence[dict[str, str]],
    dispatch_rows: Sequence[str] | None = None,
) -> tuple[bool, list[str]]:
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    sessions_section = _ensure_section(lines, heading=SESSIONS_HEADING)
    notes_section = _ensure_section(lines, heading=NOTES_HEADING)
    _write_entries(
        lines,
        section_start=sessions_section[0],
        section_end=sessions_section[1],
        entries=[_format_session(dict(row)) for row in sessions],
    )
    notes_section = _find_section(lines, heading_prefix=NOTES_HEADING)
    if notes_section is None:
        return False, ["missing brainstorm notes section after update"]
    _write_entries(
        lines,
        section_start=notes_section[0],
        section_end=notes_section[1],
        entries=[_format_note(dict(row)) for row in notes],
    )
    if dispatch_rows:
        _upsert_up_for_grabs(lines, new_rows=list(dispatch_rows))

    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    ok, violations = workboard_issue._validate_and_write(workboard_path, original_text, new_text)  # type: ignore[attr-defined]
    return ok, list(violations)


def start_session(
    workboard_path: Path,
    *,
    task_id: str,
    summary: str,
    objective: str,
    initiator: str,
    facilitator: str,
    all_hands: bool,
    invite_agents: Sequence[str],
    priority: str,
    send_summons: bool,
) -> tuple[bool, dict[str, object]]:
    task_clean = _sanitize("task_id", task_id)
    summary_clean = _sanitize("summary", summary)
    objective_clean = _sanitize("objective", objective)
    initiator_clean = _sanitize("initiator", initiator)
    facilitator_clean = _sanitize("facilitator", facilitator)
    priority_clean = _validate_priority(priority)

    violations, claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    sessions_section = _ensure_section(lines, heading=SESSIONS_HEADING)
    notes_section = _ensure_section(lines, heading=NOTES_HEADING)
    sessions, session_errors = _load_sessions(lines, sessions_section)
    notes, note_errors = _load_notes(lines, notes_section)
    if session_errors or note_errors:
        return False, {"error": "brainstorm section parse failed", "violations": session_errors + note_errors}

    existing_task_ids = {_norm(row.task_id) for row in active_tasks} | {_norm(row.task_id) for row in up_for_grabs}
    if _norm(task_clean) not in existing_task_ids:
        return False, {
            "error": f"task `{task_clean}` must exist in active tasks or up-for-grabs before brainstorm start"
        }

    invited: list[str] = []
    if all_hands:
        for claim in claims:
            if _norm(claim.agent) != _norm(facilitator_clean):
                invited.append(claim.agent)
    invited.extend(list(invite_agents))
    invited_csv = _format_agents(invited)

    session_id = _next_session_id(sessions, task_clean)
    now_iso = _now_iso()
    row = _normalize_session_fields(
        {
            "session_id": session_id,
            "task_id": task_clean,
            "initiator": initiator_clean,
            "facilitator": facilitator_clean,
            "mode": "all_hands" if all_hands else "targeted",
            "state": "active",
            "priority": priority_clean,
            "summary": summary_clean,
            "objective": objective_clean,
            "invited_agents": invited_csv,
            "responded_agents": "none",
            "decision": "none",
            "resolution_task_ids": "none",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
    )
    sessions.append(row)
    ok_write, violations_write = _write_all(workboard_path, sessions=sessions, notes=notes)
    if not ok_write:
        return False, {"error": "brainstorm start rejected by gate", "violations": violations_write}

    summon_messages: list[str] = []
    if send_summons:
        for recipient in _split_agents(invited_csv):
            ok_send, payload_send = workboard_message.send_message(
                workboard_path,
                sender=facilitator_clean,
                recipient=recipient,
                summary=f"brainstorm summon {session_id}: {summary_clean}",
                task_id=task_clean,
                kind="brainstorm_call",
                priority=priority_clean,
                requested_action=(
                    f"pause lane and contribute with `workboard_brainstorm.py --contribute --session-id {session_id}`"
                ),
                decision="pending",
            )
            if not ok_send:
                return False, {
                    "error": f"failed to send summon to `{recipient}`",
                    "session_id": session_id,
                    **payload_send,
                }
            row_msg = dict(payload_send.get("message") or {})
            summon_messages.append(str(row_msg.get("msg_id", "")).strip())

    return True, {
        "session": row,
        "invited_count": len(_split_agents(invited_csv)),
        "sent_message_count": len([item for item in summon_messages if item]),
        "message_ids": summon_messages,
    }


def contribute(
    workboard_path: Path,
    *,
    session_id: str,
    agent: str,
    kind: str,
    summary: str,
) -> tuple[bool, dict[str, object]]:
    session_clean = _sanitize("session_id", session_id)
    agent_clean = _sanitize("agent", agent)
    kind_clean = _validate_note_kind(kind)
    summary_clean = _sanitize("summary", summary)

    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    sessions_section = _ensure_section(lines, heading=SESSIONS_HEADING)
    notes_section = _ensure_section(lines, heading=NOTES_HEADING)
    sessions, session_errors = _load_sessions(lines, sessions_section)
    notes, note_errors = _load_notes(lines, notes_section)
    if session_errors or note_errors:
        return False, {"error": "brainstorm section parse failed", "violations": session_errors + note_errors}

    session_row = _session_lookup(sessions, session_clean)
    if session_row is None:
        return False, {"error": f"brainstorm session `{session_clean}` not found"}
    if _norm(session_row.get("state", "")) in {"resolved", "cancelled"}:
        return False, {"error": f"session `{session_clean}` is not accepting contributions"}

    now_iso = _now_iso()
    note = _normalize_note_fields(
        {
            "entry_id": _next_note_id(notes, agent_clean),
            "session_id": session_clean,
            "agent": agent_clean,
            "kind": kind_clean,
            "summary": summary_clean,
            "created_at": now_iso,
        }
    )
    notes.append(note)

    invited = _agent_set(session_row.get("invited_agents", "none"))
    responded = _agent_set(session_row.get("responded_agents", "none"))
    if _norm(agent_clean):
        responded.add(_norm(agent_clean))
    session_row["responded_agents"] = _format_agents(sorted(responded))
    if invited and invited.issubset(responded):
        session_row["state"] = "decision_ready"
    session_row["updated_at"] = now_iso

    ok_write, violations_write = _write_all(workboard_path, sessions=sessions, notes=notes)
    if not ok_write:
        return False, {"error": "brainstorm contribution rejected by gate", "violations": violations_write}

    pending = sorted(invited - responded) if invited else []
    return True, {
        "session_id": session_clean,
        "state": session_row.get("state", "active"),
        "note": note,
        "pending_agents": pending,
        "pending_count": len(pending),
    }


def resolve_session(
    workboard_path: Path,
    *,
    session_id: str,
    facilitator: str,
    decision_summary: str,
    dispatch_items: Sequence[str],
    force: bool,
    broadcast_decision: bool,
) -> tuple[bool, dict[str, object]]:
    session_clean = _sanitize("session_id", session_id)
    facilitator_clean = _sanitize("facilitator", facilitator)
    decision_clean = _sanitize("decision_summary", decision_summary)

    violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    sessions_section = _ensure_section(lines, heading=SESSIONS_HEADING)
    notes_section = _ensure_section(lines, heading=NOTES_HEADING)
    sessions, session_errors = _load_sessions(lines, sessions_section)
    notes, note_errors = _load_notes(lines, notes_section)
    if session_errors or note_errors:
        return False, {"error": "brainstorm section parse failed", "violations": session_errors + note_errors}

    session_row = _session_lookup(sessions, session_clean)
    if session_row is None:
        return False, {"error": f"brainstorm session `{session_clean}` not found"}
    current_state = _norm(session_row.get("state", ""))
    if current_state in {"resolved", "cancelled"}:
        return False, {"error": f"session `{session_clean}` already closed"}
    if current_state != "decision_ready" and not force:
        return False, {"error": "session is not decision_ready; use --force to resolve anyway"}

    existing_task_ids = {_norm(row.task_id) for row in active_tasks} | {_norm(row.task_id) for row in up_for_grabs}
    dispatch_rows: list[str] = []
    dispatch_task_ids: list[str] = []
    for raw_item in dispatch_items:
        task_id, scope, summary = _split_dispatch(raw_item)
        if _norm(task_id) in existing_task_ids or _norm(task_id) in {_norm(x) for x in dispatch_task_ids}:
            return False, {"error": f"dispatch task_id `{task_id}` already exists in board"}
        row = workboard_issue._format_up_for_grabs(  # type: ignore[attr-defined]
            task_id=task_id,
            scope=scope,
            summary=summary,
            reported_by=facilitator_clean,
        )
        dispatch_rows.append(row)
        dispatch_task_ids.append(task_id)

    now_iso = _now_iso()
    decision_note = _normalize_note_fields(
        {
            "entry_id": _next_note_id(notes, facilitator_clean),
            "session_id": session_clean,
            "agent": facilitator_clean,
            "kind": "decision",
            "summary": decision_clean,
            "created_at": now_iso,
        }
    )
    notes.append(decision_note)

    session_row["state"] = "resolved"
    session_row["decision"] = decision_clean
    session_row["resolution_task_ids"] = ",".join(dispatch_task_ids) if dispatch_task_ids else "none"
    session_row["updated_at"] = now_iso

    ok_write, violations_write = _write_all(
        workboard_path,
        sessions=sessions,
        notes=notes,
        dispatch_rows=dispatch_rows if dispatch_rows else None,
    )
    if not ok_write:
        return False, {"error": "brainstorm resolution rejected by gate", "violations": violations_write}

    sent_msgs = 0
    if broadcast_decision:
        invited_agents = _split_agents(session_row.get("invited_agents", "none"))
        for recipient in invited_agents:
            ok_send, payload_send = workboard_message.send_message(
                workboard_path,
                sender=facilitator_clean,
                recipient=recipient,
                summary=f"brainstorm resolved {session_clean}: {decision_clean}",
                task_id=str(session_row.get("task_id", "none")),
                kind="brainstorm_decision",
                priority=str(session_row.get("priority", "p1")),
                requested_action=(
                    "claim dispatched tasks and execute according to brainstorm plan"
                    if dispatch_task_ids
                    else "resume normal task execution"
                ),
                decision="approved",
            )
            if not ok_send:
                return False, {"error": f"decision broadcast failed for `{recipient}`", **payload_send}
            sent_msgs += 1

    return True, {
        "session_id": session_clean,
        "state": session_row.get("state", "resolved"),
        "decision": decision_clean,
        "dispatch_task_ids": dispatch_task_ids,
        "dispatch_count": len(dispatch_task_ids),
        "broadcast_count": sent_msgs,
    }


def cancel_session(
    workboard_path: Path,
    *,
    session_id: str,
    facilitator: str,
    reason: str,
) -> tuple[bool, dict[str, object]]:
    session_clean = _sanitize("session_id", session_id)
    facilitator_clean = _sanitize("facilitator", facilitator)
    reason_clean = _sanitize("reason", reason)

    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    sessions_section = _ensure_section(lines, heading=SESSIONS_HEADING)
    notes_section = _ensure_section(lines, heading=NOTES_HEADING)
    sessions, session_errors = _load_sessions(lines, sessions_section)
    notes, note_errors = _load_notes(lines, notes_section)
    if session_errors or note_errors:
        return False, {"error": "brainstorm section parse failed", "violations": session_errors + note_errors}

    session_row = _session_lookup(sessions, session_clean)
    if session_row is None:
        return False, {"error": f"brainstorm session `{session_clean}` not found"}
    if _norm(session_row.get("state", "")) in {"resolved", "cancelled"}:
        return False, {"error": f"session `{session_clean}` already closed"}

    now_iso = _now_iso()
    session_row["state"] = "cancelled"
    session_row["decision"] = f"cancelled: {reason_clean}"
    session_row["updated_at"] = now_iso
    note = _normalize_note_fields(
        {
            "entry_id": _next_note_id(notes, facilitator_clean),
            "session_id": session_clean,
            "agent": facilitator_clean,
            "kind": "decision",
            "summary": f"session cancelled: {reason_clean}",
            "created_at": now_iso,
        }
    )
    notes.append(note)
    ok_write, violations_write = _write_all(workboard_path, sessions=sessions, notes=notes)
    if not ok_write:
        return False, {"error": "brainstorm cancel rejected by gate", "violations": violations_write}
    return True, {"session_id": session_clean, "state": "cancelled", "reason": reason_clean}


def session_status(workboard_path: Path, *, session_id: str) -> tuple[bool, dict[str, object]]:
    from scripts.workboard_brainstorm_cli import session_status as _session_status

    return _session_status(workboard_path, session_id=session_id)


def list_sessions(workboard_path: Path, *, state: str) -> tuple[bool, dict[str, object]]:
    from scripts.workboard_brainstorm_cli import list_sessions as _list_sessions

    return _list_sessions(workboard_path, state=state)


def run(argv: Sequence[str] | None = None) -> int:
    from scripts.workboard_brainstorm_cli import run as _run

    return _run(argv)


if __name__ == "__main__":
    raise SystemExit(run())
