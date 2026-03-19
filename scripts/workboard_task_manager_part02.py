def _dispatch_up_for_grabs_to_idle_agents(
    *,
    workboard_path: Path,
    now: datetime,
    task_manager_agent: str,
    max_dispatch_per_cycle: int,
    online_lookback_minutes: float,
    require_claims_to_have_active_task: bool,
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

    violations, claims, _active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(
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
                    require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
                require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
        require_claims_to_have_active_task=True,
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
        require_claims_to_have_active_task=True,
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
    require_claims_to_have_active_task: bool,
    now: datetime,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    checks: dict[str, dict[str, object]] = {}
    errors: list[str] = []

    ok_sessions, payload_sessions = _sync_agent_sessions(
        workboard_path=workboard_path,
        now=now,
        session_lease_minutes=session_lease_minutes,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        apply=apply,
    )
    checks["sync_sessions"] = payload_sessions
    if not ok_sessions:
        errors.append(str(payload_sessions.get("error", "sync_sessions failed")))

    ok_inferred, payload_inferred = _sync_inferred_presence_claims(
        workboard_path=workboard_path,
        now=now,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        apply=apply,
    )
    checks["sync_inferred"] = payload_inferred
    if not ok_inferred:
        errors.append(str(payload_inferred.get("error", "sync_inferred failed")))

    ok_specialists, payload_specialists = _sync_task_specialists(
        workboard_path=workboard_path,
        now=now,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        apply=apply,
    )
    checks["silence_ping"] = payload_ping
    if not ok_ping:
        errors.extend(
            [str(item) for item in list(payload_ping.get("errors") or [])] or [str(payload_ping.get("error", ""))]
        )

    if run_auto_start:
        ok_auto_start, payload_auto_start = _auto_start_all_claimed_agents(
            workboard_path=workboard_path,
            task_manager_agent=task_manager_agent,
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
            apply=apply,
        )
        checks["auto_start"] = payload_auto_start
        if not ok_auto_start:
            errors.extend(
                [str(item) for item in list(payload_auto_start.get("errors") or [])]
                or [str(payload_auto_start.get("error", ""))]
            )

    ok_sweep, payload_sweep = _sweep_inactive(
        workboard_path=workboard_path,
        max_idle_minutes=max_idle_minutes,
        task_manager_agent=task_manager_agent,
        now=now,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        apply=apply,
    )
    checks["sweep_inactive"] = payload_sweep
    if not ok_sweep:
        errors.extend(
            [str(item) for item in list(payload_sweep.get("errors") or [])] or [str(payload_sweep.get("error", ""))]
        )

    if run_idle_dispatch:
        ok_dispatch, payload_dispatch = _dispatch_up_for_grabs_to_idle_agents(
            workboard_path=workboard_path,
            now=now,
            task_manager_agent=task_manager_agent,
            max_dispatch_per_cycle=max_dispatch_per_cycle,
            online_lookback_minutes=online_lookback_minutes,
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        apply=apply,
        now=now,
    )
    checks["sync_plans"] = payload_plans
    if not ok_plans:
        errors.append(str(payload_plans.get("error", "sync_plans failed")))

    ok_blocker_issues, payload_blocker_issues = _repair_missing_blocker_issue_rows(
        workboard_path=workboard_path,
        task_manager_agent=task_manager_agent,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        apply=apply,
    )
    checks["blocker_issue_repair"] = payload_blocker_issues
    if not ok_blocker_issues:
        errors.extend(
            [str(item) for item in list(payload_blocker_issues.get("errors") or [])]
            or [str(payload_blocker_issues.get("error", "blocked issue repair failed"))]
        )

    payload: dict[str, object] = {
        "cycle_started_at": now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "checks": checks,
        "applied": bool(apply),
    }
    if errors:
        payload["errors"] = [item for item in errors if item]
        return False, payload
    return True, payload


def _repair_missing_blocker_issue_rows(
    *,
    workboard_path: Path,
    task_manager_agent: str,
    require_claims_to_have_active_task: bool,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    if not apply:
        return True, {
            "repaired_blocker_issue_count": 0,
            "applied": False,
        }

    violations, _claims, active_tasks, _up_for_grabs, issues = claims_gate.evaluate_board(
        workboard_path,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    violations = _strip_blocked_task_violations(
        violations,
        allow_blocked_without_issue=not bool(require_claims_to_have_active_task),
    )
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    open_issue_task_ids: set[str] = {
        str(item.task_id).strip().lower() for item in issues if item.state in {"open", "triaged"}
    }
    blocked_tasks = [
        task
        for task in active_tasks
        if str(task.status).strip().lower() == "blocked"
        and str(task.task_id).strip().lower() not in open_issue_task_ids
    ]
    if not blocked_tasks:
        return True, {
            "repaired_blocker_issue_count": 0,
            "applied": True,
        }

    owner = task_manager_agent or "task-manager-agent"
    reporter = task_manager_agent or "task-manager-agent"
    repaired: list[str] = []
    errors: list[str] = []
    for task in blocked_tasks:
        issue_summary = f"blocked task {task.task_id} requires issue tracking"
        ok_block, msg_block, issue_id = workboard_issue.block_task(
            workboard_path,
            task_id=task.task_id,
            reporter=reporter,
            owner=owner,
            summary=issue_summary,
            issue_id=None,
        )
        if not ok_block:
            errors.append(f"{task.task_id}: {msg_block}")
            continue
        repaired.append(str(issue_id) if str(issue_id) else str(task.task_id))

    if errors:
        return False, {
            "error": "failed to create blocker issue row for one or more blocked tasks",
            "errors": list(errors),
            "repaired_blocker_issue_count": len(repaired),
            "repaired_blocker_issue_ids": repaired,
            "applied": True,
        }

    return True, {
        "repaired_blocker_issue_count": len(repaired),
        "repaired_blocker_issue_ids": sorted(set(repaired), key=str.lower),
        "applied": True,
    }


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
    require_claims_to_have_active_task: bool,
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
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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


def _repo_root_from_workboard(workboard_path: Path) -> Path:
    resolved = workboard_path.resolve()
    parent = resolved.parent
    if parent.name.lower() == "thomas" and parent.parent.name.lower() == "plans":
        return resolved.parents[2]
    return parent


def _read_inferred_sync_state(repo_root: Path) -> dict[str, object]:
    path = agent_presence.inferred_state_path(repo_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("entries", [])
    payload.setdefault("inferred_applied", [])
    payload.setdefault("inferred_suppressed", [])
    payload.setdefault("inferred_expired", [])
    return payload


def _write_inferred_sync_state(repo_root: Path, payload: dict[str, object]) -> None:
    path = agent_presence.inferred_state_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _scope_tokens_from_csv(raw: str | None) -> list[str]:
    return [token.strip() for token in str(raw or "").split(",") if token.strip()]


def _row_is_inferred(fields: dict[str, str]) -> bool:
    return _norm(str(fields.get("inferred", ""))) == "true"


def _scope_matches(scope: str, row_scope: str) -> bool:
    left = str(scope or "").strip()
    right = str(row_scope or "").strip()
    return bool(left and right and claims_gate._scope_overlaps(left, right))  # type: ignore[attr-defined]


def _row_scope_overlap(scope: str, row_scopes: Sequence[str]) -> bool:
    return any(_scope_matches(scope, item) for item in list(row_scopes or []))


def _inferred_claim_key(agent: str, scope: str) -> str:
    return f"{_norm(agent)}::{_norm(scope)}"


def _inferred_task_id(agent: str, scope: str) -> str:
    agent_slug = re.sub(r"[^a-z0-9]+", "-", _norm(agent)).strip("-") or "agent"
    digest = hashlib.sha1(str(scope or "").strip().lower().encode("utf-8")).hexdigest()[:8]
    return f"INFERRED-{agent_slug}-{digest}"


def _sanitize_metadata(value: str, *, fallback: str = "none") -> str:
    cleaned = str(value or "").strip().replace(";", ",").replace("\n", " ").replace("\r", " ")
    return cleaned or fallback


def _compact_paths(paths: Sequence[str], *, limit: int = 4) -> str:
    values: list[str] = []
    for item in list(paths or []):
        token = str(item or "").strip().replace(";", ",")
        if token and token not in values:
            values.append(token)
    return ",".join(values[:limit]) or "none"


def _format_inferred_claim_entry(*, candidate: dict[str, object], timestamp: str) -> str:
    agent_id = _sanitize_metadata(str(candidate.get("agent_id") or "agent"), fallback="agent")
    display_name = _sanitize_metadata(str(candidate.get("display_name") or agent_id), fallback=agent_id)
    scope = _sanitize_metadata(str(candidate.get("scope") or ""), fallback=".")
    task = _sanitize_metadata(
        str(candidate.get("recommended_task_summary") or f"Inferred work in {scope}"),
        fallback=f"Inferred work in {scope}",
    )
    confidence = _sanitize_metadata(str(candidate.get("confidence") or "medium"), fallback="medium")
    evidence_paths = _compact_paths([str(item) for item in list(candidate.get("recent_paths") or [])])
    return (
        f"- agent={agent_id}; name={display_name}; role=solo; parent=none; scope={scope}; task={task}; "
        f"inferred=true; confidence={confidence}; source=presence-monitor; "
        f"last_inferred_at={timestamp}; evidence_scope={scope}; evidence_paths={evidence_paths}"
    )


def _format_inferred_task_entry(*, candidate: dict[str, object], timestamp: str) -> str:
    agent_id = _sanitize_metadata(str(candidate.get("agent_id") or "agent"), fallback="agent")
    display_name = _sanitize_metadata(str(candidate.get("display_name") or agent_id), fallback=agent_id)
    scope = _sanitize_metadata(str(candidate.get("scope") or ""), fallback=".")
    summary = _sanitize_metadata(
        str(candidate.get("recommended_task_summary") or f"Inferred work in {scope}"),
        fallback=f"Inferred work in {scope}",
    )
    confidence = _sanitize_metadata(str(candidate.get("confidence") or "medium"), fallback="medium")
    return (
        f"- task_id={_inferred_task_id(agent_id, scope)}; agent={agent_id}; scope={scope}; summary={summary}; "
        f"status=in_progress; name={display_name}; role=solo; parent=none; "
        f"inferred=true; confidence={confidence}; source=presence-monitor; last_inferred_at={timestamp}"
    )


def _entry_state_payload(
    *,
    prior: dict[str, object] | None,
    candidate: dict[str, object] | None,
    agent_id: str,
    display_name: str,
    scope: str,
    timestamp: str,
    sync_state: str,
    linked_claim_row: str = "",
    linked_active_task_id: str = "",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "entry_key": _inferred_claim_key(agent_id, scope),
        "agent_id": agent_id,
        "display_name": display_name,
        "scope": scope,
        "confidence": str((candidate or {}).get("confidence") or (prior or {}).get("confidence") or "medium"),
        "supporting_evidence_paths": list(
            (candidate or {}).get("recent_paths") or (prior or {}).get("supporting_evidence_paths") or []
        ),
        "supporting_process_evidence": list(
            (candidate or {}).get("supporting_process_evidence")
            or (prior or {}).get("supporting_process_evidence")
            or []
        ),
        "process_pids": list((candidate or {}).get("process_pids") or (prior or {}).get("process_pids") or []),
        "first_seen": str((prior or {}).get("first_seen") or timestamp),
        "last_seen": timestamp,
        "linked_claim_row": linked_claim_row or str((prior or {}).get("linked_claim_row") or ""),
        "linked_active_task_id": linked_active_task_id or str((prior or {}).get("linked_active_task_id") or ""),
        "sync_state": sync_state,
    }
    return payload


def _sync_inferred_presence_claims(
    *,
    workboard_path: Path,
    now: datetime,
    require_claims_to_have_active_task: bool,
    apply: bool,
    expiry_minutes: float = DEFAULT_INFERRED_EXPIRY_MINUTES,
) -> tuple[bool, dict[str, object]]:
    repo_root = _repo_root_from_workboard(workboard_path)
    snapshot = agent_presence.collect_presence(repo_root=repo_root, workboard_path=workboard_path)
    candidates = [dict(row) for row in list(snapshot.get("inferred_candidates") or []) if isinstance(row, dict)]
    suppressed = [dict(row) for row in list(snapshot.get("inferred_suppressed") or []) if isinstance(row, dict)]
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    timestamp = _to_iso_utc(now)
    expiry_delta = timedelta(minutes=max(0.1, float(expiry_minutes)))

    claim_section = workboard_claim._find_claim_section(lines)  # type: ignore[attr-defined]
    active_section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]

    claim_rows: list[dict[str, object]] = []
    task_rows: list[dict[str, object]] = []
    parse_errors: list[str] = []

    for idx in workboard_claim._bullet_indices(lines, claim_section[0], claim_section[1]):  # type: ignore[attr-defined]
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            parse_errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        claim_rows.append({"idx": idx, "line": lines[idx], "fields": dict(fields)})

    for idx in workboard_claim._bullet_indices(lines, active_section[0], active_section[1]):  # type: ignore[attr-defined]
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            parse_errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        task_rows.append({"idx": idx, "line": lines[idx], "fields": dict(fields)})

    if parse_errors:
        return False, {"error": "unable to parse claim/task sections for inferred sync", "violations": parse_errors}

    explicit_claims = [row for row in claim_rows if not _row_is_inferred(dict(row["fields"]))]
    explicit_tasks = [row for row in task_rows if not _row_is_inferred(dict(row["fields"]))]
    inferred_claim_rows = {
        _inferred_claim_key(str(dict(row["fields"]).get("agent", "")), str(dict(row["fields"]).get("scope", ""))): row
        for row in claim_rows
        if _row_is_inferred(dict(row["fields"]))
    }
    inferred_task_rows = {
        str(dict(row["fields"]).get("task_id", "")).strip(): row
        for row in task_rows
        if _row_is_inferred(dict(row["fields"]))
    }

    prior_state = _read_inferred_sync_state(repo_root)
    prior_entries = {
        str(dict(entry).get("entry_key") or ""): dict(entry)
        for entry in list(prior_state.get("entries") or [])
        if isinstance(entry, dict) and str(dict(entry).get("entry_key") or "").strip()
    }

    next_entries: list[dict[str, object]] = []
    kept_inferred_claims: dict[str, str] = {}
    kept_inferred_tasks: dict[str, str] = {}
    applied: list[dict[str, object]] = []
    expired: list[dict[str, object]] = []
    seen_keys: set[str] = set()

    for candidate in candidates:
        agent_id = str(candidate.get("agent_id") or "").strip()
        display_name = str(candidate.get("display_name") or agent_id).strip() or agent_id
        scope = str(candidate.get("scope") or "").strip()
        if not agent_id or not scope:
            continue
        key = _inferred_claim_key(agent_id, scope)
        seen_keys.add(key)
        prior = prior_entries.get(key)
        same_explicit_claim = next(
            (
                row
                for row in explicit_claims
                if _norm(str(dict(row["fields"]).get("agent", ""))) == _norm(agent_id)
                and _row_scope_overlap(scope, _scope_tokens_from_csv(str(dict(row["fields"]).get("scope", ""))))
            ),
            None,
        )
        conflicting_claim = next(
            (
                row
                for row in explicit_claims
                if _norm(str(dict(row["fields"]).get("agent", ""))) != _norm(agent_id)
                and _row_scope_overlap(scope, _scope_tokens_from_csv(str(dict(row["fields"]).get("scope", ""))))
            ),
            None,
        )
        explicit_task = next(
            (
                row
                for row in explicit_tasks
                if _norm(str(dict(row["fields"]).get("agent", ""))) == _norm(agent_id)
                and _row_scope_overlap(scope, _scope_tokens_from_csv(str(dict(row["fields"]).get("scope", ""))))
            ),
            None,
        )
        inferred_task_id = _inferred_task_id(agent_id, scope)

        if conflicting_claim is not None or bool(candidate.get("conflicts_with_explicit_claim")):
            conflict_agent = (
                str(dict(conflicting_claim["fields"]).get("agent", "")).strip()
                if conflicting_claim is not None
                else str(candidate.get("conflict_agent_id") or "").strip()
            )
            row = dict(candidate)
            row["state"] = "suppressed_conflict"
            row["reason"] = f"explicit claim overlap with {conflict_agent or 'another agent'}"
            suppressed.append(row)
            next_entries.append(
                _entry_state_payload(
                    prior=prior,
                    candidate=candidate,
                    agent_id=agent_id,
                    display_name=display_name,
                    scope=scope,
                    timestamp=timestamp,
                    sync_state="suppressed_conflict",
                    linked_active_task_id=inferred_task_id,
                )
            )
            continue

        if same_explicit_claim is not None:
            next_entries.append(
                _entry_state_payload(
                    prior=prior,
                    candidate=candidate,
                    agent_id=agent_id,
                    display_name=display_name,
                    scope=scope,
                    timestamp=timestamp,
                    sync_state="refreshed_explicit",
                    linked_active_task_id=inferred_task_id,
                )
            )
            applied.append(
                {
                    "agent_id": agent_id,
                    "scope": scope,
                    "action": "explicit_claim_exists",
                    "confidence": str(candidate.get("confidence") or "medium"),
                }
            )
            continue

        claim_line = _format_inferred_claim_entry(candidate=candidate, timestamp=timestamp)
        kept_inferred_claims[key] = claim_line
        linked_task_id = ""
        if explicit_task is None:
            kept_inferred_tasks[inferred_task_id] = _format_inferred_task_entry(
                candidate=candidate, timestamp=timestamp
            )
            linked_task_id = inferred_task_id
        next_entries.append(
            _entry_state_payload(
                prior=prior,
                candidate=candidate,
                agent_id=agent_id,
                display_name=display_name,
                scope=scope,
                timestamp=timestamp,
                sync_state="refreshed" if key in inferred_claim_rows else "created",
                linked_claim_row=claim_line,
                linked_active_task_id=linked_task_id,
            )
        )
        applied.append(
            {
                "agent_id": agent_id,
                "scope": scope,
                "task_id": linked_task_id,
                "action": "refreshed" if key in inferred_claim_rows else "created",
                "confidence": str(candidate.get("confidence") or "medium"),
                "recent_paths": list(candidate.get("recent_paths") or []),
            }
        )

    for key, row in inferred_claim_rows.items():
        if key in seen_keys:
            continue
        fields = dict(row["fields"])
        agent_id = str(fields.get("agent", "")).strip()
        scope = str(fields.get("scope", "")).strip()
        display_name = str(fields.get("name", "") or agent_id).strip() or agent_id
        prior = prior_entries.get(key)
        last_seen = _parse_iso_utc(str((prior or {}).get("last_seen") or fields.get("last_inferred_at") or ""))
        if last_seen is None:
            last_seen = now - expiry_delta - timedelta(seconds=1)
        inferred_task_id = str((prior or {}).get("linked_active_task_id") or _inferred_task_id(agent_id, scope))
        if now.astimezone(timezone.utc) - last_seen > expiry_delta:
            expired.append({"agent_id": agent_id, "scope": scope, "task_id": inferred_task_id, "state": "expired"})
            next_entries.append(
                _entry_state_payload(
                    prior=prior,
                    candidate=None,
                    agent_id=agent_id,
                    display_name=display_name,
                    scope=scope,
                    timestamp=timestamp,
                    sync_state="expired",
                    linked_active_task_id=inferred_task_id,
                )
            )
            continue
        kept_inferred_claims[key] = str(row["line"])
        if inferred_task_id in inferred_task_rows:
            kept_inferred_tasks[inferred_task_id] = str(inferred_task_rows[inferred_task_id]["line"])
        next_entries.append(
            _entry_state_payload(
                prior=prior,
                candidate=None,
                agent_id=agent_id,
                display_name=display_name,
                scope=scope,
                timestamp=_to_iso_utc(last_seen),
                sync_state="stale",
                linked_claim_row=str(row["line"]),
                linked_active_task_id=inferred_task_id,
            )
        )

    explicit_claim_lines = [str(row["line"]) for row in explicit_claims]
    explicit_task_lines = [str(row["line"]) for row in explicit_tasks]
    claim_entries = [*explicit_claim_lines, *[kept_inferred_claims[key] for key in sorted(kept_inferred_claims.keys())]]
    task_entries = [*explicit_task_lines, *[kept_inferred_tasks[key] for key in sorted(kept_inferred_tasks.keys())]]

    if apply:
        _write_section_entries(
            lines, section_start=claim_section[0], section_end=claim_section[1], entries=claim_entries
        )
        active_section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
        _write_section_entries(
            lines, section_start=active_section[0], section_end=active_section[1], entries=task_entries
        )
        new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
        ok_write, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
            workboard_path,
            original_text,
            new_text,
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        )
        if not ok_write:
            return False, {"error": "inferred sync rejected by gate", "violations": list(violations)}
        _write_inferred_sync_state(
            repo_root,
            {
                "updated_at": timestamp,
                "entries": next_entries,
                "inferred_applied": applied,
                "inferred_suppressed": suppressed[:50],
                "inferred_expired": expired,
            },
        )

    return True, {
        "candidate_count": len(candidates),
        "applied_count": len(applied),
        "applied": applied[:50],
        "suppressed_count": len(suppressed),
        "suppressed": suppressed[:50],
        "expired_count": len(expired),
        "expired": expired[:50],
        "claim_entry_count": len(claim_entries),
        "active_task_entry_count": len(task_entries),
        "expiry_minutes": float(expiry_minutes),
        "applied_board_write": bool(apply),
    }


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
            alias_violations.append(f"line {idx + 1}: unauthorized model_alias `{model_alias}` for agent `{agent}`")
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
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        )
        if not ok_write:
            return False, {"error": "specialist route sync rejected by gate", "violations": list(violations_after)}

    return True, {
        "routed_task_count": len(entries),
        "tracked_task_count": len(task_rows),
        "applied": bool(apply),
    }
