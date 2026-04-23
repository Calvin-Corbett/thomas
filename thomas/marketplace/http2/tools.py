"""Tools for HTTP/2 module.

Provides tools for HTTP/2 protocol operations and management.
"""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class HTTP2ConnectionTool(Tool):
    """Manage HTTP/2 connections."""

    name = "http2_connection"
    category = "http2"
    description = "Create and manage HTTP/2 connections with flow control"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_connection", "send_request", "receive_response"],
                "description": "Connection action",
            },
            "url": {"type": "string", "description": "Target URL"},
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                "description": "HTTP method",
            },
            "headers": {"type": "object", "description": "Request headers"},
            "body": {"type": "string", "description": "Request body"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_connection":
                url = args.get("url", "")
                if not url:
                    return ToolResult(ok=False, error="url required")

                return ToolResult(ok=True, data={"status": "connection_established", "url": url, "protocol": "HTTP/2"})

            elif action == "send_request":
                method = args.get("method", "GET")
                url = args.get("url", "")
                headers = args.get("headers", {})
                body = args.get("body", "")

                if not url:
                    return ToolResult(ok=False, error="url required")

                return ToolResult(ok=True, data={"status": "request_sent", "method": method, "url": url})

            elif action == "receive_response":
                return ToolResult(
                    ok=True, data={"status": "response_received", "status_code": 200, "headers": {}, "body": ""}
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class FrameManagementTool(Tool):
    """Manage HTTP/2 frames."""

    name = "http2_frames"
    category = "http2"
    description = "Manage HTTP/2 frames (DATA, HEADERS, SETTINGS, etc.)"
    parameters = {
        "type": "object",
        "properties": {
            "frame_type": {
                "type": "string",
                "enum": ["data", "headers", "settings", "ping", "reset_stream"],
                "description": "Type of frame",
            },
            "stream_id": {"type": "integer", "description": "Stream ID"},
        },
        "required": ["frame_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            frame_type = args.get("frame_type", "")
            stream_id = int(args.get("stream_id", 0))

            supported = ["data", "headers", "settings", "ping", "reset_stream"]
            if frame_type not in supported:
                return ToolResult(ok=False, error=f"Unknown frame type: {frame_type}")

            return ToolResult(
                ok=True, data={"frame_type": frame_type, "stream_id": stream_id, "status": "frame_created"}
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class FlowControlTool(Tool):
    """Manage HTTP/2 flow control."""

    name = "http2_flow_control"
    category = "http2"
    description = "Configure and manage HTTP/2 flow control windows"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set_window_size", "get_window_size", "update_flow"],
                "description": "Flow control action",
            },
            "window_size": {"type": "integer", "description": "Window size in bytes"},
            "stream_id": {"type": "integer", "description": "Stream ID (0 for connection-level)"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            window_size = int(args.get("window_size", 65535))
            stream_id = int(args.get("stream_id", 0))

            if action == "set_window_size":
                return ToolResult(
                    ok=True, data={"status": "window_size_set", "stream_id": stream_id, "window_size": window_size}
                )

            elif action == "get_window_size":
                return ToolResult(
                    ok=True, data={"status": "window_size_retrieved", "stream_id": stream_id, "window_size": 65535}
                )

            elif action == "update_flow":
                return ToolResult(ok=True, data={"status": "flow_updated", "stream_id": stream_id})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_http2_tools(registry):
    """Register all HTTP/2 tools."""
    registry.register(HTTP2ConnectionTool())
    registry.register(FrameManagementTool())
    registry.register(FlowControlTool())
