from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_claims as gate
import scripts.workboard_message as msg_mod
import scripts.workboard_task_manager as mod

from thomas.preferences.store import PreferencesStore


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
            "`- \\`task_id=<id>; agent=<id>; scope=<path[,path...]>; summary=<short text>; "
            "status=<queued|claimed|in_progress|blocked|review|done>\\``\n\n"
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


def test_sync_plans_apply_scaffolds_missing_plan_files(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=thomas/cli/main.py; task=[WIP] models lane",
        active_tasks_block="- task_id=models-lane; agent=Codex 1; scope=thomas/cli/main.py; summary=[WIP] models lane; status=active",
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--sync-plans",
            "--plan-root",
            str(plan_root),
            "--problem-root",
            str(problem_root),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    plan_path = plan_root / "models-lane" / "PLAN.md"
    problem_path = problem_root / "models-lane" / "PROBLEM.md"
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["created_plan_count"] == 1
    assert payload["created_problem_count"] == 1
    assert plan_path.exists()
    assert problem_path.exists()
    assert "## Task Plans" in text
    assert "## Task Problems" in text
    assert "task_id=models-lane;" in text
    assert gate.evaluate(workboard) == []


def test_sync_plans_fails_without_apply_when_problem_and_plan_missing(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=thomas/cli/main.py; task=[WIP] models lane",
        active_tasks_block="- task_id=models-lane; agent=Codex 1; scope=thomas/cli/main.py; summary=[WIP] models lane; status=active",
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--sync-plans",
            "--plan-root",
            str(plan_root),
            "--problem-root",
            str(problem_root),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["missing_plan_count"] == 1
    assert payload["missing_problem_count"] == 1
    missing_plan = list(payload["missing_plans"])[0]
    missing_problem = list(payload["missing_problems"])[0]
    assert missing_plan.replace("\\", "/").endswith("/task-plans/models-lane/PLAN.md")
    assert missing_problem.replace("\\", "/").endswith("/task-problems/models-lane/PROBLEM.md")


def test_sync_plans_places_problem_entries_inside_task_problems_section(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=thomas/cli/main.py; task=[WIP] models lane",
        active_tasks_block="- task_id=models-lane; agent=Codex 1; scope=thomas/cli/main.py; summary=[WIP] models lane; status=active",
    )
    plan_root = tmp_path / "task-plans"
    problem_root = tmp_path / "task-problems"

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--sync-plans",
            "--plan-root",
            str(plan_root),
            "--problem-root",
            str(problem_root),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")
    lines = text.splitlines()

    assert rc == 0
    assert payload["ok"] is True
    heading_idx = lines.index("## Task Problems")
    next_heading = next(
        (idx for idx in range(heading_idx + 1, len(lines)) if lines[idx].startswith("## ")),
        len(lines),
    )
    section_lines = lines[heading_idx + 1 : next_heading]
    assert not any(line.strip() == "- none" for line in section_lines)
    assert any("task_id=models-lane; problem=" in line for line in section_lines)
    first_problem_idx = next(idx for idx, line in enumerate(lines) if "task_id=models-lane; problem=" in line)
    assert first_problem_idx > heading_idx


def test_sweep_inactive_apply_moves_tasks_and_marks_agent_inactive(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex Offline; scope=thomas/cli/main.py; task=[WIP] models lane",
        active_tasks_block="- task_id=models-lane; agent=Codex Offline; scope=thomas/cli/main.py; summary=[WIP] models lane; status=active",
    )
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: 1771846200)
    original_release = mod.workboard_claim.release
    release_call: dict[str, str | bool] = {}

    def _release_proxy(
        workboard_path: Path,
        *,
        agent: str,
        allow_dirty: bool = False,
        dirty_reason: str = "",
    ) -> tuple[bool, str]:
        release_call["agent"] = agent
        release_call["allow_dirty"] = bool(allow_dirty)
        release_call["dirty_reason"] = dirty_reason
        return original_release(
            workboard_path,
            agent=agent,
            allow_dirty=allow_dirty,
            dirty_reason=dirty_reason,
        )

    monkeypatch.setattr(mod.workboard_claim, "release", _release_proxy)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--sweep-inactive",
            "--max-idle-minutes",
            "1",
            "--task-manager-agent",
            "TaskManager",
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
    assert payload["stale_claim_count"] == 1
    assert payload["moved_task_ids"] == ["models-lane"]
    assert payload["sent_message_count"] == 1
    assert release_call == {
        "agent": "Codex Offline",
        "allow_dirty": True,
        "dirty_reason": "inactivity reclaim by TaskManager for Codex Offline: claim_line_age_timeout",
    }
    assert "agent=Codex Offline; scope=thomas/cli/main.py; task=[WIP] models lane" not in text
    assert "task_id=models-lane; agent=Codex Offline;" not in text
    assert "task_id=models-lane; scope=thomas/cli/main.py; summary=[WIP] models lane; reported_by=TaskManager" in text
    assert "owner=TaskManager;" in text
    assert "## Inactive Agents" in text
    assert "## Agent Message Traffic" in text
    assert "kind=ping;" in text
    assert "agent=Codex Offline; state=inactive;" in text
    assert gate.evaluate(workboard) == []


def test_sweep_inactive_uses_agent_activity_when_claim_line_is_fresh(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex Offline; scope=thomas/cli/main.py; task=[WIP] models lane",
        active_tasks_block="- task_id=models-lane; agent=Codex Offline; scope=thomas/cli/main.py; summary=[WIP] models lane; status=active",
    )
    text = workboard.read_text(encoding="utf-8")
    workboard.write_text(
        text
        + "\n## Agent Sessions\n\n"
        + "- agent=Codex Offline; model_alias=Codex Offline; session_id=sess-old; parent=none; state=active; active_task=models-lane; last_seen=2026-02-25T11:30:00+00:00\n",
        encoding="utf-8",
    )
    # Simulate a fresh claim line timestamp so stale detection must use agent activity.
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: 1772020795)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--sweep-inactive",
            "--max-idle-minutes",
            "1",
            "--task-manager-agent",
            "TaskManager",
            "--now",
            "2026-02-25T12:00:00+00:00",
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    out = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["stale_claim_count"] == 1
    assert payload["moved_task_ids"] == ["models-lane"]
    stale = list(payload["stale_claims"] or [])
    assert stale
    assert stale[0]["issue"] == "agent_activity_timeout"
    assert "agent=Codex Offline; scope=thomas/cli/main.py; task=[WIP] models lane" not in out
    assert "task_id=models-lane; agent=Codex Offline;" not in out
    assert gate.evaluate(workboard) == []


