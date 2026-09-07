"""The plans gate blocks a commit only on the committer's own task (2026-09-05).

The problems gate learned this on 2026-09-05 (9510a13e); the plans gate still
failed every commit on stale plans of tasks other agents left on the board:
34 complaints, none about the committer's task, and no commit could land.
"""

from __future__ import annotations

from pathlib import Path

from scripts.forge.gates import workboard_task_plans as gate


def _plan(task_id: str, *, owner: str, scope: str) -> str:
    return (
        f"# PLAN for {task_id}\n\n"
        f"- Owner: {owner}\n"
        "- Status: in_progress\n"
        "- Updated At: 2026-09-05T00:00:00+00:00\n"
        f"- Scope: {scope}\n\n"
        "## Summary\n\nbody\n\n## Approach\n\n- keep\n"
    )


def _board_with_two_tasks(root: Path) -> Path:
    board = root / "WORKBOARD.md"
    board.write_text(
        "# Thomas Workboard\n\n"
        "## Agent Claims (Active)\n\n"
        "- agent=worker; name=Worker; role=solo; parent=none; scope=src/a.py; task=TASK-1\n"
        "- agent=other; name=Other; role=solo; parent=none; scope=src/b.py; task=TASK-2\n\n"
        "## Active Tasks\n\n"
        "- task_id=TASK-1; agent=worker; scope=src/a.py; summary=mine; status=active\n"
        "- task_id=TASK-2; agent=other; scope=src/b.py; summary=theirs; status=active\n\n"
        "## Issues / Blockers\n\n- none\n\n"
        "## Up For Grabs\n\n- none\n\n"
        "## Task Plans\n\n"
        "- task_id=TASK-1; plan=plans/tasks/TASK-1/PLAN.md; owner=worker; status=in_progress; updated_at=now; summary=mine\n"
        "- task_id=TASK-2; plan=plans/tasks/TASK-2/PLAN.md; owner=other; status=in_progress; updated_at=now; summary=theirs\n"
        "- task_id=GONE; plan=plans/tasks/GONE/PLAN.md; owner=old; status=in_progress; updated_at=now; summary=stale\n"
        "\n## Task Problems\n\n"
        "- task_id=TASK-1; problem=plans/problems/TASK-1/PROBLEM.md; owner=worker; status=in_progress; updated_at=now; summary=mine\n"
        "- task_id=TASK-2; problem=plans/problems/TASK-2/PROBLEM.md; owner=other; status=in_progress; updated_at=now; summary=theirs\n",
        encoding="utf-8",
    )
    for task_id, owner, scope in (("TASK-1", "worker", "src/a.py"), ("TASK-2", "WRONG-OWNER", "src/b.py")):
        plan = root / "plans" / "tasks" / task_id / "PLAN.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(_plan(task_id, owner=owner, scope=scope), encoding="utf-8")
    return board


def test_another_agents_broken_plan_is_a_warning_for_the_committer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    board = _board_with_two_tasks(tmp_path)

    violations, warnings = gate.evaluate_scoped(board, agent="worker")
    assert violations == []
    assert any("TASK-2" in w and "PLAN owner differs" in w for w in warnings), warnings
    assert any("stale Task Plans row" in w for w in warnings), warnings


def test_the_owner_of_the_broken_plan_is_still_blocked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    board = _board_with_two_tasks(tmp_path)

    violations, _warnings = gate.evaluate_scoped(board, agent="other")
    assert any("TASK-2" in v and "PLAN owner differs" in v for v in violations), violations


def test_without_an_agent_everything_still_blocks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    board = _board_with_two_tasks(tmp_path)

    violations = gate.evaluate(board)
    assert any("TASK-2" in v for v in violations)
    assert any("stale Task Plans row" in v for v in violations)
    scoped_violations, scoped_warnings = gate.evaluate_scoped(board, agent="")
    assert scoped_violations == violations and scoped_warnings == []


def test_main_passes_with_warnings_only_and_prints_them(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    board = _board_with_two_tasks(tmp_path)

    code = gate.main(["--workboard", str(board), "--agent", "worker"])
    out = capsys.readouterr().out
    assert code == 0
    assert "PASS" in out
    assert "warning" in out.lower() and "TASK-2" in out


def _staged_repo(tmp_path: Path, *, changed_file: str) -> Path:
    """A repo whose HEAD board assigns TASK-1 (scope src/a.py) to worker, with one file changed and staged."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Thomas Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    plan = tmp_path / "plans" / "tasks" / "TASK-1" / "PLAN.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(_plan("TASK-1", owner="worker", scope="src/a.py"), encoding="utf-8")
    board = tmp_path / "WORKBOARD.md"
    rows = [
        "# Thomas Workboard",
        "",
        "## Agent Claims (Active)",
        "",
        "- agent=worker; name=Worker; role=solo; parent=none; scope=src/a.py; task=TASK-1",
        "",
        "## Active Tasks",
        "",
        "- task_id=TASK-1; agent=worker; scope=src/a.py; summary=mine; status=active",
        "",
        "## Issues / Blockers",
        "",
        "- none",
        "",
        "## Up For Grabs",
        "",
        "- none",
        "",
        "## Task Plans",
        "",
        "- task_id=TASK-1; plan=plans/tasks/TASK-1/PLAN.md; owner=worker; status=in_progress; updated_at=now; summary=mine",
        "",
        "## Task Problems",
        "",
        "- task_id=TASK-1; problem=plans/problems/TASK-1/PROBLEM.md; owner=worker; status=in_progress; updated_at=now; summary=mine",
        "",
    ]
    board.write_text(chr(10).join(rows), encoding="utf-8")
    for rel in ("src/a.py", "docs/notes.md"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("v1" + chr(10), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    (tmp_path / changed_file).write_text("v2" + chr(10), encoding="utf-8")
    subprocess.run(["git", "add", changed_file], cwd=tmp_path, check=True)
    return board


def test_a_commit_outside_the_tasks_scope_needs_no_plan_update(tmp_path: Path, monkeypatch) -> None:
    """HEAD's board kept listing a finished task under the committer; every later
    commit, on unrelated files, was refused until that plan was touched again."""
    board = _staged_repo(tmp_path, changed_file="docs/notes.md")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    violations, _warnings = gate.evaluate_scoped(board, staged=True, agent="worker")
    assert violations == []


def test_a_commit_inside_the_tasks_scope_still_needs_the_plan_update(tmp_path: Path, monkeypatch) -> None:
    board = _staged_repo(tmp_path, changed_file="src/a.py")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    violations, _warnings = gate.evaluate_scoped(board, staged=True, agent="worker")
    assert any("must include an updated tracked PLAN" in v for v in violations), violations
