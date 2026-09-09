"""Fake MCP server test fixture: newline-delimited JSON-RPC 2.0 over stdio.

Spawned as a subprocess by tests/test_mcp_client.py to make the MCP client
tests hermetic (no network, no third-party server). Implements the minimal
protocol surface the client exercises:

- initialize / notifications/initialized handshake
- tools/list with cursor pagination (two pages)
- tools/call for: echo, add, tag (reads FAKE_MCP_TAG env), fail (isError),
  sleep (for timeout tests)
- JSON-RPC error for unknown tools/methods
"""

from __future__ import annotations

import json
import os
import sys
import time

PAGE_ONE = [
    {
        "name": "echo",
        "description": "Echo the message back.",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "Text to echo."}},
            "required": ["message"],
        },
    },
    {
        "name": "add",
        "description": "Add two numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
]

PAGE_TWO = [
    {
        "name": "tag",
        "description": "Return the FAKE_MCP_TAG environment variable.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "fail",
        "description": "Always reports an in-band tool error.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sleep",
        "description": "Sleep for the given seconds.",
        "inputSchema": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
        },
    },
]


def _reply(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _text_result(msg_id, text: str, is_error: bool = False) -> None:
    _reply(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
        }
    )


def _error(msg_id, code: int, message: str) -> None:
    _reply({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def _handle_tools_call(msg_id, params: dict) -> None:
    name = params.get("name")
    args = params.get("arguments") or {}
    if name == "echo":
        _text_result(msg_id, str(args.get("message", "")))
    elif name == "add":
        _text_result(msg_id, str(float(args.get("a", 0)) + float(args.get("b", 0))))
    elif name == "tag":
        _text_result(msg_id, os.environ.get("FAKE_MCP_TAG", ""))
    elif name == "fail":
        _text_result(msg_id, "deliberate failure", is_error=True)
    elif name == "sleep":
        time.sleep(float(args.get("seconds", 30)))
        _text_result(msg_id, "woke")
    else:
        _error(msg_id, -32602, f"Unknown tool: {name}")


def main() -> None:
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}
        if method == "initialize":
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": params.get("protocolVersion", ""),
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "fake-mcp", "version": "1.0.0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            if params.get("cursor") == "page2":
                _reply({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": PAGE_TWO}})
            else:
                _reply({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": PAGE_ONE, "nextCursor": "page2"}})
        elif method == "tools/call":
            _handle_tools_call(msg_id, params)
        elif method == "ping":
            _reply({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        elif msg_id is not None:
            _error(msg_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