def test_reactivate_moves_task_back_to_active_lane(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- none",
        active_tasks_block="- none",
        issues_block="- issue_id=models-lane-inactive; task_id=models-lane; reporter=TaskManager; owner=TaskManager; state=open; summary=reactivate or reassign",
        up_for_grabs_block="- task_id=models-lane; scope=thomas/cli/main.py; summary=[WIP] models lane; reported_by=TaskManager",
    )
    text = workboard.read_text(encoding="utf-8")
    workboard.write_text(
        text
        + "\n## Inactive Agents\n\n"
        + "- agent=Codex Offline; state=inactive; detected_at=2026-02-25T12:00:00+00:00; idle_minutes=10; task_ids=models-lane; notify=TaskManager; action=reactivate_or_reassign\n",
        encoding="utf-8",
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--reactivate",
            "--task-id",
            "models-lane",
            "--agent",
            "Codex Offline",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    out = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert "task_id=models-lane; agent=Codex Offline;" in out
    assert (
        "task_id=models-lane; scope=thomas/cli/main.py; summary=[WIP] models lane; reported_by=TaskManager" not in out
    )
    assert "agent=Codex Offline;" in out
    assert gate.evaluate(workboard) == []


def test_sync_sessions_apply_writes_active_registry(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/cli/main.py; task=coord lane",
        active_tasks_block="- task_id=coord-lane; agent=Codex 3; scope=thomas/cli/main.py; summary=coord lane; status=active",
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--sync-sessions",
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
    assert payload["session_entry_count"] == 1
    assert payload["session_lease_minutes"] == 5.0
    assert "## Agent Sessions" in text
    assert "agent=Codex 3;" in text
    assert "state=active;" in text
    assert "active_task=coord-lane;" in text
    assert "lease_expires=" in text
    assert gate.evaluate(workboard) == []


def test_sync_sessions_apply_repairs_duplicate_session_ids_and_aliases(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block=(
            "- agent=Codex 1; scope=thomas/cli/main.py; task=lane 1\n"
            "- agent=Codex 2; scope=thomas/server/app.py; task=lane 2"
        ),
        active_tasks_block=(
            "- task_id=lane-1; agent=Codex 1; scope=thomas/cli/main.py; summary=lane 1; status=active\n"
            "- task_id=lane-2; agent=Codex 2; scope=thomas/server/app.py; summary=lane 2; status=active"
        ),
    )
    text = workboard.read_text(encoding="utf-8")
    workboard.write_text(
        text
        + "\n## Agent Sessions\n\n"
        + "- agent=Codex 1; model_alias=Codex; session_id=sess-dup; parent=none; state=active; active_task=lane-1; last_seen=2026-02-25T11:59:00+00:00\n"
        + "- agent=Codex 2; model_alias=Codex; session_id=sess-dup; parent=none; state=active; active_task=lane-2; last_seen=2026-02-25T11:59:00+00:00\n",
        encoding="utf-8",
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--sync-sessions",
            "--apply",
            "--now",
            "2026-02-25T12:00:00+00:00",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    out = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert "agent=Codex 1; model_alias=Codex; session_id=sess-dup;" in out
    assert "agent=Codex 2; model_alias=Codex-2;" in out
    assert "agent=Codex 2; model_alias=Codex-2; session_id=sess-20260225120000-codex-2;" in out
    assert gate.evaluate(workboard) == []


def test_capture_preference_stores_summary_and_verbatim(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    db_path = tmp_path / "prefs.db"
    monkeypatch.setenv("THOMAS_DB_PATH", str(db_path))

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--capture-preference",
            "--user-id",
            "task-user",
            "--preference-summary",
            "Use task manager orchestration with agent messaging and parallel workers.",
            "--preference-verbatim",
            "Always route tasks through task manager and let agents coordinate directly.",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    store = PreferencesStore(db_path=str(db_path))
    response = store.get(user_id="task-user")
    ecosystem = dict((response.onboarding.answers or {}).get("task_ecosystem") or {})
    rows = list(ecosystem.get("conduct_preferences") or [])

    assert rc == 0
    assert payload["ok"] is True
    assert payload["saved_preference_count"] == 1
    assert ecosystem.get("current_preference_summary") == (
        "Use task manager orchestration with agent messaging and parallel workers."
    )
    assert ecosystem.get("weights") == {"summary": 0.8, "verbatim": 0.2}
    assert len(rows) == 1
    assert rows[0]["summary_weight"] == 0.8
    assert rows[0]["verbatim_weight"] == 0.2
    monkeypatch.delenv("THOMAS_DB_PATH", raising=False)


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
    assert "task_id=queued-lane; scope=thomas/server/app.py; summary=[P0][NOW] queued lane start check; reported_by=task-manager-agent" in text


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
        active_tasks_block=('- task_id=lane-one; agent=Codex 1; scope=thomas/cli/main.py; summary=existing lane; status=done; name=Codex 1; role=solo; parent=none'),
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
