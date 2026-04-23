"""Tools for messages module - conversation message management."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class MessagesCreateTool(Tool):
    """Create a message."""

    name = "messages_create"
    category = "messages"
    description = "Create a new message in a conversation."
    parameters = {
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "string",
                "description": "Conversation ID",
            },
            "role": {
                "type": "string",
                "description": "Message role (user, assistant, system)",
            },
            "content": {
                "type": "string",
                "description": "Message content",
            },
            "metadata": {
                "type": "object",
                "description": "Optional metadata",
            },
        },
        "required": ["conversation_id", "role", "content"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import create_message

            msg = create_message(
                conversation_id=args["conversation_id"],
                role=args["role"],
                content=args["content"],
                metadata=args.get("metadata", {}),
            )
            return ToolResult(ok=True, data=msg or {"created": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MessagesListTool(Tool):
    """List messages in a conversation."""

    name = "messages_list"
    category = "messages"
    description = "List messages in a conversation."
    parameters = {
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "string",
                "description": "Conversation ID",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum messages (default: 50)",
            },
            "offset": {
                "type": "integer",
                "description": "Pagination offset",
            },
        },
        "required": ["conversation_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import list_messages

            messages = list_messages(
                conversation_id=args["conversation_id"],
                limit=args.get("limit", 50),
                offset=args.get("offset", 0),
            )
            return ToolResult(ok=True, data={"messages": messages or []})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MessagesDeleteTool(Tool):
    """Delete a message."""

    name = "messages_delete"
    category = "messages"
    description = "Delete a message by ID."
    parameters = {
        "type": "object",
        "properties": {
            "message_id": {
                "type": "string",
                "description": "Message ID",
            },
        },
        "required": ["message_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import delete_message

            delete_message(args["message_id"])
            return ToolResult(ok=True, data={"deleted": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_messages_tools(registry):
    """Register messages tools with the tool registry."""
    tools = [
        MessagesCreateTool(),
        MessagesListTool(),
        MessagesDeleteTool(),
    ]
    for tool in tools:
        registry.register(tool)
