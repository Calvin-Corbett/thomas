"""Graph rendering engine with layout algorithms and force-directed layout."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    """Graph node with position."""

    node_id: str
    label: str
    x: float = 0.0
    y: float = 0.0
    size: float = 10.0
    color: str = "#4CAF50"
    metadata: dict[str, Any] = field(default_factory=dict)

    def distance_to(self, other: Node) -> float:
        """Calculate distance to another node."""
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)


@dataclass
class Edge:
    """Graph edge."""

    edge_id: str
    source: str
    target: str
    weight: float = 1.0
    label: str = ""
    color: str = "#999999"


class Graph:
    """Undirected graph structure."""

    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        self._node_counter = 0
        self._edge_counter = 0

    def add_node(self, label: str, node_id: str | None = None) -> str:
        """Add node to graph."""
        if node_id is None:
            self._node_counter += 1
            node_id = f"node_{self._node_counter}"

        self.nodes[node_id] = Node(node_id=node_id, label=label)
        return node_id

    def add_edge(self, source: str, target: str, weight: float = 1.0) -> str:
        """Add edge between nodes."""
        if source not in self.nodes or target not in self.nodes:
            raise ValueError("Source or target node not found")

        self._edge_counter += 1
        edge_id = f"edge_{self._edge_counter}"
        self.edges[edge_id] = Edge(edge_id=edge_id, source=source, target=target, weight=weight)
        return edge_id

    def get_neighbors(self, node_id: str) -> list[str]:
        """Get neighboring nodes."""
        neighbors = []
        for edge in self.edges.values():
            if edge.source == node_id:
                neighbors.append(edge.target)
            elif edge.target == node_id:
                neighbors.append(edge.source)
        return neighbors

    def get_degree(self, node_id: str) -> int:
        """Get node degree."""
        return len(self.get_neighbors(node_id))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "nodes": [{"id": n.node_id, "label": n.label, "x": n.x, "y": n.y} for n in self.nodes.values()],
            "edges": [
                {"id": e.edge_id, "source": e.source, "target": e.target, "weight": e.weight}
                for e in self.edges.values()
            ],
        }


class ForceDirectedLayout:
    """Force-directed graph layout algorithm."""

    def __init__(self, graph: Graph, width: float = 800, height: float = 600, iterations: int = 100, k: float = 50.0):
        self.graph = graph
        self.width = width
        self.height = height
        self.iterations = iterations
        self.k = k  # Optimal distance
        self.damping = 0.5

    def layout(self) -> None:
        """Run layout algorithm."""
        # Initialize random positions
        for node in self.graph.nodes.values():
            node.x = random.uniform(0, self.width)
            node.y = random.uniform(0, self.height)

        # Iterative force calculation
        for _ in range(self.iterations):
            # Reset forces
            forces: dict[str, tuple[float, float]] = {}
            for node_id in self.graph.nodes:
                forces[node_id] = (0.0, 0.0)

            nodes_list = list(self.graph.nodes.values())

            # Repulsive forces (all pairs)
            for i, node1 in enumerate(nodes_list):
                for node2 in nodes_list[i + 1 :]:
                    dx = node2.x - node1.x
                    dy = node2.y - node1.y
                    dist = math.sqrt(dx * dx + dy * dy) + 0.01

                    # Repulsive force magnitude
                    force = self.k * self.k / dist

                    fx = (force * dx / dist) if dist > 0 else random.uniform(-1, 1)
                    fy = (force * dy / dist) if dist > 0 else random.uniform(-1, 1)

                    forces[node1.node_id] = (forces[node1.node_id][0] - fx, forces[node1.node_id][1] - fy)
                    forces[node2.node_id] = (forces[node2.node_id][0] + fx, forces[node2.node_id][1] + fy)

            # Attractive forces (edges)
            for edge in self.graph.edges.values():
                node1 = self.graph.nodes[edge.source]
                node2 = self.graph.nodes[edge.target]

                dx = node2.x - node1.x
                dy = node2.y - node1.y
                dist = math.sqrt(dx * dx + dy * dy) + 0.01

                # Attractive force magnitude
                force = (dist * dist) / self.k * edge.weight

                fx = (force * dx / dist) if dist > 0 else 0
                fy = (force * dy / dist) if dist > 0 else 0

                forces[edge.source] = (forces[edge.source][0] + fx, forces[edge.source][1] + fy)
                forces[edge.target] = (forces[edge.target][0] - fx, forces[edge.target][1] - fy)

            # Update positions
            for node in nodes_list:
                fx, fy = forces[node.node_id]
                node.x += fx * self.damping
                node.y += fy * self.damping

                # Keep within bounds
                node.x = max(0, min(self.width, node.x))
                node.y = max(0, min(self.height, node.y))


class HierarchicalLayout:
    """Hierarchical/layered graph layout."""

    def __init__(self, graph: Graph, root_id: str | None = None):
        self.graph = graph
        self.root_id = root_id
        self.layers: list[list[str]] = []

    def layout(self) -> None:
        """Compute hierarchical layout."""
        if not self.graph.nodes:
            return

        # Find root if not specified
        root = self.root_id or list(self.graph.nodes.keys())[0]

        # BFS to assign layers
        visited = set()
        self.layers = []
        current_layer = [root]

        while current_layer:
            self.layers.append(current_layer)
            visited.update(current_layer)
            next_layer = []

            for node_id in current_layer:
                for neighbor in self.graph.get_neighbors(node_id):
                    if neighbor not in visited:
                        next_layer.append(neighbor)

            current_layer = list(set(next_layer))

        # Assign positions based on layers
        y_spacing = 100
        for layer_idx, layer in enumerate(self.layers):
            y = layer_idx * y_spacing
            x_spacing = 800 / max(len(layer), 1)

            for node_idx, node_id in enumerate(layer):
                node = self.graph.nodes[node_id]
                node.x = (node_idx + 0.5) * x_spacing
                node.y = y


class GraphRenderer:
    """Render graph layouts."""

    def __init__(self, graph: Graph):
        self.graph = graph

    def force_directed(self, width: float = 800, height: float = 600, iterations: int = 100) -> dict[str, Any]:
        """Render using force-directed layout."""
        layout = ForceDirectedLayout(self.graph, width, height, iterations)
        layout.layout()
        return self.graph.to_dict()

    def hierarchical(self, root_id: str | None = None) -> dict[str, Any]:
        """Render using hierarchical layout."""
        layout = HierarchicalLayout(self.graph, root_id)
        layout.layout()
        return self.graph.to_dict()

    def get_stats(self) -> dict[str, Any]:
        """Get graph statistics."""
        degrees = [self.graph.get_degree(node_id) for node_id in self.graph.nodes]
        return {
            "nodes": len(self.graph.nodes),
            "edges": len(self.graph.edges),
            "avg_degree": sum(degrees) / len(degrees) if degrees else 0,
            "max_degree": max(degrees) if degrees else 0,
        }
