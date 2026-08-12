from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import scripts.crew.tasks.plans as plan_sync
import scripts.crew.workboard.problem_record as mod
import scripts.forge.gates.workboard_task_problems as task_problem_gate


def _write_workboard(tmp_path: Path, *, problems_block: str = "- none") -> Path:
    workboard = tmp_path / "plans" / "thomas" / "WORKBOARD.md"
    workboard.parent.mkdir(parents=True, exist_ok=True)
    workboard.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            "- agent=Codex Test; scope=thomas/cli/main.py; task=models-lane\n\n"
            "## Active Tasks\n\n"
            "- task_id=models-lane; agent=Codex Test; scope=thomas/cli/main.py; "
            "summary=models lane; status=active\n\n"
            "## Issues / Blockers\n\n"
            "- none\n\n"
            "## Up For Grabs\n\n"
            "- none\n\n"
            "## Task Problems\n\n"
            f"{problems_block}\n\n"
        ),
        encoding="utf-8",
    )
    return workboard


def test_help_prints_meaningful_usage(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        mod.run(["--help"])
    output = capsys.readouterr().out

    assert exc.value.code == 0
    assert "Record a failed automation step" in output
    assert "--runner" in output
    assert "--command" in output


def test_record_failure_creates_problem_artifact_and_workboard_mapping(monkeypatch, tmp_path: Path) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(plan_sync, "ROOT", tmp_path)
    monkeypatch.setattr(task_problem_gate, "ROOT", tmp_path)

    payload = mod.record_failure(
        runner="auto_checks",
        step="Surface parity gate",
        exit_code=7,
        command="python scripts/forge/gates/surface_parity.py",
        task_id="models-lane",
        agent="Codex Test",
        workboard=workboard,
        problem_root="plans/thomas/problems",
        now=datetime(2026, 6, 26, 15, 45, tzinfo=timezone.utc),
    )

    problem_path = tmp_path / "plans" / "thomas" / "problems" / "models-lane" / "PROBLEM.md"
    problem_body = problem_path.read_text(encoding="utf-8")
    workboard_body = workboard.read_text(encoding="utf-8")

    assert payload["ok"] is True
    assert payload["problem_path"] == "plans/thomas/problems/models-lane/PROBLEM.md"
    assert "task_id: `models-lane`" in problem_body
    assert "## Failure Records" in problem_body
    assert "- runner: `auto_checks`" in problem_body
    assert "- exit_code: `7`" in problem_body
    assert "task_id=models-lane; problem=plans/thomas/problems/models-lane/PROBLEM.md" in workboard_body
    assert task_problem_gate.evaluate(workboard) == []


def test_run_json_records_failure(monkeypatch, tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(plan_sync, "ROOT", tmp_path)

    rc = mod.run(
        [
            "--runner",
            "doc",
            "--step",
            "Model onboarding gate",
            "--exit-code",
            "2",
            "--command",
            "python scripts/forge/gates/model_onboarding_gate.py",
            "--task-id",
            "models-lane",
            "--agent",
            "Codex Test",
            "--workboard",
            str(workboard),
            "--problem-root",
            "plans/thomas/problems",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["task_id"] == "models-lane"
    assert payload["runner"] == "doc"
