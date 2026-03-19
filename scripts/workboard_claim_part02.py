def _remove_up_for_grabs_entry(lines: list[str], task_id: str) -> tuple[bool, str]:
    if workboard_issue_mod is None:
        return False, "workboard_issue module unavailable"
    if not task_id:
        return False, "task_id is required to remove up-for-grabs entry"
    section = workboard_issue_mod._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]
    key = _normalize_task_id(task_id)
    remove_idx: int | None = None
    entry_field: dict[str, str] | None = None
    for idx in workboard_issue_mod._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue_mod._parse_up_for_grabs_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, err
        if entry is not None and workboard_issue_mod._is_none_entry(entry):  # type: ignore[attr-defined]
            continue
        if fields and _normalize_task_id(fields.get("task_id", "")) == key:
            remove_idx = idx
            entry_field = fields
            break

    if remove_idx is None:
        return False, f"up-for-grabs task `{task_id}` not found"
    if not entry_field:
        return False, f"up-for-grabs task `{task_id}` entry is malformed"

    del lines[remove_idx]
    section = workboard_issue_mod._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]
    workboard_issue_mod._ensure_none_if_empty(lines, section_start=section[0], section_end=section[1])  # type: ignore[attr-defined]
    return True, f"removed up-for-grabs task `{entry_field.get('task_id', task_id)}`"


def claim(
    workboard_path: Path,
    *,
    agent: str,
    scope: str,
    task: str,
    name: str | None = None,
    role: str | None = None,
    parent: str | None = None,
    require_claims_to_have_active_task: bool = True,
    allow_blocked_without_issue: bool = False,
    allow_dirty: bool = False,
    dirty_reason: str = "",
    allow_presence_override: bool = False,
    presence_override_reason: str = "",
) -> tuple[bool, str]:
    ok_presence, presence_message = _presence_gate(
        workboard_path=workboard_path,
        purpose="workboard_claim",
        agent=agent,
        requested_scope=scope,
        allow_override=bool(allow_presence_override),
        override_reason=str(presence_override_reason or ""),
    )
    if not ok_presence:
        return False, presence_message

    with _file_lock(LOCK_FILE):
        dirty_paths = {"staged": [], "unstaged": [], "untracked": []}
        if _scope_guard_supported(workboard_path):
            dirty_paths = _worktree_dirty_paths(ROOT)
            offenders = sorted(
                set(
                    list(dirty_paths.get("staged") or [])
                    + list(dirty_paths.get("unstaged") or [])
                    + list(dirty_paths.get("untracked") or [])
                )
            )
            if offenders and not allow_dirty:
                sample = _sample_paths(offenders)
                return (
                    False,
                    (
                        f"repo worktree is dirty ({len(offenders)} paths): {sample}. "
                        "Refusing to claim new work until the repo is clean. "
                        "Run python scripts/check_repo_hygiene.py or python -m thomas status --strict-worktree, "
                        "or pass --allow-dirty-claim with --dirty-claim-reason."
                    ),
                )
            if offenders and allow_dirty:
                try:
                    reason = _validate_dirty_claim_reason(dirty_reason)
                except ValueError as exc:
                    return False, str(exc)
                _append_claim_override_audit(
                    agent=agent,
                    reason=reason,
                    scope=scope,
                    dirty_paths=dirty_paths,
                )
        claim_name = _resolve_display_name(name, agent)
        claim_parent = _normalize_parent_token(parent)
        claim_role = _resolve_claim_role(role, claim_parent)
        formatted = _format_claim(
            agent,
            scope,
            task,
            name=claim_name,
            role=claim_role,
            parent=claim_parent,
        )
        agent_norm = _agent_key(agent)
        original_text = workboard_path.read_text(encoding="utf-8")
        lines = original_text.splitlines()

        section_start, section_end = _find_claim_section(lines)
        bullet_idxs = _bullet_indices(lines, section_start, section_end)

        existing_idx: int | None = None
        duplicate_idx: int | None = None
        none_idxs: list[int] = []

        for idx in bullet_idxs:
            entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
            if err:
                return False, err
            if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                none_idxs.append(idx)
                continue
            if not fields:
                continue
            current_agent = _agent_key(fields.get("agent", ""))
            if current_agent == agent_norm:
                if existing_idx is None:
                    existing_idx = idx
                else:
                    duplicate_idx = idx

        if duplicate_idx is not None:
            return (
                False,
                f"duplicate existing claim entries for `{agent}` at lines {existing_idx + 1} and {duplicate_idx + 1}",
            )

        if existing_idx is not None:
            lines[existing_idx] = formatted
            action = f"updated claim for `{agent}`"
        else:
            for idx in sorted(none_idxs, reverse=True):
                del lines[idx]
                if idx < section_end:
                    section_end -= 1
            insert_at = section_end
            lines.insert(insert_at, formatted)
            action = f"added claim for `{agent}`"

        claim_task_id = _task_id_from_agent(agent)
        task_ok, task_msg = _upsert_active_task(
            lines,
            agent=agent,
            scope=scope,
            task=task,
            name=claim_name,
            role=claim_role,
            parent=claim_parent,
        )
        if not task_ok:
            if "task_id appears in both active tasks and up-for-grabs" in task_msg.lower():
                ok_remove, remove_msg = _remove_up_for_grabs_entry(lines, task_id=claim_task_id)
                if not ok_remove:
                    return False, remove_msg
                task_ok, task_msg = _upsert_active_task(
                    lines,
                    agent=agent,
                    scope=scope,
                    task=task,
                    name=claim_name,
                    role=claim_role,
                    parent=claim_parent,
                )
                if not task_ok:
                    return False, task_msg
            else:
                return False, task_msg

        overlap_guard_phrase = f"task_id appears in both active tasks and up-for-grabs: `{claim_task_id}`"

        new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
        ok, violations = _validate_and_write(
            workboard_path,
            original_text,
            new_text,
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
            allow_blocked_without_issue=bool(allow_blocked_without_issue),
        )
        if not ok and any(overlap_guard_phrase in str(item).lower() for item in violations):
            ok_remove, remove_msg = _remove_up_for_grabs_entry(lines, task_id=claim_task_id)
            if not ok_remove:
                joined = "; ".join(violations)
                return False, f"claim update rejected by gate: {joined}"

            new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
            ok, violations = _validate_and_write(
                workboard_path,
                original_text,
                new_text,
                require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
                allow_blocked_without_issue=bool(allow_blocked_without_issue),
            )

        if not ok:
            joined = "; ".join(violations)
            return False, f"claim update rejected by gate: {joined}"
        return True, f"{action}; {task_msg}"


