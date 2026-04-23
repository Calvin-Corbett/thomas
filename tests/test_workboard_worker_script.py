from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import scripts.check_workboard_claims as gate
import scripts.workboard_worker as mod

from thomas.core import task_bot_runtime


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


def test_worker_release_claim_safe_does_not_force_presence_override(tmp_path: Path, monkeypatch) -> None:
    calls: dict[str, object] = {}

    def _fake_release(workboard_path, **kwargs):  # noqa: ANN001
        calls["workboard_path"] = workboard_path
        calls.update(kwargs)
        return True, {}

    monkeypatch.setattr(mod.workboard_claim, "release", _fake_release)

    ok, err = mod._release_claim_safe(
        workboard_path=tmp_path / "WORKBOARD.md",
        agent="Worker 1",
        allow_dirty_release=False,
        dirty_release_reason="",
    )

    assert ok is True
    assert err == ""
    assert calls["agent"] == "Worker 1"
    assert calls["allow_dirty"] is False
    assert "allow_presence_override" not in calls
    assert "presence_override_reason" not in calls


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


def test_worker_uses_runtime_chat_task_when_no_command_mapping_exists(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Worker 1; scope=src/app.js; task=[WIP] runtime lane",
        active_tasks_block=(
            "- task_id=task-a; agent=Worker 1; scope=src/app.js; summary=[P1][NEXT] runtime chat task; status=active"
        ),
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": {}}, indent=2), encoding="utf-8")

    task_bot_runtime.create_execution(
        session_id="sess-runtime-worker",
        summary="Fix src/app.js",
        request_text="Fix src/app.js so the runtime worker returns RUNTIME_OK.",
        task_id="task-a",
        intent="chat_task",
        actor="thomas",
        repo_root=tmp_path,
    )

    calls: dict[str, object] = {}
    monkeypatch.setitem(
        sys.modules,
        "scripts.worker_run_chat_task",
        SimpleNamespace(
            execute_task_sync=lambda task_id, worker_agent, engine, emit_stdout: (
                calls.update(
                    {
                        "task_id": task_id,
                        "worker_agent": worker_agent,
                        "engine": engine,
                        "emit_stdout": emit_stdout,
                    }
                )
                or "RUNTIME_OK"
            )
        ),
    )

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
    assert calls == {
        "task_id": "task-a",
        "worker_agent": "Worker 1",
        "engine": "guarded_loop",
        "emit_stdout": False,
    }
    assert "agent=Worker 1; scope=src/app.js; task=[WIP] runtime lane" not in text
    assert "task_id=task-a; agent=Worker 1;" not in text
    assert "completed `task-a`" in text
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


def test_request_immediate_dispatch_uses_full_idle_capacity(tmp_path: Path, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    sent: list[dict[str, str]] = []
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        mod,
        "_send_message_safe",
        lambda **kwargs: (sent.append(dict(kwargs)) or True, None),
    )

    def _fake_dispatch_idle_agents_once(**kwargs):
        captured.update(kwargs)
        return True, {"assigned_count": 2, "assignments": [{"agent": "Worker 2"}, {"agent": "Worker 3"}]}

    monkeypatch.setattr(mod.workboard_task_manager, "dispatch_idle_agents_once", _fake_dispatch_idle_agents_once)

    ok, payload = mod._request_immediate_dispatch(
        workboard_path=workboard,
        agent="Worker 1",
        task_manager_agent="thomas",
        task_id="task-a",
        dispatch_lookback_minutes=5.0,
    )

    assert ok is True
    assert payload["assigned_count"] == 2
    assert captured["max_dispatch_per_cycle"] == 0
    assert len(sent) == 2


def test_worker_runtime_runner_accepts_production_task_intent(tmp_path: Path) -> None:
    task_bot_runtime.create_execution(
        session_id="sess-production-worker",
        summary="Build the production task pipeline",
        request_text="Build the production task pipeline",
        task_id="task-production",
        intent="production_task",
        actor="thomas",
        repo_root=tmp_path,
    )

    record = task_bot_runtime.find_by_task_id("task-production", repo_root=tmp_path)

    assert isinstance(record, dict)
    assert mod._should_use_runtime_task_runner(record) is True
