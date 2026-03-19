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
            )
        except TypeError:
            # Backward compatibility: older claim helpers may not support identity fields.
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
) -> tuple[bool, claims_gate.UpForGrabTask | None, str]:
    violations, _claims, _active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
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
