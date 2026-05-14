"""Inactive agent sweep and task recovery module.

Detects stale claims, moves work to recoverable state, and manages inactive agents.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.forge.gates import workboard_claims as claims_gate
    from scripts import workboard_issue
    from scripts.crew.workboard import claim as workboard_claim
    from scripts.crew.workboard import message as workboard_message
except Exception:  # pragma: no cover
    from forge.gates import workboard_claims as claims_gate  # type: ignore
    from crew.workboard import claim as workboard_claim  # type: ignore
    import workboard_issue  # type: ignore
    from crew.workboard import message as workboard_message  # type: ignore

try:
    from scripts.workboard_task_manager_base import (
        AGENT_SESSIONS_HEADING,
        INACTIVE_AGENTS_HEADING,
        _bullet_indices,
        _ensure_section,
        _find_section,
        _latest_message_timestamp_by_sender,
        _line_commit_unix,
        _norm,
        _parse_iso_utc,
        _parse_kv_entry,
        _sanitize,
        _strip_blocked_task_violations,
        _to_iso_utc,
        _write_section_entries,
    )
except Exception:  # pragma: no cover
    from workboard_task_manager_base import (
        AGENT_SESSIONS_HEADING,
        INACTIVE_AGENTS_HEADING,
        _bullet_indices,
        _ensure_section,
        _find_section,
        _latest_message_timestamp_by_sender,
        _line_commit_unix,
        _norm,
        _parse_iso_utc,
        _parse_kv_entry,
        _sanitize,
        _strip_blocked_task_violations,
        _to_iso_utc,
        _write_section_entries,
    )


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
    require_claims_to_have_active_task: bool,
) -> tuple[list[str], list[dict[str, object]], dict[str, list[claims_gate.ActiveTask]]]:
    violations, claims, active_tasks, _grab, _issues = claims_gate.evaluate_board(
        workboard_path,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    violations = _strip_blocked_task_violations(
        violations,
        allow_blocked_without_issue=not bool(require_claims_to_have_active_task),
    )
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
    require_claims_to_have_active_task: bool,
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
            workboard_path,
            text,
            new_text,
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
    require_claims_to_have_active_task: bool,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, stale_claims, tasks_by_agent = _stale_claims(
        workboard_path=workboard_path,
        now=now,
        max_idle_minutes=max_idle_minutes,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
                require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
            elif "no active claim" not in _norm(msg_release):
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
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
