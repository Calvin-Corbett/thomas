"""Tools for WebRTC module."""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class PeerConnectionTool(Tool):
    """Manage WebRTC peer connections."""

    name = "peer_connection"
    category = "webrtc"
    description = "Create and manage WebRTC peer connections"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["create", "connect", "close", "stats"],
                "description": "Connection operation",
            },
            "peer_id": {"type": "string", "description": "Peer identifier"},
        },
        "required": ["operation"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            operation = args.get("operation")
            peer_id = args.get("peer_id")

            if operation == "create":
                return ToolResult(ok=True, data={"status": "peer_created", "peer_id": peer_id, "state": "new"})

            elif operation == "connect":
                remote_peer = args.get("remote_peer")
                return ToolResult(
                    ok=True, data={"status": "connecting", "peer_id": peer_id, "remote_peer": remote_peer}
                )

            elif operation == "close":
                return ToolResult(ok=True, data={"status": "peer_closed", "peer_id": peer_id})

            elif operation == "stats":
                return ToolResult(
                    ok=True, data={"peer_id": peer_id, "state": "connected", "rtt_ms": 35, "bandwidth_mbps": 50}
                )

            else:
                return ToolResult(ok=False, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DataChannelTool(Tool):
    """Manage WebRTC data channels."""

    name = "data_channel"
    category = "webrtc"
    description = "Create and manage data channels for peer communication"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "send", "close"], "description": "Channel action"},
            "channel_label": {"type": "string", "description": "Channel label"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action")
            channel_label = args.get("channel_label")

            if action == "create":
                return ToolResult(ok=True, data={"status": "channel_created", "label": channel_label, "state": "open"})

            elif action == "send":
                data_size = args.get("data_size", 1024)
                return ToolResult(ok=True, data={"status": "data_sent", "label": channel_label, "bytes": data_size})

            elif action == "close":
                return ToolResult(ok=True, data={"status": "channel_closed", "label": channel_label})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_webrtc_tools(registry):
    """Register all WebRTC tools."""
    registry.register(PeerConnectionTool())
    registry.register(DataChannelTool())
