"""Message dispatch and coordination for task agents.

Handles silent agent detection, preference capture, and specialist routing.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts import task_specialists, workboard_issue
    from scripts.crew.workboard import message as workboard_message
    from scripts.forge.gates import workboard_claims as claims_gate
except ImportError:  # pragma: no cover
    import task_specialists  # type: ignore
    from crew.workboard import message as workboard_message  # type: ignore
    from forge.gates import workboard_claims as claims_gate  # type: ignore

    from scripts.crew.workboard import issue as workboard_issue  # type: ignore

try:
    from scripts.crew.tasks.base import (
        TASK_ECOSYSTEM_WEIGHTS,
        TASK_SPECIALIST_HEADING,
        _ensure_section,
        _norm,
        _parse_iso_utc,
        _sanitize,
        _strip_blocked_task_violations,
        _write_section_entries,
    )
except ImportError:  # pragma: no cover
    from crew.tasks.base import (
        TASK_ECOSYSTEM_WEIGHTS,
        TASK_SPECIALIST_HEADING,
        _ensure_section,
        _norm,
        _parse_iso_utc,
        _sanitize,
        _strip_blocked_task_violations,
        _write_section_entries,
    )

from thomas.preferences.store import PreferencesPatch, PreferencesStore, get_db_path


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
        return False, {"error": "unable to load message traffic for silence monitor", **payload_messages}
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
        if recipient_key != manager_key or kind not in active_kinds:
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
        if not is_silent or key in recent_pings:
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
            summary=f"idle monitor: no status update for `{task.task_id}` in {float(max_agent_silence_minutes):.2f} minutes",
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


def _lookup_board_task(workboard_path: Path, task_id: str) -> tuple[bool, dict[str, str] | None, str]:
    violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(
        workboard_path,
        require_claims_to_have_active_task=False,
    )
    violations = _strip_blocked_task_violations(violations, allow_blocked_without_issue=True)
    if violations:
        return False, None, "workboard invalid: " + "; ".join(violations)
    wanted = _norm(task_id)
    for row in active_tasks:
        if _norm(row.task_id) == wanted:
            return True, {"task_id": row.task_id, "scope": ",".join(row.scopes), "summary": row.summary}, "ok"
    for row in up_for_grabs:
        if _norm(row.task_id) == wanted:
            return True, {"task_id": row.task_id, "scope": ",".join(row.scopes), "summary": row.summary}, "ok"
    return False, None, f"task `{task_id}` not found on workboard"


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

    store = PreferencesStore(db_path=get_db_path())
    current = store.get(user_id=user_id)
    answers = dict(current.onboarding.answers or {})
    ecosystem = dict(answers.get("task_ecosystem") or {})
    rows = list(ecosystem.get("conduct_preferences") or [])
    now_iso = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    rows.append(
        {
            "summary": summary_clean,
            "verbatim": verbatim_clean,
            "captured_at": now_iso,
            "summary_weight": float(TASK_ECOSYSTEM_WEIGHTS["summary"]),
            "verbatim_weight": float(TASK_ECOSYSTEM_WEIGHTS["verbatim"]),
        }
    )
    ecosystem["current_preference_summary"] = summary_clean
    ecosystem["weights"] = dict(TASK_ECOSYSTEM_WEIGHTS)
    ecosystem["conduct_preferences"] = rows
    answers["task_ecosystem"] = ecosystem
    store.patch(PreferencesPatch(onboarding={"answers": answers}), user_id=user_id, thread_id=None)
    return True, {"user_id": user_id, "saved_preference_count": len(rows)}


def _sync_task_specialists(
    *,
    workboard_path: Path,
    now: datetime,
    require_claims_to_have_active_task: bool,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(
        workboard_path,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    violations = _strip_blocked_task_violations(
        violations,
        allow_blocked_without_issue=not bool(require_claims_to_have_active_task),
    )
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    tracked = [
        {"task_id": row.task_id, "scope": ",".join(row.scopes), "summary": row.summary} for row in active_tasks
    ] + [{"task_id": row.task_id, "scope": ",".join(row.scopes), "summary": row.summary} for row in up_for_grabs]

    payload: dict[str, object] = {
        "routed_task_count": len(tracked),
        "tracked_task_count": len(tracked),
        "applied": bool(apply),
    }
    if not tracked or not apply:
        return True, payload

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _ensure_section(lines, heading=TASK_SPECIALIST_HEADING)
    now_iso = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    entries: list[str] = []
    for row in sorted(tracked, key=lambda item: _norm(item["task_id"])):
        route = task_specialists.infer_specialist(
            task_id=str(row["task_id"]), scope=str(row["scope"]), summary=str(row["summary"])
        )
        entries.append(
            f"- task_id={_sanitize('task_id', str(row['task_id']))}; task_type={_sanitize('task_type', str(route['task_type']))}; "
            f"specialist={_sanitize('specialist', str(route['specialist']))}; updated_at={_sanitize('updated_at', now_iso)}"
        )

    _write_section_entries(lines, section_start=section_start, section_end=section_end, entries=entries)
    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    ok, violations_after = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path,
        text,
        new_text,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    if not ok:
        return False, {"error": "specialist sync rejected by gate", "violations": list(violations_after)}
    return True, payload


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

    if task_id_clean:
        found, row, message = _lookup_board_task(workboard_path, task_id_clean)
        if not found or row is None:
            return False, {"error": message}
        resolved_task_id = str(row["task_id"])
        resolved_scope = str(row["scope"])
        resolved_summary = str(row["summary"])
    else:
        resolved_task_id = "adhoc-task"
        resolved_scope = task_scope_clean
        resolved_summary = task_summary_clean
        if not resolved_scope and not resolved_summary:
            return False, {"error": "--task-id or ad-hoc --task-scope/--task-summary is required"}

    route = task_specialists.infer_specialist(task_id=resolved_task_id, scope=resolved_scope, summary=resolved_summary)
    return True, {
        "task_id": resolved_task_id,
        "task_scope": resolved_scope,
        "task_summary": resolved_summary,
        "task_type": str(route["task_type"]),
        "specialist": str(route["specialist"]),
        "matched_keywords": list(route.get("matched_keywords") or []),
        "score": int(route.get("score") or 0),
        "reason": str(route.get("reason") or ""),
    }


def dispatch_idle_agents_once(**kwargs) -> tuple[bool, dict[str, object]]:
    _ = kwargs
    return True, {}


def _dispatch_up_for_grabs_to_idle_agents(**kwargs) -> tuple[bool, dict[str, object]]:
    _ = kwargs
    return True, {}


def _monitor_loop(*, cycles: int, **kwargs) -> tuple[bool, dict[str, object]]:
    _ = kwargs
    return True, {"cycle_count": cycles}
