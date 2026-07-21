"""Executable MCP (Model Context Protocol) client over stdio transport.

Speaks JSON-RPC 2.0 with newline-delimited framing, which is the framing the
MCP specification defines for the stdio transport (one JSON message per line,
messages must not contain embedded newlines). The official ``mcp`` Python
package is not installed in this project's environment, so this is a clean
stdlib implementation (asyncio subprocess + json) with no third-party
dependencies.

Provides:

- :class:`McpStdioClient` -- spawn a configured stdio server, perform the
  ``initialize`` handshake (capability negotiation recorded), discover tools
  via ``tools/list`` (pagination-aware), and invoke them via ``tools/call``
  in the same session. Context-manager support and clean child shutdown.
- :class:`McpSessionRegistry` -- holds several live sessions keyed by server
  name.
- :func:`client_from_server_row` -- build a client from the server metadata
  row schema persisted by ``thomas cli mcp add`` (see
  ``thomas/cli/parity_support.py``: name/transport/command/args/env/enabled).

Layering: this module is stdlib-only on purpose (tools tier must not reach
into cli/agent/server).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO: dict[str, str] = {"name": "thomas-mcp-client", "version": "1.0.0"}
DEFAULT_REQUEST_TIMEOUT = 30.0

_STREAM_LIMIT = 10 * 1024 * 1024  # 10 MiB per line; default 64 KiB is too small for tool results
_SHUTDOWN_GRACE_SECONDS = 3.0
_MAX_LIST_PAGES = 50


class McpError(Exception):
    """Base class for MCP client errors."""


class McpTransportError(McpError):
    """Spawn failure, broken pipe, or unexpected EOF from the server process."""


class McpTimeoutError(McpError):
    """A request timed out; the child process has been terminated."""


class McpServerError(McpError):
    """The server answered with a JSON-RPC error object."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data


