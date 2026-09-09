"""Task plan and problem record synchronization module.

Ensures durable PLAN.md and PROBLEM.md files exist for all active tasks.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.workboard import issue as workboard_issue
    from scripts.forge.gates import workboard_claims as claims_gate
except ImportError:  # pragma: no cover
    from forge.gates import workboard_claims as claims_gate  # type: ignore

    from scripts.crew.workboard import issue as workboard_issue  # type: ignore

try:
    from scripts.crew.tasks import plan_metadata
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
    from scripts.crew.tasks.plan_metadata import PlanMetadata, normalize_status, reconcile_metadata
except ImportError:  # pragma: no cover
    from crew.tasks import plan_metadata  # type: ignore
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
    from crew.tasks.plan_metadata import PlanMetadata, normalize_status, reconcile_metadata  # type: ignore


def _default_plan_path(task_id: str, plan_root: str) -> str:
    return plan_metadata.default_artifact_path(task_id, plan_root, "PLAN.md", repo_root=ROOT)


def _default_problem_path(task_id: str, problem_root: str) -> str:
    return plan_metadata.default_artifact_path(task_id, problem_root, "PROBLEM.md", repo_root=ROOT)


def _build_problem_template(*, task_id: str, owner: str, summary: str, scope: str, status: str, now_iso: str) -> str:
    return plan_metadata.build_problem_template(
        task_id=task_id, owner=owner, summary=summary, scope=scope, status=status, now_iso=now_iso
    )


def _normalize_artifact_path(path: str) -> str:
    return plan_metadata.normalize_artifact_path(path, repo_root=ROOT)


def _ensure_problem_marker(path: Path, *, task_id: str) -> None:
    plan_metadata.ensure_problem_marker(path, task_id=task_id)


_upsert_target_entry = partial(
    plan_metadata.upsert_target_entry,
    find_section=_find_section,
    bullet_indices=_bullet_indices,
    parse_entry=_parse_kv_entry,
    norm=_norm,
    none_tokens=claims_gate.NONE_TOKENS,
)


def _sync_task_plans(
    *,
    workboard_path: Path,
    plan_root: str,
    problem_root: str,
    require_claims_to_have_active_task: bool,
    apply: bool,
    now: datetime,
    task_id: str = "",
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

    all_task_ids = sorted(owner_by_task.keys(), key=str.lower)
    target_key = _norm(task_id)
    if target_key:
        selected = [candidate for candidate in all_task_ids if _norm(candidate) == target_key]
        if len(selected) != 1:
            return False, {"error": f"target task `{task_id}` is not active or up for grabs"}
        tracked_task_ids = selected
    else:
        tracked_task_ids = all_task_ids

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
    reconciled_plans: list[str] = []
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
        plan_status = normalize_status(status)

        plan_abs = (ROOT / plan_path).resolve()
        if not plan_abs.exists():
            missing_plans.append(plan_path)
            if apply:
                plan_abs.parent.mkdir(parents=True, exist_ok=True)
                plan_abs.write_text(
                    plan_metadata.build_plan_template(
                        task_id=task_id,
                        owner=owner,
                        summary=summary,
                        scope=scope,
                        status=plan_status,
                        now_iso=now_iso,
                    ),
                    encoding="utf-8",
                )
                created_plans.append(plan_path)
        elif apply:
            original_plan = plan_abs.read_text(encoding="utf-8")
            reconciled = reconcile_metadata(
                original_plan,
                PlanMetadata(owner=owner, status=plan_status, updated_at=now_iso, scope=scope),
            )
            if reconciled != original_plan:
                plan_abs.write_text(reconciled, encoding="utf-8")
                reconciled_plans.append(plan_path)
        updated_plan_entries.append(
            f"- task_id={_sanitize('task_id', task_id)}; plan={_sanitize('plan', plan_path)}; "
            f"owner={_sanitize('owner', owner)}; status={_sanitize('status', plan_status)}; "
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
        if target_key:
            plan_ok, plan_message = _upsert_target_entry(
                lines,
                heading=TASK_PLANS_HEADING,
                task_id=tracked_task_ids[0],
                rendered=updated_plan_entries[0],
            )
            if not plan_ok:
                return False, {"error": plan_message}
            problem_ok, problem_message = _upsert_target_entry(
                lines,
                heading=TASK_PROBLEMS_HEADING,
                task_id=tracked_task_ids[0],
                rendered=updated_problem_entries[0],
            )
            if not problem_ok:
                return False, {"error": problem_message}
        else:
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
        "total_task_count": len(all_task_ids),
        "target_task_id": tracked_task_ids[0] if target_key else "",
        "plan_entry_count": len(updated_plan_entries),
        "created_plan_count": len(created_plans),
        "created_plans": created_plans,
        "reconciled_plan_count": len(reconciled_plans),
        "reconciled_plans": reconciled_plans,
        "missing_plan_count": len(missing_plans),
        "missing_plans": missing_plans,
        "problem_entry_count": len(updated_problem_entries),
        "created_problem_count": len(created_problems),
        "created_problems": created_problems,
        "missing_problem_count": len(missing_problems),
        "missing_problems": missing_problems,
        "applied": bool(apply),
    }


def run(argv: list[str] | None = None) -> int:
    return plan_metadata.run_targeted_sync(argv, core=sys.modules[__name__])


if __name__ == "__main__":
    raise SystemExit(run())
