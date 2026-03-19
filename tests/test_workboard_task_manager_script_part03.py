import json
from pathlib import Path

import scripts.check_workboard_claims as gate
import scripts.workboard_message as msg_mod
import scripts.workboard_task_manager as mod

from tests.test_workboard_task_manager_script_part1 import _write_workboard


def test_monitor_dispatch_handles_agent_default_task_id_collision(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        up_for_grabs_block=(
            "- task_id=codex-1-task; scope=thomas/cli/main.py; "
            "summary=[P0][NOW] codex lane dispatch collision regression; reported_by=task-manager-agent; depends_on=none"
        ),
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"

    ok_msg, payload_msg = msg_mod.send_message(
        workboard,
        sender="Codex 1",
        recipient="task-manager-agent",
        summary="terminal online",
        task_id="none",
        kind="ping",
        priority="p0",
        requested_action="none",
        decision="pending",
    )
    assert ok_msg is True, payload_msg

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--monitor",
            "--plan-root",
            str(plan_root),
            "--problem-root",
            str(problem_root),
            "--cycles",
            "1",
            "--interval-seconds",
            "0",
            "--max-idle-minutes",
            "999",
            "--max-agent-silence-minutes",
            "30",
            "--max-dispatch-per-cycle",
            "1",
            "--no-swarm-recovery",
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    checks = dict((payload.get("cycles") or [{}])[0].get("checks") or {})
    dispatch = dict(checks.get("idle_dispatch") or {})
    assert dispatch.get("assigned_count") == 1
    assert "task_id=codex-1-task; agent=Codex 1;" in text
    assert (
        "task_id=codex-1-task; scope=thomas/cli/main.py; "
        "summary=[P0][NOW] codex lane dispatch collision regression; reported_by=task-manager-agent" not in text
    )
    assert gate.evaluate(workboard) == []


def test_monitor_prioritizes_user_tasks_before_background_ecosystem(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        up_for_grabs_block=(
            "- task_id=ecosystem-lane; scope=plans/thomas/WORKBOARD.md,docs/ops/TASK_ECOSYSTEM_PROTOCOL.md; "
            "summary=[P0][NOW] maintain ecosystem queue; reported_by=task-manager-agent; depends_on=none\n"
            "- task_id=user-feature-lane; scope=thomas/server/app.py; "
            "summary=[P1][NEXT][USER] implement runtime user feature lane; reported_by=task-manager-agent"
        ),
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"

    ok_msg, payload_msg = msg_mod.send_message(
        workboard,
        sender="Codex Idle",
        recipient="task-manager-agent",
        summary="terminal online",
        task_id="none",
        kind="ping",
        priority="p1",
        requested_action="none",
        decision="pending",
    )
    assert ok_msg is True, payload_msg

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--monitor",
            "--plan-root",
            str(plan_root),
            "--problem-root",
            str(problem_root),
            "--cycles",
            "1",
            "--interval-seconds",
            "0",
            "--max-idle-minutes",
            "999",
            "--max-agent-silence-minutes",
            "30",
            "--max-dispatch-per-cycle",
            "1",
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    checks = dict((payload.get("cycles") or [{}])[0].get("checks") or {})
    dispatch = dict(checks.get("idle_dispatch") or {})
    assignments = list(dispatch.get("assignments") or [])
    assert len(assignments) == 1
    assigned = dict(assignments[0])
    assert assigned.get("task_id") == "user-feature-lane"
    assert assigned.get("priority_source") == "user"
    assert "task_id=user-feature-lane; agent=Codex Idle;" in text
    assert "task_id=ecosystem-lane; scope=plans/thomas/WORKBOARD.md,docs/ops/TASK_ECOSYSTEM_PROTOCOL.md;" in text
    assert gate.evaluate(workboard) == []


def test_monitor_auto_splits_partial_overlap_task_for_idle_dispatch(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex Busy; scope=docs/ops; task=[WIP] docs lane",
        active_tasks_block="- task_id=docs-lane; agent=Codex Busy; scope=docs/ops; summary=[WIP] docs lane; status=active",
        up_for_grabs_block=(
            "- task_id=mixed-lane; scope=docs/ops,thomas/cli/main.py; "
            "summary=[P0][NOW] mixed scope cleanup lane; reported_by=task-manager-agent; depends_on=none"
        ),
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: 1772020800)

    ok_msg, payload_msg = msg_mod.send_message(
        workboard,
        sender="Codex Idle",
        recipient="task-manager-agent",
        summary="terminal online",
        task_id="none",
        kind="ping",
        priority="p0",
        requested_action="none",
        decision="pending",
    )
    assert ok_msg is True, payload_msg

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--monitor",
            "--plan-root",
            str(plan_root),
            "--problem-root",
            str(problem_root),
            "--cycles",
            "1",
            "--interval-seconds",
            "0",
            "--task-manager-agent",
            "task-manager-agent",
            "--max-idle-minutes",
            "999",
            "--max-agent-silence-minutes",
            "30",
            "--max-dispatch-per-cycle",
            "1",
            "--no-swarm-recovery",
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    checks = dict((payload.get("cycles") or [{}])[0].get("checks") or {})
    dispatch = dict(checks.get("idle_dispatch") or {})
    assert dispatch.get("assigned_count") == 1
    assert dispatch.get("split_task_count") == 1
    assignments = list(dispatch.get("assignments") or [])
    assert assignments
    assigned = dict(assignments[0])
    assert assigned.get("agent") == "Codex Idle"
    assert assigned.get("mode") == "applied_split"
    assert assigned.get("task_id") == "mixed-lane-split-1"
    assert "task_id=mixed-lane-split-1; agent=Codex Idle; scope=thomas/cli/main.py;" in text
    assert (
        "task_id=mixed-lane; scope=docs/ops; summary=[P0][NOW] mixed scope cleanup lane; reported_by=task-manager-agent"
        in text
    )
    assert gate.evaluate(workboard) == []


def test_monitor_pings_silent_active_task_agent(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex Quiet; scope=thomas/cli/main.py; task=[WIP] quiet lane",
        active_tasks_block="- task_id=quiet-lane; agent=Codex Quiet; scope=thomas/cli/main.py; summary=[WIP] quiet lane; status=active",
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: 1772020800)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--monitor",
            "--plan-root",
            str(plan_root),
            "--problem-root",
            str(problem_root),
            "--cycles",
            "1",
            "--interval-seconds",
            "0",
            "--task-manager-agent",
            "TaskManager",
            "--max-idle-minutes",
            "999",
            "--max-agent-silence-minutes",
            "1",
            "--no-idle-dispatch",
            "--no-swarm-recovery",
            "--now",
            "2026-02-25T12:00:00+00:00",
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    checks = dict((payload.get("cycles") or [{}])[0].get("checks") or {})
    silence = dict(checks.get("silence_ping") or {})
    assert silence.get("silent_task_count") == 1
    assert silence.get("sent_message_count") == 1
    assert "kind=ping;" in text
    assert "task_id=quiet-lane;" in text
    assert "idle monitor: no status update for `quiet-lane`" in text
    assert gate.evaluate(workboard) == []


def test_monitor_starts_brainstorm_session_for_brainstorm_task(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block=(
            "- agent=Codex 1; scope=scripts/a.py; task=lane a\n- agent=Codex 2; scope=scripts/b.py; task=lane b"
        ),
        active_tasks_block=(
            "- task_id=lane-a; agent=Codex 1; scope=scripts/a.py; summary=lane a; status=active\n"
            "- task_id=lane-b; agent=Codex 2; scope=scripts/b.py; summary=lane b; status=active"
        ),
        up_for_grabs_block=(
            "- task_id=brainstorm-target; scope=plans/thomas/brainstorm.md; "
            "summary=[P0][NOW] run an all-hands brainstorm workshop to reach consensus; reported_by=task-manager-agent; depends_on=none"
        ),
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"

    ok_msg, payload_msg = msg_mod.send_message(
        workboard,
        sender="Codex Idle",
        recipient="task-manager-agent",
        summary="terminal online",
        task_id="none",
        kind="ping",
        priority="p1",
        requested_action="none",
        decision="pending",
    )
    assert ok_msg is True, payload_msg

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--monitor",
            "--plan-root",
            str(plan_root),
            "--problem-root",
            str(problem_root),
            "--cycles",
            "1",
            "--interval-seconds",
            "0",
            "--max-idle-minutes",
            "999",
            "--max-agent-silence-minutes",
            "30",
            "--max-dispatch-per-cycle",
            "1",
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    checks = dict((payload.get("cycles") or [{}])[0].get("checks") or {})
    dispatch = dict(checks.get("idle_dispatch") or {})
    assert dispatch.get("brainstorm_task_count") == 1
    assert "## Brainstorm Sessions" in text
    assert "task_id=brainstorm-target;" in text
    assert "kind=brainstorm_call;" in text
    assert gate.evaluate(workboard) == []


def test_monitor_sends_blocked_dispatch_notice_when_no_non_overlap_task(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex Busy; scope=docs/ops; task=[WIP] docs lane",
        active_tasks_block="- task_id=docs-lane; agent=Codex Busy; scope=docs/ops; summary=[WIP] docs lane; status=active",
        up_for_grabs_block=(
            "- task_id=docs-cleanup; scope=docs/ops; "
            "summary=[P1][NEXT] cleanup docs lane; reported_by=task-manager-agent"
        ),
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: 1772020800)

    ok_msg, payload_msg = msg_mod.send_message(
        workboard,
        sender="Codex Idle",
        recipient="task-manager-agent",
        summary="terminal online",
        task_id="none",
        kind="ping",
        priority="p0",
        requested_action="none",
        decision="pending",
    )
    assert ok_msg is True, payload_msg

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--monitor",
            "--plan-root",
            str(plan_root),
            "--problem-root",
            str(problem_root),
            "--cycles",
            "1",
            "--interval-seconds",
            "0",
            "--task-manager-agent",
            "task-manager-agent",
            "--max-idle-minutes",
            "999",
            "--max-agent-silence-minutes",
            "30",
            "--max-dispatch-per-cycle",
            "1",
            "--no-swarm-recovery",
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    checks = dict((payload.get("cycles") or [{}])[0].get("checks") or {})
    dispatch = dict(checks.get("idle_dispatch") or {})
    assert dispatch.get("assigned_count") == 0
    assert dispatch.get("blocked_notice_message_count") == 1
    assert "dispatch blocked for Codex Idle: no non-overlap queued task" in text
    assert "requested_action=propose scope split for queued tasks: docs-cleanup;" in text
    assert gate.evaluate(workboard) == []


def test_auto_start_assigns_existing_in_progress_task(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=thomas/cli/main.py; task=[WIP] existing lane",
        active_tasks_block=(
            "- task_id=lane-one; agent=Codex 1; scope=thomas/cli/main.py; summary=existing lane; status=in_progress"
            "; name=Codex 1; role=solo; parent=none"
        ),
        up_for_grabs_block=(
            "- task_id=queued-lane; scope=thomas/server/app.py; summary=[P0][NOW] queued lane start check; reported_by=task-manager-agent"
        ),
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--auto-start",
            "--agent",
            "Codex 1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "auto_start"
    assert payload["agent"] == "Codex 1"
    assert payload["task_id"] == "lane-one"
    assert payload["status"] == "in_progress"
    assert payload["started"] is True
    assert payload["source"] == "existing"
    text = workboard.read_text(encoding="utf-8")
    assert "task_id=lane-one; agent=Codex 1;" in text
    assert (
        "task_id=queued-lane; scope=thomas/server/app.py; summary=[P0][NOW] queued lane start check; reported_by=task-manager-agent"
        in text
    )


def test_auto_start_rejects_orchestrator_agent(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--auto-start",
            "--agent",
            "task-manager-agent",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["action"] == "auto_start"
    assert "auto-start is disabled for orchestrator agents" in str(payload.get("error", ""))


def test_auto_start_fails_when_no_up_for_grabs_available(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=thomas/cli/main.py; task=[WIP] existing lane",
        active_tasks_block=(
            "- task_id=lane-one; agent=Codex 1; scope=thomas/cli/main.py; summary=existing lane; status=done; name=Codex 1; role=solo; parent=none"
        ),
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--auto-start",
            "--agent",
            "Codex 2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["action"] == "auto_start"
    assert payload["agent"] == "Codex 2"
    assert "no up-for-grabs tasks available" in str(payload.get("error", ""))
