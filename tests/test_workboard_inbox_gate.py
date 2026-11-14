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


def test_commit_master_submission_blocks_until_inbox_is_acked(tmp_path: Path) -> None:
    repo, workboard = _init_repo(tmp_path)
    ok_send, send_payload = message_tool.send_message(
        workboard,
        sender="claude",
        recipient="codex",
        summary="do not submit yet",
        priority="p1",
        require_claims_to_have_active_task=False,
    )
    assert ok_send is True
    (repo / "feature.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "feature.py")
    layout = commit_master.CageLayout(root=tmp_path / "cage")
    layout.ensure()

    with pytest.raises(commit_master.InboxBlockedError):
        commit_master.create_submission(
            layout=layout,
            repo=repo,
            agent="codex",
            message="submit feature",
            base="HEAD",
            workboard=workboard,
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


def _ack_hook(command: str, workboard: Path) -> tuple[bool, str]:
    return workboard_inbox_hook.evaluate_hook(
        hook_payload={"tool_name": "Bash", "tool_input": {"command": command}},
        workboard_path=workboard,
        agent="claude",
    )


def _workboard_with_unread(tmp_path: Path) -> Path:
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
    return workboard


ACK = "python scripts/crew/workboard/message.py --ack --msg-id msg-test --agent claude"
INBOX = "python scripts/crew/workboard/message.py --inbox --agent claude"
DESTRUCTIVE = "rm -rf /tmp/gate-probe"


@pytest.mark.parametrize(
    "command",
    [
        f"{ACK} 2>&1 | tail -5",
        f"{ACK} | head -20",
        f"{ACK} 2>&1",
        f"{ACK}; {ACK}",
        f"{ACK} && {INBOX}",
        f"{INBOX} | grep msg-",
    ],
)
def test_hook_allows_ack_shaped_the_way_agents_actually_type_it(command: str, tmp_path: Path) -> None:
    """The escape hatch must survive pipes, redirects and chaining of allowlisted commands.

    The gate's own remediation text is a shell command. If adding `| head` makes it
    fail the gate, the instructions the gate prints cannot be followed and the gate
    becomes a deadlock: the only way to clear it is the one channel it blocks.
    """
    ok, message = _ack_hook(command, _workboard_with_unread(tmp_path))
    assert ok is True, f"ack form was blocked: {command} -> {message}"
    assert message == ""


@pytest.mark.parametrize(
    "command",
    [
        f"{DESTRUCTIVE}; {ACK}",
        f"{ACK} && {DESTRUCTIVE}",
        f"{INBOX} | bash",
        f"{INBOX} | sh",
        f"{ACK} > /tmp/gate-probe.txt",
        f"{ACK} >> /tmp/gate-probe.txt",
        "python scripts/crew/workboard/message.py --ack --msg-id $(id) --agent claude",
        "python scripts/crew/workboard/message.py --ack --msg-id `id` --agent claude",
        "python scripts/other_script.py --ack --agent claude",
        "python scripts/crew/workboard/message.py --send --to-agent codex --agent claude",
    ],
)
def test_hook_still_blocks_anything_riding_along_with_an_ack(command: str, tmp_path: Path) -> None:
    """Widening the hatch must not let arbitrary commands ride the allowlist."""
    ok, _message = _ack_hook(command, _workboard_with_unread(tmp_path))
    assert ok is False, f"non-ack command slipped through the gate: {command}"


# The allowlist splits a command into segments on ; | && and checks each one.
# It did that with a plain regex, which cannot tell a pipeline separator from a
# pipe INSIDE a quoted argument -- so `grep -oE "acked|already"` was read as two
# segments and the second, `already"`, matched no allowlist entry. A perfectly
# ordinary ack was refused. Same class for a `>` or a `$(` inside quotes.
QUOTED = 'python scripts/crew/workboard/message.py --ack --msg-id m --agent claude'
DESTRUCTIVE_TAIL = "rm -rf /tmp/gate-probe"


@pytest.mark.parametrize(
    "command",
    [
        # the exact shape that refused a real ack
        f'{QUOTED} 2>&1 | grep -oE "acked|already"',
        # a pipe inside single quotes is just a character
        f"{QUOTED} | grep -E 'open|acked'",
        # so is a redirect character inside quotes
        f'{QUOTED} | grep "a>b"',
        # and a semicolon
        f'{QUOTED} | grep "one;two"',
        # substitution syntax inside SINGLE quotes does not expand, so it is literal
        f"{QUOTED} | grep '$(not-expanded)'",
    ],
)
def test_quoted_operators_are_arguments_not_separators(command: str, tmp_path: Path) -> None:
    ok, message = _ack_hook(command, _workboard_with_unread(tmp_path))
    assert ok is True, f"a quoted operator was treated as a separator: {command} -> {message}"


@pytest.mark.parametrize(
    "command",
    [
        # inside DOUBLE quotes substitution really does expand -- still refused
        f'{QUOTED} | grep "$(id)"',
        f'{QUOTED} | grep "`id`"',
        # an unbalanced quote is unparseable; fail closed rather than guess
        f'{QUOTED} | grep "unterminated',
        # the real separators still separate
        f"{QUOTED}; {DESTRUCTIVE_TAIL}",
        f"{QUOTED} | bash",
        f"{QUOTED} > /tmp/gate-probe.txt",
    ],
)
def test_quote_awareness_does_not_weaken_the_gate(command: str, tmp_path: Path) -> None:
    ok, _message = _ack_hook(command, _workboard_with_unread(tmp_path))
    assert ok is False, f"quote handling let something through: {command}"
