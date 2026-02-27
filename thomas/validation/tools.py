"""Tools for validation module - data validation and schema checking."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class ValidationValidateTool(Tool):
    """Validate data against a schema."""

    name = "validation_validate"
    category = "validation"
    description = "Validate data against a JSON schema or rules."
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

            result = validate(
                data=args["data"],
                schema=args["schema"],
            )
            return ToolResult(ok=True, data=result or {"valid": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ValidationValidateTypesTool(Tool):
    """Type-check data fields."""

    name = "validation_validate_types"
    category = "validation"
    description = "Validate that fields have expected types."
    parameters = {
        "type": "object",
        "properties": {
            "data": {
                "type": "object",
                "description": "Data to validate",
            },
            "type_spec": {
                "type": "object",
                "description": "Field type specifications",
            },
        },
        "required": ["data", "type_spec"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .type_checker import validate_types

            result = validate_types(
                data=args["data"],
                type_spec=args["type_spec"],
            )
            return ToolResult(ok=True, data=result or {"valid": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ValidationSanitizeTool(Tool):
    """Sanitize user input."""

    name = "validation_sanitize"
    category = "validation"
    description = "Remove or escape potentially harmful content."
    parameters = {
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": "Data to sanitize",
            },
            "mode": {
                "type": "string",
                "description": "Sanitization mode (html, sql, etc.)",
            },
        },
        "required": ["data"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .sanitizer import sanitize

            result = sanitize(
                data=args["data"],
                mode=args.get("mode", "html"),
            )
            return ToolResult(ok=True, data={"sanitized": result})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ValidationValidateEmailTool(Tool):
    """Validate email address."""

    name = "validation_validate_email"
    category = "validation"
    description = "Check if an email address is valid."
    parameters = {
        "type": "object",
        "properties": {
            "email": {
                "type": "string",
                "description": "Email address to validate",
            },
        },
        "required": ["email"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .email_validator import is_valid_email

            is_valid = is_valid_email(args["email"])
            return ToolResult(ok=True, data={"valid": is_valid})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_validation_tools(registry):
    """Register validation tools with the tool registry."""
    tools = [
        ValidationValidateTool(),
        ValidationValidateTypesTool(),
        ValidationSanitizeTool(),
        ValidationValidateEmailTool(),
    ]
    for tool in tools:
        registry.register(tool)
