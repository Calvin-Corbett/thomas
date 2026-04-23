"""Message dispatch and coordination for task agents.

Handles silent agent detection, preference capture, and specialist routing.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from scripts import check_workboard_claims as claims_gate
    from scripts import task_specialists, workboard_issue, workboard_message
    from scripts import workboard_task_manager_reactivate
except Exception:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore
    import task_specialists  # type: ignore
    import workboard_issue  # type: ignore
    import workboard_message  # type: ignore
    import workboard_task_manager_reactivate  # type: ignore

try:
    from scripts.workboard_task_manager_base import (
        TASK_ECOSYSTEM_WEIGHTS,
        TASK_SPECIALIST_HEADING,
        _ensure_section,
        _norm,
        _parse_iso_utc,
        _sanitize,
        _strip_blocked_task_violations,
        _write_section_entries,
    )
except Exception:  # pragma: no cover
    from workboard_task_manager_base import (
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


def _load_worker_dispatch_catalog(workboard_path: Path) -> dict[str, object]:
    payload: dict[str, object] = {
        "tasks": set(),
        "prefixes": [],
        "has_default": True,
    }
    path = workboard_path.resolve().with_name("worker_command_catalog.json")
    if not path.exists():
        return payload
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return payload
    if not isinstance(raw, dict):
        return payload

    task_keys = {
        _norm(str(task_id))
        for task_id in dict(raw.get("tasks") or {}).keys()
        if _norm(str(task_id))
    }
    prefix_keys = sorted(
        (_norm(str(prefix)) for prefix in dict(raw.get("task_prefixes") or {}).keys() if _norm(str(prefix))),
        key=lambda item: (-len(item), item),
    )
    default_commands = [str(item).strip() for item in list(raw.get("default") or []) if str(item).strip()]
    return {
        "tasks": task_keys,
        "prefixes": prefix_keys,
        "has_default": bool(default_commands),
    }


def _worker_catalog_supports_task(task_id: str, catalog: dict[str, object]) -> bool:
    task_key = _norm(task_id)
    if not task_key:
        return False
    if task_key in set(catalog.get("tasks") or set()):
        return True
    for prefix in list(catalog.get("prefixes") or []):
        prefix_key = _norm(str(prefix))
        if prefix_key and task_key.startswith(prefix_key):
            return True
    return bool(catalog.get("has_default"))


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


def dispatch_idle_agents_once(
    *,
    workboard_path: Path,
    task_manager_agent: str,
    max_dispatch_per_cycle: int,
    online_lookback_minutes: float,
    require_claims_to_have_active_task: bool = False,
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

    ok_messages, payload_messages = workboard_message.list_messages(workboard_path)
    if not ok_messages:
        return False, {"error": "unable to load message traffic for idle dispatch", **payload_messages}

    threshold = datetime.now(timezone.utc) - timedelta(minutes=float(online_lookback_minutes))
    manager_key = _norm(task_manager_agent)
    busy_agents = {
        _norm(task.agent)
        for task in active_tasks
        if _norm(task.status) in {"queued", "claimed", "in_progress"}
    }
    online_candidates: dict[str, tuple[datetime, str]] = {}
    for row in list(payload_messages.get("messages") or []):
        sender_raw = str(row.get("from", "")).strip()
        sender = _norm(sender_raw)
        if not sender or sender == manager_key or sender in busy_agents:
            continue
        if _norm(str(row.get("task_id", ""))) not in {"", "none"}:
            continue
        kind = _norm(str(row.get("kind", "")))
        summary = _norm(str(row.get("summary", "")))
        if kind not in {"coordination", "ping"}:
            continue
        if "waiting for assignment" not in summary:
            continue
        stamp = _parse_iso_utc(str(row.get("updated_at", "")).strip() or str(row.get("created_at", "")).strip())
        if stamp is None or stamp < threshold:
            continue
        prior = online_candidates.get(sender)
        if prior is None or stamp > prior[0]:
            online_candidates[sender] = (stamp, sender_raw or sender)

    # Prefer the worker that has been idle the longest so a freshly-finished worker
    # does not keep stealing the next assignment from the rest of the pool.
    ordered_agents = [
        raw_agent
        for _agent_key, (_stamp, raw_agent) in sorted(
            online_candidates.items(),
            key=lambda item: (item[1][0].timestamp(), item[0]),
        )
    ]
    worker_catalog = _load_worker_dispatch_catalog(workboard_path)
    task_type_map = workboard_task_manager_reactivate._task_type_by_task_id(workboard_path)

    def _sort_key(task: claims_gate.UpForGrabTask) -> tuple[int, int, int, str]:
        task_type = task_type_map.get(_norm(task.task_id), "generalist_engineering")
        source = workboard_task_manager_reactivate._task_priority_source(summary=str(task.summary), task_type=task_type)
        source_rank = 0 if source == "user" else 1
        priority, urgency, text = workboard_task_manager_reactivate._task_priority_rank(task.summary)
        return (source_rank, priority, urgency, text)

    dispatched: list[dict[str, object]] = []
    errors: list[str] = []
    limit = max(0, int(max_dispatch_per_cycle))
    remaining_capacity = limit if limit > 0 else len(ordered_agents)

    for agent in ordered_agents:
        if remaining_capacity > 0 and len(dispatched) >= remaining_capacity:
            break
        violations_now, _claims_now, _active_now, up_for_grabs_now, _issues_now = claims_gate.evaluate_board(
            workboard_path,
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        )
        violations_now = _strip_blocked_task_violations(
            violations_now,
            allow_blocked_without_issue=not bool(require_claims_to_have_active_task),
        )
        if violations_now:
            return False, {"error": "workboard invalid", "violations": list(violations_now)}

        compatible_tasks = sorted(
            [
                task
                for task in up_for_grabs_now
                if _worker_catalog_supports_task(str(task.task_id), worker_catalog)
            ],
            key=_sort_key,
        )
        if not compatible_tasks:
            break
        pick = compatible_tasks[0]
        if not apply:
            dispatched.append({"agent": agent, "task_id": str(pick.task_id), "status": "preview"})
            continue
        ok_reactivate, payload_reactivate = workboard_task_manager_reactivate._reactivate_task(
            workboard_path=workboard_path,
            task_id=str(pick.task_id),
            agent=agent,
            task_summary=None,
            scope_override=None,
            name=agent,
            role="solo",
            parent="none",
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        )
        if ok_reactivate:
            dispatched.append({"agent": agent, **payload_reactivate})
            continue
        errors.append(str(payload_reactivate.get("error") or f"failed to dispatch `{pick.task_id}` to `{agent}`"))

    payload: dict[str, object] = {
        "candidate_agent_count": len(ordered_agents),
        "online_agents": ordered_agents,
        "up_for_grabs_available": len(up_for_grabs),
        "assigned_count": len(dispatched),
        "assignments": dispatched,
        "applied": bool(apply),
    }
    if errors:
        payload["errors"] = errors
        return False, payload
    return True, payload


def _dispatch_up_for_grabs_to_idle_agents(**kwargs) -> tuple[bool, dict[str, object]]:
    return dispatch_idle_agents_once(**kwargs)


def _monitor_loop(
    *,
    cycles: int,
    workboard_path: Path,
    task_manager_agent: str,
    max_agent_silence_minutes: float,
    max_dispatch_per_cycle: int,
    online_lookback_minutes: float,
    run_swarm_recovery: bool,
    run_auto_start: bool,
    run_idle_dispatch: bool,
    require_claims_to_have_active_task: bool,
    interval_seconds: float,
    now_seed: datetime | None,
    apply: bool,
    **kwargs,
) -> tuple[bool, dict[str, object]]:
    _ = kwargs
    cycle_count = 0
    loop_forever = int(cycles) == 0
    last_ping: dict[str, object] = {}
    last_dispatch: dict[str, object] = {}
    last_auto_start: dict[str, object] = {}

    while loop_forever or cycle_count < int(cycles):
        cycle_count += 1
        now = now_seed if now_seed is not None else datetime.now(timezone.utc)

        ok_ping, last_ping = _ping_silent_active_agents(
            workboard_path=workboard_path,
            now=now,
            task_manager_agent=task_manager_agent,
            max_agent_silence_minutes=float(max_agent_silence_minutes),
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
            apply=bool(apply),
        )
        if not ok_ping:
            return False, {
                "cycle_count": cycle_count,
                "run_swarm_recovery": bool(run_swarm_recovery),
                "run_auto_start": bool(run_auto_start),
                "run_idle_dispatch": bool(run_idle_dispatch),
                "ping": last_ping,
            }

        if run_auto_start:
            ok_auto, last_auto_start = workboard_task_manager_reactivate._auto_start_all_claimed_agents(
                workboard_path=workboard_path,
                task_manager_agent=task_manager_agent,
                require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
                apply=bool(apply),
            )
            if not ok_auto:
                return False, {
                    "cycle_count": cycle_count,
                    "run_swarm_recovery": bool(run_swarm_recovery),
                    "run_auto_start": bool(run_auto_start),
                    "run_idle_dispatch": bool(run_idle_dispatch),
                    "ping": last_ping,
                    "auto_start": last_auto_start,
                }

        if run_idle_dispatch:
            ok_dispatch, last_dispatch = dispatch_idle_agents_once(
                workboard_path=workboard_path,
                task_manager_agent=task_manager_agent,
                max_dispatch_per_cycle=int(max_dispatch_per_cycle),
                online_lookback_minutes=float(online_lookback_minutes),
                require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
                apply=bool(apply),
            )
            if not ok_dispatch:
                return False, {
                    "cycle_count": cycle_count,
                    "run_swarm_recovery": bool(run_swarm_recovery),
                    "run_auto_start": bool(run_auto_start),
                    "run_idle_dispatch": bool(run_idle_dispatch),
                    "ping": last_ping,
                    "auto_start": last_auto_start,
                    "idle_dispatch": last_dispatch,
                }

        if not loop_forever and cycle_count >= int(cycles):
            break
        if float(interval_seconds) > 0:
            time.sleep(float(interval_seconds))

    return True, {
        "cycle_count": cycle_count,
        "run_swarm_recovery": bool(run_swarm_recovery),
        "run_auto_start": bool(run_auto_start),
        "run_idle_dispatch": bool(run_idle_dispatch),
        "ping": last_ping,
        "auto_start": last_auto_start,
        "idle_dispatch": last_dispatch,
    }
