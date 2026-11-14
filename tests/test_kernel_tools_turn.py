"""A mounted tool reaches the next turn and the live unplug removes it."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests import _chat_v2_max_mode_support as chat_support
from thomas.agent.kernel_wiring import (
    build_agent_loop,
    default_kernel,
    register_tools_provider,
    resolve_tools_for_turn,
    set_kernel,
)
from thomas.agent.loop_tools import select_tools
from thomas.core.kernel import TOOLS, ToolsSeam
from thomas.server.app_keys import APP_TOOLS
from thomas.server.plugin_startup import dispose_plugin_handles, mount_plugin_handles
from thomas.server.plugin_supervisor import PluginSupervisor
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class BuiltinTool(Tool):
    name = "builtin.echo"
    description = "Built-in echo"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args):
        return ToolResult(ok=True, data="builtin")


class PluginTool(BuiltinTool):
    name = "plugin.echo"


class Turn:
    def __init__(self, config, llm, tools):
        self.tools = tools


def _offered(kernel, registry):
    turn = build_agent_loop(None, None, registry, default=Turn, ctx=kernel.root)
    return turn, [spec["function"]["name"] for spec in select_tools(turn, "hello") or []]


def test_server_startup_registers_tools_provider(monkeypatch):
    from aiohttp import web

    kernel = default_kernel()
    set_kernel(kernel)
    base = ToolRegistry()
    base.register(BuiltinTool())
    app = web.Application()
    app[APP_TOOLS] = base
    try:
        mount_plugin_handles(app)
        assert isinstance(kernel.root[TOOLS], ToolsSeam)
        assert kernel.root[TOOLS].get("builtin.echo") is base.get("builtin.echo")
        turn, names = _offered(kernel, base)
        assert turn.tools is base
        assert names == ["builtin.echo"]
        dispose_plugin_handles(app)
        assert not kernel.root.has(TOOLS)
    finally:
        set_kernel(None)


class TestChatV2PluginTools(chat_support.ChatV2MaxModeCase):
    async def test_chat_turn_offers_plugin_tool_and_unplug_removes_it(self):
        root = Path(self._tmpdir.name) / "plugins"
        plugin = root / "echo_plugin"
        plugin.mkdir(parents=True)
        (plugin / "__init__.py").write_text(
            "from thomas.tools.base import Tool, ToolResult\n"
            "class Echo(Tool):\n"
            "    name = 'plugin.echo'\n"
            "    description = 'Echo a plugin message'\n"
            "    parameters = {'type': 'object', 'properties': {}}\n"
            "    async def execute(self, args):\n"
            "        return ToolResult(ok=True, data='from plugin')\n"
            "class Plugin:\n"
            "    name = 'echo_plugin'\n"
            "    def get_tools(self):\n"
            "        return [Echo()]\n"
            "def get_plugin():\n"
            "    return Plugin()\n",
            encoding="utf-8",
        )
        (root / "installed_plugins.json").write_text(
            json.dumps({"plugins": {"echo_plugin": {"installed_path": str(plugin)}}}), encoding="utf-8"
        )
        kernel = default_kernel()
        base = self.app[APP_TOOLS]
        set_kernel(kernel)
        register_tools_provider(base)
        captured = []

        class CaptureBrain(chat_support._FakeBrain):
            def __init__(self, *args, **kwargs):
                captured.append(kwargs["registry"].all_specialists[0].tools)
                super().__init__(*args, **kwargs)

        async def send(session):
            with patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", CaptureBrain):
                response = await self.client.post(
                    "/api/v2/chat",
                    json={"session_id": session, "profile": "local", "message": "hello"},
                )
                assert response.status == 200
                await response.text()
            return captured[-1]

        try:
            before = await send("before-plugin")
            assert before._base is base
            assert before.get("plugin.echo") is None
            supervisor = PluginSupervisor(kernel=kernel, install_root=root).start()
            try:
                mounted = await send("with-plugin")
                assert mounted.get("plugin.echo") is not None
                assert "plugin.echo" in [tool.name for tool in mounted.list_tools()]
                assert (await mounted.execute("plugin.echo", {})).data == "from plugin"
                assert supervisor.unplug("echo_plugin")
                gone = await send("after-plugin")
                assert gone.get("plugin.echo") is None
                assert "plugin.echo" not in [tool.name for tool in gone.list_tools()]
                assert not (await gone.execute("plugin.echo", {})).ok
            finally:
                supervisor.dispose()
        finally:
            set_kernel(None)


@pytest.mark.parametrize("bad_tool", ["object", "nameless"])
def test_invalid_plugin_tool_fails_mount_without_poisoning_turn(tmp_path, monkeypatch, bad_tool):
    monkeypatch.setenv("THOMAS_PLUGIN_ENABLEMENT_STORE", str(tmp_path / "enablement.json"))
    root = tmp_path / "plugins"
    package = root / "bad_tool"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from thomas.tools.base import Tool\n"
        "class Good(Tool):\n"
        "    name = 'plugin.good'\n"
        "class Nameless(Tool):\n"
        "    pass\n"
        "class Plugin:\n"
        "    name = 'bad_tool'\n"
        "    def get_tools(self):\n"
        f"        return [Good(), {'object()' if bad_tool == 'object' else 'Nameless()'}]\n"
        "def get_plugin():\n"
        "    return Plugin()\n",
        encoding="utf-8",
    )
    (root / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"bad_tool": {"installed_path": str(package)}}}), encoding="utf-8"
    )
    base = ToolRegistry()
    base.register(BuiltinTool())
    kernel = default_kernel()
    register_tools_provider(base, ctx=kernel.root)
    supervisor = PluginSupervisor(kernel=kernel, install_root=root).start()
    try:
        assert "bad_tool" not in supervisor.mounted_names()
        assert "bad_tool" in supervisor.plugins
        assert supervisor.plugins["bad_tool"].error.startswith(("TypeError:", "ValueError:"))
        turn, names = _offered(kernel, base)
        assert turn.tools is base
        assert names == ["builtin.echo"]
        assert kernel.root[TOOLS].get("plugin.good") is None
    finally:
        supervisor.dispose()


def test_mount_supplies_first_tool_to_empty_server_and_enabled_worker_turns():
    from thomas.agent.kernel_tool_provider import MountedTools

    kernel = default_kernel()
    base = ToolRegistry()
    register_tools_provider(base, ctx=kernel.root)
    mount = MountedTools(kernel.root[TOOLS], [PluginTool()])
    kernel.root.set(TOOLS, mount)
    turn, names = _offered(kernel, base)
    assert names == ["plugin.echo"]
    assert asyncio.run(turn.tools.execute("plugin.echo", {})).ok
    worker = resolve_tools_for_turn(ToolRegistry(), ctx=kernel.root, allow_new=True)
    assert [tool.name for tool in worker.list_tools()] == ["plugin.echo"]
    mount.withdraw()
    assert turn.tools.list_tools() == []
    assert worker.list_tools() == []
    assert not asyncio.run(turn.tools.execute("plugin.echo", {})).ok
    assert _offered(kernel, base)[1] == []


def test_registered_provider_can_replace_turn_tools_without_plugin():
    kernel = default_kernel()
    set_kernel(kernel)
    original = ToolRegistry()
    original.register(BuiltinTool())
    substitute = ToolRegistry()
    try:
        kernel.root.set(TOOLS, substitute)
        turn, names = _offered(kernel, original)
        assert turn.tools is substitute
        assert names == []
    finally:
        set_kernel(None)


def test_installed_plugin_tool_appears_then_disappears_from_next_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_PLUGIN_ENABLEMENT_STORE", str(tmp_path / "enablement.json"))
    root = tmp_path / "plugins"
    plugin = root / "echo_plugin"
    plugin.mkdir(parents=True)
    (plugin / "__init__.py").write_text(
        "from thomas.tools.base import Tool, ToolResult\n"
        "class Echo(Tool):\n"
        "    name = 'plugin.echo'\n"
        "    description = 'Echo a plugin message'\n"
        "    parameters = {'type': 'object', 'properties': {}}\n"
        "    async def execute(self, args):\n"
        "        return ToolResult(ok=True, data='from plugin')\n"
        "class Plugin:\n"
        "    name = 'echo_plugin'\n"
        "    def get_tools(self):\n"
        "        return [Echo()]\n"
        "def get_plugin():\n"
        "    return Plugin()\n",
        encoding="utf-8",
    )
    (root / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"echo_plugin": {"installed_path": str(plugin)}}}), encoding="utf-8"
    )
    base = ToolRegistry()
    base.register(BuiltinTool())
    kernel = default_kernel()
    set_kernel(kernel)
    register_tools_provider(base)
    try:
        assert isinstance(kernel.root[TOOLS], ToolsSeam)
        before, names = _offered(kernel, base)
        assert before.tools is base
        assert names == ["builtin.echo"]
        supervisor = PluginSupervisor(kernel=kernel, install_root=root).start()
        try:
            assert isinstance(kernel.root[TOOLS], ToolsSeam)
            mounted, names = _offered(kernel, base)
            assert names == ["builtin.echo", "plugin.echo"]
            assert asyncio.run(mounted.tools.execute("plugin.echo", {})).data == "from plugin"
            assert "plugin.echo" in mounted.tools
            assert mounted.tools._resolve_tool_name("plugin.echo") == "plugin.echo"
            assert "plugin.echo" in [tool.name for tool in mounted.tools.search("plugin.echo")]
            assert supervisor.unplug("echo_plugin")
            assert "plugin.echo" not in [tool.name for tool in mounted.tools.list_tools()]
            assert not asyncio.run(mounted.tools.execute("plugin.echo", {})).ok
            unplugged, names = _offered(kernel, base)
            assert names == ["builtin.echo"]
            assert unplugged.tools.get("plugin.echo") is None
            assert not asyncio.run(unplugged.tools.execute("plugin.echo", {})).ok
            assert supervisor.replug("echo_plugin")
            _, names = _offered(kernel, base)
            assert names == ["builtin.echo", "plugin.echo"]
            assert "plugin.echo" not in [tool.name for tool in mounted.tools.list_tools()]
        finally:
            supervisor.dispose()
    finally:
        set_kernel(None)