@dataclass(frozen=True)
class McpToolDef:
    """A tool definition discovered from a server via ``tools/list``."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class McpCallResult:
    """Result of a ``tools/call`` round-trip."""

    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    structured: dict[str, Any] | None = None

    @property
    def text(self) -> str:
        """Concatenated text of all ``type: text`` content blocks."""
        parts = [str(block.get("text") or "") for block in self.content if block.get("type") == "text"]
        return "\n".join(part for part in parts if part)


class McpStdioClient:
    """MCP client for one stdio server: spawn, handshake, discover, call, shut down.

    Usage::

        client = McpStdioClient(name="files", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem"])
        async with client:
            tools = await client.list_tools()
            result = await client.call_tool(tools[0].name, {"path": "."})

    After :meth:`start`, negotiated ``protocol_version``, ``capabilities``,
    and ``server_info`` are recorded on the instance.
    """

    def __init__(
        self,
        *,
        name: str,
        command: str,
        args: list[str] | tuple[str, ...] = (),
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self.name = str(name or command).strip()
        self._command = str(command)
        self._args = [str(x) for x in args]
        self._env = dict(env or {})
        self._cwd = cwd
        self._request_timeout = float(request_timeout)
        self._proc: asyncio.subprocess.Process | None = None
        self._next_id = 0
        self._lock = asyncio.Lock()
        self.protocol_version: str = ""
        self.capabilities: dict[str, Any] = {}
        self.server_info: dict[str, Any] = {}

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        """Spawn the server process and perform the MCP initialize handshake."""
        if self._proc is not None:
            raise McpTransportError(f"MCP client {self.name!r} already started")
        env = {**os.environ, **self._env} if self._env else None
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
                cwd=self._cwd,
                limit=_STREAM_LIMIT,
            )
        except (OSError, ValueError) as exc:
            raise McpTransportError(f"failed to spawn MCP server {self.name!r} ({self._command}): {exc}") from exc
        result = await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": dict(CLIENT_INFO),
            },
        )
        self.protocol_version = str(result.get("protocolVersion") or "")
        capabilities = result.get("capabilities")
        self.capabilities = capabilities if isinstance(capabilities, dict) else {}
        server_info = result.get("serverInfo")
        self.server_info = server_info if isinstance(server_info, dict) else {}
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        log.debug(
            "MCP session %r established: server=%s protocol=%s",
            self.name,
            self.server_info.get("name"),
            self.protocol_version,
        )

    async def list_tools(self) -> list[McpToolDef]:
        """Discover the server's tools via ``tools/list`` (follows pagination cursors)."""
        out: list[McpToolDef] = []
        cursor: str | None = None
        for _ in range(_MAX_LIST_PAGES):
            params: dict[str, Any] = {"cursor": cursor} if cursor else {}
            result = await self._request("tools/list", params)
            rows = result.get("tools")
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                tool_name = str(row.get("name") or "").strip()
                if not tool_name:
                    continue
                schema = row.get("inputSchema")
                out.append(
                    McpToolDef(
                        name=tool_name,
                        description=str(row.get("description") or ""),
                        input_schema=schema if isinstance(schema, dict) else {},
                    )
                )
            next_cursor = result.get("nextCursor")
            cursor = str(next_cursor) if next_cursor else None
            if not cursor:
                break
        return out

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> McpCallResult:
        """Invoke a server tool via ``tools/call`` and return its content."""
        result = await self._request(
            "tools/call",
            {"name": str(tool_name), "arguments": dict(arguments or {})},
        )
        raw_content = result.get("content")
        content = [block for block in raw_content if isinstance(block, dict)] if isinstance(raw_content, list) else []
        structured = result.get("structuredContent")
        return McpCallResult(
            content=content,
            is_error=bool(result.get("isError")),
            structured=structured if isinstance(structured, dict) else None,
        )

    async def close(self) -> None:
        """Shut down the session, terminating the child process cleanly."""
        proc = self._proc
        self._proc = None
        if proc is None or proc.returncode is not None:
            return
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                log.debug("MCP %r stdin close failed: %s", self.name, exc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
        except TimeoutError:
            log.debug("MCP server %r did not exit on stdin close; killing", self.name)
            self._kill(proc)
            await proc.wait()

    async def __aenter__(self) -> McpStdioClient:
        if self._proc is None:
            await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        await self.close()
        return False

    # -- internals --------------------------------------------------------

    def _kill(self, proc: asyncio.subprocess.Process) -> None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass  # already exited

    async def _terminate_after_timeout(self, method: str) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None and proc.returncode is None:
            self._kill(proc)
            await proc.wait()
        log.warning("MCP server %r timed out on %r; child terminated", self.name, method)

    async def _send(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise McpTransportError(f"MCP session {self.name!r} is not running")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            proc.stdin.write(payload.encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            raise McpTransportError(f"MCP server {self.name!r} pipe closed while writing: {exc}") from exc

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.running:
            raise McpTransportError(f"MCP session {self.name!r} is not running")
        async with self._lock:
            self._next_id += 1
            msg_id = self._next_id
            await self._send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
            try:
                payload = await asyncio.wait_for(self._read_response(msg_id), timeout=self._request_timeout)
            except TimeoutError:
                await self._terminate_after_timeout(method)
                raise McpTimeoutError(
                    f"MCP server {self.name!r} timed out after {self._request_timeout}s on {method!r}; child terminated"
                ) from None
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            raise McpServerError(
                code if isinstance(code, int) else 0,
                str(error.get("message") or "server error"),
                error.get("data"),
            )
        result = payload.get("result")
        return result if isinstance(result, dict) else {}

    async def _read_response(self, msg_id: int) -> dict[str, Any]:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise McpTransportError(f"MCP session {self.name!r} is not running")
        while True:
            line = await proc.stdout.readline()
            if not line:
                raise McpTransportError(f"MCP server {self.name!r} closed the connection (EOF)")
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                log.debug("MCP %r: skipping non-JSON stdout line: %.120s", self.name, text)
                continue
            if not isinstance(message, dict):
                continue
            if message.get("id") == msg_id and ("result" in message or "error" in message):
                return message
            await self._handle_out_of_band(message)

    async def _handle_out_of_band(self, message: dict[str, Any]) -> None:
        """Handle server-initiated traffic seen while waiting for a response."""
        method = message.get("method")
        other_id = message.get("id")
        if method and other_id is not None:
            # Server-to-client request: answer ping, decline anything else.
            if method == "ping":
                await self._send({"jsonrpc": "2.0", "id": other_id, "result": {}})
            else:
                await self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": other_id,
                        "error": {"code": -32601, "message": f"method not supported by client: {method}"},
                    }
                )
            return
        if method:
            log.debug("MCP %r: ignoring notification %r", self.name, method)
            return
        log.debug("MCP %r: ignoring response for unknown id %r", self.name, other_id)


def client_from_server_row(row: dict[str, Any], *, request_timeout: float = DEFAULT_REQUEST_TIMEOUT) -> McpStdioClient:
    """Build a client from a persisted MCP server registry row.

    Row schema matches ``thomas cli mcp add`` metadata:
    ``{name, transport, command, args, url, env, enabled}``. Only the stdio
    transport is supported for live sessions.
    """
    name = str(row.get("name") or "").strip()
    transport = str(row.get("transport") or "stdio").strip().lower()
    if transport != "stdio":
        raise McpTransportError(f"MCP server {name or '?'}: unsupported transport {transport!r} (only stdio)")
    command = str(row.get("command") or "").strip()
    if not command:
        raise McpTransportError(f"MCP server {name or '?'}: no command configured")
    raw_args = row.get("args")
    raw_env = row.get("env")
    return McpStdioClient(
        name=name or command,
        command=command,
        args=[str(x) for x in raw_args] if isinstance(raw_args, list) else [],
        env={str(k): str(v) for k, v in raw_env.items()} if isinstance(raw_env, dict) else {},
        request_timeout=request_timeout,
    )


class McpSessionRegistry:
    """Holds several live MCP sessions keyed by server name."""

    def __init__(self) -> None:
        self._sessions: dict[str, McpStdioClient] = {}

    def names(self) -> list[str]:
        return sorted(self._sessions)

    def get(self, name: str) -> McpStdioClient | None:
        return self._sessions.get(str(name))

    async def connect(
        self,
        *,
        name: str,
        command: str,
        args: list[str] | tuple[str, ...] = (),
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> McpStdioClient:
        """Spawn + handshake a new session; replaces any stale session of the same name."""
        existing = self._sessions.get(name)
        if existing is not None:
            if existing.running:
                return existing
            await self.close(name)
        client = McpStdioClient(
            name=name, command=command, args=args, env=env, cwd=cwd, request_timeout=request_timeout
        )
        await client.start()
        self._sessions[client.name] = client
        return client

    async def connect_row(
        self, row: dict[str, Any], *, request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    ) -> McpStdioClient:
        """Connect from a persisted server registry row (see :func:`client_from_server_row`)."""
        client = client_from_server_row(row, request_timeout=request_timeout)
        existing = self._sessions.get(client.name)
        if existing is not None:
            if existing.running:
                return existing
            await self.close(client.name)
        await client.start()
        self._sessions[client.name] = client
        return client

    async def close(self, name: str) -> None:
        client = self._sessions.pop(str(name), None)
        if client is not None:
            await client.close()

    async def close_all(self) -> None:
        for name in list(self._sessions):
            await self.close(name)

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, name: str) -> bool:
        return str(name) in self._sessions
