"""The message script's current-thread view and audit explain what the inbox hides.

Split from test_workboard_message_script.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.crew.workboard.message as mod

from tests._workboard_message_fakes import _write_workboard


def test_current_thread_view_includes_acked_inbound_and_open_outbound(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex")
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-acked-in",
                "--from-agent",
                "Claude",
                "--to-agent",
                "Codex",
                "--summary",
                "plan from claude",
                "--priority",
                "p0",
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
                "--ack",
                "--msg-id",
                "msg-acked-in",
                "--by",
                "Codex",
                "--decision",
                "approved",
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
                "msg-open-out",
                "--from-agent",
                "Codex",
                "--to-agent",
                "Claude",
                "--summary",
                "implementation status",
                "--priority",
                "p0",
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
                "Other",
                "--to-agent",
                "Codex",
                "--summary",
                "stale unrelated",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(["--workboard", str(workboard), "--current", "--peer", "Claude", "--json"])
    payload = json.loads(capsys.readouterr().out)
    rows = {row["msg_id"]: row for row in payload["messages"]}

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "current"
    assert set(rows) == {"msg-acked-in", "msg-open-out"}
    assert rows["msg-acked-in"]["direction"] == "incoming"
    assert rows["msg-acked-in"]["awaiting"] == "thread"
    assert rows["msg-open-out"]["direction"] == "outgoing"
    assert rows["msg-open-out"]["awaiting"] == "peer"


def test_current_thread_view_can_filter_by_task_id(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex")
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-target",
                "--from-agent",
                "Codex",
                "--to-agent",
                "Claude",
                "--kind",
                "handoff",
                "--task-id",
                "evolve-self-p0",
                "--summary",
                "target review packet",
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
                "msg-other-task",
                "--from-agent",
                "Codex",
                "--to-agent",
                "Claude",
                "--kind",
                "handoff",
                "--task-id",
                "other-task",
                "--summary",
                "different review packet",
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
                "msg-taskless",
                "--from-agent",
                "Claude",
                "--to-agent",
                "Codex",
                "--summary",
                "old acked context",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--current",
            "--peer",
            "Claude",
            "--task-id",
            "evolve-self-p0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["task_id"] == "evolve-self-p0"
    assert payload["message_count"] == 1
    assert payload["messages"][0]["msg_id"] == "msg-target"


def test_audit_explains_empty_inbox_when_current_thread_waits_on_peer(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex")
    monkeypatch.setattr(mod, "_now_iso", lambda: "2026-01-02T00:00:00+00:00")
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-open-out",
                "--from-agent",
                "Codex",
                "--to-agent",
                "Claude",
                "--kind",
                "handoff",
                "--task-id",
                "evolve-self-p0",
                "--summary",
                "review packet waiting on Claude",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()
    monkeypatch.setattr(mod, "_now_iso", lambda: "2026-01-01T00:00:00+00:00")
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-older-out",
                "--from-agent",
                "Codex",
                "--to-agent",
                "Claude",
                "--kind",
                "handoff",
                "--task-id",
                "evolve-self-p0",
                "--summary",
                "older review packet waiting on Claude",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--audit",
            "--peer",
            "Claude",
            "--task-id",
            "evolve-self-p0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["canonical_inbox_count"] == 0
    assert payload["canonical_current_count"] == 2
    assert payload["awaiting_peer"] == 2
    assert payload["awaiting_peer_msg_id"] == "msg-older-out"
    assert payload["awaiting_peer_oldest_seconds"] > 0
    assert "waiting on the peer" in payload["diagnosis"]


def test_audit_task_filter_flags_cross_task_open_p0_from_peer(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex")
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-waiting-on-peer",
                "--from-agent",
                "Codex",
                "--to-agent",
                "Claude",
                "--kind",
                "status",
                "--task-id",
                "evolve-self-loop",
                "--summary",
                "review packet waiting on Claude",
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
                "msg-hidden-p0",
                "--from-agent",
                "Claude",
                "--to-agent",
                "Codex",
                "--kind",
                "blocker",
                "--priority",
                "p0",
                "--task-id",
                "evolve-self-p0-2026-06-22",
                "--summary",
                "stop the line on the p0 task",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--audit",
            "--peer",
            "Claude",
            "--task-id",
            "evolve-self-loop",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["canonical_inbox_count"] == 0
    assert payload["awaiting_peer"] == 1
    assert payload["cross_task_open_p0_count"] == 1
    assert payload["cross_task_open_p0"][0]["msg_id"] == "msg-hidden-p0"
    assert payload["cross_task_open_p0"][0]["task_id"] == "evolve-self-p0-2026-06-22"
    assert "task filter hides open p0" in payload["diagnosis"]


def test_audit_flags_noncanonical_peer_text_that_inbox_ignores(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    workboard.write_text(
        workboard.read_text(encoding="utf-8")
        + "\n## Agent Message Traffic\n\nClaude -> Codex: waiting for your reply on the evolve loop.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_ID", "Codex")

    rc = mod.run(["--workboard", str(workboard), "--audit", "--peer", "Claude", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["problem_count"] == 1
    assert payload["candidate_mention_count"] == 1
    assert payload["candidate_mentions"][0]["kind"] == "noncanonical_text"
    assert "noncanonical agent mentions" in payload["diagnosis"]


def test_audit_flags_peer_message_routed_to_process_identity(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex")
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--send",
                "--msg-id",
                "msg-process-route",
                "--from-agent",
                "Claude",
                "--to-agent",
                "process:4242",
                "--kind",
                "handoff",
                "--task-id",
                "evolve-self-p0",
                "--summary",
                "reply landed on a process identity",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--audit",
            "--peer",
            "Claude",
            "--task-id",
            "evolve-self-p0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["canonical_inbox_count"] == 0
    assert payload["identity_mismatch_count"] == 1
    assert payload["identity_mismatches"][0]["msg_id"] == "msg-process-route"
    assert payload["identity_mismatches"][0]["actual_to"] == "process:4242"
    assert "noncanonical identities" in payload["diagnosis"]


def test_audit_reports_stale_process_identity_without_failing_broad_audit(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    workboard.write_text(
        workboard.read_text(encoding="utf-8")
        + (
            "\n## Agent Message Traffic\n\n"
            "- msg_id=msg-old-process; from=Claude; to=process:4242; task_id=none; "
            "kind=coordination; priority=p1; state=open; summary=old process route; "
            "requested_action=stale coordination notice; decision=pending; "
            "created_at=2026-01-01T00:00:00+00:00; updated_at=2026-01-01T00:00:00+00:00; "
            "updated_by=Claude\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_ID", "Codex")

    rc = mod.run(["--workboard", str(workboard), "--audit", "--peer", "Claude", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["problem_count"] == 0
    assert payload["identity_mismatch_count"] == 0
    assert payload["stale_identity_mismatch_count"] == 1
    assert payload["stale_identity_mismatches"][0]["msg_id"] == "msg-old-process"


def test_audit_flags_malformed_message_bullets_that_break_inbox(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    workboard.write_text(
        workboard.read_text(encoding="utf-8")
        + "\n## Agent Message Traffic\n\n- msg_id=bad; from=Claude; to=Codex; brokenfield\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_ID", "Codex")

    rc = mod.run(["--workboard", str(workboard), "--audit", "--peer", "Claude", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["parse_error_count"] == 1
    assert payload["candidate_mention_count"] == 1
    assert payload["candidate_mentions"][0]["kind"] == "malformed_bullet"
    assert "parse errors" in payload["diagnosis"]
