import json
from pathlib import Path

import scripts.check_workboard_claims as gate
import scripts.workboard_message as msg_mod
import scripts.workboard_task_manager as mod

from tests.test_workboard_task_manager_script_part1 import _write_workboard


def test_sync_specialists_apply_writes_routing_rows(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 2; scope=scripts/competitors; task=benchmark routing",
        active_tasks_block=(
            "- task_id=benchmark-routing; agent=Codex 2; scope=scripts/competitors; "
            "summary=Benchmark OpenClaw latency and reliability lanes; status=active"
        ),
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--sync-specialists",
            "--apply",
            "--now",
            "2026-02-25T12:00:00+00:00",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["routed_task_count"] == 1
    assert "## Task Specialist Routing" in text
    assert "task_id=benchmark-routing;" in text
    assert "task_type=competitor_benchmark;" in text
    assert "specialist=specialist-competitor-benchmark;" in text
    assert gate.evaluate(workboard) == []


def test_specialist_for_task_resolves_from_board_task_id(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        up_for_grabs_block=(
            "- task_id=cleanup-old-ui; scope=apps/site/src/components,docs; "
            "summary=cleanup unused legacy ui assets and stale docs; reported_by=Codex 2"
        ),
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--specialist-for-task",
            "--task-id",
            "cleanup-old-ui",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["task_id"] == "cleanup-old-ui"
    assert payload["task_type"] == "repo_hygiene_cleanup"
    assert payload["specialist"] == "specialist-repo-hygiene"


def test_specialist_for_task_resolves_ad_hoc_scope_and_summary(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--specialist-for-task",
            "--task-scope",
            "thomas/server/routes/auth.py",
            "--task-summary",
            "security compliance audit for auth policy and permissions",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["task_id"] == "adhoc-task"
    assert payload["task_type"] == "security_compliance"
    assert payload["specialist"] == "specialist-security-compliance"


def test_specialist_for_task_routes_openai_specialist_framework(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--specialist-for-task",
            "--task-summary",
            "Build OpenAI specialist framework routing with Agents SDK and Responses API tool calling.",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["task_type"] == "openai_specialist_framework"
    assert payload["specialist"] == "specialist-openai-framework"


def test_specialist_for_task_does_not_route_openai_on_generic_openai_token(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--specialist-for-task",
            "--task-summary",
            "OpenAI compatibility tests for gateway regressions.",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["task_type"] == "testing_quality"
    assert payload["specialist"] == "specialist-test-rigor"


def test_specialist_for_task_routes_ecosystem_task_with_docs_scope(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        up_for_grabs_block=(
            "- task_id=ecosystem-task-priority-refresh; scope=docs/ops/TASK_ECOSYSTEM_PROTOCOL.md,plans/thomas/WORKBOARD.md; "
            "summary=refresh task priority queue and agent dispatch order; reported_by=Codex 2"
        ),
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--specialist-for-task",
            "--task-id",
            "ecosystem-task-priority-refresh",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["task_type"] == "task_ecosystem_ops"
    assert payload["specialist"] == "specialist-task-ecosystem"


def test_specialist_for_task_routes_brainstorm_tasks(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--specialist-for-task",
            "--task-summary",
            "Run an all-hands brainstorm session and facilitate consensus before dispatching work.",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["task_type"] == "brainstorm_orchestration"
    assert payload["specialist"] == "specialist-brainstorm-facilitator"


def test_specialist_for_task_routes_swarm_terminal_orchestration(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--specialist-for-task",
            "--task-summary",
            "Spawn terminals for a swarm and run terminal orchestration dispatch.",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["task_type"] == "task_ecosystem_ops"
    assert payload["specialist"] == "specialist-task-ecosystem"


def test_monitor_dispatches_online_idle_agent_to_up_for_grabs(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        up_for_grabs_block=(
            "- task_id=cleanup-lane; scope=docs/ops,plans/thomas; "
            "summary=[P0][NOW] cleanup legacy board residue; reported_by=task-manager-agent; depends_on=none"
        ),
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"

    ok_msg, payload_msg = msg_mod.send_message(
        workboard,
        sender="Codex 6",
        recipient="task-manager-agent",
        summary="swarm test terminal online",
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
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "monitor"
    assert payload["cycle_count"] == 1
    checks = dict((payload.get("cycles") or [{}])[0].get("checks") or {})
    dispatch = dict(checks.get("idle_dispatch") or {})
    assert dispatch.get("assigned_count") == 1
    assert "agent=Codex 6;" in text
    assert "task_id=cleanup-lane; agent=Codex 6;" in text
    assert "task_id=cleanup-lane; scope=docs/ops,plans/thomas;" not in text
    assert gate.evaluate(workboard) == []


def test_monitor_applies_plan_sync_before_dispatch(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        up_for_grabs_block=(
            "- task_id=cleanup-lane; scope=docs/ops,plans/thomas; "
            "summary=[P0][NOW] monitor lane with plan sync; reported_by=task-manager-agent; depends_on=none"
        ),
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"

    ok_msg, payload_msg = msg_mod.send_message(
        workboard,
        sender="Codex 6",
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

    plan_path = plan_root / "cleanup-lane" / "PLAN.md"
    problem_path = problem_root / "cleanup-lane" / "PROBLEM.md"

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "monitor"
    assert payload["plan_sync"]["tracked_task_count"] == 1
    assert payload["plan_sync"]["created_plan_count"] == 1
    assert payload["plan_sync"]["created_problem_count"] == 1
    assert plan_path.exists()
    assert problem_path.exists()
    assert "## Task Plans" in text
    assert "## Task Problems" in text
    assert "task_id=cleanup-lane;" in text
    assert gate.evaluate(workboard) == []


def test_monitor_auto_starts_claimed_agents_without_idle_agents(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block=(
            "- agent=Codex 1; scope=thomas/cli/main.py; task=[WIP] first lane\n"
            "- agent=Codex 2; scope=thomas/server/app.py; task=[WIP] second lane"
        ),
        active_tasks_block=(
            "- task_id=lane-two; agent=Codex 2; scope=thomas/server/app.py; summary=second lane; status=active"
        ),
        up_for_grabs_block=(
            "- task_id=lane-one; scope=thomas/cli/main.py; "
            "summary=[P0][NOW] claimed-lane start check; reported_by=task-manager-agent; depends_on=none"
        ),
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"

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
            "--no-idle-dispatch",
            "--no-swarm-recovery",
            "--max-idle-minutes",
            "999",
            "--max-agent-silence-minutes",
            "30",
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    auto_start = dict((payload.get("cycles") or [{}])[0].get("checks", {}).get("auto_start") or {})
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert auto_start.get("candidate_agent_count") == 2
    assert auto_start.get("attempted_count") == 2
    assert auto_start.get("assigned_count") == 2
    assert auto_start.get("auto_started_count") == 1
    assert auto_start.get("already_in_progress_count") == 1
    assert auto_start.get("no_work_available_count") == 0
    assert auto_start.get("failed_agent_count") == 0
    assert "task_id=lane-one; agent=Codex 1;" in text
    assert "task_id=lane-two; agent=Codex 2;" in text
    assert (
        "task_id=lane-one; scope=thomas/cli/main.py; "
        "summary=[P0][NOW] claimed-lane start check; reported_by=task-manager-agent"
    ) not in text
    assert gate.evaluate(workboard) == []


def test_monitor_auto_start_skips_non_startable_claimed_agents(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block=(
            "- agent=Codex 1; scope=thomas/cli/main.py; task=[WIP] first lane\n"
            "- agent=Codex 2; scope=thomas/server/app.py; task=[WIP] second lane"
        ),
        active_tasks_block=(
            "- task_id=lane-two; agent=Codex 2; scope=thomas/server/app.py; summary=second lane; status=blocked"
        ),
        up_for_grabs_block=(
            "- task_id=lane-one; scope=thomas/cli/main.py; "
            "summary=[P0][NOW] claimed-lane start check; reported_by=task-manager-agent; depends_on=none"
        ),
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"

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
            "--no-idle-dispatch",
            "--no-swarm-recovery",
            "--max-idle-minutes",
            "999",
            "--max-agent-silence-minutes",
            "30",
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    auto_start = dict((payload.get("cycles") or [{}])[0].get("checks", {}).get("auto_start") or {})
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert auto_start.get("candidate_agent_count") == 1
    assert auto_start.get("attempted_count") == 1
    assert auto_start.get("assigned_count") == 1
    assert auto_start.get("skipped_non_startable_count") == 1
    assert auto_start.get("skipped_non_startable_agents") == ["Codex 2"]
    assert "task_id=lane-one; agent=Codex 1;" in text
    assert "agent=Codex 2;" in text
    assert "status=blocked" in text
    assert gate.evaluate(workboard) == []
