"""Task plan and problem record synchronization module.

Ensures durable PLAN.md and PROBLEM.md files exist for all active tasks.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts import workboard_issue
    from scripts.forge.gates import workboard_claims as claims_gate
except ImportError:  # pragma: no cover
    import workboard_issue  # type: ignore
    from forge.gates import workboard_claims as claims_gate  # type: ignore

try:
    from scripts.crew.tasks.base import (
        ROOT,
        TASK_PLANS_HEADING,
        TASK_PROBLEMS_HEADING,
        _bullet_indices,
        _ensure_section,
        _find_section,
        _norm,
        _parse_kv_entry,
        _sanitize,
        _strip_blocked_task_violations,
        _write_section_entries,
    )
except ImportError:  # pragma: no cover
    from crew.tasks.base import (
        ROOT,
        TASK_PLANS_HEADING,
        TASK_PROBLEMS_HEADING,
        _bullet_indices,
        _ensure_section,
        _find_section,
        _norm,
        _parse_kv_entry,
        _sanitize,
        _strip_blocked_task_violations,
        _write_section_entries,
    )


def _artifact_root_path(root: str) -> Path:
    base = Path(str(root or "").strip() or ".").expanduser()
    return base if base.is_absolute() else (ROOT / base).resolve()


def _repo_relative_or_absolute(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _default_plan_path(task_id: str, plan_root: str) -> str:
    return _repo_relative_or_absolute(_artifact_root_path(plan_root) / str(task_id).strip() / "PLAN.md")


def _default_problem_path(task_id: str, problem_root: str) -> str:
    return _repo_relative_or_absolute(_artifact_root_path(problem_root) / str(task_id).strip() / "PROBLEM.md")


def _build_plan_template(*, task_id: str, owner: str, summary: str, scope: str, status: str, now_iso: str) -> str:
    return (
        f"# PLAN for {task_id}\n\n"
        f"- Owner: {owner}\n"
        f"- Status: {status}\n"
        f"- Updated At: {now_iso}\n"
        f"- Scope: {scope}\n\n"
        f"## Summary\n\n{summary}\n\n"
        "## Approach\n\n- Document the intended implementation steps here.\n"
    )


def _build_problem_template(*, task_id: str, owner: str, summary: str, scope: str, status: str, now_iso: str) -> str:
    return (
        f"# PROBLEM for {task_id}\n\n"
        f"task_id: `{task_id}`\n\n"
        f"- Owner: {owner}\n"
        f"- Status: {status}\n"
        f"- Updated At: {now_iso}\n"
        f"- Scope: {scope}\n\n"
        f"## Current Problem\n\n{summary}\n\n"
        "## Blocking Details\n\n- Capture blockers, failures, and observations here.\n"
    )


def _normalize_artifact_path(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return _repo_relative_or_absolute(candidate)
    return raw.replace("\\", "/")


def _ensure_problem_marker(path: Path, *, task_id: str) -> None:
    marker = f"task_id: `{task_id}`"
    body = path.read_text(encoding="utf-8")
    if marker in body:
        return
    lines = body.splitlines()
    if lines:
        updated = [lines[0], "", marker, "", *lines[1:]]
    else:
        updated = [marker]
    path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")


def _sync_task_plans(
    *,
    workboard_path: Path,
    plan_root: str,
    problem_root: str,
    require_claims_to_have_active_task: bool,
    apply: bool,
    now: datetime,
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
        plan_path = _normalize_artifact_path(str(plan_row.get("plan", "")).strip()) or _default_plan_path(
            task_id, plan_root
        )
        problem_path = _normalize_artifact_path(str(problem_row.get("problem", "")).strip()) or _default_problem_path(
            task_id, problem_root
        )
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
        elif apply:
            _ensure_problem_marker(problem_abs, task_id=task_id)
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
            workboard_path,
            text,
            new_text,
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
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
