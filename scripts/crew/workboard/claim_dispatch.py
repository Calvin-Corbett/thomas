#!/usr/bin/env python3
"""Dispatch logic for workboard claims."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.workboard.claim_ops import claim, release
    from scripts.crew.workboard.claim_utils import (
        DEFAULT_DISPATCH_MAX_SUGGESTIONS,
        DEFAULT_DISPATCH_TARGET_WORKERS,
        DEFAULT_MIN_DISPATCH_TARGET_WORKERS,
        DEFAULT_TASK_MANAGER_AGENT,
        TEMP_TASK_CREATOR_RELEASE_REASON,
        TEMP_TASK_CREATOR_SCOPE,
        _agent_key,
        _find_temp_task_creator_claims,
        _is_ready_task,
        _next_worker_index,
        _resolve_display_name,
        _sanitize_field,
        _task_manager_agent_keys,
        _temp_task_creator_agent,
        _temp_task_creator_manager,
        _temp_task_creator_name,
        _temp_task_creator_owner,
        _temp_task_creator_task,
        _worker_index_for_agent,
        claims_gate,
        virtual_office_identity,
        workboard_message_mod,
    )
except ImportError:  # pragma: no cover
    from crew.workboard.claim_ops import claim, release  # type: ignore
    from crew.workboard.claim_utils import (  # type: ignore
        DEFAULT_DISPATCH_MAX_SUGGESTIONS,
        DEFAULT_DISPATCH_TARGET_WORKERS,
        DEFAULT_MIN_DISPATCH_TARGET_WORKERS,
        DEFAULT_TASK_MANAGER_AGENT,
        TEMP_TASK_CREATOR_RELEASE_REASON,
        TEMP_TASK_CREATOR_SCOPE,
        _agent_key,
        _find_temp_task_creator_claims,
        _is_ready_task,
        _next_worker_index,
        _resolve_display_name,
        _sanitize_field,
        _task_manager_agent_keys,
        _temp_task_creator_agent,
        _temp_task_creator_manager,
        _temp_task_creator_name,
        _temp_task_creator_owner,
        _temp_task_creator_task,
        _worker_index_for_agent,
        claims_gate,
        virtual_office_identity,
        workboard_message_mod,
    )


def suggest_delegation(
    workboard_path: Path,
    *,
    parent_agent: str,
    max_suggestions: int = 3,
) -> tuple[bool, dict[str, object] | str]:
    violations, claims, _active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, "workboard invalid: " + "; ".join(violations)

    parent_key = _agent_key(parent_agent)
    parent_claims = [claim for claim in claims if _agent_key(claim.agent) == parent_key]
    if not parent_claims:
        return False, f"no active claim found for parent agent `{parent_agent}`"

    parent_name = str(parent_claims[0].name or parent_agent).strip()
    workers = [claim for claim in claims if _agent_key(claim.parent) == parent_key]

    max_items = max(1, int(max_suggestions))
    ready: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []

    for item in up_for_grabs:
        overlaps: list[str] = []
        for claim_row in claims:
            has_overlap = False
            for source_scope in item.scopes:
                for claimed_scope in claim_row.scopes:
                    if claims_gate._scope_overlaps(source_scope, claimed_scope):  # type: ignore[attr-defined]
                        has_overlap = True
                        break
                if has_overlap:
                    break
            if has_overlap:
                overlaps.append(claim_row.agent)

        payload: dict[str, object] = {
            "task_id": item.task_id,
            "scope": ",".join(item.scopes),
            "summary": item.summary,
            "reported_by": item.reported_by,
            "overlaps": sorted(set(overlaps), key=str.lower),
        }
        if overlaps:
            blocked.append(payload)
            continue
        ready.append(payload)

    ready = ready[:max_items]
    commands: list[str] = []
    for idx, item in enumerate(ready, start=1):
        child_agent = f"{parent_agent}-Worker-{idx}"
        child_name = virtual_office_identity.default_display_name(child_agent)
        task_label = f"[WIP][AUTO-{idx:02d}] {item['task_id']}: {item['summary']}"
        command = (
            "python scripts/crew/workboard/claim.py --claim "
            f"--agent \"{child_agent}\" --name \"{child_name}\" --role worker "
            f"--parent \"{parent_agent}\" --scope \"{item['scope']}\" --task \"{task_label}\""
        )
        commands.append(command)
        item["suggested_agent"] = child_agent
        item["suggested_name"] = child_name
        item["claim_command"] = command

    result: dict[str, object] = {
        "parent_agent": parent_agent,
        "parent_name": parent_name,
        "parent_claim_count": len(parent_claims),
        "active_worker_count": len(workers),
        "ready_suggestions": ready,
        "blocked_candidates": blocked,
        "generated_claim_commands": commands,
    }
    if not ready and blocked:
        overlap_counts: dict[str, int] = {}
        for item in blocked:
            for overlap_agent in [str(v) for v in (item.get("overlaps") or [])]:
                overlap_counts[overlap_agent] = int(overlap_counts.get(overlap_agent, 0)) + 1
        if overlap_counts:
            crowded = sorted(overlap_counts.items(), key=lambda pair: (-pair[1], pair[0]))
            hot = ", ".join([f"{agent}({count})" for agent, count in crowded[:5]])
            result["guidance"] = (
                "No non-overlapping delegation candidates. Narrow broad claim scopes first; "
                f"most frequent blockers: {hot}."
            )
    return True, result


def _send_temp_task_creator_notice(
    workboard_path: Path,
    sender: str,
    recipient: str,
    summary: str,
    requested_action: str,
) -> tuple[bool, str]:
    if workboard_message_mod is None:
        return False, "workboard_message module unavailable"
    try:
        ok, msg = workboard_message_mod.send_message(
            workboard_path=workboard_path,
            recipient_agent=recipient,
            sender_agent=sender,
            subject=f"temp-task-creator: {summary}",
            body=f"{summary}\n\nRequested action: {requested_action}",
        )
        return ok, msg
    except Exception as exc:
        return False, f"Failed to send message: {exc}"


def acquire_temp_task_creator(
    workboard_path: Path,
    *,
    owner_agent: str,
    owner_name: str,
    task_manager_agent: str = DEFAULT_TASK_MANAGER_AGENT,
    notify_task_manager: bool = True,
) -> tuple[bool, dict[str, object] | str]:
    owner_agent_clean = _sanitize_field("owner_agent", owner_agent)
    owner_name_clean = _resolve_display_name(owner_name, owner_agent_clean)
    manager_clean = _sanitize_field("task_manager_agent", task_manager_agent or DEFAULT_TASK_MANAGER_AGENT)
    lease_agent = _temp_task_creator_agent(owner_agent_clean)
    lease_name = _temp_task_creator_name(owner_name_clean)

    violations, claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, "workboard invalid: " + "; ".join(violations)

    existing = _find_temp_task_creator_claims(claims)
    if existing:
        row = existing[0]
        holder_agent = _temp_task_creator_owner(row.task, fallback=row.agent)
        holder_name = str(row.name or holder_agent).strip() or holder_agent
        holder_manager = _temp_task_creator_manager(row.task, fallback=manager_clean)
        if _agent_key(holder_agent) == _agent_key(owner_agent_clean):
            return True, {
                "status": "already_holder",
                "can_create_tasks": True,
                "holder_agent": holder_agent,
                "holder_name": holder_name,
                "manager_agent": holder_manager,
                "lease_agent": row.agent,
                "lease_scope": ",".join(list(row.scopes) or [TEMP_TASK_CREATOR_SCOPE]),
                "claim_message": "temp task creator lease already active for caller",
            }
        return True, {
            "status": "held_by_other",
            "can_create_tasks": False,
            "holder_agent": holder_agent,
            "holder_name": holder_name,
            "manager_agent": holder_manager,
            "lease_agent": row.agent,
            "lease_scope": ",".join(list(row.scopes) or [TEMP_TASK_CREATOR_SCOPE]),
            "claim_message": f"temp task creator lease already held by `{holder_agent}`",
        }

    ok_claim, msg_claim = claim(
        workboard_path,
        agent=lease_agent,
        scope=TEMP_TASK_CREATOR_SCOPE,
        task=_temp_task_creator_task(owner_agent_clean, manager_clean),
        name=lease_name,
        role="solo",
        parent="",
    )
    if not ok_claim:
        violations_retry, claims_retry, _active_retry, _grabs_retry, _issues_retry = claims_gate.evaluate_board(
            workboard_path
        )
        if not violations_retry:
            existing_retry = _find_temp_task_creator_claims(claims_retry)
            if existing_retry:
                row = existing_retry[0]
                holder_agent = _temp_task_creator_owner(row.task, fallback=row.agent)
                holder_name = str(row.name or holder_agent).strip() or holder_agent
                holder_manager = _temp_task_creator_manager(row.task, fallback=manager_clean)
                if _agent_key(holder_agent) == _agent_key(owner_agent_clean):
                    return True, {
                        "status": "already_holder",
                        "can_create_tasks": True,
                        "holder_agent": holder_agent,
                        "holder_name": holder_name,
                        "manager_agent": holder_manager,
                        "lease_agent": row.agent,
                        "lease_scope": ",".join(list(row.scopes) or [TEMP_TASK_CREATOR_SCOPE]),
                        "claim_message": str(msg_claim),
                    }
                return True, {
                    "status": "held_by_other",
                    "can_create_tasks": False,
                    "holder_agent": holder_agent,
                    "holder_name": holder_name,
                    "manager_agent": holder_manager,
                    "lease_agent": row.agent,
                    "lease_scope": ",".join(list(row.scopes) or [TEMP_TASK_CREATOR_SCOPE]),
                    "claim_message": str(msg_claim),
                }
        return False, f"temp task creator claim failed: {msg_claim}"

    payload: dict[str, object] = {
        "status": "acquired",
        "can_create_tasks": True,
        "holder_agent": owner_agent_clean,
        "holder_name": owner_name_clean,
        "manager_agent": manager_clean,
        "lease_agent": lease_agent,
        "lease_scope": TEMP_TASK_CREATOR_SCOPE,
        "claim_message": str(msg_claim),
    }

    if notify_task_manager:
        ok_notice, notice_value = _send_temp_task_creator_notice(
            workboard_path,
            sender=owner_agent_clean,
            recipient=manager_clean,
            summary=(f"no tasks available; {owner_agent_clean} claimed temporary task-creator lease"),
            requested_action=("confirm backup task creator assignment and send release when backlog is healthy"),
        )
        payload["notice_status"] = "sent" if ok_notice else "failed"
        if ok_notice and notice_value:
            payload["notice_msg_id"] = notice_value
        if not ok_notice:
            payload["notice_error"] = notice_value
    else:
        payload["notice_status"] = "skipped"
    return True, payload


def release_temp_task_creator(
    workboard_path: Path,
    *,
    actor_agent: str,
    task_manager_agent: str = DEFAULT_TASK_MANAGER_AGENT,
    notify_holder: bool = True,
) -> tuple[bool, dict[str, object] | str]:
    actor_clean = _sanitize_field("agent", actor_agent)
    manager_clean = _sanitize_field("task_manager_agent", task_manager_agent or DEFAULT_TASK_MANAGER_AGENT)
    allowed_actors = _task_manager_agent_keys(manager_clean)
    if _agent_key(actor_clean) not in allowed_actors:
        allowed_text = ", ".join(sorted(allowed_actors))
        return False, f"only {allowed_text} can release temporary task creator assignment"

    violations, claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, "workboard invalid: " + "; ".join(violations)

    temp_claims = _find_temp_task_creator_claims(claims)
    if not temp_claims:
        return True, {
            "task_manager_agent": manager_clean,
            "released_count": 0,
            "released": [],
            "release_errors": [],
            "notice_count": 0,
            "notice_errors": [],
        }

    released: list[dict[str, str]] = []
    release_errors: list[dict[str, str]] = []
    notice_ids: list[str] = []
    notice_errors: list[str] = []
    for row in temp_claims:
        holder_agent = _temp_task_creator_owner(row.task, fallback=row.agent)
        holder_name = str(row.name or holder_agent).strip() or holder_agent
        ok_release, msg_release = release(
            workboard_path,
            agent=row.agent,
            allow_dirty=True,
            dirty_reason=TEMP_TASK_CREATOR_RELEASE_REASON,
        )
        if not ok_release:
            release_errors.append(
                {
                    "lease_agent": row.agent,
                    "holder_agent": holder_agent,
                    "error": str(msg_release),
                }
            )
            continue
        released.append(
            {
                "lease_agent": row.agent,
                "holder_agent": holder_agent,
                "holder_name": holder_name,
            }
        )
        if notify_holder:
            ok_notice, notice_value = _send_temp_task_creator_notice(
                workboard_path,
                sender=manager_clean,
                recipient=holder_agent,
                summary=(f"temporary task creator lease released for {holder_agent}; backlog is covered"),
                requested_action="stop creating backup tasks and return to normal task dispatch",
            )
            if ok_notice and notice_value:
                notice_ids.append(notice_value)
            if not ok_notice:
                notice_errors.append(f"notice to `{holder_agent}` failed: {notice_value}")

    payload: dict[str, object] = {
        "task_manager_agent": manager_clean,
        "released_count": len(released),
        "released": released,
        "release_errors": release_errors,
        "notice_count": len(notice_ids),
        "notice_msg_ids": sorted(set(notice_ids), key=str.lower),
        "notice_errors": notice_errors,
    }
    if release_errors:
        return False, payload
    return True, payload


def dispatch_workers(
    workboard_path: Path,
    *,
    parent_agent: str,
    target_workers: int = DEFAULT_DISPATCH_TARGET_WORKERS,
    max_suggestions: int = DEFAULT_DISPATCH_MAX_SUGGESTIONS,
    release_ready: bool = False,
    enable_temp_creator: bool = True,
    task_manager_agent: str = DEFAULT_TASK_MANAGER_AGENT,
    notify_task_manager: bool = True,
) -> tuple[bool, dict[str, object] | str]:
    target = max(DEFAULT_MIN_DISPATCH_TARGET_WORKERS, int(target_workers or DEFAULT_DISPATCH_TARGET_WORKERS))
    max_items = max(1, int(max_suggestions or 1))
    parent_key = _agent_key(parent_agent)

    released_workers: list[str] = []
    release_errors: list[dict[str, str]] = []
    claimed_workers: list[dict[str, str]] = []
    claim_errors: list[dict[str, str]] = []
    parent_name = parent_agent
    temp_task_creator: dict[str, object] | None = None

    if release_ready:
        violations, claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
        if violations:
            return False, "workboard invalid: " + "; ".join(violations)

        parent_claims = [claim_row for claim_row in claims if _agent_key(claim_row.agent) == parent_key]
        if not parent_claims:
            return False, f"no active claim found for parent agent `{parent_agent}`"
        parent_name = str(parent_claims[0].name or parent_agent).strip() or parent_agent

        ready_workers = [
            claim_row
            for claim_row in claims
            if _agent_key(claim_row.parent) == parent_key and _is_ready_task(claim_row.task)
        ]
        for claim_row in sorted(ready_workers, key=lambda row: row.agent.lower()):
            ok_release, msg_release = release(workboard_path, agent=claim_row.agent)
            if ok_release:
                released_workers.append(claim_row.agent)
            else:
                release_errors.append({"agent": claim_row.agent, "error": str(msg_release)})

    rounds = 0
    max_rounds = max(1, target * 4)
    while rounds < max_rounds:
        rounds += 1
        violations, claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
        if violations:
            return False, "workboard invalid: " + "; ".join(violations)

        parent_claims = [claim_row for claim_row in claims if _agent_key(claim_row.agent) == parent_key]
        if not parent_claims:
            return False, f"no active claim found for parent agent `{parent_agent}`"
        parent_name = str(parent_claims[0].name or parent_agent).strip() or parent_agent

        workers = [claim_row for claim_row in claims if _agent_key(claim_row.parent) == parent_key]
        if len(workers) >= target:
            break

        ok_suggest, suggest_result = suggest_delegation(
            workboard_path,
            parent_agent=parent_agent,
            max_suggestions=max_items,
        )
        if not ok_suggest:
            return False, str(suggest_result)
        payload = dict(suggest_result) if isinstance(suggest_result, dict) else {}
        ready = list(payload.get("ready_suggestions") or [])
        if not ready:
            if enable_temp_creator and temp_task_creator is None:
                ok_temp, temp_result = acquire_temp_task_creator(
                    workboard_path,
                    owner_agent=parent_agent,
                    owner_name=parent_name,
                    task_manager_agent=task_manager_agent,
                    notify_task_manager=notify_task_manager,
                )
                if ok_temp and isinstance(temp_result, dict):
                    temp_task_creator = dict(temp_result)
                elif not ok_temp:
                    claim_errors.append(
                        {
                            "agent": parent_agent,
                            "task_id": "temp-task-creator",
                            "error": str(temp_result),
                        }
                    )
            break

        claimed_this_round = False
        attempted_this_round = False
        active_worker_keys = {_agent_key(worker.agent) for worker in workers}
        for item in ready:
            task_id = str(item.get("task_id") or "").strip()
            scope = str(item.get("scope") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not task_id or not scope or not summary:
                continue

            suggested_agent = str(item.get("suggested_agent") or "").strip()
            suggested_name = str(item.get("suggested_name") or "").strip()
            if suggested_agent and _agent_key(suggested_agent) in active_worker_keys:
                continue

            worker_index = _worker_index_for_agent(suggested_agent, parent_agent)
            if worker_index is None:
                worker_index = _next_worker_index(parent_agent, claims)
            child_agent = suggested_agent or f"{parent_agent}-Worker-{worker_index}"
            child_name = suggested_name or virtual_office_identity.default_display_name(child_agent)
            task_label = f"[WIP][AUTO-{worker_index:02d}] {task_id}: {summary}"

            attempted_this_round = True
            ok_claim, msg_claim = claim(
                workboard_path,
                agent=child_agent,
                scope=scope,
                task=task_label,
                name=child_name,
                role="worker",
                parent=parent_agent,
            )
            if ok_claim:
                claimed_workers.append(
                    {
                        "agent": child_agent,
                        "name": child_name,
                        "task_id": task_id,
                        "scope": scope,
                    }
                )
                claimed_this_round = True
                break
            claim_errors.append({"agent": child_agent, "task_id": task_id, "error": str(msg_claim)})

        if claimed_this_round:
            continue
        if attempted_this_round:
            continue
        break

    violations, claims, _active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, "workboard invalid: " + "; ".join(violations)
    workers = [claim_row for claim_row in claims if _agent_key(claim_row.parent) == parent_key]

    ready_suggestion_count = 0
    guidance = ""
    generated_claim_commands: list[str] = []
    ok_final, final_result = suggest_delegation(
        workboard_path,
        parent_agent=parent_agent,
        max_suggestions=max_items,
    )
    if ok_final and isinstance(final_result, dict):
        ready_suggestion_count = len(list(final_result.get("ready_suggestions") or []))
        guidance = str(final_result.get("guidance") or "").strip()
        generated_claim_commands = [str(cmd) for cmd in list(final_result.get("generated_claim_commands") or [])]

    result: dict[str, object] = {
        "parent_agent": parent_agent,
        "parent_name": parent_name,
        "target_workers": target,
        "max_suggestions": max_items,
        "release_ready": bool(release_ready),
        "temp_creator_enabled": bool(enable_temp_creator),
        "rounds": rounds,
        "active_worker_count": len(workers),
        "released_workers": released_workers,
        "release_errors": release_errors,
        "claimed_workers": claimed_workers,
        "claim_errors": claim_errors,
        "ready_suggestion_count": ready_suggestion_count,
        "generated_claim_commands": generated_claim_commands,
    }
    if enable_temp_creator:
        if temp_task_creator is not None:
            result["temp_task_creator"] = temp_task_creator
        else:
            result["temp_task_creator"] = {
                "status": "not_needed",
                "can_create_tasks": False,
                "holder_agent": "",
                "manager_agent": task_manager_agent,
            }
    else:
        result["temp_task_creator"] = {
            "status": "disabled",
            "can_create_tasks": False,
            "holder_agent": "",
            "manager_agent": task_manager_agent,
        }
    if guidance:
        result["guidance"] = guidance
    return True, result
