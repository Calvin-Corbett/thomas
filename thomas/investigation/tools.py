"""Tools for investigation module - issue tracking and debugging."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class InvestigationCreateIssueTool(Tool):
    """Create an investigation issue."""

    name = "investigation_create_issue"
    category = "investigation"
    description = "Create a new investigation or issue tracking entry."
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Issue title",
            },
            "description": {
                "type": "string",
                "description": "Detailed description",
            },
            "category": {
                "type": "string",
                "description": "Issue category (bug, feature, debug, etc.)",
            },
            "severity": {
                "type": "string",
                "description": "Severity (low, medium, high, critical)",
            },
        },
        "required": ["title"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .issue import create_issue

            issue = create_issue(
                title=args["title"],
                description=args.get("description", ""),
                category=args.get("category", "debug"),
                severity=args.get("severity", "medium"),
            )
            return ToolResult(ok=True, data=issue or {"created": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class InvestigationLogFindingTool(Tool):
    """Log a finding or piece of evidence."""

    name = "investigation_log_finding"
    category = "investigation"
    description = "Log evidence or findings for an investigation."
    parameters = {
        "type": "object",
        "properties": {
            "issue_id": {
                "type": "string",
                "description": "Issue ID",
            },
            "finding_type": {
                "type": "string",
                "description": "Type of finding (observation, error, metric, etc.)",
            },
            "content": {
                "type": "string",
                "description": "Finding content",
            },
        },
        "required": ["issue_id", "finding_type", "content"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .finding import log_finding

            result = log_finding(
                issue_id=args["issue_id"],
                finding_type=args["finding_type"],
                content=args["content"],
            )
            return ToolResult(ok=True, data=result or {"logged": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_investigation_tools(registry):
    """Register investigation tools with the tool registry."""
    tools = [
        InvestigationCreateIssueTool(),
        InvestigationLogFindingTool(),
    ]
    for tool in tools:
        registry.register(tool)
