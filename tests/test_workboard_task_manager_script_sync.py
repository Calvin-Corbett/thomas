from __future__ import annotations

import json
from pathlib import Path

import scripts.crew.tasks.manager as mod
import scripts.crew.tasks.plans as plan_sync
import scripts.forge.gates.workboard_claims as gate

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


def test_sync_plan_helpers_keep_repo_relative_paths_inside_repo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(plan_sync, "ROOT", tmp_path)

    plan_path = plan_sync._default_plan_path("models-lane", "plans/thomas/tasks")
    problem_path = plan_sync._default_problem_path("models-lane", "plans/thomas/problems")

    assert plan_path == "plans/thomas/tasks/models-lane/PLAN.md"
    assert problem_path == "plans/thomas/problems/models-lane/PROBLEM.md"


def test_sync_problem_template_includes_task_marker() -> None:
    body = plan_sync._build_problem_template(
        task_id="models-lane",
        owner="Codex 1",
        summary="[WIP] models lane",
        scope="thomas/cli/main.py",
        status="in_progress",
        now_iso="2026-03-28T14:12:13+00:00",
    )

    assert "task_id: `models-lane`" in body


def test_sync_problem_marker_repair_inserts_marker_after_heading(tmp_path: Path) -> None:
    problem_path = tmp_path / "PROBLEM.md"
    problem_path.write_text("# PROBLEM for models-lane\n\n- Owner: Codex 1\n", encoding="utf-8")

    plan_sync._ensure_problem_marker(problem_path, task_id="models-lane")

    body = problem_path.read_text(encoding="utf-8")
    assert body.startswith("# PROBLEM for models-lane\n\ntask_id: `models-lane`\n\n")
    assert "- Owner: Codex 1" in body


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
            "summary=Benchmark Reference CLI latency and reliability lanes; status=active"
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
