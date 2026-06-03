from __future__ import annotations

import asyncio

from thomas.tools.shell import ShellTool, _git_topology_mutation_reason


def test_git_topology_guard_blocks_branch_clone_and_worktree_commands() -> None:
    blocked_commands = [
        "git clone https://example.invalid/thomas.git C:/tmp/thomas-copy",
        "git init C:/tmp/new-repo",
        "git worktree add C:/tmp/thomas-worktree dev",
        "git worktree remove C:/tmp/thomas-worktree",
        "git switch -c codex/hidden-feature",
        "git checkout -b codex/hidden-feature",
        "git branch codex/hidden-feature",
        "git branch -m old-name new-name",
    ]

    for command in blocked_commands:
        reason = _git_topology_mutation_reason(command)
        assert reason is not None, command
        assert "repo-topology guard" in reason


def test_git_topology_guard_allows_read_only_git_commands() -> None:
    allowed_commands = [
        "git status --short",
        "git branch --show-current",
        "git branch --list",
        "git branch -vv",
        "git worktree list --porcelain",
        "git diff --stat",
    ]

    for command in allowed_commands:
        assert _git_topology_mutation_reason(command) is None, command


def test_shell_tool_rejects_git_topology_mutation_before_execution(tmp_path) -> None:
    tool = ShellTool(tmp_path)

    result = asyncio.run(tool.execute({"command": "git clone https://example.invalid/thomas.git copy"}))

    assert result.ok is False
    assert result.error is not None
    assert "repo-topology guard" in result.error
