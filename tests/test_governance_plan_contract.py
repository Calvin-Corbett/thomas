from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from scripts.crew.tasks import plans
from scripts.forge.gates import workboard_task_plans as gate


def _plan_text(*, owner: str = "worker", status: str = "in_progress", scope: str = "src/a.py") -> str:
    return (
        "# PLAN for TASK-1\n\n"
        f"- Owner: {owner}\n"
        f"- Status: {status}\n"
        "- Updated At: 2026-09-03T00:00:00+00:00\n"
        f"- Scope: {scope}\n\n"
        "## Summary\n\nHuman-authored body.\n\n"
        "## Approach\n\n- Keep this exact.\n"
    )


def _board(path: Path, *, plan_path: str = "plans/tasks/TASK-1/PLAN.md", extra_plan: str = "") -> Path:
    path.write_text(
        "# Thomas Workboard\n\n"
        "## Agent Claims (Active)\n\n"
        "- agent=worker; name=Worker; role=solo; parent=none; scope=src/a.py; task=TASK-1\n\n"
        "## Active Tasks\n\n"
        "- task_id=TASK-1; agent=worker; scope=src/a.py; summary=work; status=active\n\n"
        "## Issues / Blockers\n\n- none\n\n"
        "## Up For Grabs\n\n- none\n\n"
        "## Task Plans\n\n"
        f"- task_id=TASK-1; plan={plan_path}; owner=worker; status=in_progress; updated_at=now; summary=work\n"
        f"{extra_plan}"
        "\n## Task Problems\n\n"
        "- task_id=TASK-1; problem=plans/problems/TASK-1/PROBLEM.md; owner=worker; "
        "status=in_progress; updated_at=now; summary=work\n",
        encoding="utf-8",
    )
    return path


