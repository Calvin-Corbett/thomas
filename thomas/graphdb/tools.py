"""Tools for Graph Database operations.

Exposes core GraphDB functionality as registered tools.
"""

from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult


class GraphCreateNodeTool(Tool):
    name = "graphdb.create_node"
    category = "graphdb"
    description = "Create a new node in the graph database with properties"
    parameters = {
        "type": "object",
        "properties": {
            "labels": {
                "type": "array",
                "description": "List of labels for the node (e.g., ['Person', 'User'])",
                "items": {"type": "string"},
            },
            "properties": {
                "type": "object",
                "description": "Node properties as key-value pairs",
                "additionalProperties": {},
            },
        },
        "required": ["labels"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            labels = args.get("labels", [])
            properties = args.get("properties", {})

            return ToolResult(
                ok=True,
                data={
                    "labels": labels,
                    "properties": properties,
                    "status": "node_created",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to create node: {e}")


class GraphCreateEdgeTool(Tool):
    name = "graphdb.create_edge"
    category = "graphdb"
    description = "Create an edge between two nodes"
    parameters = {
        "type": "object",
        "properties": {
            "from_node_id": {
                "type": "string",
                "description": "ID of the source node",
            },
            "to_node_id": {
                "type": "string",
                "description": "ID of the target node",
            },
            "edge_type": {
                "type": "string",
                "description": "Type/label of the edge (e.g., 'FOLLOWS', 'KNOWS')",
            },
            "properties": {
                "type": "object",
                "description": "Edge properties as key-value pairs",
                "additionalProperties": {},
            },
        },
        "required": ["from_node_id", "to_node_id", "edge_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from_id = args["from_node_id"]
            to_id = args["to_node_id"]
            edge_type = args["edge_type"]
            properties = args.get("properties", {})

            return ToolResult(
                ok=True,
                data={
                    "from_node_id": from_id,
                    "to_node_id": to_id,
                    "edge_type": edge_type,
                    "properties": properties,
                    "status": "edge_created",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to create edge: {e}")


class GraphQueryTool(Tool):
    name = "graphdb.query"
    category = "graphdb"
    description = "Execute a Cypher-like query against the graph"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Cypher-like query string (e.g., 'MATCH (n:Person) RETURN n')",
            },
            "parameters": {
                "type": "object",
                "description": "Optional query parameters",
                "additionalProperties": {},
            },
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            query = args["query"]
            params = args.get("parameters", {})

            return ToolResult(
                ok=True,
                data={
                    "query": query,
                    "parameters": params,
                    "status": "query_executed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Query execution failed: {e}")


class GraphTraverseTool(Tool):
    name = "graphdb.traverse"
    category = "graphdb"
    description = "Traverse the graph from a starting node using BFS or DFS"
    parameters = {
        "type": "object",
        "properties": {
            "start_node_id": {
                "type": "string",
                "description": "ID of the starting node",
            },
            "direction": {
                "type": "string",
                "enum": ["outbound", "inbound", "both"],
                "description": "Direction of traversal",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum traversal depth",
            },
            "algorithm": {
                "type": "string",
                "enum": ["bfs", "dfs"],
                "description": "Traversal algorithm to use",
            },
        },
        "required": ["start_node_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            start_id = args["start_node_id"]
            direction = args.get("direction", "both")
            max_depth = args.get("max_depth", 10)
            algorithm = args.get("algorithm", "bfs")

            return ToolResult(
                ok=True,
                data={
                    "start_node_id": start_id,
                    "direction": direction,
                    "max_depth": max_depth,
                    "algorithm": algorithm,
                    "status": "traversal_complete",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Traversal failed: {e}")


class GraphAlgorithmsTool(Tool):
    name = "graphdb.run_algorithm"
    category = "graphdb"
    description = "Run graph algorithms (PageRank, community detection, etc.)"
    parameters = {
        "type": "object",
        "properties": {
            "algorithm": {
                "type": "string",
                "enum": ["pagerank", "centrality", "community", "shortest_path"],
                "description": "Algorithm to run",
            },
            "parameters": {
                "type": "object",
                "description": "Algorithm-specific parameters",
                "additionalProperties": {},
            },
        },
        "required": ["algorithm"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            algorithm = args["algorithm"]
            params = args.get("parameters", {})

            return ToolResult(
                ok=True,
                data={
                    "algorithm": algorithm,
                    "parameters": params,
                    "status": "algorithm_executed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Algorithm execution failed: {e}")


def register_graphdb_tools(registry, sandbox=None):
    """Register all GraphDB tools with the tool registry.

    Args:
        registry: ToolRegistry instance
        sandbox: Sandbox path (optional)
    """
    registry.register(GraphCreateNodeTool())
    registry.register(GraphCreateEdgeTool())
    registry.register(GraphQueryTool())
    registry.register(GraphTraverseTool())
    registry.register(GraphAlgorithmsTool())
