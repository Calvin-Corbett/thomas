from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import scripts.crew.workboard.message as mod
import scripts.forge.gates.workboard_claims as gate

from tests._workboard_message_fakes import _write_workboard


def test_send_creates_message_section_and_entry(tmp_path: Path, capsys) -> None:
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
            "need scope approval",
            "--task-id",
            "models-lane",
            "--kind",
            "scope_change",
            "--priority",
            "p0",
            "--requested-action",
            "approve scope extension",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "send"
    assert payload["message"]["state"] == "open"
    assert "## Agent Message Traffic" in text
    assert "from=Codex 1;" in text
    assert "to=task-manager-agent;" in text
    assert gate.evaluate(workboard) == []


def test_canonical_repo_root_anchors_to_one_board() -> None:
    # The default board + lock must anchor to the PRIMARY worktree so every
    # linked worktree shares ONE coordination surface. Resolver must return a
    # real repo root (plans/thomas present) and the default board lives under it.
    root = mod._canonical_repo_root()
    assert (root / "plans" / "thomas").exists(), root
    assert root / "plans" / "thomas" / "WORKBOARD.md" == mod.DEFAULT_WORKBOARD
    assert mod.LOCK_FILE.parent == root / "runtime" / "coordination"


def test_send_reports_and_verifies_delivery_board(tmp_path: Path, capsys) -> None:
    # A send must report WHICH board it wrote and only succeed if the message is
    # actually present there (no silent misdelivery / lost-write reporting PASS).
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--send",
            "--from-agent",
            "Claude",
            "--to-agent",
            "Codex",
            "--summary",
            "delivery check",
            "--kind",
            "coordination",
            "--priority",
            "p1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    # Delivery target is surfaced and matches the board actually written.
    assert payload["workboard"] == str(workboard)
    msg_id = payload["message"]["msg_id"]
    assert msg_id in workboard.read_text(encoding="utf-8")


def test_cli_accepts_leading_action_and_board_alias(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "send",
                "--board",
                str(workboard),
                "--from-agent",
                "Codex",
                "--to-agent",
                "Claude",
                "--summary",
                "compat packet",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc_audit = mod.run(["audit", "--board", str(workboard), "--agent", "Codex", "--peer", "Claude", "--json"])
    audit_payload = json.loads(capsys.readouterr().out)
    assert rc_audit == 0
    assert audit_payload["ok"] is True
    assert audit_payload["awaiting_peer"] == 1

    rc_current = mod.run(["current", "--board", str(workboard), "--agent", "Codex", "--peer", "Claude", "--json"])
    current_payload = json.loads(capsys.readouterr().out)
    assert rc_current == 0
    assert current_payload["ok"] is True
    assert current_payload["messages"][0]["msg_id"]


def test_script_entry_accepts_leading_action_and_board_alias(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--send",
                "--workboard",
                str(workboard),
                "--from-agent",
                "Codex",
                "--to-agent",
                "Claude",
                "--summary",
                "entry compat packet",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "message.py",
            "audit",
            "--board",
            str(workboard),
            "--agent",
            "Codex",
            "--peer",
            "Claude",
            "--json",
        ],
    )

    rc = mod.run()
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["awaiting_peer"] == 1


def test_wait_returns_ready_when_inbound_message_is_open(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--from-agent",
                "Claude",
                "--to-agent",
                "Codex",
                "--summary",
                "verdict ready",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "wait",
            "--board",
            str(workboard),
            "--agent",
            "Codex",
            "--peer",
            "Claude",
            "--timeout-seconds",
            "0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["wait_status"] == "ready"
    assert payload["timed_out"] is False
    assert payload["awaiting_me"] == 1


def test_wait_times_out_when_thread_is_waiting_on_peer(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--from-agent",
                "Codex",
                "--to-agent",
                "Claude",
                "--summary",
                "waiting for review",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "wait",
            "--board",
            str(workboard),
            "--agent",
            "Codex",
            "--peer",
            "Claude",
            "--timeout-seconds",
            "0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["wait_status"] == "timeout"
    assert payload["timed_out"] is True
    assert payload["awaiting_me"] == 0
    assert payload["awaiting_peer"] == 1


def test_wait_fail_on_timeout_returns_nonzero(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--from-agent",
                "Codex",
                "--to-agent",
                "Claude",
                "--summary",
                "waiting for review",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "wait",
            "--board",
            str(workboard),
            "--agent",
            "Codex",
            "--peer",
            "Claude",
            "--timeout-seconds",
            "0",
            "--fail-on-timeout",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["wait_status"] == "timeout"
    assert payload["timed_out"] is True
    assert "timed out waiting for inbound message" in payload["error"]


def test_wait_fail_on_timeout_still_succeeds_when_ready(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--from-agent",
                "Claude",
                "--to-agent",
                "Codex",
                "--summary",
                "review ready",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "wait",
            "--board",
            str(workboard),
            "--agent",
            "Codex",
            "--peer",
            "Claude",
            "--timeout-seconds",
            "0",
            "--fail-on-timeout",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["wait_status"] == "ready"
    assert payload["timed_out"] is False


def test_send_round_trips_escaped_message_text(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--send",
            "--msg-id",
            "msg-rich",
            "--from-agent",
            "Codex 1",
            "--to-agent",
            "Claude",
            "--summary",
            "proof complete; needs review",
            "--requested-action",
            "Read the probe result\nthen red-team the ranker; reply approved or rejected",
            "--json",
        ]
    )
    send_payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert send_payload["message"]["summary"] == "proof complete; needs review"
    assert "proof complete\\; needs review" in text
    assert "Read the probe result\\nthen red-team the ranker\\; reply approved or rejected" in text

    rc_list = mod.run(["--workboard", str(workboard), "--list", "--to-agent", "Claude", "--json"])
    list_payload = json.loads(capsys.readouterr().out)

    assert rc_list == 0
    assert list_payload["messages"][0]["summary"] == "proof complete; needs review"
    assert list_payload["messages"][0]["requested_action"] == (
        "Read the probe result\nthen red-team the ranker; reply approved or rejected"
    )
    assert gate.evaluate(workboard) == []
