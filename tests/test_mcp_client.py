"""CAP-067: executable MCP client with same-session discovery and tool use.

All tests run against the hermetic fake MCP server subprocess in
tests/_fake_mcp_server.py (newline-delimited JSON-RPC 2.0 over stdio).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from thomas.core.config import AppConfig, MemoryConfig
from thomas.tools.mcp_bridge import register_mcp_tools
from thomas.tools.mcp_client import (
    McpServerError,
    McpSessionRegistry,
    McpStdioClient,
    McpTimeoutError,
    McpTransportError,
    client_from_server_row,
)
from thomas.tools.mcp_tools import mcp_tool_name, register_mcp_server_tools, unregister_mcp_server_tools
from thomas.tools.registry import ToolRegistry

FAKE_SERVER = str(Path(__file__).parent / "_fake_mcp_server.py")


def _client(name: str = "fake", **kwargs) -> McpStdioClient:
    return McpStdioClient(name=name, command=sys.executable, args=[FAKE_SERVER], **kwargs)


def _server_row(name: str = "fake", **overrides) -> dict:
    row = {
        "name": name,
        "transport": "stdio",
        "command": sys.executable,
        "args": [FAKE_SERVER],
        "url": "",
        "env": {},
        "enabled": True,
    }
    row.update(overrides)
    return row


def _write_registry(tmp_path: Path, rows: list[dict]) -> AppConfig:
    state_dir = tmp_path / ".thomas" / "cli"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "mcp_servers.json").write_text(json.dumps({"servers": rows}), encoding="utf-8")
    return AppConfig(memory=MemoryConfig(root=str(tmp_path)))


# -- (1)+(2) spawn/connect + handshake -----------------------------------


@pytest.mark.asyncio
async def test_handshake_records_capability_negotiation():
    async with _client() as client:
        assert client.running
        assert client.server_info.get("name") == "fake-mcp"
        assert client.protocol_version  # negotiated version recorded
        assert "tools" in client.capabilities  # capability negotiation recorded


@pytest.mark.asyncio
async def test_spawn_failure_is_transport_error():
    client = McpStdioClient(name="missing", command="definitely-not-a-real-executable-xyz")
    with pytest.raises(McpTransportError):
        await client.start()


@pytest.mark.asyncio
async def test_env_from_server_row_reaches_child():
    row = _server_row(env={"FAKE_MCP_TAG": "row-env-tag"})
    async with client_from_server_row(row) as client:
        result = await client.call_tool("tag", {})
        assert result.text == "row-env-tag"


# -- (3) same-session discovery ------------------------------------------


@pytest.mark.asyncio
async def test_tools_list_discovers_all_tools_across_pages():
    async with _client() as client:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        # page one + page two (pagination cursor followed)
        assert names == ["echo", "add", "tag", "fail", "sleep"]
        echo = tools[0]
        assert echo.description == "Echo the message back."
        assert echo.input_schema["required"] == ["message"]


# -- (4) tool use: round-trip + error mapping + timeout ------------------


@pytest.mark.asyncio
async def test_tool_call_roundtrip_same_session_as_discovery():
    async with _client() as client:
        discovered = [t.name for t in await client.list_tools()]
        assert "echo" in discovered
        result = await client.call_tool("echo", {"message": "hello mcp"})
        assert not result.is_error
        assert result.text == "hello mcp"
        added = await client.call_tool("add", {"a": 2, "b": 3})
        assert added.text == "5.0"


@pytest.mark.asyncio
async def test_server_jsonrpc_error_maps_to_structured_client_error():
    async with _client() as client:
        with pytest.raises(McpServerError) as excinfo:
            await client.call_tool("no-such-tool", {})
        assert excinfo.value.code == -32602
        assert "no-such-tool" in excinfo.value.message


@pytest.mark.asyncio
async def test_in_band_tool_error_flagged_on_result():
    async with _client() as client:
        result = await client.call_tool("fail", {})
        assert result.is_error
        assert result.text == "deliberate failure"


@pytest.mark.asyncio
async def test_timeout_terminates_child_cleanly():
    client = _client(request_timeout=1.0)
    await client.start()
    proc = client._proc  # keep a handle to verify child termination
    with pytest.raises(McpTimeoutError):
        await client.call_tool("sleep", {"seconds": 30})
    assert not client.running
    assert proc is not None and proc.returncode is not None  # child terminated


# -- (5) lifecycle: shutdown, context manager, session registry ----------


@pytest.mark.asyncio
async def test_close_terminates_child_and_is_idempotent():
    client = _client()
    await client.start()
    proc = client._proc
    await client.close()
    assert not client.running
    assert proc is not None and proc.returncode is not None
    await client.close()  # idempotent


@pytest.mark.asyncio
async def test_context_manager_shuts_down_on_exit():
    client = _client()
    async with client:
        proc = client._proc
        assert client.running
    assert not client.running
    assert proc is not None and proc.returncode is not None


@pytest.mark.asyncio
async def test_session_registry_holds_multiple_live_sessions():
    sessions = McpSessionRegistry()
    try:
        alpha = await sessions.connect(name="alpha", command=sys.executable, args=[FAKE_SERVER])
        beta = await sessions.connect_row(_server_row(name="beta"))
        assert sessions.names() == ["alpha", "beta"]
        assert len(sessions) == 2 and "alpha" in sessions
        assert sessions.get("alpha") is alpha
        # both sessions are live and independently usable
        assert (await alpha.call_tool("echo", {"message": "a"})).text == "a"
        assert (await beta.call_tool("echo", {"message": "b"})).text == "b"
        # reconnecting an already-live name reuses the session
        assert await sessions.connect(name="alpha", command=sys.executable, args=[FAKE_SERVER]) is alpha
    finally:
        await sessions.close_all()
    assert sessions.names() == []
    assert not alpha.running and not beta.running


@pytest.mark.asyncio
async def test_non_stdio_row_rejected():
    with pytest.raises(McpTransportError):
        client_from_server_row(_server_row(transport="sse", url="http://localhost:1"))


# -- runtime tool surface: adapter registers mcp.<server>.<tool> ---------


@pytest.mark.asyncio
async def test_adapter_registers_namespaced_tools_and_executes_same_session():
    registry = ToolRegistry()
    async with _client(name="fake") as client:
        names = await register_mcp_server_tools(registry, client)
        assert mcp_tool_name("fake", "echo") in names
        assert "mcp.fake.echo" in registry
        # call through the normal registry surface in the SAME session
        result = await registry.execute("mcp.fake.echo", {"message": "via registry"})
        assert result.ok
        assert result.data == "via registry"
        # error mapping: in-band tool error becomes a failed ToolResult
        failed = await registry.execute("mcp.fake.fail", {})
        assert not failed.ok
        assert "deliberate failure" in (failed.error or "")
        unregister_mcp_server_tools(registry, names)
        assert "mcp.fake.echo" not in registry


@pytest.mark.asyncio
async def test_adapter_maps_transport_error_after_shutdown():
    registry = ToolRegistry()
    client = _client(name="fake")
    await client.start()
    await register_mcp_server_tools(registry, client)
    await client.close()
    result = await registry.execute("mcp.fake.echo", {"message": "late"})
    assert not result.ok
    assert "MCP transport error" in (result.error or "")


# -- startup bridge: config-driven connect + register --------------------


@pytest.mark.asyncio
async def test_bridge_connects_configured_servers_and_registers_tools(tmp_path):
    config = _write_registry(
        tmp_path,
        [
            _server_row(name="fake", env={"FAKE_MCP_TAG": "bridge-tag"}),
            _server_row(name="disabled", enabled=False),
            _server_row(name="broken", command="definitely-not-a-real-executable-xyz"),
        ],
    )
    registry = ToolRegistry()
    bridge = await register_mcp_tools(registry, config)
    try:
        assert bridge.list_servers() == ["fake"]  # disabled skipped, broken logged+skipped
        assert "mcp.fake.echo" in bridge.list_tools("fake")
        result = await registry.execute("mcp.fake.tag", {})
        assert result.ok
        assert result.data == "bridge-tag"
    finally:
        await bridge.aclose()
    assert bridge.list_servers() == []


@pytest.mark.asyncio
async def test_bridge_with_no_registry_file_is_empty(tmp_path):
    config = AppConfig(memory=MemoryConfig(root=str(tmp_path)))
    registry = ToolRegistry()
    bridge = await register_mcp_tools(registry, config)
    assert bridge.list_servers() == []
    assert len(registry) == 0


# -- CLI wiring: mcp tools / mcp call ------------------------------------


def test_cli_mcp_tools_live_discovery(tmp_path):
    from thomas.cli.compat_mcp import mcp as mcp_group

    config = _write_registry(tmp_path, [_server_row(name="fake")])
    runner = CliRunner()
    result = runner.invoke(mcp_group, ["tools", "fake", "--json"], obj={"config": config})
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["server_info"]["name"] == "fake-mcp"
    assert [t["name"] for t in payload["tools"]] == ["echo", "add", "tag", "fail", "sleep"]


def test_cli_mcp_call_discovery_and_use_in_one_session(tmp_path):
    from thomas.cli.compat_mcp import mcp as mcp_group

    config = _write_registry(tmp_path, [_server_row(name="fake")])
    runner = CliRunner()
    result = runner.invoke(
        mcp_group,
        ["call", "fake", "echo", "--args", '{"message": "cli hello"}', "--json"],
        obj={"config": config},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["text"] == "cli hello"
    assert payload["is_error"] is False
    assert "echo" in payload["discovered_tools"]


def test_cli_mcp_call_unknown_tool_fails_with_available_list(tmp_path):
    from thomas.cli.compat_mcp import mcp as mcp_group

    config = _write_registry(tmp_path, [_server_row(name="fake")])
    runner = CliRunner()
    result = runner.invoke(mcp_group, ["call", "fake", "nope"], obj={"config": config})
    assert result.exit_code != 0
    assert "not found" in result.output
    assert "echo" in result.output
