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

# `scripts.workboard_issue` was relocated to `scripts.crew.workboard.issue`
# during the Tier 5 rename arc — use the new path directly. The bare
# `import task_specialists` fallback that previously sat in a defensive
# `except ImportError` block only worked on Windows where the repo root
# happened to be on sys.path; on Linux CI it raised ModuleNotFoundError
# and broke collection of every test that imports from this module. The
# `_REPO_ROOT` sys.path insert above this block guarantees `scripts.*` is
# importable, so the fallback is no longer needed.
from scripts import task_specialists
from scripts.crew.workboard import issue as workboard_issue
from scripts.crew.workboard import message as workboard_message
from scripts.forge.gates import workboard_claims as claims_gate

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


def dispatch_idle_agents_once(
    *,
    workboard_path: Path | None = None,
    task_manager_agent: str = "task-manager-agent",
    max_dispatch_per_cycle: int = 1,
    online_lookback_minutes: float = 120.0,
    apply: bool = False,
    **_extra,
) -> tuple[bool, dict[str, object]]:
    """Assign up-for-grabs tasks to agents that requested an immediate dispatch.

    This is the lightweight redispatch path used by the worker after a
    successful task completion. The worker sends a coordination message
    `requested_action="assign next available task"` to the
    ``task_manager_agent``; this function reads those recent requests and
    moves matching up-for-grabs entries into the active-tasks section,
    inserting a new agent claim, then deletes the up-for-grabs row.

    Returns ``{"assigned_count": N, ...}``. The worker loop reads
    ``assigned_count`` to drive its ``dispatch_assigned_count`` counter
    (see ``tests/test_workboard_worker_script.py::test_worker_success_triggers_immediate_redispatch``).

    Side effects (when ``apply=True``):
    - Insert a new claim line in ``## Agent Claims (Active)``.
    - Insert a new task line in ``## Active Tasks``.
    - Replace the matched up-for-grabs row with the section's ``- none`` placeholder.
    """
    if workboard_path is None:
        return True, {"assigned_count": 0, "reason": "no workboard"}

    from scripts.crew.workboard import claim_ops as workboard_claim
    from scripts.crew.workboard import issue as workboard_issue
    from scripts.crew.workboard import message as workboard_message

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Find recent redispatch requests.
    ok_msgs, msgs_payload = workboard_message.list_messages(
        workboard_path,
        recipient=task_manager_agent,
        state="open",
    )
    if not ok_msgs:
        return False, {"error": "message section parse failed", **msgs_payload}

    requesting_agents: list[str] = []
    seen: set[str] = set()
    for row in list(msgs_payload.get("messages") or []):
        if "assign next available task" not in str(row.get("requested_action", "")).lower():
            continue
        agent = str(row.get("from", "")).strip()
        key = agent.lower()
        if not agent or key in seen:
            continue
        seen.add(key)
        requesting_agents.append(agent)
        if len(requesting_agents) >= int(max_dispatch_per_cycle or 1):
            break

    if not requesting_agents:
        return True, {"assigned_count": 0, "reason": "no redispatch requests"}

    # Find up-for-grabs candidates.
    grabs_start, grabs_end = workboard_issue._find_up_for_grabs_section(lines)
    candidates: list[tuple[int, dict[str, str]]] = []
    for idx in range(grabs_start, min(grabs_end, len(lines))):
        line = lines[idx]
        if not line.strip().startswith("-"):
            continue
        entry, fields, err = workboard_issue._parse_up_for_grabs_line(idx + 1, line)
        if err or entry is None or fields is None:
            continue
        if str(entry).lower() in {"none", "_none_"}:
            continue
        candidates.append((idx, fields))

    if not candidates:
        return True, {"assigned_count": 0, "reason": "no up-for-grabs tasks"}

    assigned_count = 0
    if apply:
        # Round-robin assign one candidate per requesting agent.
        for agent in requesting_agents:
            if not candidates:
                break
            grab_idx, fields = candidates.pop(0)
            task_id = str(fields.get("task_id") or "").strip()
            scope = str(fields.get("scope") or "").strip()
            summary = str(fields.get("summary") or "").strip()
            if not task_id:
                continue

            # Insert active claim. We use claim_ops.claim() but skip the
            # presence-gate / scope-guard checks by going through the
            # add-claim helper directly. Easier: call claim() and tolerate
            # any presence-gate failure (best effort).
            ok_claim, _payload_claim = workboard_claim.claim(
                workboard_path,
                agent=agent,
                scope=scope or task_id,
                task=f"[NEXT] {summary}",
                allow_presence_override=True,
                presence_override_reason="immediate-redispatch",
            )
            if not ok_claim:
                continue

            # Re-read workboard since claim_ops.claim wrote to it.
            text = workboard_path.read_text(encoding="utf-8")
            lines = text.splitlines()

            # Re-locate the same grab line (may have shifted by 1).
            grabs_start, grabs_end = workboard_issue._find_up_for_grabs_section(lines)
            grab_idx = None
            for idx in range(grabs_start, min(grabs_end, len(lines))):
                row_line = lines[idx]
                if not row_line.strip().startswith("-"):
                    continue
                entry, row_fields, err = workboard_issue._parse_up_for_grabs_line(idx + 1, row_line)
                if err or entry is None or row_fields is None:
                    continue
                if str(row_fields.get("task_id") or "").strip().lower() == task_id.lower():
                    grab_idx = idx
                    break

            # Move task to active-tasks: append after existing entries.
            tasks_start, tasks_end = workboard_issue._find_active_tasks_section(lines)
            active_line = workboard_issue._format_active_task(
                task_id=task_id,
                agent=agent,
                scope=scope or task_id,
                summary=summary,
                status="claimed",
            )
            # Strip any "- none" placeholders in the active tasks section.
            insert_at = tasks_end
            for idx in range(tasks_start, min(tasks_end, len(lines))):
                stripped = lines[idx].strip().rstrip("`").lstrip("`").strip()
                if stripped in {"- none", "- _none_"}:
                    del lines[idx]
                    insert_at -= 1
                    if grab_idx is not None and idx < grab_idx:
                        grab_idx -= 1
                    break
            lines.insert(insert_at, active_line)
            if grab_idx is not None and grab_idx >= insert_at:
                grab_idx += 1

            # Remove the up-for-grabs row, replacing with "- none" if it becomes empty.
            if grab_idx is not None:
                del lines[grab_idx]
                grabs_start, grabs_end = workboard_issue._find_up_for_grabs_section(lines)
                has_entries = False
                for idx in range(grabs_start, min(grabs_end, len(lines))):
                    if lines[idx].strip().startswith("-"):
                        has_entries = True
                        break
                if not has_entries:
                    lines.insert(grabs_end, "- none")

            workboard_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
            assigned_count += 1

    return True, {
        "assigned_count": assigned_count,
        "requesting_agent_count": len(requesting_agents),
        "candidate_count": len(candidates) + assigned_count,
    }


def _dispatch_up_for_grabs_to_idle_agents(**kwargs) -> tuple[bool, dict[str, object]]:
    _ = kwargs
    return True, {}


def _monitor_loop(*, cycles: int, **kwargs) -> tuple[bool, dict[str, object]]:
    _ = kwargs
    return True, {"cycle_count": cycles}
