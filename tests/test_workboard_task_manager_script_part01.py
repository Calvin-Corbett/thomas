from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_claims as gate
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


def test_sync_inferred_apply_creates_provisional_claim_and_task(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setattr(
        mod.agent_presence,
        "collect_presence",
        lambda **_: {
            "success": True,
            "repo_root": str(tmp_path),
            "generated_at": "2026-02-25T12:00:00+00:00",
            "active_count": 1,
            "agents": [],
            "recent_activity": [],
            "services": [],
            "warnings": [],
            "conflicts": [],
            "inferred_candidates": [
                {
                    "agent_id": "claude",
                    "display_name": "Claude",
                    "scope": "thomas/cli",
                    "confidence": "high",
                    "recent_paths": ["thomas/cli/main.py"],
                    "process_pids": ["4242"],
                    "supporting_process_evidence": ["Claude.exe"],
                    "recommended_task_summary": "Inferred work in thomas/cli",
                }
            ],
            "inferred_applied": [],
            "inferred_suppressed": [],
            "inferred_expired": [],
        },
    )

    rc = mod.run(
        ["--workboard", str(workboard), "--sync-inferred", "--apply", "--now", "2026-02-25T12:00:00+00:00", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "sync_inferred"
    assert payload["applied_count"] == 1
    assert "inferred=true" in text
    assert "agent=claude; name=Claude; role=solo; parent=none; scope=thomas/cli;" in text
    assert "task_id=INFERRED-claude-" in text
    assert gate.evaluate(workboard) == []


def test_sync_inferred_suppresses_conflicting_explicit_claim(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex Busy; scope=thomas/cli; task=[WIP] explicit lane",
        active_tasks_block="- task_id=busy-lane; agent=Codex Busy; scope=thomas/cli; summary=explicit lane; status=in_progress",
    )
    monkeypatch.setattr(
        mod.agent_presence,
        "collect_presence",
        lambda **_: {
            "success": True,
            "repo_root": str(tmp_path),
            "generated_at": "2026-02-25T12:00:00+00:00",
            "active_count": 1,
            "agents": [],
            "recent_activity": [],
            "services": [],
            "warnings": [],
            "conflicts": [],
            "inferred_candidates": [
                {
                    "agent_id": "claude",
                    "display_name": "Claude",
                    "scope": "thomas/cli",
                    "confidence": "high",
                    "recent_paths": ["thomas/cli/main.py"],
                    "process_pids": ["4242"],
                    "supporting_process_evidence": ["Claude.exe"],
                    "recommended_task_summary": "Inferred work in thomas/cli",
                    "conflicts_with_explicit_claim": True,
                    "conflict_agent_id": "Codex Busy",
                }
            ],
            "inferred_applied": [],
            "inferred_suppressed": [],
            "inferred_expired": [],
        },
    )

    rc = mod.run(
        ["--workboard", str(workboard), "--sync-inferred", "--apply", "--now", "2026-02-25T12:00:00+00:00", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["applied_count"] == 0
    assert payload["suppressed_count"] >= 1
    assert "agent=claude;" not in text
    assert text.count("inferred=true") == 0
    assert gate.evaluate(workboard) == []


def test_sync_inferred_expires_stale_rows_without_supporting_evidence(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block=(
            "- agent=claude; name=Claude; role=solo; parent=none; scope=thomas/cli; task=Inferred work in thomas/cli; "
            "inferred=true; confidence=high; source=presence-monitor; last_inferred_at=2026-02-25T11:40:00+00:00; "
            "evidence_scope=thomas/cli; evidence_paths=thomas/cli/main.py"
        ),
        active_tasks_block=(
            f"- task_id={mod._inferred_task_id('claude', 'thomas/cli')}; agent=claude; scope=thomas/cli; summary=Inferred work in thomas/cli; status=in_progress; "
            "name=Claude; role=solo; parent=none; inferred=true; confidence=high; source=presence-monitor; last_inferred_at=2026-02-25T11:40:00+00:00"
        ),
    )
    state_path = tmp_path / "runtime" / "coordination" / "inferred_presence_sync.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "entry_key": "claude::thomas/cli",
                        "agent_id": "claude",
                        "display_name": "Claude",
                        "scope": "thomas/cli",
                        "confidence": "high",
                        "first_seen": "2026-02-25T11:35:00+00:00",
                        "last_seen": "2026-02-25T11:40:00+00:00",
                        "linked_active_task_id": mod._inferred_task_id("claude", "thomas/cli"),
                        "sync_state": "created",
                    }
                ],
                "inferred_applied": [],
                "inferred_suppressed": [],
                "inferred_expired": [],
                "updated_at": "2026-02-25T11:40:00+00:00",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        mod.agent_presence,
        "collect_presence",
        lambda **_: {
            "success": True,
            "repo_root": str(tmp_path),
            "generated_at": "2026-02-25T12:00:00+00:00",
            "active_count": 0,
            "agents": [],
            "recent_activity": [],
            "services": [],
            "warnings": [],
            "conflicts": [],
            "inferred_candidates": [],
            "inferred_applied": [],
            "inferred_suppressed": [],
            "inferred_expired": [],
        },
    )

    rc = mod.run(
        ["--workboard", str(workboard), "--sync-inferred", "--apply", "--now", "2026-02-25T12:00:00+00:00", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["expired_count"] == 1
    assert "inferred=true" not in text
    assert gate.evaluate(workboard) == []
