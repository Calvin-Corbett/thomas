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
    now: datetime,
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    checks: dict[str, dict[str, object]] = {}
    errors: list[str] = []

    ok_sessions, payload_sessions = _sync_agent_sessions(
        workboard_path=workboard_path,
        now=now,
        session_lease_minutes=session_lease_minutes,
        apply=apply,
    )
    checks["sync_sessions"] = payload_sessions
    if not ok_sessions:
        errors.append(str(payload_sessions.get("error", "sync_sessions failed")))

    ok_specialists, payload_specialists = _sync_task_specialists(
        workboard_path=workboard_path,
        now=now,
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
        apply=apply,
    )
    checks["silence_ping"] = payload_ping
    if not ok_ping:
        errors.extend(
            [str(item) for item in list(payload_ping.get("errors") or [])] or [str(payload_ping.get("error", ""))]
        )

    ok_sweep, payload_sweep = _sweep_inactive(
        workboard_path=workboard_path,
        max_idle_minutes=max_idle_minutes,
        task_manager_agent=task_manager_agent,
        now=now,
        apply=apply,
    )
    checks["sweep_inactive"] = payload_sweep
    if not ok_sweep:
        errors.extend(
            [str(item) for item in list(payload_sweep.get("errors") or [])] or [str(payload_sweep.get("error", ""))]
        )

    if run_auto_start:
        ok_auto_start, payload_auto_start = _auto_start_all_claimed_agents(
            workboard_path=workboard_path,
            task_manager_agent=task_manager_agent,
            apply=apply,
        )
        checks["auto_start"] = payload_auto_start
        if not ok_auto_start:
            errors.extend(
                [str(item) for item in list(payload_auto_start.get("errors") or [])]
                or [str(payload_auto_start.get("error", ""))]
            )

    if run_idle_dispatch:
        ok_dispatch, payload_dispatch = _dispatch_up_for_grabs_to_idle_agents(
            workboard_path=workboard_path,
            now=now,
            task_manager_agent=task_manager_agent,
            max_dispatch_per_cycle=max_dispatch_per_cycle,
            online_lookback_minutes=online_lookback_minutes,
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
        apply=apply,
        now=now,
    )
    checks["sync_plans"] = payload_plans
    if not ok_plans:
        errors.append(str(payload_plans.get("error", "sync_plans failed")))

    payload: dict[str, object] = {
        "cycle_started_at": now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "checks": checks,
        "applied": bool(apply),
    }
    if errors:
        payload["errors"] = [item for item in errors if item]
        return False, payload
    return True, payload


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
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, claims, active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
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
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
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
        )
        if not ok_write:
            return False, {"error": "specialist route sync rejected by gate", "violations": list(violations_after)}

    return True, {
        "routed_task_count": len(entries),
        "tracked_task_count": len(task_rows),
        "applied": bool(apply),
    }


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

    if not task_id_clean and not task_scope_clean and not task_summary_clean:
        return False, {"error": "provide --task-id or --task-scope/--task-summary"}

    if task_id_clean:
        violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
        if violations:
            return False, {"error": "workboard invalid", "violations": list(violations)}
        matches = _task_rows_for_specialist_routing(active_tasks=active_tasks, up_for_grabs=up_for_grabs)
        selected = next((row for row in matches if _norm(row.get("task_id", "")) == _norm(task_id_clean)), None)
        if selected is None:
            return False, {"error": f"task `{task_id_clean}` not found in active/up-for-grabs lanes"}
        task_scope_clean = selected.get("scope", "")
        task_summary_clean = selected.get("summary", "")
        task_id_clean = selected.get("task_id", task_id_clean)

    route = task_specialists.infer_specialist(
        task_id=task_id_clean or "adhoc-task",
        scope=task_scope_clean,
        summary=task_summary_clean,
    )
    payload = {
        "task_id": task_id_clean or "adhoc-task",
        "task_scope": task_scope_clean,
        "task_summary": task_summary_clean,
        "task_type": route.get("task_type"),
        "specialist": route.get("specialist"),
        "matched_keywords": list(route.get("matched_keywords") or []),
        "reason": route.get("reason"),
        "score": int(route.get("score") or 0),
    }
    return True, payload


def _default_plan_path(task_id: str, plan_root: str) -> str:
    safe_task_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(task_id or "").strip()).strip("-") or "task"
    rel = Path(plan_root) / safe_task_id / "PLAN.md"
    return str(rel).replace("\\", "/")


