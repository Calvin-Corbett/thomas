"""Tools for nodes module - DAG node execution and workflow management."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class NodesCreateNodeTool(Tool):
    """Create a workflow node."""

    name = "nodes_create_node"
    category = "nodes"
    description = "Create a new workflow node."
    parameters = {
        "type": "object",
        "properties": {
            "node_id": {
                "type": "string",
                "description": "Node identifier",
            },
            "node_type": {
                "type": "string",
                "description": "Node type (task, branch, merge, etc.)",
            },
            "config": {
                "type": "object",
                "description": "Node configuration",
            },
        },
        "required": ["node_id", "node_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .node import create_node

            node = create_node(
                node_id=args["node_id"],
                node_type=args["node_type"],
                config=args.get("config", {}),
            )
            return ToolResult(ok=True, data=node or {"created": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NodesExecuteNodeTool(Tool):
    """Execute a node."""

    name = "nodes_execute_node"
    category = "nodes"
    description = "Execute a workflow node with given inputs."
    parameters = {
        "type": "object",
        "properties": {
            "node_id": {
                "type": "string",
                "description": "Node ID",
            },
            "inputs": {
                "type": "object",
                "description": "Input data",
            },
        },
        "required": ["node_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .executor import execute_node

            result = execute_node(
                node_id=args["node_id"],
                inputs=args.get("inputs", {}),
            )
            return ToolResult(ok=True, data=result or {"executed": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NodesGetNodeStatusTool(Tool):
    """Get node execution status."""

    name = "nodes_get_node_status"
    category = "nodes"
    description = "Get the execution status of a node."
    parameters = {
        "type": "object",
        "properties": {
            "node_id": {
                "type": "string",
                "description": "Node ID",
            },
        },
        "required": ["node_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .executor import get_status

            status = get_status(args["node_id"])
            return ToolResult(ok=True, data=status or {"status": "unknown"})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_nodes_tools(registry):
    """Register nodes tools with the tool registry."""
    tools = [
        NodesCreateNodeTool(),
        NodesExecuteNodeTool(),
        NodesGetNodeStatusTool(),
    ]
    for tool in tools:
        registry.register(tool)
