"""Releasing an agent's own task rows from the workboard.

Kept apart from ``claim_utils`` (already over the line limit): that module's ``_release_active_task`` serves the
takeover of another agent's claim and refuses more than one row; this one serves an agent releasing its own claim.
"""

from __future__ import annotations

try:
    from scripts.crew.workboard.claim_utils import (
        NONE_ENTRY,
        _agent_key,
        _bullet_indices,
        _find_active_tasks_section,
        _parse_active_task_line,
    )
except ImportError:  # pragma: no cover - run as a loose script, as claim_ops does
    from crew.workboard.claim_utils import (  # type: ignore
        NONE_ENTRY,
        _agent_key,
        _bullet_indices,
        _find_active_tasks_section,
        _parse_active_task_line,
    )


def _release_all_active_tasks(lines: list[str], *, agent: str) -> tuple[bool, str]:
    """Drop every Active Task row of ``agent``: what releasing that agent's own claim means.

    ``_release_active_task`` refuses when there are two rows, which is right when another agent's claim is taken
    over (it cannot tell which row goes with which scope) but wrong here: an agent that re-pointed its claim at a
    renamed task has two rows, could never release, and its rows then blocked every other agent's commits.
    """
    section = _find_active_tasks_section(lines)
    found: list[tuple[int, str]] = []
    for idx in _bullet_indices(lines, section[0], section[1]):
        entry, fields, err = _parse_active_task_line(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is None:
            continue
        entry_agent = str(fields.get("agent", "") or "")
        if entry_agent and _agent_key(entry_agent) != _agent_key(agent):
            continue
        found.append((idx, entry))
    if not found:
        return False, "no active tasks found"
    for idx, _task_id in reversed(found):
        del lines[idx]
    section = _find_active_tasks_section(lines)
    bullets = range(section[0], min(section[1], len(lines)))
    if not any(lines[bullet_idx].strip().startswith("-") for bullet_idx in bullets):
        lines.insert(section[0], NONE_ENTRY + "\n")
    return True, "released active task(s) " + ", ".join(f"`{task_id}`" for _, task_id in found)


def sync_plans_after_release(workboard_path) -> str:
    """Clear the plan and problem rows of the tasks just released, so the plan gate does not fail on them.

    Releasing a claim drops its Active Task rows but left the matching Task Plans and Task Problems rows, and the
    next commit by anyone failed on "stale Task Plans row for unknown task" until someone ran ``--sync-plans``. Only
    the real board is synced: a board in a test folder must not make plan folders in the repository.
    """
    from datetime import datetime, timezone

    try:
        from scripts.crew.tasks.base import DEFAULT_PLAN_ROOT, DEFAULT_PROBLEM_ROOT
        from scripts.crew.tasks.plans import _sync_task_plans
    except ImportError:  # pragma: no cover - run as a loose script, as claim_ops does
        from crew.tasks.base import DEFAULT_PLAN_ROOT, DEFAULT_PROBLEM_ROOT  # type: ignore
        from crew.tasks.plans import _sync_task_plans  # type: ignore
    ok, details = _sync_task_plans(
        workboard_path=workboard_path,
        plan_root=DEFAULT_PLAN_ROOT,
        problem_root=DEFAULT_PROBLEM_ROOT,
        require_claims_to_have_active_task=True,
        apply=True,
        now=datetime.now(timezone.utc),
    )
    return (
        "plan rows synced"
        if ok
        else f"plan rows not synced ({details.get('error') or details.get('violations') or 'see --sync-plans'})"
    )
