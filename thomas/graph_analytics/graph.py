"""
Graph data structure and basic operations.

Implements adjacency list representation for efficient graph operations.
Supports directed and undirected graphs with optional edge weights.
"""

import copy
from typing import Any

from thomas.graph_analytics._exceptions import InvalidGraphError
from thomas.graph_analytics._types import GraphType, Node, NodeID


class Graph:
    """
    Graph data structure using adjacency list representation.

    Supports directed and undirected graphs with weighted edges.
    Uses both forward and reverse adjacency lists for efficient operations.

    Attributes:
        graph_type: Type of graph (DIRECTED, UNDIRECTED, WEIGHTED).
        _nodes: Dictionary mapping node IDs to Node objects.
        _adjacency: Forward adjacency list.
        _reverse_adjacency: Reverse adjacency list (for directed graphs).
    """

    def __init__(self, graph_type: GraphType = GraphType.DIRECTED) -> None:
        """
        Initialize an empty graph.

        Args:
            graph_type: Type of graph to create.
        """
        self.graph_type = graph_type
        self._nodes: dict[Any, Node] = {}
        self._adjacency: dict[Any, list[tuple[Any, float]]] = {}
        self._reverse_adjacency: dict[Any, list[tuple[Any, float]]] = {}

    def add_node(self, node_id: NodeID, **attrs: Any) -> None:
        """
        Add a node to the graph.

        Args:
            node_id: Unique identifier for the node.
            **attrs: Optional node attributes.

        Raises:
            InvalidGraphError: If node already exists.
        """
        if node_id in self._nodes:
            raise InvalidGraphError(f"Node {node_id} already exists")

        self._nodes[node_id] = Node(node_id, dict(attrs))
        self._adjacency[node_id] = []
        self._reverse_adjacency[node_id] = []

    def add_edge(self, src: NodeID, dst: NodeID, weight: float = 1.0, **attrs: Any) -> None:
        """
        Add an edge to the graph.

        Creates nodes if they don't exist. Handles multi-edges by updating
        the weight of existing edges.

        Args:
            src: Source node ID.
            dst: Destination node ID.
            weight: Edge weight (default 1.0).
            **attrs: Optional edge attributes.

        Raises:
            InvalidGraphError: If nodes don't exist and can't be created.
        """
        # Auto-create nodes if they don't exist
        if src not in self._nodes:
            self.add_node(src)
        if dst not in self._nodes:
            self.add_node(dst)

        # Check for existing edge (multi-edge handling)
        for i, (neighbor, _) in enumerate(self._adjacency[src]):
            if neighbor == dst:
                # Update existing edge
                self._adjacency[src][i] = (neighbor, weight)
                if self.graph_type != GraphType.DIRECTED:
                    for j, (n, _) in enumerate(self._reverse_adjacency[src]):
                        if n == dst:
                            self._reverse_adjacency[src][j] = (n, weight)
                else:
                    for j, (n, _) in enumerate(self._reverse_adjacency[dst]):
                        if n == src:
                            self._reverse_adjacency[dst][j] = (n, weight)
                return

        # Add new edge
        self._adjacency[src].append((dst, weight))

        if self.graph_type == GraphType.DIRECTED:
            self._reverse_adjacency[dst].append((src, weight))
        else:
            # Undirected: add reverse edge
            self._reverse_adjacency[src].append((dst, weight))
            self._adjacency[dst].append((src, weight))
            self._reverse_adjacency[dst].append((src, weight))

    def remove_node(self, node_id: NodeID) -> None:
        """
        Remove a node and all its incident edges.

        Args:
            node_id: ID of node to remove.

        Raises:
            KeyError: If node doesn't exist.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Node {node_id} not found")

        # Remove all edges incident to this node
        for neighbor, _ in self._adjacency[node_id]:
            if self.graph_type == GraphType.DIRECTED:
                self._reverse_adjacency[neighbor] = [
                    (n, w) for n, w in self._reverse_adjacency[neighbor] if n != node_id
                ]
            else:
                self._adjacency[neighbor] = [(n, w) for n, w in self._adjacency[neighbor] if n != node_id]
                self._reverse_adjacency[neighbor] = [
                    (n, w) for n, w in self._reverse_adjacency[neighbor] if n != node_id
                ]

        # Remove incoming edges
        for neighbor, _ in self._reverse_adjacency[node_id]:
            self._adjacency[neighbor] = [(n, w) for n, w in self._adjacency[neighbor] if n != node_id]

        # Remove node
        del self._nodes[node_id]
        del self._adjacency[node_id]
        del self._reverse_adjacency[node_id]

    def remove_edge(self, src: NodeID, dst: NodeID) -> None:
        """
        Remove an edge from the graph.

        Args:
            src: Source node ID.
            dst: Destination node ID.

        Raises:
            KeyError: If edge doesn't exist.
        """
        if src not in self._nodes or dst not in self._nodes:
            raise KeyError("Edge endpoints not found")

        # Remove forward edge
        original_length = len(self._adjacency[src])
        self._adjacency[src] = [(n, w) for n, w in self._adjacency[src] if n != dst]

        if len(self._adjacency[src]) == original_length:
            raise KeyError(f"Edge {src} -> {dst} not found")

        if self.graph_type == GraphType.DIRECTED:
            self._reverse_adjacency[dst] = [(n, w) for n, w in self._reverse_adjacency[dst] if n != src]
        else:
            self._reverse_adjacency[src] = [(n, w) for n, w in self._reverse_adjacency[src] if n != dst]
            self._adjacency[dst] = [(n, w) for n, w in self._adjacency[dst] if n != src]
            self._reverse_adjacency[dst] = [(n, w) for n, w in self._reverse_adjacency[dst] if n != src]

    def neighbors(self, node_id: NodeID) -> list[NodeID]:
        """
        Get outgoing neighbors of a node.

        Args:
            node_id: ID of the node.

        Returns:
            List of neighbor node IDs.

        Raises:
            KeyError: If node doesn't exist.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Node {node_id} not found")
        return [n for n, _ in self._adjacency[node_id]]

    def degree(self, node_id: NodeID) -> int:
        """
        Get the degree of a node (for undirected graphs).

        Args:
            node_id: ID of the node.

        Returns:
            Degree (number of neighbors).

        Raises:
            KeyError: If node doesn't exist.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Node {node_id} not found")
        return len(self._adjacency[node_id])

    def in_degree(self, node_id: NodeID) -> int:
        """
        Get the in-degree of a node (for directed graphs).

        Args:
            node_id: ID of the node.

        Returns:
            In-degree (number of incoming edges).

        Raises:
            KeyError: If node doesn't exist.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Node {node_id} not found")
        return len(self._reverse_adjacency[node_id])

    def out_degree(self, node_id: NodeID) -> int:
        """
        Get the out-degree of a node (for directed graphs).

        Args:
            node_id: ID of the node.

        Returns:
            Out-degree (number of outgoing edges).

        Raises:
            KeyError: If node doesn't exist.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Node {node_id} not found")
        return len(self._adjacency[node_id])

    def has_edge(self, src: NodeID, dst: NodeID) -> bool:
        """
        Check if an edge exists.

        Args:
            src: Source node ID.
            dst: Destination node ID.

        Returns:
            True if edge exists, False otherwise.
        """
        if src not in self._nodes:
            return False
        return any(n == dst for n, _ in self._adjacency[src])

    def get_edge_weight(self, src: NodeID, dst: NodeID) -> float | None:
        """
        Get the weight of an edge.

        Args:
            src: Source node ID.
            dst: Destination node ID.

        Returns:
            Edge weight or None if edge doesn't exist.
        """
        if src not in self._nodes:
            return None
        for neighbor, weight in self._adjacency[src]:
            if neighbor == dst:
                return weight
        return None

    def num_nodes(self) -> int:
        """Return the number of nodes in the graph."""
        return len(self._nodes)

    def num_edges(self) -> int:
        """Return the number of edges in the graph."""
        total = sum(len(neighbors) for neighbors in self._adjacency.values())
        if self.graph_type != GraphType.DIRECTED:
            total //= 2  # Each undirected edge counted twice
        return total

    def nodes(self) -> list[NodeID]:
        """Return list of all node IDs."""
        return list(self._nodes.keys())

    def edges(self) -> list[tuple[NodeID, NodeID, float]]:
        """
        Return list of all edges as (src, dst, weight) tuples.

        For undirected graphs, returns each edge once.
        """
        edge_list: list[tuple[NodeID, NodeID, float]] = []
        seen: set[tuple[NodeID, NodeID]] = set()

        for src in self._adjacency:
            for dst, weight in self._adjacency[src]:
                if self.graph_type == GraphType.DIRECTED:
                    edge_list.append((src, dst, weight))
                else:
                    key = tuple(sorted([src, dst]))
                    if key not in seen:
                        edge_list.append((src, dst, weight))
                        seen.add(key)

        return edge_list

    def adjacency_matrix(self) -> list[list[float]]:
        """
        Convert graph to adjacency matrix.

        Returns:
            2D list representing adjacency matrix.
        """
        nodes = sorted(self.nodes())
        n = len(nodes)
        node_to_idx = {node: i for i, node in enumerate(nodes)}

        matrix = [[0.0 for _ in range(n)] for _ in range(n)]

        for src, neighbors in self._adjacency.items():
            i = node_to_idx[src]
            for dst, weight in neighbors:
                j = node_to_idx[dst]
                matrix[i][j] = weight

        return matrix

    def has_self_loop(self, node_id: NodeID) -> bool:
        """
        Check if a node has a self-loop.

        Args:
            node_id: ID of the node.

        Returns:
            True if node has self-loop, False otherwise.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Node {node_id} not found")
        return any(n == node_id for n, _ in self._adjacency[node_id])

    def self_loops(self) -> list[NodeID]:
        """Return list of nodes with self-loops."""
        return [node for node in self._nodes if self.has_self_loop(node)]

    def subgraph(self, nodes: list[NodeID]) -> "Graph":
        """
        Extract a subgraph containing only specified nodes and edges between them.

        Args:
            nodes: List of node IDs to include.

        Returns:
            New Graph object containing the subgraph.

        Raises:
            KeyError: If any node doesn't exist.
        """
        for node in nodes:
            if node not in self._nodes:
                raise KeyError(f"Node {node} not found")

        subgraph = Graph(self.graph_type)
        node_set = set(nodes)

        # Add nodes with attributes
        for node in nodes:
            orig_node = self._nodes[node]
            subgraph.add_node(node, **orig_node.attrs)

        # Add edges within subgraph
        for src in nodes:
            for dst, weight in self._adjacency[src]:
                if dst in node_set:
                    subgraph.add_edge(src, dst, weight)

        return subgraph

    def copy(self) -> "Graph":
        """
        Create a deep copy of the graph.

        Returns:
            New Graph object with copied data.
        """
        new_graph = Graph(self.graph_type)

        # Copy nodes
        for node_id, node_obj in self._nodes.items():
            new_graph.add_node(node_id, **copy.deepcopy(node_obj.attrs))

        # Copy edges
        for src, neighbors in self._adjacency.items():
            for dst, weight in neighbors:
                if self.graph_type == GraphType.DIRECTED:
                    new_graph.add_edge(src, dst, weight)
                else:
                    # For undirected, only add each edge once
                    if src < dst:
                        new_graph.add_edge(src, dst, weight)

        return new_graph

    def transpose(self) -> "Graph":
        """
        Create a transpose of the graph (reverse all edges).

        Returns:
            New Graph with reversed edges.
        """
        if self.graph_type != GraphType.DIRECTED:
            raise InvalidGraphError("Transpose only defined for directed graphs")

        transposed = Graph(GraphType.DIRECTED)

        # Add nodes
        for node_id, node_obj in self._nodes.items():
            transposed.add_node(node_id, **copy.deepcopy(node_obj.attrs))

        # Add reversed edges
        for src, neighbors in self._adjacency.items():
            for dst, weight in neighbors:
                transposed.add_edge(dst, src, weight)

        return transposed

    def __len__(self) -> int:
        """Return the number of nodes."""
        return len(self._nodes)

    def __contains__(self, node_id: NodeID) -> bool:
        """Check if node exists in graph."""
        return node_id in self._nodes

    def __repr__(self) -> str:
        """Return string representation of graph."""
        return f"Graph(type={self.graph_type.value}, " f"nodes={self.num_nodes()}, edges={self.num_edges()})"
