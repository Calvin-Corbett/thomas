"""Adapter exposing discovered MCP tools as Thomas tool registrations.

Turns tool definitions discovered from a live :class:`McpStdioClient` session
into :class:`~thomas.tools.base.Tool` instances registered under name-spaced
names (``mcp.<server>.<tool>``) so the agent loop can call remote MCP tools
through the normal :class:`~thomas.tools.registry.ToolRegistry` surface in the
same session that discovered them.
"""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult
from thomas.tools.mcp_client import (
    McpServerError,
    McpStdioClient,
    McpTimeoutError,
    McpToolDef,
    McpTransportError,
)
from thomas.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

MCP_TOOL_CATEGORY = "mcp"


def mcp_tool_name(server_name: str, tool_name: str) -> str:
    """Registry name for a remote MCP tool: ``mcp.<server>.<tool>``."""
    return f"mcp.{server_name}.{tool_name}"


class McpProxyTool(Tool):
    """A Thomas tool that proxies calls to a tool on a live MCP session.

    Errors are mapped to structured :class:`ToolResult` failures instead of
    raising: server JSON-RPC errors, transport failures, timeouts (the client
    terminates the child on timeout), and in-band ``isError`` tool results.
    """

    category = MCP_TOOL_CATEGORY

    def __init__(self, client: McpStdioClient, tool_def: McpToolDef) -> None:
        self._client = client
        self._remote_name = tool_def.name
        self.name = mcp_tool_name(client.name, tool_def.name)
        self.description = tool_def.description or f"MCP tool {tool_def.name!r} on server {client.name!r}"
        self.parameters = dict(tool_def.input_schema) if tool_def.input_schema else {"type": "object", "properties": {}}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        """Round-trip ``tools/call`` on the live session with the given arguments."""
        try:
            result = await self._client.call_tool(self._remote_name, args)
        except McpTimeoutError as exc:
            return ToolResult(ok=False, error=f"MCP timeout: {exc}")
        except McpServerError as exc:
            return ToolResult(ok=False, error=f"MCP server error: {exc}")
        except McpTransportError as exc:
            return ToolResult(ok=False, error=f"MCP transport error: {exc}")
        if result.is_error:
            return ToolResult(ok=False, error=result.text or "MCP tool reported an error")
        if result.structured is not None:
            return ToolResult(ok=True, data=result.structured)
        if result.content and all(block.get("type") == "text" for block in result.content):
            return ToolResult(ok=True, data=result.text)
        return ToolResult(ok=True, data=result.content)


async def register_mcp_server_tools(registry: ToolRegistry, client: McpStdioClient) -> list[str]:
    """Discover the session's tools (``tools/list``) and register proxies.

    Returns the registered (name-spaced) tool names. Discovery and later calls
    share the same live session held by ``client``.
    """
    names: list[str] = []
    for tool_def in await client.list_tools():
        proxy = McpProxyTool(client, tool_def)
        registry.register(proxy)
        names.append(proxy.name)
    log.debug("Registered %d MCP tools from server %r", len(names), client.name)
    return names


def unregister_mcp_server_tools(registry: ToolRegistry, names: list[str]) -> None:
    """Remove previously registered MCP proxy tools (e.g. after session shutdown)."""
    for name in names:
        registry.unregister(name)
