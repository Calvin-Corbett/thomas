from __future__ import annotations

import json
from pathlib import Path

import scripts.forge.gates.workboard_task_problems as mod


def _write_workboard(
    tmp_path: Path,
    *,
    claims_block: str = "- none",
    active_tasks_block: str = "- none",
    up_for_grabs_block: str = "- none",
    problems_block: str = "- none",
) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            f"{active_tasks_block}\n\n"
            "## Issues / Blockers\n\n"
            "- none\n\n"
            "## Up For Grabs\n\n"
            f"{up_for_grabs_block}\n\n"
            "## Task Problems\n\n"
            f"{problems_block}\n\n"
            "## Supporting Docs (Not Plan Sources)\n\n"
            "- docs/PROJECT_SCOPE.md\n"
        ),
        encoding="utf-8",
    )
    return path


def test_evaluate_passes_with_task_problem_mapping(monkeypatch, tmp_path: Path) -> None:
    problem_path = tmp_path / "plans" / "thomas" / "problems" / "models-lane" / "PROBLEM.md"
    problem_path.parent.mkdir(parents=True, exist_ok=True)
    problem_path.write_text("# Task Problem Record: models-lane\n\ntask_id: `models-lane`\n", encoding="utf-8")

    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=thomas/cli/main.py; task=[WIP] models lane",
        active_tasks_block=(
            "- task_id=models-lane; agent=Codex 1; scope=thomas/cli/main.py; summary=[WIP] models lane; status=active"
        ),
        problems_block=(
            "- task_id=models-lane; problem=plans/thomas/problems/models-lane/PROBLEM.md; owner=Codex 1; "
            "status=in_progress; updated_at=2026-02-27T12:00:00+00:00; summary=[WIP] models lane"
        ),
    )

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    violations = mod.evaluate(workboard)
    assert violations == []


def test_evaluate_fails_when_tracked_task_missing_problem_mapping(monkeypatch, tmp_path: Path) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=thomas/cli/main.py; task=[WIP] models lane",
        active_tasks_block=(
            "- task_id=models-lane; agent=Codex 1; scope=thomas/cli/main.py; summary=[WIP] models lane; status=active"
        ),
        problems_block="- none",
    )

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    violations = mod.evaluate(workboard)
    assert any("missing task problem mapping for `models-lane`" in item for item in violations)


def test_run_json_fail_payload_for_missing_workboard(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing.md"
    rc = mod.run(["--workboard", str(missing), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"] == "workboard_task_problems"
