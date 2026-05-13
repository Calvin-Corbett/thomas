from __future__ import annotations

import json
from pathlib import Path

import scripts.forge.gates.workboard_claims as gate
import scripts.workboard_audit_backstop as mod


def _write_workboard(
    tmp_path: Path,
    *,
    claims_block: str = "- none",
    active_tasks_block: str = "- none",
    issues_block: str = "- none",
    up_for_grabs_block: str = "- none",
) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            "Claim format:\n"
            "`- \\`agent=<id>; scope=<path[,path...]>; task=<short text>\\``\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; agent=<id>; scope=<path[,path...]>; summary=<short text>; status=<active|blocked>\\``\n\n"
            f"{active_tasks_block}\n\n"
            "## Issues / Blockers\n\n"
            "Issue format:\n"
            "`- \\`issue_id=<id>; task_id=<task_id>; reporter=<id>; owner=<id|unassigned>; state=<open|triaged|resolved>; summary=<short text>\\``\n\n"
            f"{issues_block}\n\n"
            "## Up For Grabs\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; scope=<path[,path...]>; summary=<short text>; reported_by=<id>\\``\n\n"
            f"{up_for_grabs_block}\n"
        ),
        encoding="utf-8",
    )
    return path


def test_backstop_check_fails_when_missing(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(["--workboard", str(workboard), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "missing recurring workboard audit backstop task" in payload["violations"][0]


def test_backstop_check_alias_compatibility(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(["--workboard", str(workboard), "--check", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "missing recurring workboard audit backstop task" in payload["violations"][0]


def test_backstop_apply_adds_canonical_task(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(["--workboard", str(workboard), "--apply", "--json"])
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["applied"] is True
    assert mod.BACKSTOP_TASK_ID in text
    assert gate.evaluate(workboard) == []


def test_backstop_check_fails_when_not_last_up_for_grabs_entry(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        up_for_grabs_block="\n".join(
            [
                f"- task_id={mod.BACKSTOP_TASK_ID}; scope={mod.BACKSTOP_SCOPE}; summary={mod.BACKSTOP_SUMMARY}; reported_by={mod.BACKSTOP_REPORTED_BY}",
                "- task_id=other-task; scope=thomas/tools; summary=other; reported_by=bot",
            ]
        ),
    )
    rc = mod.run(["--workboard", str(workboard), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert any("must be the last Up For Grabs entry" in item for item in payload["violations"])