def release(
    workboard_path: Path,
    *,
    agent: str,
    allow_dirty: bool = False,
    dirty_reason: str = "",
    require_done_state: bool = False,
    allow_presence_override: bool = False,
    presence_override_reason: str = "",
) -> tuple[bool, str]:
    with _file_lock(LOCK_FILE):
        agent_norm = _agent_key(agent)
        original_text = workboard_path.read_text(encoding="utf-8")
        lines = original_text.splitlines()
        section_start, section_end = _find_claim_section(lines)
        bullet_idxs = _bullet_indices(lines, section_start, section_end)

        remove_idxs: list[int] = []
        remove_scopes: list[str] = []
        keep_active = 0
        for idx in bullet_idxs:
            entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
            if err:
                return False, err
            if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                continue
            if not fields:
                continue
            current_agent = _agent_key(fields.get("agent", ""))
            if current_agent == agent_norm:
                remove_idxs.append(idx)
                remove_scopes.extend(
                    [
                        _normalize_scope_token(token)
                        for token in str(fields.get("scope", "")).split(",")
                        if _normalize_scope_token(token)
                    ]
                )
            else:
                keep_active += 1

        if not remove_idxs:
            return False, f"no active claim found for `{agent}`"

        ok_task_ids, task_payload = _task_ids_for_agent(lines, agent=agent)
        if not ok_task_ids:
            return False, str(task_payload)
        released_task_ids = [item for item in list(task_payload) if str(item).strip()]

        if require_done_state:
            active_section_start, active_section_end = _ensure_active_tasks_section(lines)
            not_ready: list[str] = []
            for idx in _bullet_indices(lines, active_section_start, active_section_end):
                entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
                if err:
                    return False, err
                if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                    continue
                if not fields:
                    continue
                if _agent_key(fields.get("agent", "")) != agent_norm:
                    continue
                task_id = str(fields.get("task_id", "")).strip() or "unknown-task"
                status_raw = str(fields.get("status", "")).strip()
                status, _status_err = claims_gate.normalize_active_task_status(status_raw)
                status = status or status_raw.lower() or "unknown"
                if status not in {"done", "blocked"}:
                    not_ready.append(f"{task_id}:{status}")
            if not_ready:
                return (
                    False,
                    (
                        f"agent `{agent}` cannot release claim because task statuses are not close-ready: "
                        + ", ".join(not_ready)
                        + " (expected done or blocked)"
                    ),
                )

        clean_scopes = sorted(set(remove_scopes), key=str.lower)
        ok_presence, presence_message = _presence_gate(
            workboard_path=workboard_path,
            purpose="workboard_release",
            agent=agent,
            requested_scope=clean_scopes,
            allow_override=bool(allow_presence_override),
            override_reason=str(presence_override_reason or ""),
        )
        if not ok_presence:
            return False, presence_message
        dirty_paths = {"staged": [], "unstaged": [], "untracked": []}
        if clean_scopes and _scope_guard_supported(workboard_path):
            dirty_paths = _claimed_scope_dirty_paths(clean_scopes)
            offenders = sorted(
                set(
                    list(dirty_paths.get("staged") or [])
                    + list(dirty_paths.get("unstaged") or [])
                    + list(dirty_paths.get("untracked") or [])
                )
            )
            if offenders and not allow_dirty:
                sample = _sample_paths(offenders)
                return (
                    False,
                    (
                        f"agent `{agent}` has dirty files in claimed scope ({len(offenders)}): {sample}. "
                        "Commit or stash these files before release, or pass "
                        "--allow-dirty-release with --dirty-release-reason."
                    ),
                )
            if offenders and allow_dirty:
                try:
                    reason = _validate_dirty_release_reason(dirty_reason)
                except ValueError as exc:
                    return False, str(exc)
                try:
                    _append_release_override_audit(
                        agent=agent,
                        reason=reason,
                        scopes=clean_scopes,
                        dirty_paths=dirty_paths,
                    )
                except Exception as exc:
                    return False, f"failed to write release override audit: {exc}"
        elif allow_dirty and _scope_guard_supported(workboard_path):
            try:
                _validate_dirty_release_reason(dirty_reason)
            except ValueError as exc:
                return False, str(exc)

        for idx in sorted(remove_idxs, reverse=True):
            del lines[idx]
            if idx < section_end:
                section_end -= 1

        if keep_active == 0:
            lines.insert(section_end, NONE_ENTRY)

        task_ok, task_msg = _release_active_task(lines, agent=agent)
        if not task_ok:
            return False, task_msg

        issues_ok, issues_msg, removed_issue_count = _cleanup_auto_inactive_issues_for_tasks(
            lines,
            task_ids=released_task_ids,
        )
        if not issues_ok:
            return False, issues_msg

        new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
        ok, violations = _validate_and_write(workboard_path, original_text, new_text)
        if not ok:
            joined = "; ".join(violations)
            return False, f"claim release rejected by gate: {joined}"
        return (
            True,
            f"released claim for `{agent}`; {task_msg}; " f"cleaned_auto_inactive_issues={removed_issue_count}",
        )


