"""Task reactivation and auto-start orchestration module.

Manages picking tasks for agents, reactivating parked work, and auto-starting execution.
"""

from __future__ import annotations

from pathlib import Path

try:
    pass
except Exception:  # pragma: no cover
    pass  # type: ignore

try:
    from scripts.forge.gates import workboard_claims as claims_gate
    from scripts import (
        workboard_claim,
        workboard_issue,
        workboard_task_manager_sweep,
    )
    from thomas.core import task_bot_runtime
except Exception:  # pragma: no cover
    from forge.gates import workboard_claims as claims_gate  # type: ignore
    import workboard_claim  # type: ignore
    import workboard_issue  # type: ignore
    import workboard_task_manager_sweep  # type: ignore

    from thomas.core import task_bot_runtime  # type: ignore

try:
    from scripts.workboard_task_manager_base import (
        DEFAULT_ORCHESTRATOR_ERROR,
        DEFAULT_TASK_MANAGER_AGENT,
        ROOT,
        TASK_STATUS_TRANSITIONS,
        _is_orchestrator_agent,
        _norm,
        _normalize_task_status,
        _replace_status_field,
        _strip_blocked_task_violations,
        _task_priority_rank,
        _task_priority_source,
        _task_type_by_task_id,
    )
except Exception:  # pragma: no cover
    from workboard_task_manager_base import (
        DEFAULT_ORCHESTRATOR_ERROR,
        DEFAULT_TASK_MANAGER_AGENT,
        ROOT,
        TASK_STATUS_TRANSITIONS,
        _is_orchestrator_agent,
        _norm,
        _normalize_task_status,
        _replace_status_field,
        _strip_blocked_task_violations,
        _task_priority_rank,
        _task_priority_source,
        _task_type_by_task_id,
    )


_get_up_for_grabs_task = workboard_task_manager_sweep._get_up_for_grabs_task
_remove_up_for_grabs_task = workboard_task_manager_sweep._remove_up_for_grabs_task
_remove_inactive_agent = workboard_task_manager_sweep._remove_inactive_agent