def _default_problem_path(task_id: str, problem_root: str) -> str:
    safe_task_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(task_id or "").strip()).strip("-") or "task"
    rel = Path(problem_root) / safe_task_id / "PROBLEM.md"
    return str(rel).replace("\\", "/")


def _build_plan_template(
    *,
    task_id: str,
    owner: str,
    summary: str,
    scope: str,
    status: str,
    now_iso: str,
) -> str:
    return (
        f"# Task Plan: {task_id}\n\n"
        f"- task_id: `{task_id}`\n"
        f"- owner: `{owner}`\n"
        f"- status: `{status}`\n"
        f"- scope: `{scope}`\n"
        f"- summary: {summary}\n"
        f"- created_at_utc: `{now_iso}`\n\n"
        "## Objective\n\n"
        "- Define the desired end state for this task.\n\n"
        "## Constraints\n\n"
        "- List hard constraints and guardrails before implementation.\n\n"
        "## Plan\n\n"
        "1. Gather current context and failure signals.\n"
        "2. Implement the smallest complete change that resolves root cause.\n"
        "3. Validate with focused tests and runtime checks.\n\n"
        "## Progress Log\n\n"
        f"- {now_iso} check-in: PLAN scaffold generated by task manager.\n\n"
        "## Handoff Notes\n\n"
        "- Record what is done, what remains, and exact resume commands.\n"
    )


def _build_problem_template(
    *,
    task_id: str,
    owner: str,
    summary: str,
    scope: str,
    status: str,
    now_iso: str,
) -> str:
    return (
        f"# Task Problem Record: {task_id}\n\n"
        f"- task_id: `{task_id}`\n"
        f"- owner: `{owner}`\n"
        f"- status: `{status}`\n"
        f"- scope: `{scope}`\n"
        f"- summary: {summary}\n"
        f"- created_at_utc: `{now_iso}`\n"
        f"- last_synced_at_utc: `{now_iso}`\n\n"
        "## Problem Statement\n\n"
        "- Describe what is broken, missing, or risky.\n\n"
        "## Evidence\n\n"
        "- Link logs, failing tests, screenshots, or message ids.\n\n"
        "## Root Cause Hypothesis\n\n"
        "- Capture the current best explanation before coding.\n\n"
        "## Fix Plan\n\n"
        "1. Implement the smallest root-cause fix.\n"
        "2. Validate using focused tests and runtime checks.\n"
        "3. Record final outcome and residual risk.\n\n"
        "## Outcome\n\n"
        "- Pending implementation.\n"
    )


