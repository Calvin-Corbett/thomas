"""Startup bridge: connect configured MCP servers and register their tools.

Consumed best-effort by the REPL startup path (``thomas/cli/repl.py`` imports
``register_mcp_tools`` and calls it with the live tool registry and app
config). For every enabled stdio server in the persisted MCP registry it
spawns a session, performs the MCP handshake, discovers tools, and registers
``mcp.<server>.<tool>`` proxies so the agent loop can call them in the same
session. Per-server failures are logged and skipped -- one broken server must
not take down startup.

The state-file location mirrors ``thomas/cli/parity_support.mcp_registry_path``
(``<memory root>/.thomas/cli/mcp_servers.json``). It is re-derived here because
the tools tier must not import cli (see ``thomas/_architecture.py``).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig
from thomas.tools.mcp_client import (
    DEFAULT_REQUEST_TIMEOUT,
    McpError,
    McpSessionRegistry,
    McpStdioClient,
)
from thomas.tools.mcp_tools import register_mcp_server_tools
from thomas.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


def mcp_registry_file(config: AppConfig) -> Path:
    """Path of the persisted MCP server registry written by ``thomas mcp add``."""
    return config.memory.root_path / ".thomas" / "cli" / "mcp_servers.json"


def load_mcp_server_rows(config: AppConfig) -> list[dict[str, Any]]:
    """Read persisted MCP server metadata rows; missing/corrupt file yields []."""
    path = mcp_registry_file(config)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("MCP registry file %s unreadable: %s", path, exc)
        return []
    rows = payload.get("servers") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


class McpBridge:
    """Live MCP sessions plus the tool names each contributed to the registry."""

    def __init__(self, sessions: McpSessionRegistry, tool_names_by_server: dict[str, list[str]]) -> None:
        self._sessions = sessions
        self._tool_names_by_server = tool_names_by_server

    @property
    def sessions(self) -> McpSessionRegistry:
        return self._sessions

    def list_servers(self) -> list[str]:
        """Names of servers with an established session."""
        return self._sessions.names()

    def get_session(self, name: str) -> McpStdioClient | None:
        return self._sessions.get(name)

    def list_tools(self, server: str | None = None) -> list[str]:
        """Registered ``mcp.<server>.<tool>`` names, optionally for one server."""
        if server is not None:
            return list(self._tool_names_by_server.get(str(server), []))
        out: list[str] = []
        for names in self._tool_names_by_server.values():
            out.extend(names)
        return sorted(out)

    async def aclose(self) -> None:
        """Terminate all child server processes."""
        await self._sessions.close_all()


async def register_mcp_tools(
    registry: ToolRegistry,
    config: AppConfig,
    *,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> McpBridge:
    """Connect all enabled stdio MCP servers and register their tools.

    Args:
        registry: Live tool registry the discovered tools are added to.
        config: App config (locates the persisted MCP server metadata).
        request_timeout: Per-request timeout for each session.

    Returns:
        McpBridge holding the live sessions; callers own shutdown via
        ``await bridge.aclose()``.
    """
    sessions = McpSessionRegistry()
    tool_names_by_server: dict[str, list[str]] = {}
    for row in load_mcp_server_rows(config):
        if not bool(row.get("enabled", True)):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        transport = str(row.get("transport") or "stdio").strip().lower()
        if transport != "stdio":
            log.debug("MCP server %r skipped: transport %r not supported for live sessions", name, transport)
            continue
        try:
            client = await sessions.connect_row(row, request_timeout=request_timeout)
            tool_names_by_server[name] = await register_mcp_server_tools(registry, client)
        except McpError as exc:
            log.warning("MCP server %r failed to connect: %s", name, exc)
            await sessions.close(name)
    return McpBridge(sessions, tool_names_by_server)
