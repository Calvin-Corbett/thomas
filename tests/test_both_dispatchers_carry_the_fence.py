"""Both Build dispatch paths carry a run's file fence (2026-09-07).

The loop's write tools refuse ``protected_paths`` (see
test_a_run_cannot_write_into_a_fenced_file.py), and the Redesign path stores
the fence on the conversation. An audit found the two entries the engine
actually calls did not pass it on: ``dispatch_via_agent_loop`` accepted no
such keyword, and ``dispatch_via_claude_cli`` runs ``claude -p`` outside the
loop entirely, so a CLI run had no fence at all.

The outer dispatcher now forwards the list into every pass, and the CLI
dispatcher turns it into Claude Code permission deny rules (``Edit(path)``,
the one rule kind Claude Code consults for every built-in write; directories
as globs) handed over in a
settings file, so a fenced write is refused by the CLI itself.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil import dispatch_agent_loop, dispatch_claude_cli


@pytest.fixture
def clean_git_repo(tmp_path: Path) -> Path:
    """A committed repo: the dispatchers branch before they run, so a bare folder never reaches the runner."""
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True, capture_output=True)
    return root


def test_the_agent_loop_dispatcher_forwards_the_fence_into_every_pass(monkeypatch, clean_git_repo) -> None:
    seen: list[dict] = []

    def fake_pass(prompt, cwd, timeout, emit, **kwargs):  # noqa: ANN001
        seen.append(kwargs)
        return 0, "done"

    monkeypatch.setattr(dispatch_agent_loop, "_run_agent_loop_pass", fake_pass)
    dispatch_agent_loop.dispatch_via_agent_loop(
        "change the chip",
        cwd=clean_git_repo,
        dry_run=False,
        verify=False,
        token_check=lambda: True,
        protected_paths=["thomas/server/web/chat.html", "thomas/forge/anvil/"],
    )
    assert seen, "no pass ran"
    assert seen[0]["protected_paths"] == ["thomas/server/web/chat.html", "thomas/forge/anvil/"]


def test_the_claude_cli_dispatcher_turns_the_fence_into_deny_rules(clean_git_repo) -> None:
    argv_seen: list[list[str]] = []

    def fake_runner(cmd, *args, **kwargs):  # noqa: ANN001
        argv_seen.append(list(cmd))
        return 0, "ok"

    dispatch_claude_cli.dispatch_via_claude_cli(
        "change the chip",
        cwd=clean_git_repo,
        dry_run=False,
        verify=False,
        runner=fake_runner,
        claude_bin="claude",
        protected_paths=["thomas/server/web/chat.html", "thomas/forge/anvil/"],
    )
    assert argv_seen, "the CLI never ran"
    cmd = argv_seen[0]
    assert "--settings" in cmd, cmd
    settings_path = Path(cmd[cmd.index("--settings") + 1])
    rules = json.loads(settings_path.read_text(encoding="utf-8"))["permissions"]["deny"]
    assert "Edit(thomas/server/web/chat.html)" in rules
    # Only Edit(path) rules are consulted by Claude Code; a Write(path) rule would be ignored noise.
    assert not any(rule.startswith(("Write(", "MultiEdit(", "NotebookEdit(")) for rule in rules), rules
    assert "Edit(thomas/forge/anvil/**)" in rules
    assert all(rule.startswith("Edit(") for rule in rules)


def test_no_fence_means_no_settings_flag(clean_git_repo) -> None:
    argv_seen: list[list[str]] = []

    def fake_runner(cmd, *args, **kwargs):  # noqa: ANN001
        argv_seen.append(list(cmd))
        return 0, "ok"

    dispatch_claude_cli.dispatch_via_claude_cli(
        "change the chip", cwd=clean_git_repo, dry_run=False, verify=False, runner=fake_runner, claude_bin="claude"
    )
    assert argv_seen and "--settings" not in argv_seen[0]


def test_a_fenced_run_is_never_granted_a_shell(monkeypatch, clean_git_repo) -> None:
    """A shell can write anywhere, so a fence and a shell cannot coexist honestly:
    the dispatcher keeps the shell off for a fenced run and says so in the stream."""
    seen: list[dict] = []
    events: list[dict] = []

    def fake_pass(prompt, cwd, timeout, emit, **kwargs):  # noqa: ANN001
        seen.append(kwargs)
        return 0, "done"

    monkeypatch.setattr(dispatch_agent_loop, "_run_agent_loop_pass", fake_pass)
    dispatch_agent_loop.dispatch_via_agent_loop(
        "change the chip",
        cwd=clean_git_repo,
        dry_run=False,
        verify=False,
        token_check=lambda: True,
        allow_shell=True,
        emit=events.append,
        protected_paths=["thomas/server/web/chat.html"],
    )
    assert seen and seen[0]["allow_shell"] is False
    assert any("shell" in str(e).lower() and "fence" in str(e).lower() for e in events), events
