from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.crew.workboard import message as message_tool
from scripts.forge import commit_master
from scripts.forge.gates import workboard_inbox as mod
from scripts.forge.gates import workboard_inbox_hook


def _write_workboard(tmp_path: Path) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims\n\n"
            "- none\n\n"
            "## Active Tasks\n\n"
            "- none\n\n"
            "## Issues / Blockers\n\n"
            "- none\n\n"
            "## Up For Grabs\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )
    return path


def test_inbox_gate_passes_with_no_unread_messages(tmp_path: Path) -> None:
    ok, payload = mod.evaluate(workboard_path=_write_workboard(tmp_path), agent="codex")

    assert ok is True
    assert payload["ok"] is True
    assert payload["unread_count"] == 0


def test_inbox_gate_blocks_unread_messages_until_acked(tmp_path: Path) -> None:
    workboard = _write_workboard(tmp_path)
    ok_send, _payload = message_tool.send_message(
        workboard,
        sender="claude",
        recipient="codex",
        summary="stop before touching scripts",
        priority="p0",
        requested_action="ack before commit",
        require_claims_to_have_active_task=False,
    )
    assert ok_send is True

    ok, payload = mod.evaluate(workboard_path=workboard, agent="codex")
    assert ok is False
    assert payload["ok"] is False
    assert payload["unread_count"] == 1
    assert payload["unread_messages"][0]["from"] == "claude"

    ok_ack, _ack_payload = message_tool.ack_message(workboard, msg_id="msg-1", actor="codex")
    assert ok_ack is False

    ok_list, list_payload = message_tool.list_messages(workboard, recipient="codex", state="open")
    assert ok_list is True
    msg_id = list_payload["messages"][0]["msg_id"]
    ok_ack, _ack_payload = message_tool.ack_message(workboard, msg_id=str(msg_id), actor="codex")
    assert ok_ack is True

    ok_after, payload_after = mod.evaluate(workboard_path=workboard, agent="codex")
    assert ok_after is True
    assert payload_after["unread_count"] == 0


def test_inbox_gate_requires_identity(tmp_path: Path, monkeypatch) -> None:
    for key in message_tool.AGENT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("CODEX_SHELL", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    ok, payload = mod.evaluate(workboard_path=_write_workboard(tmp_path))

    assert ok is False
    assert payload["ok"] is False
    assert "agent identity is required" in payload["error"]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)


def _init_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    workboard = repo / "plans" / "thomas" / "WORKBOARD.md"
    workboard.parent.mkdir(parents=True, exist_ok=True)
    workboard.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims\n\n"
            "- none\n\n"
            "## Active Tasks\n\n"
            "- none\n\n"
            "## Issues / Blockers\n\n"
            "- none\n\n"
            "## Up For Grabs\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo, workboard


def test_commit_master_submission_blocks_relevant_inbox_until_acked(tmp_path: Path) -> None:
    repo, workboard = _init_repo(tmp_path)
    ok_unrelated, unrelated_payload = message_tool.send_message(
        workboard,
        sender="claude",
        recipient="codex",
        summary="FYI no overlap with submitted file",
        priority="p1",
        requested_action="watch docs/README.md later",
        require_claims_to_have_active_task=False,
    )
    assert ok_unrelated is True
    (repo / "src").mkdir()
    (repo / "src" / "feature.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "src/feature.py")
    layout = commit_master.CageLayout(root=tmp_path / "cage")
    layout.ensure()

    submission = commit_master.create_submission(
        layout=layout,
        repo=repo,
        agent="codex",
        message="submit feature",
        base="HEAD",
        workboard=workboard,
        submission_id="sub-unrelated-ok",
    )
    assert (submission / "submission.json").exists()

    ok_ack, _ack_payload = message_tool.ack_message(
        workboard,
        msg_id=str(unrelated_payload["message"]["msg_id"]),
        actor="codex",
    )
    assert ok_ack is True

    ok_send, send_payload = message_tool.send_message(
        workboard,
        sender="claude",
        recipient="codex",
        summary="do not submit src/feature.py yet",
        priority="p1",
        requested_action="ack before submitting src/feature.py",
        require_claims_to_have_active_task=False,
    )
    assert ok_send is True

    with pytest.raises(commit_master.InboxBlockedError):
        commit_master.create_submission(
            layout=layout,
            repo=repo,
            agent="codex",
            message="submit feature",
            base="HEAD",
            workboard=workboard,
            submission_id="sub-feature-blocked",
        )

    msg_id = str(send_payload["message"]["msg_id"])
    ok_ack, _ack_payload = message_tool.ack_message(workboard, msg_id=msg_id, actor="codex")
    assert ok_ack is True
    submission = commit_master.create_submission(
        layout=layout,
        repo=repo,
        agent="codex",
        message="submit feature",
        base="HEAD",
        workboard=workboard,
        submission_id="sub-feature-ok",
    )
    assert (submission / "submission.json").exists()


def test_claude_hook_blocks_edit_tools_with_unread_messages(tmp_path: Path) -> None:
    workboard = _write_workboard(tmp_path)
    ok_send, _payload = message_tool.send_message(
        workboard,
        sender="codex",
        recipient="claude",
        summary="stop before edit",
        priority="p0",
        require_claims_to_have_active_task=False,
    )
    assert ok_send is True

    ok, message = workboard_inbox_hook.evaluate_hook(
        hook_payload={"tool_name": "Write", "tool_input": {"file_path": "scripts/example.py"}},
        workboard_path=workboard,
        agent="claude",
    )

    assert ok is False
    assert "Unread Thomas workboard messages" in message
    assert "stop before edit" in message


def test_claude_hook_allows_single_ack_command_with_unread_messages(tmp_path: Path) -> None:
    workboard = _write_workboard(tmp_path)
    ok_send, _payload = message_tool.send_message(
        workboard,
        sender="codex",
        recipient="claude",
        summary="ack me",
        priority="p0",
        require_claims_to_have_active_task=False,
    )
    assert ok_send is True

    ok, message = workboard_inbox_hook.evaluate_hook(
        hook_payload={
            "tool_name": "Bash",
            "tool_input": {
                "command": "python scripts/crew/workboard/message.py --ack --msg-id msg-test --agent claude"
            },
        },
        workboard_path=workboard,
        agent="claude",
    )

    assert ok is True
    assert message == ""
