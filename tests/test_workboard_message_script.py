from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
