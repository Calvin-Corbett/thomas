from __future__ import annotations

import json
from pathlib import Path

import scripts.crew.workboard.message as message_tool
import scripts.crew.workboard.worker as mod
import scripts.forge.gates.workboard_claims as gate


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


def test_worker_stops_before_task_when_inbox_has_unread_message(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {"task-a": ["python -c \"print('should not run')\""]}}, indent=2), encoding="utf-8")

    ok_send, send_payload = message_tool.send_message(
        workboard,
        sender="Coordinator",
        recipient="Worker 1",
        task_id="task-a",
        kind="blocker",
        priority="p0",
        summary="Stop and read this first",
        requested_action="Ack/respond before continuing.",
    )
    assert ok_send, send_payload

    def _unexpected_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("worker executed a task command before clearing unread inbox messages")

    monkeypatch.setattr(mod.subprocess, "run", _unexpected_run)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Worker 1",
            "--task-manager-agent",
            "task-manager-agent",
            "--catalog",
            str(catalog),
            "--cycles",
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

    assert rc == 1
    assert payload["ok"] is False
    assert payload["completed_count"] == 0
    assert payload["failure_count"] == 0
    assert payload["inbox_blocked_count"] == 1
    assert payload["last_inbox_message_ids"] == [send_payload["message"]["msg_id"]]
    assert "task_id=task-a; agent=Worker 1;" in text
    assert "worker paused: `Worker 1` has 1 unread workboard message(s)" in text


def test_worker_executes_assigned_task_and_releases_on_success(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
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
    assert "agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane" not in text
    assert "task_id=task-a; agent=Worker 1;" not in text
    assert "completed `task-a`" in text
    assert gate.evaluate(workboard) == []


def test_worker_failure_keeps_claim_by_default(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
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
    assert "agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane" in text
    assert "task_id=task-a; agent=Worker 1;" in text
    assert "automation failed for `task-a`" in text
    assert gate.evaluate(workboard) == []


def test_worker_release_on_no_command_flag(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
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
    assert "agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane" not in text
    assert "task_id=task-a; agent=Worker 1;" not in text
    assert "no automation command configured for `task-a`" in text
    assert gate.evaluate(workboard) == []


def test_worker_success_triggers_immediate_redispatch(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; task=[WIP] automation lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=scripts/forge/gates/plan_structure_gate.py; "
            "summary=[P1][NEXT] run automation lane; status=claimed"
        ),
        up_for_grabs_block=(
            "- task_id=task-b; scope=scripts/forge/gates/plan_structure_gate.py; "
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
    assert "task_id=task-b; scope=scripts/forge/gates/plan_structure_gate.py;" not in text
    assert gate.evaluate(workboard) == []
