"""Tools for flow builder operations."""

from typing import Any

from thomas.flows import core
from thomas.tools.base import Tool, ToolResult


class FlowDesignTool(Tool):
    """Design and manage flows."""

    name = "flow_design"
    category = "flows"
    description = "Create and design visual flows with nodes and edges"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_flow", "add_node", "add_edge", "validate", "flow_stats"],
                "description": "Design action",
            },
            "flow_id": {"type": "string", "description": "Flow identifier"},
            "name": {"type": "string", "description": "Flow/node name"},
            "node_type": {
                "type": "string",
                "enum": ["start", "end", "action", "decision", "merge"],
                "description": "Node type",
            },
            "node_id": {"type": "string", "description": "Node identifier"},
            "source": {"type": "string", "description": "Source node"},
            "target": {"type": "string", "description": "Target node"},
            "label": {"type": "string", "description": "Edge label"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.flows: dict[str, core.Flow] = {}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_flow":
                flow_id = args.get("flow_id", "")
                name = args.get("name", "")
                if not flow_id or not name:
                    return ToolResult(ok=False, error="flow_id and name required")

                flow = core.Flow(flow_id, name)
                self.flows[flow_id] = flow
                return ToolResult(ok=True, data={"flow_id": flow_id, "created": True})

            elif action == "add_node":
                flow_id = args.get("flow_id", "")
                node_type = args.get("node_type", "")
                name = args.get("name", "")

                if not flow_id or not node_type:
                    return ToolResult(ok=False, error="flow_id and node_type required")

                flow = self.flows.get(flow_id)
                if not flow:
                    return ToolResult(ok=False, error=f"Flow {flow_id} not found")

                node_id = flow.add_node(core.NodeType(node_type), name)
                return ToolResult(ok=True, data={"node_id": node_id})

            elif action == "add_edge":
                flow_id = args.get("flow_id", "")
                source = args.get("source", "")
                target = args.get("target", "")
                label = args.get("label")

                if not flow_id or not source or not target:
                    return ToolResult(ok=False, error="flow_id, source, target required")

                flow = self.flows.get(flow_id)
                if not flow:
                    return ToolResult(ok=False, error=f"Flow {flow_id} not found")

                edge_id = flow.add_edge(source, target, label)
                return ToolResult(ok=True, data={"edge_id": edge_id})

            elif action == "validate":
                flow_id = args.get("flow_id", "")
                if not flow_id:
                    return ToolResult(ok=False, error="flow_id required")

                flow = self.flows.get(flow_id)
                if not flow:
                    return ToolResult(ok=False, error=f"Flow {flow_id} not found")

                is_valid, error = flow.validate()
                return ToolResult(ok=True, data={"valid": is_valid, "error": error})

            elif action == "flow_stats":
                flow_id = args.get("flow_id", "")
                if not flow_id:
                    return ToolResult(ok=False, error="flow_id required")

                flow = self.flows.get(flow_id)
                if not flow:
                    return ToolResult(ok=False, error=f"Flow {flow_id} not found")

                stats = flow.get_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class FlowExecutionTool(Tool):
    """Execute flows."""

    name = "flow_execute"
    category = "flows"
    description = "Execute flows with state tracking"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start_execution", "execute_step", "execute_full", "get_state"],
                "description": "Execution action",
            },
            "flow_id": {"type": "string", "description": "Flow identifier"},
            "execution_id": {"type": "string", "description": "Execution identifier"},
            "variables": {"type": "object", "description": "Initial variables"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.flows: dict[str, core.Flow] = {}
        self.executors: dict[str, core.FlowExecutor] = {}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            flow_id = args.get("flow_id", "")
            execution_id = args.get("execution_id", "")

            if action == "start_execution":
                if not flow_id:
                    return ToolResult(ok=False, error="flow_id required")

                flow = self.flows.get(flow_id)
                if not flow:
                    return ToolResult(ok=False, error=f"Flow {flow_id} not found")

                executor = core.FlowExecutor(flow)
                variables = args.get("variables", {})
                exec_id = executor.create_execution(variables)
                self.executors[exec_id] = executor
                return ToolResult(ok=True, data={"execution_id": exec_id})

            elif action == "execute_step":
                if not execution_id:
                    return ToolResult(ok=False, error="execution_id required")

                executor = self.executors.get(execution_id)
                if not executor:
                    return ToolResult(ok=False, error=f"Execution {execution_id} not found")

                success, error = await executor.execute_step(execution_id)
                state = executor.get_execution_state(execution_id)
                return ToolResult(ok=success, data=state or {"error": error})

            elif action == "execute_full":
                if not execution_id:
                    return ToolResult(ok=False, error="execution_id required")

                executor = self.executors.get(execution_id)
                if not executor:
                    return ToolResult(ok=False, error=f"Execution {execution_id} not found")

                success, error = await executor.execute_full(execution_id)
                state = executor.get_execution_state(execution_id)
                return ToolResult(ok=success, data=state or {"error": error})

            elif action == "get_state":
                if not execution_id:
                    return ToolResult(ok=False, error="execution_id required")

                executor = self.executors.get(execution_id)
                if not executor:
                    return ToolResult(ok=False, error=f"Execution {execution_id} not found")

                state = executor.get_execution_state(execution_id)
                return ToolResult(ok=True, data=state or {})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_flows_tools(registry):
    """Register all flow tools."""
    registry.register(FlowDesignTool())
    registry.register(FlowExecutionTool())
