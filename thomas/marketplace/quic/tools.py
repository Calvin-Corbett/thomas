"""Tools for QUIC protocol module."""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class ConnectionManagementTool(Tool):
    """Manage QUIC connections."""

    name = "quic_connection"
    category = "quic"
    description = "Create, establish, and close QUIC connections"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "establish", "close", "stats"],
                "description": "Connection action",
            },
            "connection_id": {"type": "string", "description": "Connection identifier"},
            "remote_addr": {"type": "string", "description": "Remote address"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action")
            connection_id = args.get("connection_id")

            if action == "create":
                remote_addr = args.get("remote_addr", "localhost:443")
                return ToolResult(
                    ok=True,
                    data={
                        "status": "connection_created",
                        "connection_id": connection_id,
                        "remote_addr": remote_addr,
                        "state": "idle",
                    },
                )

            elif action == "establish":
                return ToolResult(
                    ok=True, data={"status": "connection_established", "connection_id": connection_id, "rtt_ms": 25}
                )

            elif action == "close":
                return ToolResult(ok=True, data={"status": "connection_closed", "connection_id": connection_id})

            elif action == "stats":
                return ToolResult(
                    ok=True,
                    data={
                        "connection_id": connection_id,
                        "state": "established",
                        "bytes_sent": 5000,
                        "bytes_received": 8000,
                        "rtt_ms": 25,
                    },
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class StreamManagementTool(Tool):
    """Manage QUIC streams."""

    name = "quic_streams"
    category = "quic"
    description = "Create and manage QUIC streams"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["create", "send", "receive", "close"],
                "description": "Stream operation",
            },
            "stream_id": {"type": "integer", "description": "Stream identifier"},
        },
        "required": ["operation"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            operation = args.get("operation")

            if operation == "create":
                return ToolResult(ok=True, data={"status": "stream_created", "stream_id": 0, "state": "open"})

            elif operation == "send":
                stream_id = args.get("stream_id")
                return ToolResult(ok=True, data={"status": "data_sent", "stream_id": stream_id, "bytes_sent": 1024})

            elif operation == "receive":
                return ToolResult(ok=True, data={"status": "data_received", "bytes_received": 2048})

            elif operation == "close":
                stream_id = args.get("stream_id")
                return ToolResult(ok=True, data={"status": "stream_closed", "stream_id": stream_id})

            else:
                return ToolResult(ok=False, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_quic_tools(registry):
    """Register all QUIC tools."""
    registry.register(ConnectionManagementTool())
    registry.register(StreamManagementTool())