def _sync_task_plans(
    *,
    workboard_path: Path,
    plan_root: str,
    problem_root: str,
    apply: bool,
    now: datetime,
) -> tuple[bool, dict[str, object]]:
    violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    owner_by_task: dict[str, str] = {}
    summary_by_task: dict[str, str] = {}
    scope_by_task: dict[str, str] = {}
    status_by_task: dict[str, str] = {}

    for row in active_tasks:
        key = str(row.task_id).strip()
        owner_by_task[key] = row.agent
        summary_by_task[key] = row.summary
        scope_by_task[key] = ",".join(row.scopes)
        status_by_task[key] = row.status

    for row in up_for_grabs:
        key = str(row.task_id).strip()
        owner_by_task.setdefault(key, "unassigned")
        summary_by_task.setdefault(key, row.summary)
        scope_by_task.setdefault(key, ",".join(row.scopes))
        status_by_task.setdefault(key, "up_for_grabs")

    tracked_task_ids = sorted(owner_by_task.keys(), key=str.lower)

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _ensure_section(lines, heading=TASK_PLANS_HEADING)
    problems_start, problems_end = _ensure_section(lines, heading=TASK_PROBLEMS_HEADING)

    existing_plans: dict[str, dict[str, str]] = {}
    existing_problems: dict[str, dict[str, str]] = {}
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
        task_id = str(fields.get("task_id", "")).strip()
        if not task_id:
            parse_errors.append(f"line {idx + 1}: missing task_id")
            continue
        existing_plans[_norm(task_id)] = fields

    for idx in _bullet_indices(lines, problems_start, problems_end):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            parse_errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        task_id = str(fields.get("task_id", "")).strip()
        if not task_id:
            parse_errors.append(f"line {idx + 1}: missing task_id")
            continue
        existing_problems[_norm(task_id)] = fields

    if parse_errors:
        return False, {"error": "task artifact section parse failed", "violations": parse_errors}

    created_plans: list[str] = []
    missing_plans: list[str] = []
    created_problems: list[str] = []
    missing_problems: list[str] = []
    updated_plan_entries: list[str] = []
    updated_problem_entries: list[str] = []
    now_iso = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    for task_id in tracked_task_ids:
        plan_row = existing_plans.get(_norm(task_id), {})
        problem_row = existing_problems.get(_norm(task_id), {})
        plan_path = str(plan_row.get("plan", "")).strip() or _default_plan_path(task_id, plan_root)
        problem_path = str(problem_row.get("problem", "")).strip() or _default_problem_path(task_id, problem_root)
        owner = owner_by_task[task_id]
        summary = summary_by_task[task_id]
        scope = scope_by_task[task_id]
        status = status_by_task[task_id]

        plan_abs = (ROOT / plan_path).resolve()
        if not plan_abs.exists():
            missing_plans.append(plan_path)
            if apply:
                plan_abs.parent.mkdir(parents=True, exist_ok=True)
                plan_abs.write_text(
                    _build_plan_template(
                        task_id=task_id,
                        owner=owner,
                        summary=summary,
                        scope=scope,
                        status=status,
                        now_iso=now_iso,
                    ),
                    encoding="utf-8",
                )
                created_plans.append(plan_path)
        updated_plan_entries.append(
            f"- task_id={_sanitize('task_id', task_id)}; plan={_sanitize('plan', plan_path)}; "
            f"owner={_sanitize('owner', owner)}; status={_sanitize('status', status)}; "
            f"updated_at={_sanitize('updated_at', now_iso)}; "
            f"summary={_sanitize('summary', summary)}"
        )

        problem_abs = (ROOT / problem_path).resolve()
        if not problem_abs.exists():
            missing_problems.append(problem_path)
            if apply:
                problem_abs.parent.mkdir(parents=True, exist_ok=True)
                problem_abs.write_text(
                    _build_problem_template(
                        task_id=task_id,
                        owner=owner,
                        summary=summary,
                        scope=scope,
                        status=status,
                        now_iso=now_iso,
                    ),
                    encoding="utf-8",
                )
                created_problems.append(problem_path)
        updated_problem_entries.append(
            f"- task_id={_sanitize('task_id', task_id)}; problem={_sanitize('problem', problem_path)}; "
            f"owner={_sanitize('owner', owner)}; status={_sanitize('status', status)}; "
            f"updated_at={_sanitize('updated_at', now_iso)}; "
            f"summary={_sanitize('summary', summary)}"
        )

    if (missing_plans or missing_problems) and not apply:
        return False, {
            "error": "missing task artifact files",
            "missing_plan_count": len(missing_plans),
            "missing_plans": missing_plans,
            "missing_problem_count": len(missing_problems),
            "missing_problems": missing_problems,
            "tracked_task_count": len(tracked_task_ids),
        }

    if apply:
        _write_section_entries(
            lines, section_start=section_start, section_end=section_end, entries=updated_plan_entries
        )
        refreshed_problems = _find_section(lines, heading_prefix=TASK_PROBLEMS_HEADING)
        if refreshed_problems is None:
            return False, {"error": f"missing `## {TASK_PROBLEMS_HEADING}` section after sync update"}
        _write_section_entries(
            lines,
            section_start=refreshed_problems[0],
            section_end=refreshed_problems[1],
            entries=updated_problem_entries,
        )
        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        ok, violations_after = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
            workboard_path, text, new_text
        )
        if not ok:
            return False, {"error": "workboard update rejected by gate", "violations": list(violations_after)}

    return True, {
        "tracked_task_count": len(tracked_task_ids),
        "plan_entry_count": len(updated_plan_entries),
        "created_plan_count": len(created_plans),
        "created_plans": created_plans,
        "missing_plan_count": len(missing_plans),
        "missing_plans": missing_plans,
        "problem_entry_count": len(updated_problem_entries),
        "created_problem_count": len(created_problems),
        "created_problems": created_problems,
        "missing_problem_count": len(missing_problems),
        "missing_problems": missing_problems,
        "applied": bool(apply),
    }


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
) -> tuple[list[str], list[dict[str, object]], dict[str, list[claims_gate.ActiveTask]]]:
    violations, claims, active_tasks, _grab, _issues = claims_gate.evaluate_board(workboard_path)
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
            workboard_path, text, new_text
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
    apply: bool,
) -> tuple[bool, dict[str, object]]:
    violations, stale_claims, tasks_by_agent = _stale_claims(
        workboard_path=workboard_path,
        now=now,
        max_idle_minutes=max_idle_minutes,
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
            elif "no active claim found" not in _norm(msg_release):
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
