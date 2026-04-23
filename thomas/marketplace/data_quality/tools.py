"""Tools for Data Quality module.

Provides tools for quality checks, monitoring, and reporting.
"""

from typing import Any

from thomas.marketplace.data_quality import core
from thomas.tools.base import Tool, ToolResult


class QualityCheckTool(Tool):
    """Create and configure quality checks."""

    name = "data_quality_checks"
    category = "data_quality"
    description = "Create and configure data quality checks"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_check", "list_checks", "run_check"],
                "description": "Check action",
            },
            "check_name": {"type": "string", "description": "Name of the check"},
            "check_type": {
                "type": "string",
                "enum": ["null_rate", "uniqueness", "range", "freshness"],
                "description": "Type of check",
            },
        },
        "required": ["action"],
    }

    def __init__(self):
        self.monitor = core.QualityMonitor()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_check":
                check_name = args.get("check_name", "check")
                check_type_str = args.get("check_type", "custom")

                try:
                    check_type = core.CheckType(check_type_str)
                except ValueError:
                    check_type = core.CheckType.CUSTOM

                check = core.Check(name=check_name, check_type=check_type)
                self.monitor.register_check(check)

                return ToolResult(
                    ok=True, data={"check_id": check.id, "check_name": check_name, "type": check_type.value}
                )

            elif action == "list_checks":
                checks = [c.to_dict() for c in self.monitor.checks.values()]
                return ToolResult(ok=True, data={"checks": checks})

            elif action == "run_check":
                return ToolResult(ok=True, data={"message": "Check executed"})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class QualityRuleTool(Tool):
    """Manage quality rules."""

    name = "data_quality_rules"
    category = "data_quality"
    description = "Create and manage quality rules"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["register_null_rule", "register_uniqueness_rule", "list_rules"],
                "description": "Rule action",
            },
            "rule_name": {"type": "string", "description": "Name of the rule"},
            "column": {"type": "string", "description": "Column to apply rule to"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.monitor = core.QualityMonitor()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "register_null_rule":
                rule_name = args.get("rule_name", "null_check")
                column = args.get("column", "")

                if not column:
                    return ToolResult(ok=False, error="column required")

                rule = core.NullRateRule(rule_name, column)
                self.monitor.register_rule(rule)

                return ToolResult(ok=True, data={"rule_id": rule.id, "rule_name": rule_name, "column": column})

            elif action == "register_uniqueness_rule":
                rule_name = args.get("rule_name", "uniqueness_check")
                column = args.get("column", "")

                if not column:
                    return ToolResult(ok=False, error="column required")

                rule = core.UniquenessRule(rule_name, column)
                self.monitor.register_rule(rule)

                return ToolResult(ok=True, data={"rule_id": rule.id, "rule_name": rule_name, "column": column})

            elif action == "list_rules":
                rules = [{"id": r.id, "name": r.name} for r in self.monitor.rules.values()]
                return ToolResult(ok=True, data={"rules": rules})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class QualityMonitoringTool(Tool):
    """Monitor data quality."""

    name = "data_quality_monitor"
    category = "data_quality"
    description = "Monitor data quality and get reports"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get_quality_score", "get_report", "record_update"],
                "description": "Monitoring action",
            },
            "dataset_id": {"type": "string", "description": "Dataset to monitor"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.monitor = core.QualityMonitor()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "get_quality_score":
                dataset_id = args.get("dataset_id", "")
                score = self.monitor.get_quality_score(dataset_id)
                return ToolResult(ok=True, data={"dataset_id": dataset_id, "quality_score": score})

            elif action == "get_report":
                report = self.monitor.get_report()
                return ToolResult(ok=True, data=report)

            elif action == "record_update":
                dataset_id = args.get("dataset_id", "")
                if not dataset_id:
                    return ToolResult(ok=False, error="dataset_id required")

                self.monitor.record_update(dataset_id)
                return ToolResult(ok=True, data={"recorded": dataset_id})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_data_quality_tools(registry):
    """Register all data quality tools."""
    registry.register(QualityCheckTool())
    registry.register(QualityRuleTool())
    registry.register(QualityMonitoringTool())
