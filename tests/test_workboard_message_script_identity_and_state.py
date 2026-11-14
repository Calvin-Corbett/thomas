"""The message script fails closed without identity and guards every state transition.

Split from test_workboard_message_script.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.crew.workboard.message as mod
import scripts.forge.gates.workboard_claims as gate

from tests._workboard_message_fakes import _write_workboard


def test_list_without_identity_fails_closed(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    for key in mod.AGENT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("CODEX_SHELL", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    rc = mod.run(["--workboard", str(workboard), "--list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "--list defaults to this agent's unread inbox" in payload["error"]


def test_list_all_preserves_board_wide_view_without_identity(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    for key in mod.AGENT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("CODEX_SHELL", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-a",
                "--from-agent",
                "Claude",
                "--to-agent",
                "Codex 2",
                "--summary",
                "coord one",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(["--workboard", str(workboard), "--list", "--all", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["message_count"] == 1


def test_unread_inbox_sorts_p0_before_high_volume_p2(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex")
    for idx in range(6):
        assert (
            mod.run(
                [
                    "--workboard",
                    str(workboard),
                    "--send",
                    "--msg-id",
                    f"msg-p2-{idx}",
                    "--from-agent",
                    "Claude",
                    "--to-agent",
                    "Codex",
                    "--summary",
                    f"low priority {idx}",
                    "--priority",
                    "p2",
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
                "--send",
                "--msg-id",
                "msg-p0",
                "--from-agent",
                "Claude",
                "--to-agent",
                "Codex",
                "--summary",
                "urgent coordination",
                "--priority",
                "p0",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(["--workboard", str(workboard), "--list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["message_count"] == 7
    assert payload["messages"][0]["msg_id"] == "msg-p0"


def test_brainstorm_message_kind_is_supported(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--send",
            "--from-agent",
            "task-manager-agent",
            "--to-agent",
            "Codex 1",
            "--summary",
            "brainstorm summon for architecture lane",
            "--task-id",
            "brainstorm-target",
            "--kind",
            "brainstorm_call",
            "--priority",
            "p0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["message"]["kind"] == "brainstorm_call"
    assert gate.evaluate(workboard) == []


def test_ack_rejects_non_recipient_actor(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-1",
                "--from-agent",
                "Codex 1",
                "--to-agent",
                "task-manager-agent",
                "--summary",
                "requesting scope approval",
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
            "--ack",
            "--msg-id",
            "msg-1",
            "--by",
            "Codex 1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert "only recipient" in payload["error"]


def test_ack_uses_agent_identity_when_by_is_omitted(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-1",
                "--from-agent",
                "Claude",
                "--to-agent",
                "Codex",
                "--summary",
                "please ack",
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
            "--ack",
            "--msg-id",
            "msg-1",
            "--agent",
            "Codex",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["message"]["state"] == "acked"
    assert payload["message"]["updated_by"] == "Codex"


def test_state_transitions_and_resolve_actor_guard(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-2",
                "--from-agent",
                "Codex 1",
                "--to-agent",
                "Codex 2",
                "--summary",
                "handoff context",
                "--json",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc_bad_resolve = mod.run(
        [
            "--workboard",
            str(workboard),
            "--resolve",
            "--msg-id",
            "msg-2",
            "--by",
            "Codex 3",
            "--json",
        ]
    )
    bad_resolve_payload = json.loads(capsys.readouterr().out)
    assert rc_bad_resolve == 1
    assert bad_resolve_payload["ok"] is False
    assert "only sender" in bad_resolve_payload["error"]

    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--ack",
                "--msg-id",
                "msg-2",
                "--by",
                "Codex 2",
                "--json",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc_second_ack = mod.run(
        [
            "--workboard",
            str(workboard),
            "--ack",
            "--msg-id",
            "msg-2",
            "--by",
            "Codex 2",
            "--json",
        ]
    )
    second_ack_payload = json.loads(capsys.readouterr().out)
    assert rc_second_ack == 1
    assert second_ack_payload["ok"] is False
    assert "already in state `acked`" in second_ack_payload["error"]

    rc_resolve = mod.run(
        [
            "--workboard",
            str(workboard),
            "--resolve",
            "--msg-id",
            "msg-2",
            "--by",
            "Codex 1",
            "--json",
        ]
    )
    resolve_payload = json.loads(capsys.readouterr().out)
    assert rc_resolve == 0
    assert resolve_payload["ok"] is True
    assert resolve_payload["message"]["state"] == "resolved"


def test_send_rejects_taskless_non_coordination_kind(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--send",
            "--from-agent",
            "Codex 1",
            "--to-agent",
            "task-manager-agent",
            "--summary",
            "worker online status without task id",
            "--kind",
            "status",
            "--task-id",
            "none",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert "task_id is required for kind `status`" in payload["error"]
