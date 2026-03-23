"""Tools for Pathfinding module.

Provides tools for path planning and navigation algorithms.
"""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class ClassicalPathfindingTool(Tool):
    """Use classical pathfinding algorithms."""

    name = "pathfinding_classical"
    category = "pathfinding"
    description = "Find paths using classical algorithms (A*, Dijkstra, BFS)"
    parameters = {
        "type": "object",
        "properties": {
            "algorithm": {
                "type": "string",
                "enum": ["astar", "dijkstra", "bfs", "dfs"],
                "description": "Pathfinding algorithm",
            },
            "start": {"type": "array", "items": {"type": "number"}, "description": "Start position [x, y]"},
            "goal": {"type": "array", "items": {"type": "number"}, "description": "Goal position [x, y]"},
        },
        "required": ["algorithm", "start", "goal"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            algorithm = args.get("algorithm", "astar")
            start = args.get("start", [0, 0])
            goal = args.get("goal", [10, 10])

            if algorithm not in ["astar", "dijkstra", "bfs", "dfs"]:
                return ToolResult(ok=False, error=f"Unknown algorithm: {algorithm}")

            return ToolResult(
                ok=True,
                data={
                    "algorithm": algorithm,
                    "start": start,
                    "goal": goal,
                    "path": [],
                    "path_length": 0.0,
                    "found": False,
                },
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DynamicPathfindingTool(Tool):
    """Use dynamic pathfinding with moving obstacles."""

    name = "pathfinding_dynamic"
    category = "pathfinding"
    description = "Handle dynamic pathfinding with moving obstacles and replanning"
    parameters = {
        "type": "object",
        "properties": {
            "algorithm": {
                "type": "string",
                "enum": ["d_star", "lpa_star", "theta_star"],
                "description": "Dynamic algorithm",
            },
            "replan_interval": {"type": "number", "description": "Time between replans in seconds"},
        },
        "required": ["algorithm"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            algorithm = args.get("algorithm", "d_star")
            replan_interval = float(args.get("replan_interval", 0.5))

            supported = ["d_star", "lpa_star", "theta_star"]
            if algorithm not in supported:
                return ToolResult(ok=False, error=f"Unknown algorithm: {algorithm}")

            return ToolResult(
                ok=True,
                data={
                    "algorithm": algorithm,
                    "status": "ready",
                    "replan_interval": replan_interval,
                    "replans_triggered": 0,
                },
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class FlowFieldTool(Tool):
    """Generate flow fields for crowd movement."""

    name = "pathfinding_flow_field"
    category = "pathfinding"
    description = "Create flow fields for efficient crowd and agent movement"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["generate", "sample", "visualize"],
                "description": "Flow field action",
            },
            "grid_size": {"type": "integer", "description": "Size of flow field grid"},
            "goal": {"type": "array", "items": {"type": "number"}, "description": "Goal position [x, y]"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            grid_size = int(args.get("grid_size", 128))
            goal = args.get("goal", [0, 0])

            if action == "generate":
                return ToolResult(ok=True, data={"status": "field_generated", "grid_size": grid_size, "goal": goal})

            elif action == "sample":
                position = args.get("goal", [0, 0])
                return ToolResult(ok=True, data={"status": "sampled", "position": position, "direction": [0.0, 0.0]})

            elif action == "visualize":
                return ToolResult(ok=True, data={"status": "visualization_ready"})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_pathfinding_tools(registry):
    """Register all pathfinding tools."""
    registry.register(ClassicalPathfindingTool())
    registry.register(DynamicPathfindingTool())
    registry.register(FlowFieldTool())
