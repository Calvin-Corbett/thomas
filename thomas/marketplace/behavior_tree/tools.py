"""Tools for Behavior Tree module.

Provides tools for creating, executing, and monitoring behavior trees.
"""

from typing import Any

from thomas.marketplace.behavior_tree import core
from thomas.tools.base import Tool, ToolResult


class TreeExecutionTool(Tool):
    """Execute behavior trees and manage execution context."""

    name = "behavior_tree_execute"
    category = "behavior_tree"
    description = "Create and execute behavior trees"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["execute_default", "create_tree", "get_last_execution"],
                "description": "Execution action",
            },
            "tree_name": {"type": "string", "description": "Name for the tree"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.trees: dict[str, core.BehaviorTree] = {}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "execute_default":
                # Create a simple default tree for demo
                root = core.Sequence("root")
                root.add_child(core.Condition("check", lambda ctx: True))
                root.add_child(core.Action("act", self._sample_action))

                tree = core.BehaviorTree(root, "default_tree")
                status = await tree.execute()

                self.trees["default_tree"] = tree
                return ToolResult(ok=True, data={"tree_id": tree.id, "status": status.value})

            elif action == "create_tree":
                tree_name = args.get("tree_name", "tree")
                root = core.Sequence(f"{tree_name}_root")
                tree = core.BehaviorTree(root, tree_name)
                self.trees[tree_name] = tree

                return ToolResult(ok=True, data={"tree_id": tree.id, "tree_name": tree_name})

            elif action == "get_last_execution":
                if not self.trees:
                    return ToolResult(ok=False, error="No trees created yet")

                last_tree = list(self.trees.values())[-1]
                if not last_tree.executions:
                    return ToolResult(ok=False, error="No executions yet")

                execution = last_tree.executions[-1]
                return ToolResult(
                    ok=True,
                    data={
                        "tree_name": last_tree.name,
                        "execution_id": last_tree.id,
                        "log_entries": len(execution.execution_log),
                        "variables": execution.variables,
                    },
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    async def _sample_action(self, context: core.ExecutionContext) -> bool:
        """Sample action for testing."""
        return True


class TreeNodeTool(Tool):
    """Manage behavior tree nodes."""

    name = "behavior_tree_nodes"
    category = "behavior_tree"
    description = "Create and configure tree nodes"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_node_types", "get_node_info"],
                "description": "Node management action",
            },
            "node_type": {"type": "string", "description": "Type of node to get info about"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "list_node_types":
                node_types = [
                    {"name": "Selector", "description": "Returns success if any child succeeds"},
                    {"name": "Sequence", "description": "Returns success only if all children succeed"},
                    {"name": "Parallel", "description": "Executes all children concurrently"},
                    {"name": "Condition", "description": "Checks a boolean condition"},
                    {"name": "Action", "description": "Executes an async action"},
                    {"name": "Inverter", "description": "Decorator that flips success/failure"},
                    {"name": "Repeater", "description": "Decorator that repeats child execution"},
                ]
                return ToolResult(ok=True, data={"node_types": node_types})

            elif action == "get_node_info":
                node_type = args.get("node_type", "")

                node_info = {
                    "Selector": {
                        "description": "Returns success if any child succeeds",
                        "children_min": 1,
                        "children_max": None,
                        "composite": True,
                    },
                    "Sequence": {
                        "description": "Returns success only if all children succeed",
                        "children_min": 1,
                        "children_max": None,
                        "composite": True,
                    },
                    "Parallel": {
                        "description": "Executes all children concurrently",
                        "children_min": 1,
                        "children_max": None,
                        "composite": True,
                    },
                    "Condition": {
                        "description": "Checks a boolean condition",
                        "children_min": 0,
                        "children_max": 0,
                        "composite": False,
                    },
                    "Action": {
                        "description": "Executes an async action",
                        "children_min": 0,
                        "children_max": 0,
                        "composite": False,
                    },
                }

                if node_type in node_info:
                    return ToolResult(ok=True, data=node_info[node_type])
                else:
                    return ToolResult(ok=False, error=f"Unknown node type: {node_type}")

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TreeMonitoringTool(Tool):
    """Monitor behavior tree execution."""

    name = "behavior_tree_monitor"
    category = "behavior_tree"
    description = "Monitor tree execution, logs, and statistics"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get_status", "validate_tree"], "description": "Monitoring action"},
            "tree_id": {"type": "string", "description": "Tree identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.monitored_trees: dict[str, core.BehaviorTree] = {}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "get_status":
                if not self.monitored_trees:
                    return ToolResult(ok=True, data={"trees_monitored": 0, "total_executions": 0})

                total_executions = sum(len(t.executions) for t in self.monitored_trees.values())
                return ToolResult(
                    ok=True, data={"trees_monitored": len(self.monitored_trees), "total_executions": total_executions}
                )

            elif action == "validate_tree":
                tree_id = args.get("tree_id", "")

                if tree_id in self.monitored_trees:
                    tree = self.monitored_trees[tree_id]
                    errors = tree.validate()
                    return ToolResult(ok=True, data={"valid": len(errors) == 0, "errors": errors})
                else:
                    return ToolResult(ok=False, error=f"Tree not found: {tree_id}")

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_behavior_tree_tools(registry):
    """Register all behavior tree tools."""
    registry.register(TreeExecutionTool())
    registry.register(TreeNodeTool())
    registry.register(TreeMonitoringTool())
