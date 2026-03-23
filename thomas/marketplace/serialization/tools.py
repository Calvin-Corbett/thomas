"""Tools for serialization module - object serialization and deserialization."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class SerializationSerializeTool(Tool):
    """Serialize an object."""

    name = "serialization_serialize"
    category = "serialization"
    description = "Serialize an object to JSON or other formats."
    parameters = {
        "type": "object",
        "properties": {
            "object": {
                "type": "object",
                "description": "Object to serialize",
            },
            "format": {
                "type": "string",
                "description": "Format (json, pickle, msgpack, etc.)",
            },
        },
        "required": ["object"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .serializer import serialize

            result = serialize(
                obj=args["object"],
                format=args.get("format", "json"),
            )
            return ToolResult(ok=True, data={"serialized": result or {}})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SerializationDeserializeTool(Tool):
    """Deserialize data."""

    name = "serialization_deserialize"
    category = "serialization"
    description = "Deserialize data from various formats."
    parameters = {
        "type": "object",
        "properties": {
            "data": {
                "type": ["string", "object"],
                "description": "Serialized data",
            },
            "format": {
                "type": "string",
                "description": "Format (json, pickle, msgpack, etc.)",
            },
        },
        "required": ["data"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .serializer import deserialize

            result = deserialize(
                data=args["data"],
                format=args.get("format", "json"),
            )
            return ToolResult(ok=True, data={"deserialized": result or {}})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SerializationValidateSchemaTool(Tool):
    """Validate against a schema."""

    name = "serialization_validate_schema"
    category = "serialization"
    description = "Validate data against a schema."
    parameters = {
        "type": "object",
        "properties": {
            "data": {
                "type": "object",
                "description": "Data to validate",
            },
            "schema": {
                "type": "object",
                "description": "JSON schema",
            },
        },
        "required": ["data", "schema"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .validator import validate

            is_valid = validate(
                data=args["data"],
                schema=args["schema"],
            )
            return ToolResult(ok=True, data={"valid": is_valid})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_serialization_tools(registry):
    """Register serialization tools with the tool registry."""
    tools = [
        SerializationSerializeTool(),
        SerializationDeserializeTool(),
        SerializationValidateSchemaTool(),
    ]
    for tool in tools:
        registry.register(tool)
