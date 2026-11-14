"""The message script replaces open threads, serializes sends, and answers the inbox.

Split from test_workboard_message_script.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import scripts.crew.workboard.message as mod
import scripts.forge.gates.workboard_claims as gate

from tests._workboard_message_fakes import _write_workboard


def test_send_replace_open_resolves_prior_matching_thread(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-old",
                "--from-agent",
                "codex",
                "--to-agent",
                "claude",
                "--kind",
                "handoff",
                "--task-id",
                "evolve-self-p0",
                "--summary",
                "old packet",
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
                "msg-other",
                "--from-agent",
                "codex",
                "--to-agent",
                "claude",
                "--kind",
                "handoff",
                "--task-id",
                "other-task",
                "--summary",
                "unrelated packet",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--send",
            "--replace-open",
            "--msg-id",
            "msg-new",
            "--from-agent",
            "codex",
            "--to-agent",
            "claude",
            "--kind",
            "handoff",
            "--task-id",
            "evolve-self-p0",
            "--summary",
            "new packet",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    ok, list_payload = mod.list_messages(workboard)
    rows = {row["msg_id"]: row for row in list_payload["messages"]}

    assert rc == 0
    assert payload["ok"] is True
    assert payload["replaced_count"] == 1
    assert payload["replaced_messages"][0]["msg_id"] == "msg-old"
    assert payload["message"]["msg_id"] == "msg-new"
    assert ok is True
    assert rows["msg-old"]["state"] == "resolved"
    assert rows["msg-old"]["updated_by"] == "codex"
    assert rows["msg-new"]["state"] == "open"
    assert rows["msg-other"]["state"] == "open"
    assert gate.evaluate(workboard) == []


def test_send_replace_open_requires_real_task_id(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-old",
                "--from-agent",
                "codex",
                "--to-agent",
                "claude",
                "--kind",
                "coordination",
                "--summary",
                "old taskless packet",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--send",
            "--replace-open",
            "--msg-id",
            "msg-new",
            "--from-agent",
            "codex",
            "--to-agent",
            "claude",
            "--kind",
            "coordination",
            "--summary",
            "new taskless packet",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    ok, list_payload = mod.list_messages(workboard)
    rows = {row["msg_id"]: row for row in list_payload["messages"]}

    assert rc == 1
    assert payload["ok"] is False
    assert "--replace-open requires a non-none --task-id" in payload["error"]
    assert ok is True
    assert set(rows) == {"msg-old"}
    assert rows["msg-old"]["state"] == "open"


def test_send_replace_open_peer_resolves_same_peer_thread_only(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    seeds = [
        ("msg-old-task", "codex", "claude", "handoff", "task-a"),
        ("msg-old-status", "codex", "claude", "status", "task-b"),
        ("msg-inbound", "claude", "codex", "status", "task-a"),
        ("msg-other-peer", "codex", "gemini", "status", "task-a"),
    ]
    for msg_id, sender, recipient, kind, task_id in seeds:
        assert (
            mod.run(
                [
                    "--workboard",
                    str(workboard),
                    "--send",
                    "--msg-id",
                    msg_id,
                    "--from-agent",
                    sender,
                    "--to-agent",
                    recipient,
                    "--kind",
                    kind,
                    "--task-id",
                    task_id,
                    "--summary",
                    f"{msg_id} packet",
                ]
            )
            == 0
        )
        _ = capsys.readouterr()

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--send",
            "--replace-open-peer",
            "--msg-id",
            "msg-current",
            "--from-agent",
            "codex",
            "--to-agent",
            "claude",
            "--kind",
            "coordination",
            "--summary",
            "single current packet",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    ok, list_payload = mod.list_messages(workboard)
    rows = {row["msg_id"]: row for row in list_payload["messages"]}

    assert rc == 0
    assert payload["ok"] is True
    assert payload["replaced_count"] == 2
    assert {row["msg_id"] for row in payload["replaced_messages"]} == {"msg-old-task", "msg-old-status"}
    assert ok is True
    assert rows["msg-old-task"]["state"] == "resolved"
    assert rows["msg-old-status"]["state"] == "resolved"
    assert rows["msg-inbound"]["state"] == "open"
    assert rows["msg-other-peer"]["state"] == "open"
    assert rows["msg-current"]["state"] == "open"


def test_concurrent_sends_are_serialized_without_lost_messages(tmp_path: Path) -> None:
    workboard = _write_workboard(tmp_path)

    def _send(idx: int) -> bool:
        ok, _payload = mod.send_message(
            workboard,
            sender="claude",
            recipient="codex",
            summary=f"concurrent message {idx}",
            require_claims_to_have_active_task=False,
        )
        return ok

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(_send, range(60)))

    ok, payload = mod.list_messages(workboard, recipient="codex", state="open")

    assert all(results)
    assert ok is True
    assert payload["message_count"] == 60
    assert len({row["msg_id"] for row in payload["messages"]}) == 60


def test_ack_and_resolve_message_updates_state_and_decision(tmp_path: Path, capsys) -> None:
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
                "scope conflict with codex 2",
                "--json",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc_ack = mod.run(
        [
            "--workboard",
            str(workboard),
            "--ack",
            "--msg-id",
            "msg-1",
            "--by",
            "task-manager-agent",
            "--decision",
            "approved",
            "--json",
        ]
    )
    ack_payload = json.loads(capsys.readouterr().out)
    assert rc_ack == 0
    assert ack_payload["message"]["state"] == "acked"
    assert ack_payload["message"]["decision"] == "approved"

    rc_resolve = mod.run(
        [
            "--workboard",
            str(workboard),
            "--resolve",
            "--msg-id",
            "msg-1",
            "--by",
            "Codex 1",
            "--decision",
            "approved",
            "--json",
        ]
    )
    resolve_payload = json.loads(capsys.readouterr().out)
    assert rc_resolve == 0
    assert resolve_payload["message"]["state"] == "resolved"
    assert resolve_payload["message"]["updated_by"] == "Codex 1"
    assert gate.evaluate(workboard) == []


def test_list_filters_by_recipient(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-a",
                "--from-agent",
                "Codex 1",
                "--to-agent",
                "Codex 2",
                "--summary",
                "coord one",
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
                "msg-b",
                "--from-agent",
                "Codex 3",
                "--to-agent",
                "Codex 4",
                "--summary",
                "coord two",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--list",
            "--to-agent",
            "Codex 2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["message_count"] == 1
    assert payload["messages"][0]["msg_id"] == "msg-a"


def test_list_defaults_to_current_agent_unread_inbox(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex 2")
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
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-b",
                "--from-agent",
                "Claude",
                "--to-agent",
                "Codex 3",
                "--summary",
                "coord two",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(["--workboard", str(workboard), "--list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["message_count"] == 1
    assert payload["messages"][0]["msg_id"] == "msg-a"
    assert payload["messages"][0]["age_seconds"].isdigit()


def test_inbox_alias_defaults_to_current_agent_unread_inbox(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex")
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-inbox",
                "--from-agent",
                "Claude",
                "--to-agent",
                "Codex",
                "--summary",
                "new coordination",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(["--workboard", str(workboard), "--inbox", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "inbox"
    assert payload["message_count"] == 1
    assert payload["messages"][0]["msg_id"] == "msg-inbox"


def test_read_only_views_refuse_a_missing_workboard(tmp_path: Path, capsys, monkeypatch) -> None:
    # A board that is not there is not an empty inbox: reporting zero messages
    # let a gate pass on a path nobody ever wrote to.
    missing = tmp_path / "missing" / "WORKBOARD.md"
    monkeypatch.setenv("AGENT_ID", "Codex")

    for args, action in (
        (["--list", "--all"], "list"),
        (["--inbox"], "inbox"),
        (["--current", "--peer", "Claude"], "current"),
    ):
        rc = mod.run(["--workboard", str(missing), *args, "--json"])
        payload = json.loads(capsys.readouterr().out)

        assert rc == 1
        assert payload["ok"] is False
        assert payload["action"] == action
        assert payload["missing_workboard"] is True
        assert str(missing) in payload["error"]

    rc_send = mod.run(
        [
            "--workboard",
            str(missing),
            "--send",
            "--from-agent",
            "Codex",
            "--to-agent",
            "Claude",
            "--summary",
            "should fail closed",
            "--json",
        ]
    )
    send_payload = json.loads(capsys.readouterr().out)

    assert rc_send == 1
    assert send_payload["ok"] is False
    assert "missing workboard file" in send_payload["error"]
