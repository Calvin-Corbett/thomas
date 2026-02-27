"""Tools for graph rendering operations."""

from typing import Any

from thomas.graph_engine import core
from thomas.tools.base import Tool, ToolResult


class GraphBuilderTool(Tool):
    """Build and manage graphs."""

    name = "graph_builder"
    category = "graph_engine"
    description = "Build graphs with nodes and edges"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_graph", "add_node", "add_edge", "list_nodes", "graph_stats"],
                "description": "Graph action",
            },
            "graph_id": {"type": "string", "description": "Graph identifier"},
            "label": {"type": "string", "description": "Node label"},
            "node_id": {"type": "string", "description": "Node ID"},
            "source": {"type": "string", "description": "Source node"},
            "target": {"type": "string", "description": "Target node"},
            "weight": {"type": "number", "description": "Edge weight"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.graphs: dict[str, core.Graph] = {}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_graph":
                graph_id = args.get("graph_id", f"graph_{len(self.graphs)}")
                graph = core.Graph()
                self.graphs[graph_id] = graph
                return ToolResult(ok=True, data={"graph_id": graph_id})

            elif action == "add_node":
                graph_id = args.get("graph_id", "")
                label = args.get("label", "")
                if not graph_id or not label:
                    return ToolResult(ok=False, error="graph_id and label required")

                graph = self.graphs.get(graph_id)
                if not graph:
                    return ToolResult(ok=False, error=f"Graph {graph_id} not found")

                node_id = graph.add_node(label)
                return ToolResult(ok=True, data={"node_id": node_id})

            elif action == "add_edge":
                graph_id = args.get("graph_id", "")
                source = args.get("source", "")
                target = args.get("target", "")
                weight = args.get("weight", 1.0)

                if not graph_id or not source or not target:
                    return ToolResult(ok=False, error="graph_id, source, target required")

                graph = self.graphs.get(graph_id)
                if not graph:
                    return ToolResult(ok=False, error=f"Graph {graph_id} not found")

                edge_id = graph.add_edge(source, target, weight)
                return ToolResult(ok=True, data={"edge_id": edge_id})

            elif action == "list_nodes":
                graph_id = args.get("graph_id", "")
                if not graph_id:
                    return ToolResult(ok=False, error="graph_id required")

                graph = self.graphs.get(graph_id)
                if not graph:
                    return ToolResult(ok=False, error=f"Graph {graph_id} not found")

                nodes = [{"id": n.node_id, "label": n.label} for n in graph.nodes.values()]
                return ToolResult(ok=True, data={"nodes": nodes, "count": len(nodes)})

            elif action == "graph_stats":
                graph_id = args.get("graph_id", "")
                if not graph_id:
                    return ToolResult(ok=False, error="graph_id required")

                graph = self.graphs.get(graph_id)
                if not graph:
                    return ToolResult(ok=False, error=f"Graph {graph_id} not found")

                renderer = core.GraphRenderer(graph)
                stats = renderer.get_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LayoutTool(Tool):
    """Compute graph layouts."""

    name = "graph_layout"
    category = "graph_engine"
    description = "Compute force-directed and hierarchical layouts"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["force_directed", "hierarchical"], "description": "Layout algorithm"},
            "graph_id": {"type": "string", "description": "Graph identifier"},
            "iterations": {"type": "integer", "description": "Iterations for force-directed"},
            "root_id": {"type": "string", "description": "Root node for hierarchical"},
        },
        "required": ["action", "graph_id"],
    }

    def __init__(self):
        self.graphs: dict[str, core.Graph] = {}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            graph_id = args.get("graph_id", "")

            graph = self.graphs.get(graph_id)
            if not graph:
                return ToolResult(ok=False, error=f"Graph {graph_id} not found")

            renderer = core.GraphRenderer(graph)

            if action == "force_directed":
                iterations = args.get("iterations", 100)
                result = renderer.force_directed(iterations=iterations)
                return ToolResult(ok=True, data=result)

            elif action == "hierarchical":
                root_id = args.get("root_id")
                result = renderer.hierarchical(root_id)
                return ToolResult(ok=True, data=result)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_graph_engine_tools(registry):
    """Register all graph engine tools."""
    registry.register(GraphBuilderTool())
    registry.register(LayoutTool())
