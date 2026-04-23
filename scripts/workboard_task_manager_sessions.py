"""Agent session and inferred presence claim management."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from scripts import check_workboard_claims as claims_gate
    from scripts import workboard_issue
except Exception:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore
    import workboard_issue  # type: ignore

try:
    from scripts.workboard_task_manager_base import (
        AGENT_SESSIONS_HEADING,
        _bullet_indices,
        _ensure_section,
        _is_authorized_model_alias,
        _norm,
        _parse_kv_entry,
        _sanitize,
        _strip_blocked_task_violations,
        _write_section_entries,
    )
except Exception:  # pragma: no cover
    from workboard_task_manager_base import (
        AGENT_SESSIONS_HEADING,
        _bullet_indices,
        _ensure_section,
        _is_authorized_model_alias,
        _norm,
        _parse_kv_entry,
        _sanitize,
        _strip_blocked_task_violations,
        _write_section_entries,
    )


def _default_model_alias(agent: str, preferred_name: str = "") -> str:
    preferred = str(preferred_name or "").strip()
    if preferred:
        return preferred
    raw_agent = str(agent or "").strip()
    if not raw_agent:
        return "agent"
    digits_match = re.search(r"(\d+)\s*$", raw_agent)
    digits = digits_match.group(1) if digits_match else ""
    base = re.sub(r"[\s_-]*\d+\s*$", "", raw_agent).strip(" -_") or raw_agent
    return f"{base}-{digits}" if digits else base


def _slug(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", _norm(value)).strip("-")
    return token or "agent"


def _parse_existing_sessions(
    lines: list[str], section_start: int, section_end: int
) -> tuple[dict[str, dict[str, str]], list[str]]:
    rows: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for idx in _bullet_indices(lines, section_start, section_end):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        agent = str(fields.get("agent", "")).strip()
        if not agent:
            errors.append(f"line {idx + 1}: missing agent")
            continue
        rows.setdefault(_norm(agent), fields)
    return rows, errors


def _unique_alias(candidate: str, *, agent: str, used: set[str]) -> str:
    if _norm(candidate) not in used and str(candidate or "").strip():
        return candidate
    fallback = _default_model_alias(agent)
    if _norm(fallback) not in used:
        return fallback
    base = fallback or candidate or str(agent or "agent").strip() or "agent"
    counter = 2
    while True:
        variant = f"{base}-{counter}"
        if _norm(variant) not in used:
            return variant
        counter += 1


def _sync_agent_sessions(
    *,
    workboard_path: Path,
    now: datetime,
    session_lease_minutes: float,
    require_claims_to_have_active_task: bool,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, claims, active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(
        workboard_path,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    violations = _strip_blocked_task_violations(
        violations,
        allow_blocked_without_issue=not bool(require_claims_to_have_active_task),
    )
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _ensure_section(lines, heading=AGENT_SESSIONS_HEADING)
    existing_rows, parse_errors = _parse_existing_sessions(lines, section_start, section_end)
    if parse_errors:
        return False, {"error": "agent sessions parse failed", "violations": parse_errors}

    active_task_by_agent: dict[str, str] = {}
    for task in sorted(active_tasks, key=lambda row: (str(row.agent).lower(), int(row.line_no))):
        active_task_by_agent.setdefault(_norm(task.agent), str(task.task_id))

    lease_delta = timedelta(minutes=float(session_lease_minutes))
    now_utc = now.astimezone(timezone.utc).replace(microsecond=0)
    now_iso = now_utc.isoformat()
    lease_iso = (now_utc + lease_delta).isoformat()
    stamp = now_utc.strftime("%Y%m%d%H%M%S")

    used_aliases: set[str] = set()
    used_session_ids: set[str] = set()
    created_session_ids = 0
    entries: list[str] = []

    for claim in sorted(claims, key=lambda row: (str(row.agent).lower(), int(row.line_no))):
        agent = str(claim.agent).strip()
        agent_key = _norm(agent)
        existing = existing_rows.get(agent_key, {})
        preferred_alias = str(existing.get("model_alias", "")).strip()
        if not _is_authorized_model_alias(preferred_alias, agent):
            preferred_alias = _default_model_alias(agent, str(claim.name or "").strip())
        alias = _unique_alias(preferred_alias, agent=agent, used=used_aliases)
        used_aliases.add(_norm(alias))

        existing_session_id = str(existing.get("session_id", "")).strip()
        if (
            existing_session_id
            and _norm(existing_session_id) not in used_session_ids
            and alias == str(existing.get("model_alias", "")).strip()
        ):
            session_id = existing_session_id
        else:
            session_id = f"sess-{stamp}-{_slug(alias)}"
            created_session_ids += 1
        used_session_ids.add(_norm(session_id))

        last_seen = str(existing.get("last_seen", "")).strip() or now_iso
        parent = str(claim.parent or existing.get("parent") or "none").strip() or "none"
        active_task = active_task_by_agent.get(agent_key, "none") or "none"
        state = "active" if active_task != "none" else str(existing.get("state", "idle")).strip() or "idle"

        entries.append(
            f"- agent={_sanitize('agent', agent)}; model_alias={_sanitize('model_alias', alias)}; "
            f"session_id={_sanitize('session_id', session_id)}; parent={_sanitize('parent', parent)}; "
            f"state={_sanitize('state', state)}; active_task={_sanitize('active_task', active_task)}; "
            f"last_seen={_sanitize('last_seen', last_seen)}; lease_expires={_sanitize('lease_expires', lease_iso)}"
        )

    payload: dict[str, object] = {
        "session_entry_count": len(entries),
        "created_session_count": int(created_session_ids),
        "session_lease_minutes": float(session_lease_minutes),
        "applied": bool(apply),
    }
    if not apply:
        return True, payload

    _write_section_entries(lines, section_start=section_start, section_end=section_end, entries=entries)
    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    ok, violations_after = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path,
        text,
        new_text,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    if not ok:
        return False, {"error": "session sync rejected by gate", "violations": list(violations_after)}
    return True, payload


def _sync_inferred_presence_claims(
    *,
    workboard_path: Path,
    now: datetime,
    require_claims_to_have_active_task: bool,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    _ = (workboard_path, now, require_claims_to_have_active_task, apply)
    return True, {"candidate_count": 0, "applied_count": 0, "suppressed_count": 0, "expired_count": 0}
