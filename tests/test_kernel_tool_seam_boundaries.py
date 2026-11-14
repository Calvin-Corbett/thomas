"""Policy and turn-boundary checks for mounted kernel tools."""

import asyncio

from tests.test_kernel_tools_turn import BuiltinTool, PluginTool, _offered
from thomas.agent.kernel_tool_provider import MountedTools
from thomas.agent.kernel_wiring import (
    build_agent_loop,
    default_kernel,
    register_tools_provider,
    resolve_tools_for_turn,
    set_kernel,
)
from thomas.core.kernel import TOOLS
from thomas.server.chat_tool_policy import PolicyToolRegistryView, ToolRuntimePolicy
from thomas.server.worker_runtime import _apply_tool_deny
from thomas.tools.base import ToolResult
from thomas.tools.registry import ToolRegistry


def test_policy_boundary_still_filters_mounted_tool():
    kernel = default_kernel()
    base = ToolRegistry()
    base.register(BuiltinTool())
    register_tools_provider(base, ctx=kernel.root)
    policy = ToolRuntimePolicy(
        allow_shell=False,
        allow_file_write=False,
        allow_network=False,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=True,
        tool_timeout_s=30,
        max_parallel_tools=1,
        allowed_paths=(),
        blocked_commands=(),
    )
    mounted = MountedTools(kernel.root[TOOLS], [BuiltinTool()])
    kernel.root.set(TOOLS, mounted)
    restricted = PolicyToolRegistryView(ToolRegistry(), policy)
    turn, names = _offered(kernel, restricted)
    assert isinstance(turn.tools, PolicyToolRegistryView)
    assert names == []
    assert turn.tools.get("builtin.echo") is None
    assert not asyncio.run(turn.tools.execute("builtin.echo", {})).ok


def test_restricted_and_denied_turns_cannot_gain_mounted_tools():
    kernel = default_kernel()
    base = ToolRegistry()
    base.register(BuiltinTool())
    register_tools_provider(base, ctx=kernel.root)
    mount = MountedTools(kernel.root[TOOLS], [PluginTool()])
    kernel.root.set(TOOLS, mount)
    set_kernel(kernel)
    try:
        assert _offered(kernel, ToolRegistry())[1] == []
        narrow = ToolRegistry()
        narrow.register(BuiltinTool())
        assert _offered(kernel, narrow)[0].tools is narrow
        worker = resolve_tools_for_turn(narrow, allow_new=True)
        _apply_tool_deny(worker, frozenset({"plugin.echo"}))
        assert worker.get("plugin.echo") is None
        assert [tool.name for tool in worker.list_tools()] == ["builtin.echo"]
        assert not asyncio.run(worker.execute("plugin.echo", {})).ok
        _apply_tool_deny(worker, frozenset({"builtin.echo"}))
        assert worker.list_tools() == []
        assert not asyncio.run(worker.execute("builtin.echo", {})).ok
        allowed = resolve_tools_for_turn(narrow, allow_new=True)
        spawned = BuiltinTool()
        spawned.name = "other.tool"
        allowed.register(spawned)
        assert allowed.get("other.tool") is spawned
        mount.withdraw()
        assert allowed.get("other.tool") is spawned
        assert allowed.get("plugin.echo") is None

        class ReviewTools:
            def list_tools(self):
                return [BuiltinTool()]

            async def execute(self, name, args):
                return ToolResult(ok=False, error="review boundary")

        review = ReviewTools()
        assert build_agent_loop(None, None, review, default=lambda config, llm, tools: tools, ctx=kernel.root) is review
    finally:
        set_kernel(None)


def test_worker_deny_survives_loop_construction_with_two_mounted_plugins():
    kernel = default_kernel()
    base = ToolRegistry()
    base.register(BuiltinTool())
    register_tools_provider(base, ctx=kernel.root)
    first = MountedTools(kernel.root[TOOLS], [PluginTool()])
    kernel.root.set(TOOLS, first)
    second_tool = PluginTool()
    second_tool.name = "plugin.second"
    second = MountedTools(kernel.root[TOOLS], [second_tool])
    kernel.root.set(TOOLS, second)

    worker = resolve_tools_for_turn(base, ctx=kernel.root, allow_new=True)
    _apply_tool_deny(worker, frozenset({"plugin.echo"}))
    assert worker.get("plugin.echo") is None
    assert worker.get("plugin.second") is second_tool

    turn = build_agent_loop(None, None, worker, default=lambda config, llm, tools: tools, ctx=kernel.root)
    assert turn.get("plugin.echo") is None
    assert "plugin.echo" not in [tool.name for tool in turn.list_tools()]
    assert not asyncio.run(turn.execute("plugin.echo", {})).ok
    assert asyncio.run(turn.execute("plugin.second", {})).ok


def test_overlapping_plugin_tools_keep_remaining_provider_on_unplug():
    kernel = default_kernel()
    base = ToolRegistry()
    base.register(BuiltinTool())
    register_tools_provider(base, ctx=kernel.root)
    first = MountedTools(kernel.root[TOOLS], [BuiltinTool()])
    kernel.root.set(TOOLS, first)
    second = MountedTools(kernel.root[TOOLS], [BuiltinTool()])
    kernel.root.set(TOOLS, second)
    turn, names = _offered(kernel, base)
    assert names == ["builtin.echo"]
    first.withdraw()
    assert turn.tools.get("builtin.echo") is not None
    second.withdraw()
    assert turn.tools.get("builtin.echo") is base.get("builtin.echo")
