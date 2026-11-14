"""Build's actual dispatch receives mounted tools on its next enabled turn."""

import asyncio

import pytest

import thomas.agent.kernel_wiring as kernel_wiring
from tests.test_kernel_tools_turn import PluginTool
from thomas.agent.kernel_tool_provider import MountedTools
from thomas.agent.kernel_wiring import default_kernel, register_tools_provider, set_kernel
from thomas.core.config import load_config
from thomas.core.kernel import TOOLS
from thomas.forge.anvil import dispatch_agent_loop
from thomas.tools.registry import ToolRegistry


class ToolsetSeen(Exception):
    def __init__(self, names):
        self.names = names


def _build_tools(tmp_path, monkeypatch, *, autonomy_level=3, file_access="project"):
    def capture(config, llm, tools, **kwargs):
        raise ToolsetSeen({tool.name for tool in tools.list_tools()})

    monkeypatch.setattr(kernel_wiring, "build_agent_loop", capture)
    config = load_config(tmp_path / "thomas.toml")
    profile = next(iter(config.models))
    with pytest.raises(ToolsetSeen) as seen:
        asyncio.run(
            dispatch_agent_loop._agent_loop_pass_async(
                "fix",
                str(tmp_path),
                60,
                lambda event: None,
                profile=profile,
                autonomy_level=autonomy_level,
                file_access=file_access,
            )
        )
    return seen.value.names


def test_build_turn_receives_mounted_tool_then_loses_it(tmp_path, monkeypatch):
    kernel = default_kernel()
    register_tools_provider(ToolRegistry(), ctx=kernel.root)
    set_kernel(kernel)
    try:
        original = _build_tools(tmp_path, monkeypatch, autonomy_level=3, file_access="project")
        mount = MountedTools(kernel.root[TOOLS], [PluginTool()])
        kernel.root.set(TOOLS, mount)
        offered = _build_tools(tmp_path, monkeypatch, autonomy_level=3, file_access="project")
        assert offered == original | {"plugin.echo"}
        assert "plugin.echo" not in _build_tools(tmp_path, monkeypatch, autonomy_level=2, file_access="project")
        assert "plugin.echo" not in _build_tools(tmp_path, monkeypatch, autonomy_level=3, file_access="read_only")
        mount.withdraw()
        assert _build_tools(tmp_path, monkeypatch, autonomy_level=3, file_access="project") == original
    finally:
        set_kernel(None)
