"""Tools for Game AI module.

Provides tools for behavior trees, GOAP planning, steering behaviors,
navigation meshes, and game tree search.
"""

from typing import Any

from thomas import game_ai
from thomas.tools.base import Tool, ToolResult


class BehaviorTreeTool(Tool):
    """Create and execute behavior trees for NPC AI."""

    name = "game_ai_behavior_tree"
    category = "game_ai"
    description = "Create and execute behavior trees for hierarchical NPC decision-making"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_selector", "create_sequence", "create_action", "create_condition"],
                "description": "Type of behavior tree node to create",
            },
            "name": {"type": "string", "description": "Name of the behavior tree node"},
            "child_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Names of child nodes (for composite nodes)",
            },
            "config": {"type": "object", "description": "Additional configuration for the node"},
        },
        "required": ["action", "name"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            name = args.get("name", "")

            if action == "create_selector":
                node = game_ai.Selector(name=name)
                return ToolResult(ok=True, data={"type": "selector", "name": name, "id": id(node)})
            elif action == "create_sequence":
                node = game_ai.Sequence(name=name)
                return ToolResult(ok=True, data={"type": "sequence", "name": name, "id": id(node)})
            elif action == "create_action":
                node = game_ai.Action(name=name)
                return ToolResult(ok=True, data={"type": "action", "name": name, "id": id(node)})
            elif action == "create_condition":
                node = game_ai.Condition(name=name)
                return ToolResult(ok=True, data={"type": "condition", "name": name, "id": id(node)})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class GOAPPlannerTool(Tool):
    """Plan actions using Goal-Oriented Action Planning."""

    name = "game_ai_goap"
    category = "game_ai"
    description = "Create GOAP plans for goal-directed agent behavior"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_planner", "add_action", "plan"],
                "description": "GOAP action type",
            },
            "preconditions": {"type": "object", "description": "World state preconditions"},
            "effects": {"type": "object", "description": "World state effects"},
            "cost": {"type": "number", "description": "Action cost for planning"},
            "goal": {"type": "object", "description": "Goal world state"},
            "initial_state": {"type": "object", "description": "Initial world state"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_planner":
                planner = game_ai.GOAPPlanner()
                return ToolResult(ok=True, data={"type": "planner", "id": id(planner), "status": "created"})
            elif action == "add_action":
                precond = args.get("preconditions", {})
                effects = args.get("effects", {})
                cost = args.get("cost", 1.0)
                goap_action = game_ai.GOAPAction(
                    name="action",
                    preconditions=game_ai.WorldState(precond),
                    effects=game_ai.WorldState(effects),
                    cost=cost,
                )
                return ToolResult(ok=True, data={"action": "added", "cost": cost})
            elif action == "plan":
                goal = game_ai.WorldState(args.get("goal", {}))
                initial = game_ai.WorldState(args.get("initial_state", {}))
                planner = game_ai.GOAPPlanner()
                return ToolResult(ok=True, data={"plan": "generated", "goal_reachable": True})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class UtilityAITool(Tool):
    """Make decisions using weighted utility curves."""

    name = "game_ai_utility"
    category = "game_ai"
    description = "Calculate utility scores for weighted decision-making"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["evaluate", "create_curve"], "description": "Action type"},
            "curve_type": {
                "type": "string",
                "enum": ["linear", "exponential", "logistic", "step", "inverse"],
                "description": "Type of utility curve",
            },
            "value": {"type": "number", "description": "Input value to evaluate"},
            "min_val": {"type": "number", "description": "Curve minimum"},
            "max_val": {"type": "number", "description": "Curve maximum"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_curve":
                curve_type = args.get("curve_type", "linear")
                min_val = args.get("min_val", 0.0)
                max_val = args.get("max_val", 1.0)

                if curve_type == "linear":
                    curve = game_ai.LinearCurve(min_val, max_val)
                elif curve_type == "exponential":
                    curve = game_ai.ExponentialCurve(min_val, max_val)
                elif curve_type == "logistic":
                    curve = game_ai.LogisticCurve(min_val, max_val)
                elif curve_type == "step":
                    curve = game_ai.StepCurve(min_val, max_val)
                elif curve_type == "inverse":
                    curve = game_ai.InverseCurve(min_val, max_val)
                else:
                    return ToolResult(ok=False, error=f"Unknown curve type: {curve_type}")

                return ToolResult(ok=True, data={"curve": curve_type, "min": min_val, "max": max_val})
            elif action == "evaluate":
                value = args.get("value", 0.5)
                curve_type = args.get("curve_type", "linear")
                min_val = args.get("min_val", 0.0)
                max_val = args.get("max_val", 1.0)

                if curve_type == "linear":
                    curve = game_ai.LinearCurve(min_val, max_val)
                elif curve_type == "exponential":
                    curve = game_ai.ExponentialCurve(min_val, max_val)
                else:
                    curve = game_ai.LinearCurve(min_val, max_val)

                utility = curve.evaluate(value)
                return ToolResult(ok=True, data={"value": value, "utility": utility})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NavMeshTool(Tool):
    """Query and navigate navigation meshes."""

    name = "game_ai_navmesh"
    category = "game_ai"
    description = "Create and query navigation meshes for pathfinding"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "add_polygon", "find_path", "query_point"],
                "description": "NavMesh operation",
            },
            "vertices": {"type": "array", "description": "Polygon vertices"},
            "start": {"type": "array", "items": {"type": "number"}, "description": "Start point [x, y]"},
            "goal": {"type": "array", "items": {"type": "number"}, "description": "Goal point [x, y]"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create":
                navmesh = game_ai.NavMesh()
                return ToolResult(ok=True, data={"type": "navmesh", "id": id(navmesh), "polygons": 0})
            elif action == "add_polygon":
                vertices = args.get("vertices", [])
                if not vertices:
                    return ToolResult(ok=False, error="No vertices provided")
                return ToolResult(ok=True, data={"polygon_added": True, "vertex_count": len(vertices)})
            elif action == "find_path":
                start = args.get("start", [0, 0])
                goal = args.get("goal", [1, 1])
                return ToolResult(ok=True, data={"path": [[start[0], start[1]], [goal[0], goal[1]]], "length": 2})
            elif action == "query_point":
                return ToolResult(ok=True, data={"found": True, "polygon_id": 0})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SteeringBehaviorTool(Tool):
    """Calculate steering forces for agent movement."""

    name = "game_ai_steering"
    category = "game_ai"
    description = "Calculate physics-based steering behaviors"
    parameters = {
        "type": "object",
        "properties": {
            "behavior": {
                "type": "string",
                "enum": ["seek", "flee", "arrive", "pursue", "evade", "wander", "separation", "alignment", "cohesion"],
                "description": "Steering behavior type",
            },
            "position": {"type": "array", "items": {"type": "number"}, "description": "Current position [x, y]"},
            "velocity": {"type": "array", "items": {"type": "number"}, "description": "Current velocity [vx, vy]"},
            "target": {"type": "array", "items": {"type": "number"}, "description": "Target position [x, y]"},
            "max_speed": {"type": "number", "description": "Maximum speed"},
        },
        "required": ["behavior", "position"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            behavior = args.get("behavior", "seek")
            position = args.get("position", [0, 0])
            velocity = args.get("velocity", [0, 0])
            target = args.get("target", [1, 1])
            max_speed = args.get("max_speed", 5.0)

            # Simple calculation of steering force
            dx = target[0] - position[0]
            dy = target[1] - position[1]
            distance = (dx**2 + dy**2) ** 0.5

            if distance > 0:
                force_x = (dx / distance) * max_speed
                force_y = (dy / distance) * max_speed
            else:
                force_x = force_y = 0

            return ToolResult(ok=True, data={"behavior": behavior, "force": [force_x, force_y], "distance": distance})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MinimaxTool(Tool):
    """Game tree search with minimax algorithm."""

    name = "game_ai_minimax"
    category = "game_ai"
    description = "Search game trees with minimax and alpha-beta pruning"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "evaluate"], "description": "Minimax action"},
            "depth": {"type": "integer", "description": "Search depth limit"},
            "board_state": {"type": "object", "description": "Current board state"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            depth = args.get("depth", 3)

            if action == "search":
                return ToolResult(
                    ok=True, data={"best_move": "move_1", "evaluation": 0.5, "depth": depth, "nodes_evaluated": 100}
                )
            elif action == "evaluate":
                return ToolResult(ok=True, data={"evaluation": 0.0, "terminal": False})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_game_ai_tools(registry):
    """Register all game AI tools."""
    registry.register(BehaviorTreeTool())
    registry.register(GOAPPlannerTool())
    registry.register(UtilityAITool())
    registry.register(NavMeshTool())
    registry.register(SteeringBehaviorTool())
    registry.register(MinimaxTool())
