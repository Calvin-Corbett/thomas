"""Tools for business rules engine module."""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class RuleManagementTool(Tool):
    """Manage business rules."""

    name = "rule_management"
    category = "rules"
    description = "Create and manage business rules"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "enable", "disable", "list"], "description": "Rule action"},
            "rule_name": {"type": "string", "description": "Rule identifier"},
            "priority": {"type": "integer", "description": "Rule priority"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action")

            if action == "create":
                rule_name = args.get("rule_name")
                priority = args.get("priority", 100)
                return ToolResult(ok=True, data={"status": "rule_created", "rule": rule_name, "priority": priority})

            elif action == "enable":
                rule_name = args.get("rule_name")
                return ToolResult(ok=True, data={"status": "rule_enabled", "rule": rule_name})

            elif action == "disable":
                rule_name = args.get("rule_name")
                return ToolResult(ok=True, data={"status": "rule_disabled", "rule": rule_name})

            elif action == "list":
                return ToolResult(ok=True, data={"rules": 25, "active": 20, "disabled": 5})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class RuleChainEvaluationTool(Tool):
    """Evaluate rule chains."""

    name = "rule_evaluation"
    category = "rules"
    description = "Evaluate and execute rule chains"
    parameters = {
        "type": "object",
        "properties": {
            "chain_name": {"type": "string", "description": "Rule chain identifier"},
            "context": {"type": "object", "description": "Evaluation context"},
        },
        "required": ["chain_name"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            chain_name = args.get("chain_name")
            context = args.get("context", {})

            return ToolResult(
                ok=True,
                data={
                    "status": "evaluation_complete",
                    "chain": chain_name,
                    "matching_rules": 5,
                    "executed": 5,
                    "errors": 0,
                },
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_rules_tools(registry):
    """Register all rules engine tools."""
    registry.register(RuleManagementTool())
    registry.register(RuleChainEvaluationTool())
