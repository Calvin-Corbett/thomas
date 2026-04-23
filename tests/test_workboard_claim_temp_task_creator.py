from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_claims as gate
import scripts.workboard_claim as mod

from tests.workboard_claim_test_helpers import write_workboard as _write_workboard


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
    assert "can release temporary task creator assignment" in payload_release["error"]


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

    assert rc_release == 1
    assert payload_release["ok"] is False
    assert payload_release["released_count"] == 0
    assert payload_release["release_errors"][0]["lease_agent"].startswith("temp-task-creator")
    assert "presence gate requires override" in payload_release["release_errors"][0]["error"]
    assert "TEMP-TASK-CREATOR" in text
    assert gate.evaluate(workboard) == []


def test_release_temp_task_creator_does_not_force_override_flags(tmp_path: Path, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active; name=Prime; role=parent; parent=none",
    )
    monkeypatch.setattr(mod, "_send_temp_task_creator_notice", lambda *args, **kwargs: (True, "msg-temp-5"))
    ok_claim, _payload_claim = mod.dispatch_workers(workboard, parent_agent="Codex 3")
    assert ok_claim is True

    calls: dict[str, object] = {}

    def _fake_release(workboard_path, **kwargs):  # noqa: ANN001
        calls["workboard_path"] = workboard_path
        calls.update(kwargs)
        return True, "released"

    monkeypatch.setattr(mod, "release", _fake_release)

    ok_release, payload_release = mod.release_temp_task_creator(
        workboard,
        actor_agent="task-manager-agent",
    )

    assert ok_release is True
    assert payload_release["released_count"] == 1
    assert calls["agent"].startswith("temp-task-creator")
    assert "allow_dirty" not in calls
    assert "dirty_reason" not in calls
    assert "allow_presence_override" not in calls
    assert "presence_override_reason" not in calls
