from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_claims as gate
import scripts.workboard_worker as mod


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
            f"{up_for_grabs_block}\n\n"
            "## Supporting Docs (Not Plan Sources)\n\n"
            "- docs/PROJECT_SCOPE.md\n"
        ),
        encoding="utf-8",
    )
    return path


def test_worker_executes_assigned_task_and_releases_on_success(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/check_plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/check_plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {"task-a": ["python -c \"print('ok')\""]}}, indent=2), encoding="utf-8")

    class _Completed:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "ok\n"
            self.stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: _Completed())

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "2",
            "--max-completions",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["completed_count"] == 1
    assert "agent=Worker 1; scope=scripts/check_plan_structure_gate.py; task=[WIP] automation lane" not in text
    assert "task_id=task-a; agent=Worker 1;" not in text
    assert "completed `task-a`" in text
    assert gate.evaluate(workboard) == []


def test_worker_failure_keeps_claim_by_default(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/check_plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/check_plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps({"tasks": {"task-a": ['python -c "import sys; sys.exit(5)"']}}, indent=2), encoding="utf-8"
    )

    class _Completed:
        def __init__(self) -> None:
            self.returncode = 5
            self.stdout = ""
            self.stderr = "boom\n"

    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: _Completed())

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--stop-on-failure",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 1
    assert payload["ok"] is False
    assert payload["failure_count"] >= 1
    assert "agent=Worker 1; scope=scripts/check_plan_structure_gate.py; task=[WIP] automation lane" in text
    assert "task_id=task-a; agent=Worker 1;" in text
    assert "automation failed for `task-a`" in text
    assert gate.evaluate(workboard) == []


def test_worker_release_on_no_command_flag(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/check_plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/check_plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {}}, indent=2), encoding="utf-8")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--release-on-no-command",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["no_command_count"] == 1
    assert "agent=Worker 1; scope=scripts/check_plan_structure_gate.py; task=[WIP] automation lane" not in text
    assert "task_id=task-a; agent=Worker 1;" not in text
    assert "no automation command configured for `task-a`" in text
    assert gate.evaluate(workboard) == []


def test_worker_success_triggers_immediate_redispatch(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/check_plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/check_plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=claimed"
        ),
        up_for_grabs_block=(
            "- task_id=task-b; scope=scripts/check_plan_structure_gate.py; "
            "summary=[P1][NEXT] follow-up automation lane; reported_by=task-manager-agent"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {"task-a": ["python -c \"print('ok')\""]}}, indent=2), encoding="utf-8")

    class _Completed:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "ok\n"
            self.stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: _Completed())

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--catalog",
            str(catalog),
            "--cycles",
            "2",
            "--max-completions",
            "1",
            "--poll-seconds",
            "0",
            "--idle-heartbeat-seconds",
            "0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["completed_count"] == 1
    assert payload["dispatch_request_count"] == 1
    assert payload["dispatch_assigned_count"] == 1
    assert "task_id=task-b; agent=Worker 1;" in text
    assert "task_id=task-b; scope=scripts/check_plan_structure_gate.py;" not in text
    assert gate.evaluate(workboard) == []
