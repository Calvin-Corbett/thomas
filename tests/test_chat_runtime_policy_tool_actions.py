"""Per-action tool policy: ssh, diff, blocked commands and memory scopes.

Split from tests/test_chat_runtime_policy.py along the seam
scripts/forge/seam_finder.py named (zero crossings; the shared probe tool
lives in tests/_chat_runtime_policy_fakes.py).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._chat_runtime_policy_fakes import _ProbeTool
from thomas.chat.memory_layers import MemoryCoordinator
from thomas.server.chat_runtime_policy import PolicyToolRegistryView, ToolRuntimePolicy
from thomas.tools.registry import ToolRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy_overrides", "denial"),
    [
        ({"allow_file_write": False}, "allow_file_write"),
        ({"allow_network": False}, "allow_network"),
    ],
)
async def test_shell_cannot_bypass_file_or_network_policy(
    policy_overrides: dict[str, bool],
    denial: str,
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    shell = _ProbeTool("shell.exec")
    registry.register(shell)
    policy = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=True,
        allow_browser=True,
        allow_channels=True,
        allow_git=True,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, replace(policy, **policy_overrides), base_root=tmp_path)

    assert view.get("shell.exec") is None
    result = await view.execute("shell.exec", {"command": "echo unsafe"})
    assert not result.ok
    assert denial in str(result.error)
    assert not shell.calls


@pytest.mark.asyncio
async def test_action_aware_ssh_policy_blocks_file_mutation_and_path_escape(tmp_path: Path) -> None:
    registry = ToolRegistry()
    ssh = _ProbeTool("ssh.exec")
    registry.register(ssh)
    read_only = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=False,
        allow_network=True,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=(),
    )
    assert not (
        await PolicyToolRegistryView(registry, read_only, base_root=tmp_path).execute(
            "ssh.exec", {"action": "download", "local_path": "outside.txt"}
        )
    ).ok

    allowlisted = replace(read_only, allow_file_write=True, allowed_paths=("workspace",))
    view = PolicyToolRegistryView(registry, allowlisted, base_root=tmp_path)
    assert not (await view.execute("ssh.exec", {"action": "upload", "local_path": "outside.txt"})).ok
    assert (await view.execute("ssh.exec", {"action": "upload", "local_path": "workspace/inside.txt"})).ok
    assert not (
        await view.execute(
            "ssh.exec",
            {
                "action": "upload",
                "local_path": "workspace/inside.txt",
                "key_path": "../outside/id_ed25519",
            },
        )
    ).ok


@pytest.mark.asyncio
async def test_diff_policy_keeps_preview_readable_and_scopes_write_targets(tmp_path: Path) -> None:
    registry = ToolRegistry()
    preview = _ProbeTool("diff.preview")
    create = _ProbeTool("diff.create")
    patch = _ProbeTool("diff.apply_patch")
    for tool in (preview, create, patch):
        registry.register(tool)
    policy = ToolRuntimePolicy(
        allow_shell=False,
        allow_file_write=True,
        allow_network=False,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=("workspace",),
        blocked_commands=(),
    )
    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)

    assert view.get("diff.preview") is not None
    assert not (await view.execute("diff.create", {"file": "outside.py"})).ok
    assert (await view.execute("diff.create", {"file": "workspace/inside.py"})).ok
    assert not (
        await view.execute(
            "diff.apply_patch",
            {"patch": "--- a/outside.py\n+++ b/outside.py\n@@ -1 +1 @@\n-a\n+b\n"},
        )
    ).ok
    assert (
        await view.execute(
            "diff.apply_patch",
            {"patch": "--- a/workspace/a.py\n+++ b/workspace/a.py\n@@ -1 +1 @@\n-a\n+b\n"},
        )
    ).ok


@pytest.mark.asyncio
async def test_blocked_command_policy_disables_shell_instead_of_parsing_obfuscation(tmp_path: Path) -> None:
    registry = ToolRegistry()
    shell = _ProbeTool("shell.exec")
    registry.register(shell)
    policy = ToolRuntimePolicy(
        allow_shell=True,
        allow_file_write=True,
        allow_network=True,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=False,
        tool_timeout_s=120,
        max_parallel_tools=6,
        allowed_paths=(),
        blocked_commands=("curl",),
    )

    view = PolicyToolRegistryView(registry, policy, base_root=tmp_path)
    assert view.get("shell.exec") is None
    assert not (await view.execute("shell.exec", {"command": 'c""url https://example.com'})).ok
    assert not shell.calls


@pytest.mark.asyncio
async def test_memory_policy_does_not_query_disabled_scopes() -> None:
    class _Memory:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def retrieve(self, **kwargs):  # noqa: ANN003
            self.calls.append(dict(kwargs))
            return "secret memory"

    memory = _Memory()
    policy = SimpleNamespace(
        include_thread=False,
        include_global=True,
        include_profile=False,
        pins_only=False,
        context_budget=1200,
    )
    coordinator = MemoryCoordinator(memory, "session-1", policy=policy)
    conversation = SimpleNamespace(last_user_message=lambda: "hello", last_assistant_message=lambda: "")
    context = await coordinator.refresh(prompt="hello", conversation=conversation, iteration=0)
    assert not memory.calls
    assert not context.episodic
    assert not context.semantic
