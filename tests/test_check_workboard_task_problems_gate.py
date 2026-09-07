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


def test_git_ignored_absent_record_still_counts_as_a_mapping(monkeypatch, tmp_path: Path) -> None:
    """The CI shape: the record is mapped in the workboard, git-ignored, and absent on disk.

    .gitignore excludes plans/thomas/problems/* after a 2026-05-19 incident, so a
    CI checkout never contains these files while a developer machine always does.
    Skipping the *violation* for an ignored path is correct. An earlier fix used
    `continue`, which also skipped registering the entry, so the task then
    reported as having no mapping at all -- the gate failed in CI on two tasks
    whose mappings were present in the workboard the whole time.
    """
    # deliberately NOT created on disk -- this is what a CI checkout looks like
    problem_rel = "plans/thomas/problems/models-lane/PROBLEM.md"
    assert not (tmp_path / problem_rel).exists()

    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=thomas/cli/main.py; task=[WIP] models lane",
        active_tasks_block=(
            "- task_id=models-lane; agent=Codex 1; scope=thomas/cli/main.py; summary=[WIP] models lane; status=active"
        ),
        problems_block=(
            f"- task_id=models-lane; problem={problem_rel}; owner=Codex 1; "
            "status=in_progress; updated_at=2026-02-27T12:00:00+00:00; summary=[WIP] models lane"
        ),
    )

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "_path_is_git_ignored", lambda path: True)
    violations = mod.evaluate(workboard)

    assert not any("missing task problem mapping" in item for item in violations), violations
    assert not any("problem file missing" in item for item in violations), violations


def test_absent_record_that_is_NOT_ignored_still_reports_missing(monkeypatch, tmp_path: Path) -> None:
    """The skip must be narrow: a genuinely missing, trackable record still fails."""
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
    monkeypatch.setattr(mod, "_path_is_git_ignored", lambda path: False)
    violations = mod.evaluate(workboard)

    assert any("problem file missing" in item for item in violations), violations


def test_another_agents_missing_mapping_is_a_warning_for_the_committer_not_a_block(monkeypatch, tmp_path: Path) -> None:
    """A commit used to be blocked by mappings of tasks that were not the committer's."""
    problem_path = tmp_path / "plans" / "thomas" / "problems" / "mine" / "PROBLEM.md"
    problem_path.parent.mkdir(parents=True, exist_ok=True)
    problem_path.write_text(
        "# Task Problem Record: mine" + chr(10) + chr(10) + "task_id: `mine`" + chr(10), encoding="utf-8"
    )

    workboard = _write_workboard(
        tmp_path,
        claims_block=(
            "- agent=claude; scope=thomas/a.py; task=[WIP] mine"
            + chr(10)
            + "- agent=codex; scope=thomas/b.py; task=[WIP] theirs"
        ),
        active_tasks_block=(
            "- task_id=mine; agent=claude; scope=thomas/a.py; summary=[WIP] mine; status=active"
            + chr(10)
            + "- task_id=theirs; agent=codex; scope=thomas/b.py; summary=[WIP] theirs; status=active"
        ),
        problems_block=(
            "- task_id=mine; problem=plans/thomas/problems/mine/PROBLEM.md; owner=claude; "
            "status=in_progress; updated_at=2026-02-27T12:00:00+00:00; summary=[WIP] mine"
        ),
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)

    # Nobody's perspective (CI): the missing mapping for `theirs` is a violation.
    assert any("theirs" in v for v in mod.evaluate(workboard))
    # The committer claude: their own tasks are clean, codex's gap is a warning.
    violations, warnings = mod.evaluate_scoped(workboard, agent="claude")
    assert violations == []
    assert any("theirs" in w for w in warnings)
    # The committer codex owns the gap: it blocks.
    violations, _warnings = mod.evaluate_scoped(workboard, agent="codex")
    assert any("theirs" in v for v in violations)
