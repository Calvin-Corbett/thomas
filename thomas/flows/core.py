"""Visual flow builder with nodes, edges, execution, branching, and merging."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    """Node types."""

    START = "start"
    END = "end"
    ACTION = "action"
    DECISION = "decision"
    MERGE = "merge"


@dataclass
class Node:
    """Flow node."""

    node_id: str
    node_type: NodeType
    name: str
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {"node_id": self.node_id, "node_type": self.node_type.value, "name": self.name, "config": self.config}


@dataclass
class Edge:
    """Connection between nodes."""

    edge_id: str
    source_node: str
    target_node: str
    label: str | None = None
    condition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "edge_id": self.edge_id,
            "source": self.source_node,
            "target": self.target_node,
            "label": self.label,
            "condition": self.condition,
        }


@dataclass
class ExecutionContext:
    """Execution context for flow."""

    execution_id: str
    flow_id: str
    variables: dict[str, Any] = field(default_factory=dict)
    current_node: str | None = None
    visited_nodes: list[str] = field(default_factory=list)
    completed: bool = False
    error: str | None = None


class Flow:
    """Visual flow definition."""

    def __init__(self, flow_id: str, name: str):
        self.flow_id = flow_id
        self.name = name
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        self.start_node: str | None = None
        self.end_nodes: list[str] = []
        self._node_counter = 0
        self._edge_counter = 0

    def add_node(
        self, node_type: NodeType, name: str, node_id: str | None = None, config: dict[str, Any] | None = None
    ) -> str:
        """Add a node to the flow."""
        if node_id is None:
            self._node_counter += 1
            node_id = f"node_{self._node_counter}"

        if node_id in self.nodes:
            raise ValueError(f"Node {node_id} already exists")

        node = Node(node_id=node_id, node_type=node_type, name=name, config=config or {})
        self.nodes[node_id] = node

        if node_type == NodeType.START:
            self.start_node = node_id
        elif node_type == NodeType.END:
            self.end_nodes.append(node_id)

        return node_id

    def add_edge(self, source: str, target: str, label: str | None = None, condition: str | None = None) -> str:
        """Add an edge between nodes."""
        if source not in self.nodes or target not in self.nodes:
            raise ValueError("Source or target node not found")

        self._edge_counter += 1
        edge_id = f"edge_{self._edge_counter}"

        edge = Edge(edge_id=edge_id, source_node=source, target_node=target, label=label, condition=condition)
        self.edges[edge_id] = edge
        return edge_id

    def get_outgoing_edges(self, node_id: str) -> list[Edge]:
        """Get edges from a node."""
        return [e for e in self.edges.values() if e.source_node == node_id]

    def get_incoming_edges(self, node_id: str) -> list[Edge]:
        """Get edges to a node."""
        return [e for e in self.edges.values() if e.target_node == node_id]

    def validate(self) -> tuple[bool, str | None]:
        """Validate flow structure."""
        if not self.start_node:
            return False, "No start node defined"

        if not self.end_nodes:
            return False, "No end nodes defined"

        # Check connectivity
        visited = set()
        to_visit = [self.start_node]

        while to_visit:
            node_id = to_visit.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)

            for edge in self.get_outgoing_edges(node_id):
                if edge.target_node not in visited:
                    to_visit.append(edge.target_node)

        unreachable = set(self.nodes.keys()) - visited
        if unreachable:
            return False, f"Unreachable nodes: {unreachable}"

        return True, None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "flow_id": self.flow_id,
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges.values()],
            "start_node": self.start_node,
            "end_nodes": self.end_nodes,
        }

    def get_stats(self) -> dict[str, Any]:
        """Get flow statistics."""
        return {
            "flow_id": self.flow_id,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "start_node": self.start_node,
            "end_nodes": len(self.end_nodes),
            "is_valid": self.validate()[0],
        }


class FlowExecutor:
    """Execute flows with branching and merging."""

    def __init__(self, flow: Flow):
        self.flow = flow
        self.executions: dict[str, ExecutionContext] = {}
        self._execution_counter = 0

    def create_execution(self, variables: dict[str, Any] | None = None) -> str:
        """Create a new execution."""
        self._execution_counter += 1
        execution_id = f"exec_{self._execution_counter}"

        ctx = ExecutionContext(execution_id=execution_id, flow_id=self.flow.flow_id, variables=variables or {})
        self.executions[execution_id] = ctx
        return execution_id

    async def execute_step(self, execution_id: str) -> tuple[bool, str | None]:
        """Execute a single step."""
        ctx = self.executions.get(execution_id)
        if not ctx:
            return False, f"Execution {execution_id} not found"

        if ctx.completed:
            return False, "Execution already completed"

        # Determine current node
        if ctx.current_node is None:
            ctx.current_node = self.flow.start_node
        else:
            # Move to next node
            edges = self.flow.get_outgoing_edges(ctx.current_node)
            if not edges:
                ctx.completed = True
                return True, "Flow completed"

            # Select first edge (simple decision logic)
            next_node = edges[0].target_node
            ctx.current_node = next_node

        ctx.visited_nodes.append(ctx.current_node)

        # Check if end node
        if ctx.current_node in self.flow.end_nodes:
            ctx.completed = True

        return True, None

    async def execute_full(self, execution_id: str) -> tuple[bool, str | None]:
        """Execute flow to completion."""
        ctx = self.executions.get(execution_id)
        if not ctx:
            return False, f"Execution {execution_id} not found"

        max_steps = 100
        steps = 0

        while not ctx.completed and steps < max_steps:
            success, error = await self.execute_step(execution_id)
            if not success:
                return False, error
            steps += 1

        if steps >= max_steps:
            return False, "Max steps exceeded"

        return True, None

    def get_execution_state(self, execution_id: str) -> dict[str, Any] | None:
        """Get execution state."""
        ctx = self.executions.get(execution_id)
        if not ctx:
            return None

        return {
            "execution_id": execution_id,
            "flow_id": ctx.flow_id,
            "current_node": ctx.current_node,
            "visited_nodes": ctx.visited_nodes,
            "completed": ctx.completed,
            "variables": ctx.variables,
            "error": ctx.error,
        }