def set_task_status(
    workboard_path: Path,
    *,
    task_id: str,
    status: str,
    actor: str,
    enforce_transition: bool = True,
    require_claims_to_have_active_task: bool = True,
) -> tuple[bool, dict[str, object]]:
    """Set task status with transition validation."""
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
    section = workboard_issue._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    target_idx: int | None = None
    current_status = ""
    for idx in workboard_issue._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
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
    require_claims_to_have_active_task: bool = True,
) -> tuple[bool, dict[str, object]]:
    found, row, message = _get_up_for_grabs_task(workboard_path, task_id)
    if not found or row is None:
        return False, {"error": message}

    scope = str(scope_override or row.get("scope") or "").strip()
    summary = str(task_summary or row.get("summary") or "").strip()
    if not scope:
        return False, {"error": f"task `{task_id}` has empty scope and no --scope override was provided"}
    if not summary:
        return False, {"error": f"task `{task_id}` has empty summary and no --summary override was provided"}

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    claim_section = workboard_issue._find_claim_section(lines)  # type: ignore[attr-defined]
    claim_line = f"- agent={agent}; scope={scope}; task={summary}"
    claim_found = False
    for idx in sorted(workboard_issue._bullet_indices(lines, claim_section[0], claim_section[1]), reverse=True):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue._parse_claim_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, {"error": err}
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            del lines[idx]
            continue
        if not fields:
            continue
        if _norm(fields.get("agent", "")) == _norm(agent):
            lines[idx] = claim_line
            claim_found = True
        elif _norm(fields.get("task", "")) == _norm(summary):
            del lines[idx]
    if not claim_found:
        claim_section = workboard_issue._find_claim_section(lines)  # type: ignore[attr-defined]
        lines.insert(claim_section[1], claim_line)

    active_section = workboard_issue._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    replacement = workboard_issue._format_active_task(  # type: ignore[attr-defined]
        task_id=task_id,
        agent=agent,
        scope=scope,
        summary=summary,
        status="claimed",
    )
    target_idx: int | None = None
    for idx in sorted(workboard_issue._bullet_indices(lines, active_section[0], active_section[1]), reverse=True):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, {"error": err}
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            del lines[idx]
            continue
        if not fields:
            continue
        if _norm(fields.get("task_id", "")) == _norm(task_id):
            if target_idx is None:
                target_idx = idx
            else:
                del lines[idx]
    active_section = workboard_issue._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    if target_idx is None:
        lines.insert(active_section[1], replacement)
    else:
        lines[target_idx] = replacement

    ok_remove_grab, msg_remove_grab = _remove_up_for_grabs_task(lines, task_id=task_id)
    if not ok_remove_grab:
        return False, {"error": msg_remove_grab}

    ok_inactive, inactive_msg = _remove_inactive_agent(lines, agent=agent)
    if not ok_inactive:
        return False, {"error": inactive_msg}

    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    ok_write, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path,
        text,
        new_text,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    if not ok_write:
        return False, {"error": "reactivation update rejected by gate", "violations": list(violations)}

    return True, {
        "task_id": task_id,
        "agent": agent,
        "scope": scope,
        "summary": summary,
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
    require_claims_to_have_active_task: bool,
) -> tuple[bool, claims_gate.UpForGrabTask | None, str]:
    violations, _claims, _active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(
        workboard_path,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    violations = _strip_blocked_task_violations(
        violations,
        allow_blocked_without_issue=not bool(require_claims_to_have_active_task),
    )
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


def _load_active_tasks_for_agent(
    workboard_path: Path,
    *,
    agent: str,
) -> tuple[bool, list[dict[str, str]], list[str]]:
    agent_key = _norm(agent)
    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        section = workboard_issue._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    except Exception as exc:
        return False, [], [str(exc)]

    items: list[dict[str, str]] = []
    errors: list[str] = []
    for idx in workboard_issue._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        if _norm(fields.get("agent", "")) == agent_key:
            items.append(fields)
    if errors:
        return False, [], errors
    return True, items, []


def _auto_start_task_for_agent(
    *,
    workboard_path: Path,
    agent: str,
    task_manager_agent: str,
    require_claims_to_have_active_task: bool,
) -> tuple[bool, dict[str, object]]:
    if not str(agent).strip():
        return False, {"error": "agent id is required for auto-start"}
    if _is_orchestrator_agent(agent):
        return False, {"error": DEFAULT_ORCHESTRATOR_ERROR}

    ok_tasks, agent_active, parse_errors = _load_active_tasks_for_agent(
        workboard_path,
        agent=agent,
    )
    if not ok_tasks:
        return False, {"error": "active task section parse failed", "violations": parse_errors}

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

        def _active_sort_key(item: dict[str, str]) -> tuple[int, int, int, str]:
            summary = str(item.get("summary", ""))
            status = str(item.get("status", ""))
            priority, urgency, text = _task_priority_rank(summary)
            return (_active_status_rank(status), priority, urgency, text)

        working_tasks = [
            item
            for item in agent_active
            if _normalize_task_status(item.get("status", "")) in {"in_progress", "claimed", "queued"}
        ]
        if working_tasks:
            target_task = sorted(working_tasks, key=_active_sort_key)[0]
            current_status = _normalize_task_status(str(target_task.get("status", "")))
            if current_status == "in_progress":
                return True, {
                    "agent": agent,
                    "task_id": str(target_task.get("task_id", "")),
                    "status": "in_progress",
                    "started": True,
                    "source": "existing",
                }

            if current_status == "queued":
                ok_claimed, payload_claimed = set_task_status(
                    workboard_path,
                    task_id=str(target_task.get("task_id", "")),
                    status="claimed",
                    actor=agent,
                    enforce_transition=True,
                    require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
                )
                if not ok_claimed:
                    return False, {
                        "error": f"failed to move `{target_task.get('task_id', '')}` from queued to claimed",
                        "details": payload_claimed,
                    }

            ok_in_progress, payload_in_progress = set_task_status(
                workboard_path,
                task_id=str(target_task.get("task_id", "")),
                status="in_progress",
                actor=agent,
                enforce_transition=True,
                require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
            )
            if not ok_in_progress:
                return False, {
                    "error": f"unable to move `{target_task.get('task_id', '')}` to in_progress",
                    "details": payload_in_progress,
                }

            return True, {
                "agent": agent,
                "task_id": str(target_task.get("task_id", "")),
                "status": "in_progress",
                "started": True,
                "source": "existing",
                "previous_status": current_status,
            }

        non_startable = sorted(
            [
                {
                    "task_id": str(item.get("task_id", "")),
                    "status": _normalize_task_status(str(item.get("status", ""))),
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

    ok_pick, pick, pick_error = _pick_auto_start_up_for_grabs_task(
        workboard_path=workboard_path,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
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
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
    require_claims_to_have_active_task: bool,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, claims, active_tasks, up_for_grabs, _ = claims_gate.evaluate_board(
        workboard_path,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    violations = _strip_blocked_task_violations(
        violations,
        allow_blocked_without_issue=not bool(require_claims_to_have_active_task),
    )
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
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
        if error_text.startswith("agent `") and "non-startable active task state(s)" in error_text:
            skipped_non_startable_agents.append(agent)
            continue

        if str(payload_start.get("error", "")).strip().lower().startswith("no up-for-grabs tasks available"):
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
