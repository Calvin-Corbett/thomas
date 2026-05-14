from __future__ import annotations

import json
from pathlib import Path

import scripts.crew.workboard.brainstorm as mod
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


def test_start_all_hands_creates_session_and_summons(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block=(
            "- agent=Codex 1; scope=scripts/a.py; task=lane a\n" "- agent=Codex 2; scope=scripts/b.py; task=lane b"
        ),
        active_tasks_block=(
            "- task_id=brainstorm-target; agent=Codex 1; scope=scripts/a.py; summary=lane a; status=active\n"
            "- task_id=lane-b; agent=Codex 2; scope=scripts/b.py; summary=lane b; status=active"
        ),
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--start",
            "--task-id",
            "brainstorm-target",
            "--summary",
            "brainstorm architecture improvements",
            "--objective",
            "align all agents on final execution plan",
            "--facilitator",
            "task-manager-agent",
            "--all-hands",
            "--priority",
            "p0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "start"
    assert payload["session"]["mode"] == "all_hands"
    assert payload["invited_count"] == 2
    assert payload["sent_message_count"] == 2
    assert "## Brainstorm Sessions" in text
    assert "## Brainstorm Notes" in text
    assert "kind=brainstorm_call;" in text
    assert gate.evaluate(workboard) == []


def test_contributions_drive_decision_ready_state(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=scripts/a.py; task=lane a",
        active_tasks_block="- task_id=brainstorm-target; agent=Codex 1; scope=scripts/a.py; summary=lane a; status=active",
    )
    rc_start = mod.run(
        [
            "--workboard",
            str(workboard),
            "--start",
            "--task-id",
            "brainstorm-target",
            "--summary",
            "brainstorm split plan",
            "--objective",
            "pick clear implementation split",
            "--facilitator",
            "task-manager-agent",
            "--invite-agents",
            "Codex 1,Codex 2",
            "--no-summons",
            "--json",
        ]
    )
    start_payload = json.loads(capsys.readouterr().out)
    session_id = str(start_payload["session"]["session_id"])
    assert rc_start == 0

    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--contribute",
                "--session-id",
                session_id,
                "--agent",
                "Codex 1",
                "--kind",
                "proposal",
                "--summary",
                "split by workflow ownership and integration lane",
                "--json",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--contribute",
            "--session-id",
            session_id,
            "--agent",
            "Codex 2",
            "--kind",
            "risk",
            "--summary",
            "avoid scope overlaps and enforce lane-specific tests",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["state"] == "decision_ready"
    assert payload["pending_count"] == 0
    assert gate.evaluate(workboard) == []


def test_resolve_dispatches_tasks_and_broadcasts(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=scripts/a.py; task=lane a",
        active_tasks_block="- task_id=brainstorm-target; agent=Codex 1; scope=scripts/a.py; summary=lane a; status=active",
    )
    rc_start = mod.run(
        [
            "--workboard",
            str(workboard),
            "--start",
            "--task-id",
            "brainstorm-target",
            "--summary",
            "brainstorm split plan",
            "--objective",
            "pick clear implementation split",
            "--facilitator",
            "task-manager-agent",
            "--invite-agents",
            "Codex 1,Codex 2",
            "--no-summons",
            "--json",
        ]
    )
    start_payload = json.loads(capsys.readouterr().out)
    session_id = str(start_payload["session"]["session_id"])
    assert rc_start == 0

    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--contribute",
                "--session-id",
                session_id,
                "--agent",
                "Codex 1",
                "--summary",
                "proposal one",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--contribute",
                "--session-id",
                session_id,
                "--agent",
                "Codex 2",
                "--summary",
                "proposal two",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--resolve-session",
            "--session-id",
            session_id,
            "--facilitator",
            "task-manager-agent",
            "--summary",
            "approved split into command lane and test lane",
            "--dispatch-item",
            "brainstorm-followup|scripts/crew/tasks/manager.py|implement brainstorm orchestration updates",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["state"] == "resolved"
    assert payload["dispatch_count"] == 1
    assert payload["broadcast_count"] == 2
    assert "task_id=brainstorm-followup; scope=scripts/crew/tasks/manager.py;" in text
    assert "kind=brainstorm_decision;" in text
    assert gate.evaluate(workboard) == []