def list_claims(workboard_path: Path) -> tuple[bool, list[str] | str]:
    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _find_claim_section(lines)
    bullet_idxs = _bullet_indices(lines, section_start, section_end)

    claims: list[str] = []
    for idx in bullet_idxs:
        entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if fields:
            claims.append(lines[idx].strip())
    return True, claims


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
            "python scripts/workboard_claim.py --claim "
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
        parent="none",
    )
    if not ok_claim:
        # Recover gracefully from race conditions where another agent wins the lease.
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


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add/list/release active agent claims in WORKBOARD.md.")
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help="Path to workboard markdown file (default: plans/thomas/WORKBOARD.md)",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--claim", action="store_true", help="Add or update an active claim for --agent.")
    action.add_argument("--release", action="store_true", help="Release active claim for --agent.")
    action.add_argument("--list", action="store_true", help="List active claims.")
    action.add_argument(
        "--suggest-delegation",
        action="store_true",
        help="Suggest non-overlapping `## Up For Grabs` tasks to delegate to child workers.",
    )
    action.add_argument(
        "--dispatch-workers",
        action="store_true",
        help="Release READY workers (optional) and claim suggested worker tasks for a parent agent.",
    )
    action.add_argument(
        "--release-temp-task-creator",
        action="store_true",
        help="Manager-only: release active temporary task-creator lease(s).",
    )
    parser.add_argument("--agent", help="Agent identifier (defaults to env/git user when omitted).")
    parser.add_argument(
        "--name",
        help="Human-readable claim name/callsign (defaults to --agent when omitted).",
    )
    parser.add_argument(
        "--role",
        choices=list(CLAIM_ROLE_VALUES),
        help="Claim role: solo, parent, or worker (auto-derived when omitted).",
    )
    parser.add_argument(
        "--parent",
        help="Parent agent id for worker claims (use `none` to clear).",
    )
    parser.add_argument("--scope", help="Claim scope path(s), comma separated.")
    parser.add_argument("--task", help="Short task description (defaults to current git branch).")
    parser.add_argument(
        "--max-suggestions",
        type=int,
        default=3,
        help="Maximum delegation suggestions to emit with --suggest-delegation (default: 3).",
    )
    parser.add_argument(
        "--dispatch-target-workers",
        type=int,
        default=DEFAULT_DISPATCH_TARGET_WORKERS,
        help=(
            "Target active workers for --dispatch-workers (minimum 2). "
            f"(default: {DEFAULT_DISPATCH_TARGET_WORKERS})."
        ),
    )
    parser.add_argument(
        "--dispatch-max-suggestions",
        type=int,
        default=DEFAULT_DISPATCH_MAX_SUGGESTIONS,
        help=(
            "Maximum suggestions inspected during --dispatch-workers " f"(default: {DEFAULT_DISPATCH_MAX_SUGGESTIONS})."
        ),
    )
    parser.add_argument(
        "--dispatch-release-ready",
        action="store_true",
        help="With --dispatch-workers, release READY worker claims before claiming new work.",
    )
    parser.add_argument(
        "--dispatch-no-temp-creator",
        action="store_true",
        help="With --dispatch-workers, disable automatic temporary task-creator fallback when no tasks are available.",
    )
    parser.add_argument(
        "--dispatch-no-temp-creator-notice",
        action="store_true",
        help="With --dispatch-workers, skip coordination notice to task-manager when temp-task-creator is acquired.",
    )
    parser.add_argument(
        "--task-manager-agent",
        default=DEFAULT_TASK_MANAGER_AGENT,
        help=(
            "Task-manager agent id used by temporary task-creator fallback " f"(default: {DEFAULT_TASK_MANAGER_AGENT})."
        ),
    )
    parser.add_argument(
        "--allow-dirty-release",
        action="store_true",
        help=(
            "Allow --release to proceed even when claimed scope has dirty files. " "Requires --dirty-release-reason."
        ),
    )
    parser.add_argument(
        "--dirty-release-reason",
        default="",
        help="Required reason (>=12 chars) when --allow-dirty-release is used.",
    )
    parser.add_argument(
        "--allow-dirty-claim",
        action="store_true",
        help=("Allow --claim to proceed even when the repo worktree is dirty. " "Requires --dirty-claim-reason."),
    )
    parser.add_argument(
        "--dirty-claim-reason",
        default="",
        help="Required reason (>=12 chars) when --allow-dirty-claim is used.",
    )
    parser.add_argument(
        "--allow-presence-override",
        action="store_true",
        help=(
            "Allow claim/release to proceed when the repo presence monitor detects other active or unregistered agents. "
            "Requires --presence-override-reason."
        ),
    )
    parser.add_argument(
        "--presence-override-reason",
        default="",
        help="Required reason (>=12 chars) when --allow-presence-override is used.",
    )