def test_sync_repairs_reordered_stale_header_without_rewriting_body(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(plans, "ROOT", tmp_path)
    plan = tmp_path / "plans" / "tasks" / "TASK-1" / "PLAN.md"
    plan.parent.mkdir(parents=True)
    body = "## Summary\n\nHuman-authored body.\n\n## Approach\n\n- Keep this exact.\n"
    plan.write_text(
        "# PLAN for TASK-1\n\n- Scope: stale.py\n- Owner: old\n- Status: blocked\n- Updated At: old\n\n" + body,
        encoding="utf-8",
    )
    problem = tmp_path / "plans" / "problems" / "TASK-1" / "PROBLEM.md"
    problem.parent.mkdir(parents=True)
    problem.write_text("# PROBLEM\n\ntask_id: `TASK-1`\n", encoding="utf-8")
    board = _board(tmp_path / "WORKBOARD.md")

    ok, result = plans._sync_task_plans(
        workboard_path=board,
        plan_root="plans/tasks",
        problem_root="plans/problems",
        require_claims_to_have_active_task=True,
        apply=True,
        now=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )

    assert ok is True, result
    updated = plan.read_text(encoding="utf-8")
    assert updated.splitlines()[2:6] == [
        "- Owner: worker",
        "- Status: in_progress",
        "- Updated At: 2026-09-03T00:00:00+00:00",
        "- Scope: src/a.py",
    ]
    assert updated[updated.index("## Summary") :] == body
    assert result["reconciled_plans"] == ["plans/tasks/TASK-1/PLAN.md"]


def test_targeted_sync_reconciles_only_requested_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(plans, "ROOT", tmp_path)
    plan_one = tmp_path / "plans" / "tasks" / "TASK-1" / "PLAN.md"
    plan_two = tmp_path / "plans" / "tasks" / "TASK-2" / "PLAN.md"
    problem_one = tmp_path / "plans" / "problems" / "TASK-1" / "PROBLEM.md"
    problem_two = tmp_path / "plans" / "problems" / "TASK-2" / "PROBLEM.md"
    for path in (plan_one, plan_two, problem_one, problem_two):
        path.parent.mkdir(parents=True, exist_ok=True)
    plan_one.write_text(_plan_text(scope="stale.py"), encoding="utf-8")
    plan_two.write_text(_plan_text(owner="other", scope="src/b.py").replace("TASK-1", "TASK-2"), encoding="utf-8")
    problem_one.write_text("# PROBLEM\n\ntask_id: `TASK-1`\n", encoding="utf-8")
    problem_two.write_text("# PROBLEM\n\ntask_id: `TASK-2`\n", encoding="utf-8")
    board = _board(tmp_path / "WORKBOARD.md")
    board.write_text(
        board.read_text(encoding="utf-8")
        .replace(
            "- agent=worker; name=Worker; role=solo; parent=none; scope=src/a.py; task=TASK-1",
            "- agent=worker; name=Worker; role=solo; parent=none; scope=src/a.py; task=TASK-1\n"
            "- agent=other; name=Other; role=solo; parent=none; scope=src/b.py; task=TASK-2",
        )
        .replace(
            "- task_id=TASK-1; agent=worker; scope=src/a.py; summary=work; status=active",
            "- task_id=TASK-1; agent=worker; scope=src/a.py; summary=work; status=active\n"
            "- task_id=TASK-2; agent=other; scope=src/b.py; summary=other work; status=active",
        )
        .replace(
            "\n\n## Task Problems",
            "\n- task_id=TASK-2; plan=plans/tasks/TASK-2/PLAN.md; owner=other; status=in_progress; "
            "updated_at=old; summary=other work\n\n## Task Problems",
        )
        .replace(
            "- task_id=TASK-1; problem=plans/problems/TASK-1/PROBLEM.md; owner=worker; "
            "status=in_progress; updated_at=now; summary=work",
            "- task_id=TASK-1; problem=plans/problems/TASK-1/PROBLEM.md; owner=worker; "
            "status=in_progress; updated_at=now; summary=work\n"
            "- task_id=TASK-2; problem=plans/problems/TASK-2/PROBLEM.md; owner=other; "
            "status=in_progress; updated_at=old; summary=other work",
        ),
        encoding="utf-8",
    )
    plan_two_before = plan_two.read_bytes()
    problem_two_before = problem_two.read_bytes()
    unrelated_rows_before = [line for line in board.read_text(encoding="utf-8").splitlines() if "TASK-2" in line]

    ok, result = plans._sync_task_plans(
        workboard_path=board,
        plan_root="plans/tasks",
        problem_root="plans/problems",
        require_claims_to_have_active_task=True,
        apply=True,
        now=datetime(2026, 9, 3, tzinfo=timezone.utc),
        task_id="TASK-1",
    )

    assert ok is True, result
    assert plan_two.read_bytes() == plan_two_before
    assert problem_two.read_bytes() == problem_two_before
    assert [
        line for line in board.read_text(encoding="utf-8").splitlines() if "TASK-2" in line
    ] == unrelated_rows_before
    assert result["target_task_id"] == "TASK-1"


def test_targeted_sync_has_a_dedicated_cli_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(plans, "ROOT", tmp_path)
    plan = tmp_path / "plans" / "tasks" / "TASK-1" / "PLAN.md"
    problem = tmp_path / "plans" / "problems" / "TASK-1" / "PROBLEM.md"
    plan.parent.mkdir(parents=True)
    problem.parent.mkdir(parents=True)
    plan.write_text(_plan_text(scope="stale.py"), encoding="utf-8")
    problem.write_text("# PROBLEM\n\ntask_id: `TASK-1`\n", encoding="utf-8")
    board = _board(tmp_path / "WORKBOARD.md")

    rc = plans.run(
        [
            "--workboard",
            str(board),
            "--task-id",
            "TASK-1",
            "--plan-root",
            "plans/tasks",
            "--problem-root",
            "plans/problems",
            "--now",
            "2026-09-03T00:00:00+00:00",
            "--apply",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["target_task_id"] == "TASK-1"


@pytest.mark.parametrize(
    ("plan_text", "needle"),
    [
        ("", "missing PLAN"),
        (_plan_text(owner="other"), "PLAN owner differs"),
        (_plan_text(status="blocked"), "PLAN status differs"),
        (_plan_text(scope="src/b.py"), "PLAN scope differs"),
        (
            "# PLAN for TASK-1\n\n- Scope: src/a.py\n- Owner: worker\n- Status: in_progress\n"
            "- Updated At: now\n\n## Summary\n\nbody\n",
            "not in canonical order",
        ),
    ],
)
def test_gate_rejects_missing_stale_status_scope_and_reordered_metadata(
    tmp_path: Path, monkeypatch, plan_text: str, needle: str
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    board = _board(tmp_path / "WORKBOARD.md")
    if plan_text:
        plan = tmp_path / "plans" / "tasks" / "TASK-1" / "PLAN.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(plan_text, encoding="utf-8")
    violations = gate.evaluate(board)
    assert any(needle in item for item in violations), violations


def test_gate_rejects_stale_task_plans_row(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    plan = tmp_path / "plans" / "tasks" / "TASK-1" / "PLAN.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(_plan_text(), encoding="utf-8")
    board = _board(
        tmp_path / "WORKBOARD.md",
        extra_plan=(
            "- task_id=OLD; plan=plans/tasks/OLD/PLAN.md; owner=old; status=in_progress; "
            "updated_at=now; summary=stale\n"
        ),
    )
    assert any("stale Task Plans row" in item for item in gate.evaluate(board))


@pytest.mark.parametrize(
    ("plan_text", "needle"),
    [
        ("", "missing PLAN"),
        (_plan_text(owner="unassigned", status="up_for_grabs", scope="src/q.py"), "heading is not canonical"),
        (_plan_text(owner="worker", status="up_for_grabs", scope="src/q.py"), "PLAN owner differs"),
        (_plan_text(owner="unassigned", status="queued", scope="src/q.py"), "PLAN status differs"),
        (_plan_text(owner="unassigned", status="up_for_grabs", scope="src/stale.py"), "PLAN scope differs"),
    ],
)
def test_gate_fully_validates_queued_plan_artifact(tmp_path: Path, monkeypatch, plan_text: str, needle: str) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    board = _board(tmp_path / "WORKBOARD.md", plan_path="plans/tasks/QUEUE-1/PLAN.md")
    board.write_text(
        board.read_text(encoding="utf-8")
        .replace(
            "- agent=worker; name=Worker; role=solo; parent=none; scope=src/a.py; task=TASK-1",
            "- none",
        )
        .replace(
            "- task_id=TASK-1; agent=worker; scope=src/a.py; summary=work; status=active",
            "- none",
        )
        .replace(
            "## Up For Grabs\n\n- none",
            "## Up For Grabs\n\n- task_id=QUEUE-1; scope=src/q.py; summary=queued work; reported_by=worker",
        )
        .replace("task_id=TASK-1", "task_id=QUEUE-1")
        .replace("owner=worker; status=in_progress", "owner=unassigned; status=up_for_grabs"),
        encoding="utf-8",
    )
    if plan_text:
        plan = tmp_path / "plans" / "tasks" / "QUEUE-1" / "PLAN.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(plan_text, encoding="utf-8")
    violations = gate.evaluate(board)
    assert any(needle in item for item in violations), violations


def test_staged_gate_rejects_untracked_queued_plan(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    board = _board(tmp_path / "WORKBOARD.md", plan_path="plans/tasks/QUEUE-1/PLAN.md")
    board.write_text(
        board.read_text(encoding="utf-8")
        .replace(
            "- agent=worker; name=Worker; role=solo; parent=none; scope=src/a.py; task=TASK-1",
            "- none",
        )
        .replace(
            "- task_id=TASK-1; agent=worker; scope=src/a.py; summary=work; status=active",
            "- none",
        )
        .replace(
            "## Up For Grabs\n\n- none",
            "## Up For Grabs\n\n- task_id=QUEUE-1; scope=src/q.py; summary=queued work; reported_by=worker",
        )
        .replace("task_id=TASK-1", "task_id=QUEUE-1")
        .replace("owner=worker; status=in_progress", "owner=unassigned; status=up_for_grabs"),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "WORKBOARD.md"], cwd=tmp_path, check=True)
    plan = tmp_path / "plans" / "tasks" / "QUEUE-1" / "PLAN.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        _plan_text(owner="unassigned", status="up_for_grabs", scope="src/q.py").replace("TASK-1", "QUEUE-1"),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    violations = gate.evaluate(board, staged=True)
    assert any("PLAN is not tracked" in item for item in violations), violations


def _init_staged_repo(tmp_path: Path, *, update_plan: bool) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Thomas Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    plan = tmp_path / "plans" / "tasks" / "TASK-1" / "PLAN.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(_plan_text(), encoding="utf-8")
    board = _board(tmp_path / "WORKBOARD.md")
    source = tmp_path / "src" / "a.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    if update_plan:
        plan.write_text(_plan_text().replace("00:00:00", "00:01:00"), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return board


def test_staged_gate_requires_committing_agents_updated_plan(tmp_path: Path, monkeypatch) -> None:
    board = _init_staged_repo(tmp_path, update_plan=False)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    violations = gate.evaluate(board, staged=True, agent="worker")
    assert any("must include an updated tracked PLAN" in item for item in violations), violations


def test_staged_gate_passes_when_exact_updated_plan_is_included(tmp_path: Path, monkeypatch) -> None:
    board = _init_staged_repo(tmp_path, update_plan=True)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    assert gate.evaluate(board, staged=True, agent="worker") == []


def test_staged_gate_rejects_untracked_plan(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    board = _board(tmp_path / "WORKBOARD.md")
    subprocess.run(["git", "add", "WORKBOARD.md"], cwd=tmp_path, check=True)
    plan = tmp_path / "plans" / "tasks" / "TASK-1" / "PLAN.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(_plan_text(), encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    violations = gate.evaluate(board, staged=True, agent="worker")
    assert any("PLAN is not tracked" in item for item in violations), violations


def test_git_subprocess_decodes_staged_content_as_utf8(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, **kwargs):
        calls.append(dict(kwargs))
        return subprocess.CompletedProcess(command, 0, "legacy \x9d smart quote\n", "")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    assert gate._git("show", ":plans/thomas/WORKBOARD.md").returncode == 0
    assert calls == [
        {
            "cwd": gate.ROOT,
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "check": False,
        }
    ]
