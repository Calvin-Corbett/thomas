from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import scripts.crew.workboard.message as mod
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


def test_read_only_views_tolerate_missing_workboard(tmp_path: Path, capsys, monkeypatch) -> None:
    missing = tmp_path / "missing" / "WORKBOARD.md"
    monkeypatch.setenv("AGENT_ID", "Codex")

    for args, action in (
        (["--list", "--all"], "list"),
        (["--inbox"], "inbox"),
        (["--current", "--peer", "Claude"], "current"),
    ):
        rc = mod.run(["--workboard", str(missing), *args, "--json"])
        payload = json.loads(capsys.readouterr().out)

        assert rc == 0
        assert payload["ok"] is True
        assert payload["action"] == action
        assert payload["missing_workboard"] is True
        assert payload["message_count"] == 0
        assert payload["messages"] == []

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
