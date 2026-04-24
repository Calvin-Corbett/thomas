"""MCP (Model Context Protocol) bridge for Thomas tool registry.

Exposes Thomas tools as an MCP server so that any MCP-compatible client
(Claude Desktop, external tools, LangGraph, etc.) can discover and invoke them.

Supports both stdio and HTTP transports via the ``mcp`` Python SDK (FastMCP).

Usage — stdio (local, Claude Desktop integration)::

    python -m thomas.tools.mcp_bridge

Usage — streamable HTTP::

    python -m thomas.tools.mcp_bridge --transport http --port 8100

The bridge reads the live :class:`ToolRegistry` and converts each
registered :class:`Tool` into an MCP tool with the same name, description,
and JSON Schema parameters.
"""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy MCP SDK import — the ``mcp`` package is an optional dependency.
# ---------------------------------------------------------------------------

_MCP_AVAILABLE: bool = False
_FastMCP: Any = None

try:
    from mcp.server.fastmcp import FastMCP as _FastMCPClass

    _FastMCP = _FastMCPClass
    _MCP_AVAILABLE = True
except ImportError:
    pass


def mcp_available() -> bool:
    """Return True if the ``mcp`` Python package is installed."""
    return _MCP_AVAILABLE


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class MCPBridge:
    """Wraps a Thomas :class:`ToolRegistry` as an MCP server.

    Each tool in the registry becomes an MCP tool whose ``inputSchema``
    mirrors the tool's existing ``parameters`` JSON Schema and whose handler
    delegates to :meth:`Tool.safe_execute`.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        server_name: str = "thomas",
        server_version: str = "0.14.57",
    ) -> None:
        if not _MCP_AVAILABLE:
            raise RuntimeError("The 'mcp' package is required for MCP support. Install it with: pip install mcp")
        self._registry = registry
        self._server: Any = _FastMCP(
            name=server_name,
            version=server_version,
        )
        self._registered: set[str] = set()
        self._sync_tools()

    # -- tool synchronisation -----------------------------------------------

    def _sync_tools(self) -> None:
        """Register every tool in the Thomas registry as an MCP tool."""
        for tool in self._registry.list_tools():
            if tool.name in self._registered:
                continue
            self._register_tool(tool)

    def _register_tool(self, tool: Tool) -> None:
        """Register a single Thomas tool as an MCP tool."""
        name = tool.name
        description = tool.description or f"Thomas tool: {name}"

        # Build the MCP handler that delegates to the Thomas tool.
        async def _handler(
            _tool: Tool = tool,
            **kwargs: Any,
        ) -> str:
            result: ToolResult = await _tool.safe_execute(kwargs)
            return result.to_content()

        # Attach metadata so FastMCP can advertise the schema.
        _handler.__name__ = name
        _handler.__doc__ = description

        # Use the low-level add_tool API when parameters are a raw schema
        # dict (which is the case for Thomas tools).  FastMCP's decorator
        # API infers schemas from type hints, but we already have them.
        self._server.add_tool(
            fn=_handler,
            name=name,
            description=description,
        )
        self._registered.add(name)
        log.debug("MCP: registered tool %s", name)

    def refresh(self) -> None:
        """Re-sync: pick up tools added to the registry after init."""
        self._sync_tools()

    # -- server lifecycle ---------------------------------------------------

    def run_stdio(self) -> None:
        """Run the MCP server over stdio (blocking)."""
        log.info("MCP bridge starting (stdio transport)")
        self._server.run(transport="stdio")

    def run_http(self, host: str = "127.0.0.1", port: int = 8100) -> None:
        """Run the MCP server over streamable HTTP (blocking)."""
        log.info("MCP bridge starting (HTTP transport on %s:%d)", host, port)
        self._server.run(
            transport="streamable-http",
            host=host,
            port=port,
        )

    @property
    def server(self) -> Any:
        """Return the underlying FastMCP server instance."""
        return self._server

    # -- introspection ------------------------------------------------------

    def list_tool_names(self) -> list[str]:
        """Return names of all tools exposed via MCP."""
        return sorted(self._registered)

    def tool_count(self) -> int:
        """Return the number of MCP-exposed tools."""
        return len(self._registered)


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def create_mcp_bridge(
    registry: ToolRegistry,
    *,
    server_name: str = "thomas",
    server_version: str = "0.14.57",
) -> MCPBridge:
    """Create and return an :class:`MCPBridge` for *registry*.

    Raises :class:`RuntimeError` if the ``mcp`` package is not installed.
    """
    return MCPBridge(
        registry,
        server_name=server_name,
        server_version=server_version,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main() -> None:
    """Entry point for ``python -m thomas.tools.mcp_bridge``."""
    import argparse

    parser = argparse.ArgumentParser(description="Thomas MCP bridge")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8100, help="HTTP bind port")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Bootstrap a minimal registry with all default tools.
    registry = ToolRegistry()

    # Import and register the built-in tool modules.
    try:
        from thomas.tools import _register_defaults

        _register_defaults(registry)
    except ImportError:
        log.warning("Could not import default tools; registry will be empty")

    bridge = create_mcp_bridge(registry)
    log.info("MCP bridge ready with %d tools", bridge.tool_count())

    if args.transport == "http":
        bridge.run_http(host=args.host, port=args.port)
    else:
        bridge.run_stdio()


if __name__ == "__main__":
    _main()
