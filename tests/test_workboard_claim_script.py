from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import scripts.check_workboard_claims as gate
import scripts.workboard_claim as mod


def _write_workboard(
    tmp_path: Path,
    claims_block: str = "- none",
    *,
    active_tasks_block: str = "- none",
    issues_block: str = "- none",
    up_for_grabs_block: str = "- none",
) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Current Priorities\n\n"
            "- Placeholder\n\n"
            "## Agent Claims (Active)\n\n"
            "Use this section to announce active ownership and prevent conflicting edits.\n"
            "Claim format:\n"
            "`- \\`agent=<id>; name=<callsign>; role=<solo|parent|worker>; parent=<id|none>; scope=<path[,path...]>; task=<short text>\\``\n\n"
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


def test_claim_adds_entry_and_removes_none_placeholder(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--claim",
            "--agent",
            "Codex 3",
            "--scope",
            "thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py,tests/prompt_pack",
            "--task",
            "dom snapshot runtime fix",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")
    lines = text.splitlines()
    claim_start, claim_end = mod._find_claim_section(lines)
    active_start, active_end = mod._find_active_tasks_section(lines)
    claim_block = "\n".join(lines[claim_start:claim_end])
    active_block = "\n".join(lines[active_start:active_end])

    assert rc == 0
    assert "Workboard claim tool: PASS" in out
    assert "- none" not in claim_block
    assert "- none" not in active_block
    assert "agent=Codex 3;" in text
    assert gate.evaluate(workboard) == []


def test_claim_updates_existing_agent_entry(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser; task=old task",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/cli/commands/browser; summary=old task; status=active",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--claim",
            "--agent",
            "codex 3",
            "--scope",
            "thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py",
            "--task",
            "new task",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")
    lines = text.splitlines()
    claim_start, claim_end = mod._find_claim_section(lines)
    active_start, active_end = mod._find_active_tasks_section(lines)
    claim_block = "\n".join(lines[claim_start:claim_end])
    active_block = "\n".join(lines[active_start:active_end])

    assert rc == 0
    assert "updated claim for `codex 3`" in out
    assert claim_block.count("agent=codex 3;") == 1
    assert active_block.count("agent=codex 3;") == 1
    assert "task=new task" in text
    assert gate.evaluate(workboard) == []


def test_release_restores_none_when_last_claim_removed(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot; status=active",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
            "--agent",
            "Codex 3",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "released claim for `Codex 3`" in out
    assert "- none" in text
    assert "agent=Codex 3;" not in text
    assert gate.evaluate(workboard) == []


def test_release_cleans_auto_inactive_issue_for_released_task(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot; status=active",
        issues_block=(
            "- issue_id=codex-3-task-inactive; task_id=codex-3-task; reporter=TaskManager; "
            "owner=TaskManager; state=open; summary=agent marked inactive reactivate or reassign"
        ),
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
            "--agent",
            "Codex 3",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "released claim for `Codex 3`" in out
    assert "cleaned_auto_inactive_issues=1" in out
    assert "issue_id=codex-3-task-inactive;" not in text
    assert gate.evaluate(workboard) == []


def test_release_fails_when_agent_claim_missing(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path, "- none")
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
            "--agent",
            "Codex 9",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "no active claim found for `Codex 9`" in out


def test_release_fails_when_claim_scope_has_dirty_files(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot; status=active",
    )
    monkeypatch.setattr(mod, "_scope_guard_supported", lambda _: True)
    monkeypatch.setattr(
        mod,
        "_claimed_scope_dirty_paths",
        lambda scopes: {
            "staged": ["thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py"],
            "unstaged": [],
            "untracked": [],
        },
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
            "--agent",
            "Codex 3",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "dirty files in claimed scope" in out
    assert "--allow-dirty-release" in out


def test_release_allow_dirty_requires_reason(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot; status=active",
    )
    monkeypatch.setattr(mod, "_scope_guard_supported", lambda _: True)
    monkeypatch.setattr(
        mod,
        "_claimed_scope_dirty_paths",
        lambda scopes: {
            "staged": [],
            "unstaged": ["thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py"],
            "untracked": [],
        },
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
            "--agent",
            "Codex 3",
            "--allow-dirty-release",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "dirty release reason is required" in out


def test_release_allow_dirty_with_reason_writes_audit(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot; status=active",
    )
    audit_log = tmp_path / "workboard_release_override_audit.jsonl"
    monkeypatch.setattr(mod, "_scope_guard_supported", lambda _: True)
    monkeypatch.setattr(mod, "RELEASE_OVERRIDE_AUDIT_LOG", audit_log)
    monkeypatch.setattr(
        mod,
        "_claimed_scope_dirty_paths",
        lambda scopes: {
            "staged": ["thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py"],
            "unstaged": [],
            "untracked": [],
        },
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
            "--agent",
            "Codex 3",
            "--allow-dirty-release",
            "--dirty-release-reason",
            "handoff in progress",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")
    rows = [line for line in audit_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = json.loads(rows[-1])

    assert rc == 0
    assert "Workboard claim tool: PASS" in out
    assert "agent=Codex 3;" not in text
    assert payload["agent"] == "Codex 3"
    assert payload["reason"] == "handoff in progress"


def test_list_shows_active_claims_only(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "\n".join(
            [
                "- none",
                "- agent=Codex 1; scope=thomas/cli/pack_bridge.py; task=no-op parity",
            ]
        ),
    )
    rc = mod.run(["--workboard", str(workboard), "--list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Workboard claim tool: PASS" in out
    assert "agent=Codex 1;" in out
    assert "- none" not in out


def test_list_json_returns_structured_roster(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 1; name=Scout; role=solo; parent=none; scope=thomas/cli/pack_bridge.py; task=no-op parity",
        active_tasks_block="- task_id=codex-1-task; agent=Codex 1; scope=thomas/cli/pack_bridge.py; summary=no-op parity; status=active",
    )
    rc = mod.run(["--workboard", str(workboard), "--list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "list"
    assert payload["active_claim_count"] == 1
    assert payload["active_claims"][0]["agent"] == "Codex 1"
    assert payload["active_claims"][0]["name"] == "Scout"


def test_claim_infers_agent_and_branch_task_when_omitted(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("THOMAS_AGENT_NAME", "Codex Auto")
    monkeypatch.setattr(mod, "_detect_branch_name", lambda: "feature/workboard-claims")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--claim",
            "--scope",
            "thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Workboard claim tool: PASS" in out
    assert "agent=Codex Auto;" in text
    assert "task=branch feature/workboard-claims" in text
    assert gate.evaluate(workboard) == []


def test_release_infers_agent_from_environment(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex Auto; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot",
        active_tasks_block="- task_id=codex-auto-task; agent=Codex Auto; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot; status=active",
    )
    monkeypatch.setenv("THOMAS_AGENT_NAME", "Codex Auto")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "released claim for `Codex Auto`" in out
    assert "- none" in text
    assert gate.evaluate(workboard) == []


def test_release_requires_agent_when_no_default_available(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path, "- none")
    monkeypatch.delenv("THOMAS_AGENT_NAME", raising=False)
    monkeypatch.delenv("CODEX_AGENT_NAME", raising=False)
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.setattr(mod, "_detect_agent_default", lambda: None)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "agent is required" in out


def test_claim_prefers_explicit_agent_id_env_when_agent_omitted(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex ID")
    monkeypatch.delenv("THOMAS_AGENT_NAME", raising=False)
    monkeypatch.delenv("CODEX_AGENT_NAME", raising=False)
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.setattr(mod, "_detect_branch_name", lambda: "feature/workboard-claims")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--claim",
            "--scope",
            "thomas/cli/main.py",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Workboard claim tool: PASS" in out
    assert "agent=Codex ID;" in text


def test_claim_and_release_use_file_lock(tmp_path: Path, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    lock_calls: list[Path] = []

    @contextmanager
    def _fake_lock(lock_file: Path, timeout: float = 10.0):
        lock_calls.append(lock_file)
        yield

    monkeypatch.setattr(mod, "_file_lock", _fake_lock)

    ok_claim, _ = mod.claim(
        workboard,
        agent="Codex Lock",
        scope="thomas/cli/main.py",
        task="lock claim",
    )
    ok_release, _ = mod.release(workboard, agent="Codex Lock")

    assert ok_claim is True
    assert ok_release is True
    assert lock_calls == [mod.LOCK_FILE, mod.LOCK_FILE]


def test_claim_adds_identity_metadata_fields(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--claim",
            "--agent",
            "Codex 3",
            "--name",
            "Prime-Orchestrator",
            "--role",
            "parent",
            "--scope",
            "thomas/cli/main.py",
            "--task",
            "identity lane",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Workboard claim tool: PASS" in out
    assert "agent=Codex 3; name=Prime-Orchestrator; role=parent; parent=none;" in text
    assert gate.evaluate(workboard) == []


def test_claim_worker_role_requires_parent(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--claim",
            "--agent",
            "Codex 3-Worker-1",
            "--name",
            "Worker-One",
            "--role",
            "worker",
            "--scope",
            "thomas/core",
            "--task",
            "worker lane",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "worker role requires --parent" in out


def test_suggest_delegation_returns_non_overlapping_candidate(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active",
        up_for_grabs_block="- task_id=task-a; scope=thomas/server/routes; summary=server lane; reported_by=bot",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--suggest-delegation",
            "--agent",
            "Codex 3",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "ready delegation suggestions" in out
    assert "task-a: server lane" in out
    assert '--agent "Codex 3-Worker-1"' in out


def test_dispatch_workers_releases_ready_and_claims_lane(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "\n".join(
            [
                "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
                "- agent=Codex 3-Worker-1; name=Prime-worker-1; role=worker; parent=Codex 3; scope=thomas/server/old; task=[READY][AUTO-01] old lane",
            ]
        ),
        active_tasks_block="\n".join(
            [
                "- task_id=codex-3-task; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active; name=Prime; role=parent; parent=none",
                "- task_id=codex-3-worker-1-task; agent=Codex 3-Worker-1; scope=thomas/server/old; summary=[READY][AUTO-01] old lane; status=active; name=Prime-worker-1; role=worker; parent=Codex 3",
            ]
        ),
        up_for_grabs_block="- task_id=task-a; scope=thomas/server/new; summary=server lane; reported_by=bot",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--dispatch-workers",
            "--agent",
            "Codex 3",
            "--dispatch-target-workers",
            "1",
            "--dispatch-release-ready",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "dispatch_workers"
    assert payload["released_workers"] == ["Codex 3-Worker-1"]
    assert payload["active_worker_count"] == 1
    assert payload["claimed_workers"][0]["task_id"] == "task-a"
    assert "summary=[WIP][AUTO-01] task-a: server lane" in text
    assert gate.evaluate(workboard) == []


def test_dispatch_workers_passes_when_no_ready_candidates(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active; name=Prime; role=parent; parent=none",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--dispatch-workers",
            "--agent",
            "Codex 3",
            "--dispatch-target-workers",
            "2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "dispatch_workers"
    assert payload["active_worker_count"] == 0
    assert payload["claimed_workers"] == []
    assert payload["ready_suggestion_count"] == 0


def test_dispatch_workers_retries_after_transient_claim_error(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active; name=Prime; role=parent; parent=none",
        up_for_grabs_block="- task_id=task-a; scope=thomas/server/new; summary=server lane; reported_by=bot",
    )

    original_claim = mod.claim
    state = {"raised": False}

    def _flaky_claim(*args, **kwargs):  # type: ignore[no-untyped-def]
        if not state["raised"]:
            state["raised"] = True
            return False, "simulated race"
        return original_claim(*args, **kwargs)

    monkeypatch.setattr(mod, "claim", _flaky_claim)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--dispatch-workers",
            "--agent",
            "Codex 3",
            "--dispatch-target-workers",
            "1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["active_worker_count"] == 1
    assert payload["claimed_workers"][0]["task_id"] == "task-a"
    assert payload["claim_errors"]


def test_dispatch_workers_claims_temp_task_creator_when_board_is_empty(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active; name=Prime; role=parent; parent=none",
    )
    monkeypatch.setattr(mod, "_send_temp_task_creator_notice", lambda *args, **kwargs: (True, "msg-temp-1"))

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--dispatch-workers",
            "--agent",
            "Codex 3",
            "--dispatch-target-workers",
            "2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["temp_task_creator"]["status"] == "acquired"
    assert payload["temp_task_creator"]["can_create_tasks"] is True
    assert payload["temp_task_creator"]["holder_agent"] == "Codex 3"
    assert payload["temp_task_creator"]["notice_status"] == "sent"
    assert "TEMP-TASK-CREATOR" in text
    assert gate.evaluate(workboard) == []


def test_dispatch_workers_temp_task_creator_is_single_owner(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "\n".join(
            [
                "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent/a; task=coord lane a",
                "- agent=Codex 4; name=Echo; role=parent; parent=none; scope=thomas/agent/b; task=coord lane b",
            ]
        ),
        active_tasks_block="\n".join(
            [
                "- task_id=codex-3-task; agent=Codex 3; scope=thomas/agent/a; summary=coord lane a; status=active; name=Prime; role=parent; parent=none",
                "- task_id=codex-4-task; agent=Codex 4; scope=thomas/agent/b; summary=coord lane b; status=active; name=Echo; role=parent; parent=none",
            ]
        ),
    )
    monkeypatch.setattr(mod, "_send_temp_task_creator_notice", lambda *args, **kwargs: (True, "msg-temp-2"))

    rc_a = mod.run(
        [
            "--workboard",
            str(workboard),
            "--dispatch-workers",
            "--agent",
            "Codex 3",
            "--json",
        ]
    )
    payload_a = json.loads(capsys.readouterr().out)
    assert rc_a == 0
    assert payload_a["temp_task_creator"]["status"] == "acquired"

    rc_b = mod.run(
        [
            "--workboard",
            str(workboard),
            "--dispatch-workers",
            "--agent",
            "Codex 4",
            "--json",
        ]
    )
    payload_b = json.loads(capsys.readouterr().out)
    assert rc_b == 0
    assert payload_b["temp_task_creator"]["status"] == "held_by_other"
    assert payload_b["temp_task_creator"]["holder_agent"] == "Codex 3"
    assert payload_b["temp_task_creator"]["can_create_tasks"] is False

    violations, claims, _active, _grabs, _issues = gate.evaluate_board(workboard)
    assert violations == []
    temp_claims = [row for row in claims if mod._is_temp_task_creator_task(row.task)]
    assert len(temp_claims) == 1


def test_release_temp_task_creator_requires_task_manager_agent(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active; name=Prime; role=parent; parent=none",
    )
    monkeypatch.setattr(mod, "_send_temp_task_creator_notice", lambda *args, **kwargs: (True, "msg-temp-3"))
    rc_claim = mod.run(
        [
            "--workboard",
            str(workboard),
            "--dispatch-workers",
            "--agent",
            "Codex 3",
            "--json",
        ]
    )
    assert rc_claim == 0
    _ = capsys.readouterr().out

    rc_release = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release-temp-task-creator",
            "--agent",
            "Codex 3",
            "--json",
        ]
    )
    payload_release = json.loads(capsys.readouterr().out)

    assert rc_release == 1
    assert payload_release["ok"] is False
    assert "only `task-manager-agent` can release temporary task creator assignment" in payload_release["error"]


def test_release_temp_task_creator_clears_lease(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active; name=Prime; role=parent; parent=none",
    )
    monkeypatch.setattr(mod, "_send_temp_task_creator_notice", lambda *args, **kwargs: (True, "msg-temp-4"))
    rc_claim = mod.run(
        [
            "--workboard",
            str(workboard),
            "--dispatch-workers",
            "--agent",
            "Codex 3",
            "--json",
        ]
    )
    assert rc_claim == 0
    _ = capsys.readouterr().out

    rc_release = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release-temp-task-creator",
            "--agent",
            "task-manager-agent",
            "--json",
        ]
    )
    payload_release = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc_release == 0
    assert payload_release["ok"] is True
    assert payload_release["released_count"] == 1
    assert "TEMP-TASK-CREATOR" not in text
    assert gate.evaluate(workboard) == []
