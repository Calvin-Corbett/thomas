"""Stdio MCP bridge from a Claude Build lead to its authenticated run channel."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx

from .run_channel_client import RunChannelClient
from .run_channel_tools import AgentStatusTool, SpawnAgentsTool, StopAgentTool, WaitAgentsTool

SERVER_NAME = "thomas_praxis"
# Every Build lead with a run channel gets these four. `delete_files` is not among them: only a run
# that may edit is offered it (DELETE_TOOL_NAME, OFFER_DELETE_FLAG).
MCP_TOOL_NAMES = tuple(
    f"mcp__{SERVER_NAME}__{name}" for name in ("spawn_agents", "wait_agents", "agent_status", "stop_agent")
)
DELETE_TOOL_NAME = f"mcp__{SERVER_NAME}__delete_files"
OFFER_DELETE_FLAG = "--offer-delete"
_ACTIONS = {
    "spawn_agents": ("spawn", SpawnAgentsTool.parameters),
    "wait_agents": ("wait", WaitAgentsTool.parameters),
    "agent_status": ("status", AgentStatusTool.parameters),
    "stop_agent": ("stop_child", StopAgentTool.parameters),
}
_DELETE_SCHEMA = {
    "type": "object",
    "properties": {
        "paths": {
            "type": "array",
            "minItems": 1,
            "maxItems": 200,  # RunChannel.delete_files refuses a longer list
            "items": {"type": "string"},
            "description": "Files to delete, each relative to this Build run's project folder.",
        },
        "why": {"type": "string", "description": "Why these files go; the run's history records it."},
    },
    "required": ["paths", "why"],
    "additionalProperties": False,
}
_DESCRIPTIONS = {
    "spawn_agents": "Start cited read, review, or verification children in this Build run.",
    "wait_agents": "Wait for child events and terminal results in this Build run.",
    "agent_status": "Read child status without waiting.",
    "stop_agent": "Stop one child in this Build run.",
    "delete_files": (
        "Delete files in this Build run's project folder, and nothing else. Give paths relative to the "
        "project folder. A path outside it, the folder itself, anything inside .git, a folder, a symlink or "
        "junction, or a file that does not exist is refused, and the result says which and why; every other "
        "path is deleted. Say why in `why`: the run's history records what was deleted."
    ),
}


def server_config(python_executable: str, *, offer_delete: bool = True) -> dict[str, Any]:
    """The token remains in the inherited process environment, never in a file.

    ``offer_delete`` defaults to an editing run's config, the only kind of run that starts a Claude
    Build lead; a run that may not edit passes False and its bridge never lists ``delete_files``.
    """
    # -P: the bridge starts in the project folder, and a Thomas project's folder is a copy of Thomas's source.
    # With plain -m that copy's own, older bridge ran instead of this one (no delete_files, 2026-09-25).
    args = ["-P", "-m", __name__, *([OFFER_DELETE_FLAG] if offer_delete else [])]
    return {"mcpServers": {SERVER_NAME: {"command": python_executable, "args": args}}}


def _actions(offer_delete: bool) -> dict[str, tuple[str, dict[str, Any]]]:
    return {**_ACTIONS, "delete_files": ("delete", _DELETE_SCHEMA)} if offer_delete else _ACTIONS


def _tool_list(offer_delete: bool = False) -> list[dict[str, Any]]:
    return [
        {"name": name, "description": _DESCRIPTIONS[name], "inputSchema": schema}
        for name, (_, schema) in _actions(offer_delete).items()
    ]


async def handle(
    message: dict[str, Any], client: RunChannelClient, *, offer_delete: bool = False
) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        version = str((message.get("params") or {}).get("protocolVersion") or "2024-11-05")
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": "1"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _tool_list(offer_delete)}
    elif method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        actions = _actions(offer_delete)
        if name not in actions:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "unknown tool"}}
        payload = params.get("arguments") or {}
        if not isinstance(payload, dict):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "arguments must be an object"},
            }
        action = actions[name][0]
        if name == "spawn_agents":
            payload = {"units": payload.get("units"), "why_parallel": payload.get("why_parallel")}
        elif name == "delete_files":
            payload = {"paths": payload.get("paths"), "why": payload.get("why")}
        elif name in {"wait_agents", "agent_status"}:
            payload = {
                "agent_ids": payload.get("agent_ids"),
                "after": payload.get("after"),
                "timeout": payload.get("timeout", 30),
            }
        else:
            payload = {"agent_id": payload.get("agent_id")}
        try:
            report = await client.call(action, payload)
            result = {"content": [{"type": "text", "text": json.dumps(report)}], "isError": False}
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "unknown method"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main(argv: list[str] | None = None) -> int:
    offer_delete = OFFER_DELETE_FLAG in (sys.argv[1:] if argv is None else argv)
    client = RunChannelClient.from_environment()
    if client is None:
        print("Praxis run channel is unavailable for this Claude run", file=sys.stderr)
        return 2
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                continue
            response = asyncio.run(handle(message, client, offer_delete=offer_delete))
            if response is not None:
                sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except (json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
            print(f"Praxis MCP request failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
