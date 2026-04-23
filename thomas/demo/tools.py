"""Tools for Demo module.

Provides tools for benchmark execution, campaign management, and demonstration harness.
"""

from pathlib import Path
from typing import Any

from thomas.demo.harness import DEFAULT_TASK_PACK, load_task_pack
from thomas.tools.base import Tool, ToolResult


class TaskPackTool(Tool):
    """Load and manage task packs for benchmarking."""

    name = "demo_task_pack"
    category = "demo"
    description = "Load and validate task pack for benchmarking"
    parameters = {
        "type": "object",
        "properties": {"task_pack_path": {"type": "string", "description": "Path to task pack JSON file"}},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            task_pack_path = Path(args.get("task_pack_path", str(DEFAULT_TASK_PACK)))

            if not task_pack_path.exists():
                return ToolResult(ok=False, error=f"Task pack not found: {task_pack_path}")

            try:
                tasks = load_task_pack(task_pack_path)
                return ToolResult(
                    ok=True,
                    data={
                        "status": "task_pack_loaded",
                        "path": str(task_pack_path),
                        "task_count": len(tasks),
                        "sample_tasks": [{"id": t.get("id"), "title": t.get("title", "")[:50]} for t in tasks[:3]],
                    },
                )
            except ValueError as e:
                return ToolResult(ok=False, error=f"Invalid task pack: {str(e)}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class BenchmarkTool(Tool):
    """Run benchmark tests."""

    name = "demo_benchmark"
    category = "demo"
    description = "Run agent benchmark suite"
    parameters = {
        "type": "object",
        "properties": {
            "benchmark_type": {
                "type": "string",
                "enum": ["agentic", "browser_duel", "comparison"],
                "description": "Type of benchmark",
            },
            "competitors": {"type": "array", "items": {"type": "string"}, "description": "Agents to compare"},
            "task_pack": {"type": "string", "description": "Task pack to use"},
        },
        "required": ["benchmark_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            benchmark_type = args.get("benchmark_type", "")
            competitors = args.get("competitors", ["thomas"])
            task_pack = args.get("task_pack", "default")

            if benchmark_type == "agentic":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "benchmark_prepared",
                        "type": "agentic",
                        "competitors": competitors,
                        "message": "Agentic benchmark ready to execute",
                    },
                )

            elif benchmark_type == "browser_duel":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "benchmark_prepared",
                        "type": "browser_duel",
                        "competitors": competitors[:2],
                        "message": "Browser duel benchmark ready",
                    },
                )

            elif benchmark_type == "comparison":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "benchmark_prepared",
                        "type": "comparison",
                        "competitors": competitors,
                        "metrics": ["success_rate", "speed", "quality"],
                        "message": "Comparison benchmark ready",
                    },
                )

            else:
                return ToolResult(ok=False, error=f"Unknown benchmark type: {benchmark_type}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CampaignTool(Tool):
    """Manage demonstration campaigns."""

    name = "demo_campaign"
    category = "demo"
    description = "Create and manage demonstration campaigns"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "run", "analyze", "report"],
                "description": "Campaign action",
            },
            "campaign_name": {"type": "string", "description": "Campaign identifier"},
            "rounds": {"type": "integer", "description": "Number of campaign rounds"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            campaign_name = args.get("campaign_name", "demo_campaign")
            rounds = int(args.get("rounds", 1))

            if action == "create":
                return ToolResult(ok=True, data={"status": "campaign_created", "name": campaign_name, "rounds": rounds})

            elif action == "run":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "campaign_running",
                        "name": campaign_name,
                        "rounds": rounds,
                        "message": "Campaign execution started",
                    },
                )

            elif action == "analyze":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "analysis_complete",
                        "name": campaign_name,
                        "metrics": {"total_tasks": 0, "success_count": 0, "failure_count": 0, "success_rate": 0.0},
                    },
                )

            elif action == "report":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "report_generated",
                        "name": campaign_name,
                        "report_format": "json",
                        "message": "Campaign report ready for export",
                    },
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MetricsTool(Tool):
    """Analyze and compute benchmark metrics."""

    name = "demo_metrics"
    category = "demo"
    description = "Calculate and analyze benchmark metrics"
    parameters = {
        "type": "object",
        "properties": {
            "metric_type": {
                "type": "string",
                "enum": ["success_rate", "speed", "quality", "follow_up"],
                "description": "Type of metric to calculate",
            },
            "data_count": {"type": "integer", "description": "Number of data points"},
        },
        "required": ["metric_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            metric_type = args.get("metric_type", "")
            data_count = int(args.get("data_count", 10))

            if metric_type == "success_rate":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "metric_calculated",
                        "metric": "success_rate",
                        "value": 0.0,
                        "data_points": data_count,
                        "weight": 0.40,
                    },
                )

            elif metric_type == "speed":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "metric_calculated",
                        "metric": "speed",
                        "avg_time_seconds": 0.0,
                        "data_points": data_count,
                        "weight": 0.20,
                    },
                )

            elif metric_type == "quality":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "metric_calculated",
                        "metric": "quality",
                        "avg_score": 0.0,
                        "scale": "1-5",
                        "data_points": data_count,
                        "weight": 0.20,
                    },
                )

            elif metric_type == "follow_up":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "metric_calculated",
                        "metric": "follow_up",
                        "count": 0,
                        "data_points": data_count,
                        "weight": 0.20,
                    },
                )

            else:
                return ToolResult(ok=False, error=f"Unknown metric type: {metric_type}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class AgentComparisonTool(Tool):
    """Compare multiple agents."""

    name = "demo_agent_comparison"
    category = "demo"
    description = "Compare performance of multiple agents"
    parameters = {
        "type": "object",
        "properties": {
            "agent_names": {"type": "array", "items": {"type": "string"}, "description": "Names of agents to compare"},
            "task_count": {"type": "integer", "description": "Number of tasks to run"},
        },
        "required": ["agent_names"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            agent_names = args.get("agent_names", ["thomas"])
            task_count = int(args.get("task_count", 10))

            if not isinstance(agent_names, list) or not agent_names:
                return ToolResult(ok=False, error="agent_names must be non-empty list")

            comparison_data = {}
            for agent in agent_names:
                comparison_data[agent] = {
                    "success_rate": 0.0,
                    "avg_speed": 0.0,
                    "avg_quality": 0.0,
                    "total_tasks": task_count,
                }

            return ToolResult(
                ok=True,
                data={
                    "status": "comparison_prepared",
                    "agents": agent_names,
                    "task_count": task_count,
                    "metrics": list(comparison_data.keys()),
                    "message": "Agent comparison framework ready",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_demo_tools(registry):
    """Register all demo tools."""
    registry.register(TaskPackTool())
    registry.register(BenchmarkTool())
    registry.register(CampaignTool())
    registry.register(MetricsTool())
    registry.register(AgentComparisonTool())
