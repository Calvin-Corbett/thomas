"""A plan sync rewrites only the plans whose metadata actually changed.

``_sync_task_plans`` stamped ``Updated At: <now>`` into every tracked plan and
only then compared the result with the file. Once the clock had moved past the
old stamp the two could never be equal, so every untargeted sync rewrote every
task's PLAN.md. One ``manager.py --sync-plans --apply`` on 2026-09-10 left 24
other tasks' plans modified in the shared checkout, each differing by that one
line and nothing else.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.crew.tasks import plans

OLD_STAMP = "2026-09-03T00:00:00+00:00"
LATER = datetime(2026, 9, 10, 12, 55, 7, tzinfo=timezone.utc)


def _plan(task_id: str, *, owner: str, scope: str) -> str:
    return (
        f"# PLAN for {task_id}\n\n"
        f"- Owner: {owner}\n"
        "- Status: in_progress\n"
        f"- Updated At: {OLD_STAMP}\n"
        f"- Scope: {scope}\n\n"
        "## Summary\n\nHuman-authored body.\n"
    )


def _write_plan(root: Path, task_id: str, text: str) -> Path:
    plan = root / "plans" / "tasks" / task_id / "PLAN.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(text, encoding="utf-8")
    return plan


def _board(root: Path) -> Path:
    board = root / "WORKBOARD.md"
    board.write_text(
        "# Thomas Workboard\n\n"
        "## Agent Claims (Active)\n\n"
        "- agent=worker; name=Worker; role=solo; parent=none; scope=src/a.py; task=TASK-1\n"
        "- agent=other; name=Other; role=solo; parent=none; scope=src/b.py; task=TASK-2\n\n"
        "## Active Tasks\n\n"
        "- task_id=TASK-1; agent=worker; scope=src/a.py; summary=work; status=active\n"
        "- task_id=TASK-2; agent=other; scope=src/b.py; summary=other work; status=active\n\n"
        "## Issues / Blockers\n\n- none\n\n"
        "## Up For Grabs\n\n- none\n",
        encoding="utf-8",
    )
    for task_id in ("TASK-1", "TASK-2"):
        problem = root / "plans" / "problems" / task_id / "PROBLEM.md"
        problem.parent.mkdir(parents=True, exist_ok=True)
        problem.write_text(f"# PROBLEM\n\ntask_id: `{task_id}`\n", encoding="utf-8")
    return board


def _sync(board: Path, *, now: datetime = LATER) -> dict[str, object]:
    ok, result = plans._sync_task_plans(
        workboard_path=board,
        plan_root="plans/tasks",
        problem_root="plans/problems",
        require_claims_to_have_active_task=True,
        apply=True,
        now=now,
    )
    assert ok is True, result
    return result


def _task_plans_rows(board: Path) -> list[str]:
    # Rows only: the blank lines around them are laid out once, when the sync
    # first creates the section, and that is not the churn under test.
    lines = board.read_text(encoding="utf-8").splitlines()
    start = lines.index("## Task Plans")
    end = next((idx for idx in range(start + 1, len(lines)) if lines[idx].startswith("## ")), len(lines))
    return [line for line in lines[start + 1 : end] if line.startswith("- task_id=")]


def test_a_sync_does_not_restamp_plans_whose_metadata_already_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(plans, "ROOT", tmp_path)
    board = _board(tmp_path)
    mine = _write_plan(tmp_path, "TASK-1", _plan("TASK-1", owner="worker", scope="src/a.py"))
    theirs = _write_plan(tmp_path, "TASK-2", _plan("TASK-2", owner="other", scope="src/b.py"))
    before = (mine.read_bytes(), theirs.read_bytes())

    result = _sync(board)

    assert (mine.read_bytes(), theirs.read_bytes()) == before
    assert result["reconciled_plans"] == []


def test_an_untargeted_sync_writes_only_the_plan_that_changed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(plans, "ROOT", tmp_path)
    board = _board(tmp_path)
    stale = _write_plan(tmp_path, "TASK-1", _plan("TASK-1", owner="worker", scope="stale.py"))
    current = _write_plan(tmp_path, "TASK-2", _plan("TASK-2", owner="other", scope="src/b.py"))
    current_before = current.read_bytes()

    result = _sync(board)

    assert current.read_bytes() == current_before
    assert result["reconciled_plans"] == ["plans/tasks/TASK-1/PLAN.md"]
    rewritten = stale.read_text(encoding="utf-8")
    assert "- Scope: src/a.py" in rewritten
    assert f"- Updated At: {LATER.isoformat()}" in rewritten


def test_a_later_sync_leaves_the_task_plans_rows_as_they_were(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(plans, "ROOT", tmp_path)
    board = _board(tmp_path)
    _write_plan(tmp_path, "TASK-1", _plan("TASK-1", owner="worker", scope="src/a.py"))
    _write_plan(tmp_path, "TASK-2", _plan("TASK-2", owner="other", scope="src/b.py"))

    _sync(board)
    rows_after_first = _task_plans_rows(board)
    _sync(board, now=LATER + timedelta(hours=1))

    assert len(rows_after_first) == 2
    assert _task_plans_rows(board) == rows_after_first
