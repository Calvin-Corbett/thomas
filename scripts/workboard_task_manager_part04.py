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
    auto_task_id = workboard_claim._task_id_from_agent(agent)  # type: ignore[attr-defined]

    scope = str(scope_override or row.get("scope") or "").strip()
    summary = str(task_summary or row.get("summary") or "").strip()
    if not scope:
        return False, {"error": f"task `{task_id}` has empty scope and no --scope override was provided"}
    if not summary:
        return False, {"error": f"task `{task_id}` has empty summary and no --summary override was provided"}

    claim_kwargs: dict[str, object] = {}
    if name is not None:
        claim_kwargs["name"] = name
    if role is not None:
        claim_kwargs["role"] = role
    if parent is not None:
        claim_kwargs["parent"] = parent

    removed_up_for_grabs_before_claim = False

    def _attempt_claim() -> tuple[bool, str]:
        try:
            return workboard_claim.claim(
                workboard_path,
                agent=agent,
                scope=scope,
                task=f"[WIP] {summary}",
                **claim_kwargs,
                require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
                allow_blocked_without_issue=not bool(require_claims_to_have_active_task),
            )
        except TypeError:
            # Backward compatibility: older claim helpers may not support identity fields.
            try:
                return workboard_claim.claim(
                    workboard_path,
                    agent=agent,
                    scope=scope,
                    task=f"[WIP] {summary}",
                    **claim_kwargs,
                    require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
                    allow_blocked_without_issue=not bool(require_claims_to_have_active_task),
                )
            except TypeError:
                return workboard_claim.claim(
                    workboard_path,
                    agent=agent,
                    scope=scope,
                    task=f"[WIP] {summary}",
                )

    ok_claim, msg_claim = _attempt_claim()
    if not ok_claim:
        duplicate_task_id_conflict = _norm(task_id) == _norm(
            auto_task_id
        ) and "task_id appears in both active tasks and up-for-grabs" in _norm(str(msg_claim))
        if not duplicate_task_id_conflict:
            return False, {"error": msg_claim}

        preclaim_text = workboard_path.read_text(encoding="utf-8")
        preclaim_lines = preclaim_text.splitlines()
        ok_remove_preclaim, msg_remove_preclaim = _remove_up_for_grabs_task(
            preclaim_lines,
            task_id=task_id,
        )
        if not ok_remove_preclaim:
            return False, {"error": msg_remove_preclaim}
        preclaim_next = "\n".join(preclaim_lines) + ("\n" if preclaim_text.endswith("\n") else "")
        ok_preclaim_write, preclaim_violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
            workboard_path,
            preclaim_text,
            preclaim_next,
        )
        if not ok_preclaim_write:
            return False, {
                "error": "preclaim up-for-grabs removal rejected by gate",
                "violations": list(preclaim_violations),
            }
        removed_up_for_grabs_before_claim = True
        ok_claim, msg_claim = _attempt_claim()
        if not ok_claim:
            workboard_path.write_text(preclaim_text, encoding="utf-8")
            return False, {"error": msg_claim}

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    if not removed_up_for_grabs_before_claim:
        ok_remove_grab, msg_remove_grab = _remove_up_for_grabs_task(lines, task_id=task_id)
        if not ok_remove_grab:
            active_section_for_check = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
            for idx in workboard_claim._bullet_indices(lines, active_section_for_check[0], active_section_for_check[1]):  # type: ignore[attr-defined]
                entry, fields, err = workboard_claim._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
                if err:
                    return False, {"error": err}
                if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                    continue
                if not fields:
                    continue
                if _norm(fields.get("task_id", "")) == _norm(task_id):
                    removed_up_for_grabs_before_claim = True
                    break
                if _norm(fields.get("task_id", "")) == _norm(auto_task_id):
                    removed_up_for_grabs_before_claim = True
                    break
            if not removed_up_for_grabs_before_claim:
                return False, {"error": msg_remove_grab}

    claim_section = workboard_claim._find_claim_section(lines)  # type: ignore[attr-defined]
    claim_name = agent
    claim_role = "solo"
    claim_parent = "none"
    for idx in workboard_claim._bullet_indices(lines, claim_section[0], claim_section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_claim._parse_claim_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, {"error": err}
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        if _norm(fields.get("agent", "")) != _norm(agent):
            continue
        claim_name = str(fields.get("name") or agent).strip() or agent
        claim_role = str(fields.get("role") or claim_role).strip() or claim_role
        claim_parent = str(fields.get("parent") or claim_parent).strip() or claim_parent
        break

    active_section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    target_idx: int | None = None
    auto_idx: int | None = None

    for idx in workboard_claim._bullet_indices(lines, active_section[0], active_section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_claim._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, {"error": err}
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        if _norm(fields.get("task_id", "")) == _norm(task_id):
            target_idx = idx
        if _norm(fields.get("task_id", "")) == _norm(auto_task_id):
            auto_idx = idx

    replacement = workboard_claim._format_active_task(  # type: ignore[attr-defined]
        task_id=task_id,
        agent=agent,
        scope=scope,
        summary=f"[WIP] {summary}",
        status="claimed",
        name=claim_name,
        role=claim_role,
        parent=claim_parent,
    )

    if target_idx is not None:
        lines[target_idx] = replacement
    elif auto_idx is not None:
        lines[auto_idx] = replacement
    else:
        for idx in sorted(workboard_claim._bullet_indices(lines, active_section[0], active_section[1]), reverse=True):  # type: ignore[attr-defined]
            entry = lines[idx].strip()[2:].strip()
            if entry.lower() in claims_gate.NONE_TOKENS:
                del lines[idx]
        active_section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
        lines.insert(active_section[1], replacement)

    active_section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    seen_target = False
    for idx in sorted(workboard_claim._bullet_indices(lines, active_section[0], active_section[1]), reverse=True):  # type: ignore[attr-defined]
        entry, fields, err = workboard_claim._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, {"error": err}
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        if _norm(fields.get("task_id", "")) == _norm(task_id):
            if seen_target:
                del lines[idx]
            else:
                seen_target = True
        elif _norm(fields.get("task_id", "")) == _norm(auto_task_id):
            del lines[idx]

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
        "summary": f"[WIP] {summary}",
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
        section = workboard_claim._find_active_tasks_section(lines)  # type: ignore[attr-defined]
    except Exception as exc:
        return False, [], [str(exc)]

    items: list[dict[str, str]] = []
    errors: list[str] = []
    for idx in workboard_claim._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_claim._parse_active_task_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
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


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Task-manager automation for WORKBOARD protocols.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--auto-start",
        action="store_true",
        help="Auto-claim and move a task to in_progress for --agent when no working task is active.",
    )
    actions.add_argument("--sync-plans", action="store_true", help="Ensure per-task plan entries/files exist.")
    actions.add_argument("--sweep-inactive", action="store_true", help="Detect and process inactive agents.")
    actions.add_argument("--reactivate", action="store_true", help="Reactivate a task from Up For Grabs.")
    actions.add_argument("--sync-sessions", action="store_true", help="Sync active/inactive agent sessions.")
    actions.add_argument(
        "--monitor",
        action="store_true",
        help=(
            "Run monitor loop: sync board, recover swarms, auto-start claimed agents, "
            "ping silence, sweep inactive, and dispatch idle agents."
        ),
    )
    actions.add_argument(
        "--sync-inferred", action="store_true", help="Sync inferred presence claims/tasks into the board."
    )
    actions.add_argument(
        "--sync-specialists",
        action="store_true",
        help="Sync task-type specialist routes for active/up-for-grabs tasks.",
    )
    actions.add_argument(
        "--specialist-for-task",
        action="store_true",
        help="Return specialist route for one board task id or ad-hoc scope/summary text.",
    )
    actions.add_argument(
        "--capture-preference",
        action="store_true",
        help="Store task-orchestration preference (summary + verbatim) in preferences.",
    )

    parser.add_argument("--apply", action="store_true", help="Apply mutations instead of dry-run checks.")
    parser.add_argument("--now", default="", help="Optional ISO now override for deterministic checks.")

    parser.add_argument("--plan-root", default=DEFAULT_PLAN_ROOT, help="Plan root path for generated PLAN.md files.")
    parser.add_argument(
        "--problem-root",
        default=DEFAULT_PROBLEM_ROOT,
        help="Problem root path for generated PROBLEM.md files.",
    )

    parser.add_argument(
        "--max-idle-minutes",
        type=float,
        default=DEFAULT_MAX_IDLE_MINUTES,
        help="Idle threshold in minutes for inactive-agent detection (default: 1).",
    )
    parser.add_argument(
        "--task-manager-agent",
        default=DEFAULT_TASK_MANAGER_AGENT,
        help="Agent id assigned as issue owner/notification target.",
    )
    parser.add_argument(
        "--max-agent-silence-minutes",
        type=float,
        default=DEFAULT_MAX_AGENT_SILENCE_MINUTES,
        help="Silence threshold before pinging active-task agents (default: 5).",
    )
    parser.add_argument(
        "--session-lease-minutes",
        type=float,
        default=DEFAULT_SESSION_LEASE_MINUTES,
        help="Lease TTL for active sessions before they are considered expired (default: 5).",
    )
    parser.add_argument(
        "--max-dispatch-per-cycle",
        type=int,
        default=DEFAULT_MAX_DISPATCH_PER_CYCLE,
        help="Maximum up-for-grabs tasks to auto-dispatch per monitor cycle (default: 2).",
    )
    parser.add_argument(
        "--online-lookback-minutes",
        type=float,
        default=30.0,
        help="Lookback window used to consider an agent online via message traffic (default: 30).",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=DEFAULT_MONITOR_CYCLES,
        help="Monitor cycle count (0 means run continuously; default: 1).",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_MONITOR_INTERVAL_SECONDS,
        help="Delay between monitor cycles (default: 30).",
    )
    parser.add_argument(
        "--no-swarm-recovery",
        action="store_true",
        help="Disable automatic swarm missing-agent relaunch in --monitor mode.",
    )
    parser.add_argument(
        "--no-idle-dispatch",
        action="store_true",
        help="Disable automatic up-for-grabs dispatch to online idle agents in --monitor mode.",
    )
    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        help="Disable automatic claimed-agent auto-start in --monitor mode.",
    )

    parser.add_argument("--task-id", default="", help="Task id for --reactivate or --specialist-for-task.")
    parser.add_argument("--agent", default="", help="Agent id for --reactivate.")
    parser.add_argument("--summary", default="", help="Optional summary override for --reactivate.")
    parser.add_argument("--scope", default="", help="Optional scope override for --reactivate.")
    parser.add_argument("--task-scope", default="", help="Scope text for ad-hoc --specialist-for-task routing.")
    parser.add_argument("--task-summary", default="", help="Summary text for ad-hoc --specialist-for-task routing.")
    parser.add_argument("--name", default="", help="Optional claim display name for --reactivate.")
    parser.add_argument("--role", default="", help="Optional role for --reactivate (solo|parent|worker).")
    parser.add_argument("--parent", default="", help="Optional parent id for --reactivate worker role.")
    parser.add_argument("--user-id", default="default", help="Preferences user id for --capture-preference.")
    parser.add_argument(
        "--preference-summary",
        default="",
        help="Preference summary used as primary weighted instruction for --capture-preference.",
    )
    parser.add_argument(
        "--preference-verbatim",
        default="",
        help="Verbatim user instruction to retain for audit context with --capture-preference.",
    )

    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()
    if not workboard_path.exists():
        payload = {
            "action": "workboard_task_manager",
            "ok": False,
            "error": f"missing workboard file: {workboard_path}",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1

    try:
        now = _parse_now(args.now)
    except Exception as exc:
        payload = {"action": "workboard_task_manager", "ok": False, "error": f"invalid --now value: {exc}"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1

    if args.max_idle_minutes <= 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--max-idle-minutes must be > 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.max_agent_silence_minutes <= 0:
        payload = {
            "action": "workboard_task_manager",
            "ok": False,
            "error": "--max-agent-silence-minutes must be > 0",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.max_dispatch_per_cycle < 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--max-dispatch-per-cycle must be >= 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.session_lease_minutes <= 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--session-lease-minutes must be > 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.online_lookback_minutes <= 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--online-lookback-minutes must be > 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.cycles < 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--cycles must be >= 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.interval_seconds < 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--interval-seconds must be >= 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1

    if args.monitor:
        now_seed = now if str(args.now).strip() else None
        ok_plan_sync, plan_sync_details = _sync_task_plans(
            workboard_path=workboard_path,
            plan_root=str(args.plan_root),
            problem_root=str(args.problem_root),
            require_claims_to_have_active_task=False,
            apply=bool(args.apply),
            now=now,
        )
        if not ok_plan_sync:
            payload = {
                "action": "monitor",
                "ok": False,
                "workboard": str(workboard_path),
                "plan_sync": plan_sync_details,
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- plan sync failed: {payload.get('error', plan_sync_details.get('error', 'unknown'))}")
            return 1
        ok, details = _monitor_loop(
            workboard_path=workboard_path,
            plan_root=str(args.plan_root),
            problem_root=str(args.problem_root),
            task_manager_agent=str(args.task_manager_agent),
            max_idle_minutes=float(args.max_idle_minutes),
            max_agent_silence_minutes=float(args.max_agent_silence_minutes),
            session_lease_minutes=float(args.session_lease_minutes),
            max_dispatch_per_cycle=int(args.max_dispatch_per_cycle),
            online_lookback_minutes=float(args.online_lookback_minutes),
            run_swarm_recovery=not bool(args.no_swarm_recovery),
            run_auto_start=not bool(args.no_auto_start),
            run_idle_dispatch=not bool(args.no_idle_dispatch),
            require_claims_to_have_active_task=False,
            cycles=int(args.cycles),
            interval_seconds=float(args.interval_seconds),
            now_seed=now_seed,
            apply=bool(args.apply),
        )
        payload = {
            "action": "monitor",
            "ok": bool(ok),
            "workboard": str(workboard_path),
            "plan_sync": plan_sync_details,
            **details,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            print(
                f"- cycles run: {payload.get('cycle_count', 0)}; "
                f"swarm recovery: {payload.get('run_swarm_recovery')}; "
                f"auto-start: {payload.get('run_auto_start')}; "
                f"idle dispatch: {payload.get('run_idle_dispatch')}"
            )
            if ok_plan_sync:
                print(
                    "- plan sync: "
                    f"tracked={payload.get('plan_sync', {}).get('tracked_task_count', 0)}; "
                    f"created plans={payload.get('plan_sync', {}).get('created_plan_count', 0)}; "
                    f"created problems={payload.get('plan_sync', {}).get('created_problem_count', 0)}; "
                    f"missing plans={payload.get('plan_sync', {}).get('missing_plan_count', 0)}; "
                    f"missing problems={payload.get('plan_sync', {}).get('missing_problem_count', 0)}"
                )
        return 0 if ok else 1

    if args.sync_plans:
        ok, details = _sync_task_plans(
            workboard_path=workboard_path,
            plan_root=str(args.plan_root),
            problem_root=str(args.problem_root),
            require_claims_to_have_active_task=True,
            apply=bool(args.apply),
            now=now,
        )
        payload = {"action": "sync_plans", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- tracked tasks: {payload.get('tracked_task_count', 0)}; "
                    f"plan entries: {payload.get('plan_entry_count', 0)}; "
                    f"created plans: {payload.get('created_plan_count', 0)}; "
                    f"problem entries: {payload.get('problem_entry_count', 0)}; "
                    f"created problems: {payload.get('created_problem_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync plans failed')}")
        return 0 if ok else 1

    if args.sync_sessions:
        ok, details = _sync_agent_sessions(
            workboard_path=workboard_path,
            now=now,
            session_lease_minutes=float(args.session_lease_minutes),
            require_claims_to_have_active_task=True,
            apply=bool(args.apply),
        )
        payload = {"action": "sync_sessions", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- session entries: {payload.get('session_entry_count', 0)}; "
                    f"created session ids: {payload.get('created_session_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync sessions failed')}")
        return 0 if ok else 1

    if args.sync_inferred:
        ok, details = _sync_inferred_presence_claims(
            workboard_path=workboard_path,
            now=now,
            require_claims_to_have_active_task=True,
            apply=bool(args.apply),
        )
        payload = {"action": "sync_inferred", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- inferred candidates: {payload.get('candidate_count', 0)}; "
                    f"applied: {payload.get('applied_count', 0)}; "
                    f"suppressed: {payload.get('suppressed_count', 0)}; "
                    f"expired: {payload.get('expired_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync inferred failed')}")
        return 0 if ok else 1

    if args.sync_specialists:
        ok, details = _sync_task_specialists(
            workboard_path=workboard_path,
            now=now,
            require_claims_to_have_active_task=True,
            apply=bool(args.apply),
        )
        payload = {"action": "sync_specialists", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- routed tasks: {payload.get('routed_task_count', 0)}; "
                    f"tracked tasks: {payload.get('tracked_task_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync specialists failed')}")
        return 0 if ok else 1

    if args.specialist_for_task:
        ok, details = _specialist_for_task(
            workboard_path=workboard_path,
            task_id=str(args.task_id).strip(),
            task_scope=str(args.task_scope).strip(),
            task_summary=str(args.task_summary).strip(),
        )
        payload = {"action": "specialist_for_task", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(f"- task `{payload.get('task_id')}` -> {payload.get('task_type')} / {payload.get('specialist')}")
            else:
                print(f"- {payload.get('error', 'specialist resolution failed')}")
        return 0 if ok else 1

    if args.sweep_inactive:
        ok, details = _sweep_inactive(
            workboard_path=workboard_path,
            max_idle_minutes=float(args.max_idle_minutes),
            task_manager_agent=str(args.task_manager_agent),
            now=now,
            require_claims_to_have_active_task=True,
            apply=bool(args.apply),
        )
        payload = {"action": "sweep_inactive", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            print(
                f"- stale claims: {payload.get('stale_claim_count', 0)} (threshold {float(args.max_idle_minutes):.2f}m)"
            )
            if args.apply:
                print(
                    f"- moved tasks: {payload.get('moved_task_count', 0)}; "
                    f"released agents: {payload.get('released_agent_count', 0)}"
                )
                print(f"- coordination pings: {payload.get('sent_message_count', 0)}")
            if not ok:
                for item in payload.get("errors", []):
                    print(f"- {item}")
        return 0 if ok else 1

    if args.auto_start:
        ok_agent, resolved_agent, agent_error = _resolve_auto_start_agent(args.agent)
        if not ok_agent:
            payload = {"action": "auto_start", "ok": False, "error": agent_error}
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- {payload['error']}")
            return 1

        ok, details = _auto_start_task_for_agent(
            workboard_path=workboard_path,
            agent=resolved_agent,
            task_manager_agent=str(args.task_manager_agent),
            require_claims_to_have_active_task=False,
        )
        payload = {
            "action": "auto_start",
            "ok": bool(ok),
            "workboard": str(workboard_path),
            "agent": resolved_agent,
            **details,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                source = str(details.get("source") or "unknown")
                print(f"- started task `{details.get('task_id')}` for `{resolved_agent}` (source: {source})")
            else:
                print(f"- {details.get('error', 'auto-start failed')}")
        return 0 if ok else 1

    if args.reactivate:
        if _is_orchestrator_agent(str(args.agent)):
            payload = {
                "action": "reactivate",
                "ok": False,
                "error": "reactivate is disabled for orchestrator agents",
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- {payload['error']}")
            return 1
        if not str(args.task_id).strip() or not str(args.agent).strip():
            payload = {
                "action": "reactivate",
                "ok": False,
                "error": "--task-id and --agent are required for --reactivate",
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- {payload['error']}")
            return 1
        ok, details = _reactivate_task(
            workboard_path=workboard_path,
            task_id=str(args.task_id).strip(),
            agent=str(args.agent).strip(),
            task_summary=str(args.summary).strip() or None,
            scope_override=str(args.scope).strip() or None,
            name=str(args.name).strip() or None,
            role=str(args.role).strip() or None,
            parent=str(args.parent).strip() or None,
        )
        if ok:
            task_id = str(details.get("task_id") or args.task_id).strip()
            ok_status, payload_status = set_task_status(
                workboard_path,
                task_id=task_id,
                status="in_progress",
                actor=str(args.agent).strip(),
                enforce_transition=True,
            )
            if not ok_status:
                details = {
                    "error": "reactivation succeeded but transition to in_progress failed",
                    "reactivation": details,
                    "status_error": payload_status,
                }
                ok = False

        payload = {"action": "reactivate", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(f"- reactivated task `{payload.get('task_id')}` for `{payload.get('agent')}`")
            else:
                print(f"- {payload.get('error', 'reactivation failed')}")
        return 0 if ok else 1

    if args.capture_preference:
        ok, details = _capture_task_ecosystem_preference(
            user_id=str(args.user_id).strip() or "default",
            summary=str(args.preference_summary).strip(),
            verbatim=str(args.preference_verbatim).strip(),
            now=now,
        )
        payload = {
            "action": "capture_preference",
            "ok": bool(ok),
            "workboard": str(workboard_path),
            **details,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- captured preference for user `{payload.get('user_id')}` "
                    f"(total stored: {payload.get('saved_preference_count', 0)})"
                )
            else:
                print(f"- {payload.get('error', 'capture preference failed')}")
        return 0 if ok else 1

    payload = {"action": "workboard_task_manager", "ok": False, "error": "no action selected"}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Workboard task manager: FAIL")
        print(f"- {payload['error']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
