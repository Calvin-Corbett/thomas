"""
Minimum spanning tree algorithms.

Implements Kruskal's, Prim's, and Borůvka's algorithms for finding MSTs.
"""

import heapq
from typing import Any

from thomas.graph_analytics._types import GraphType
from thomas.graph_analytics.graph import Graph


class UnionFind:
    """
    Union-Find (Disjoint Set Union) data structure.

    Supports efficient find and union operations with path compression and union by rank.
    """

    def __init__(self, nodes: list[Any]) -> None:
        """
        Initialize union-find structure.

        Args:
            nodes: List of elements to manage.
        """
        self.parent: dict[Any, Any] = {node: node for node in nodes}
        self.rank: dict[Any, int] = {node: 0 for node in nodes}

    def find(self, node: Any) -> Any:
        """
        Find the root of the set containing node (with path compression).

        Args:
            node: Element to find.

        Returns:
            Root of the set.
        """
        if self.parent[node] != node:
            self.parent[node] = self.find(self.parent[node])
        return self.parent[node]

    def union(self, node1: Any, node2: Any) -> bool:
        """
        Union two sets (with union by rank).

        Args:
            node1: First element.
            node2: Second element.

        Returns:
            True if union was performed, False if already in same set.
        """
        root1 = self.find(node1)
        root2 = self.find(node2)

        if root1 == root2:
            return False

        if self.rank[root1] < self.rank[root2]:
            self.parent[root1] = root2
        elif self.rank[root1] > self.rank[root2]:
            self.parent[root2] = root1
        else:
            self.parent[root2] = root1
            self.rank[root1] += 1

        return True


def kruskal_mst(graph: Graph) -> tuple[float, list[tuple[Any, Any, float]]]:
    """
    Find minimum spanning tree using Kruskal's algorithm.

    Sorts edges by weight and adds them if they don't create a cycle.
    Time complexity: O(E log E).

    Args:
        graph: Input undirected weighted graph.

    Returns:
        Tuple of (total_weight, edge_list).

    Raises:
        ValueError: If graph is not connected.
    """
    if graph.graph_type == GraphType.DIRECTED:
        raise ValueError("Kruskal's algorithm requires undirected graph")

    edges = graph.edges()

    # Sort edges by weight
    sorted_edges = sorted(edges, key=lambda x: x[2])

    # Initialize union-find
    uf = UnionFind(graph.nodes())

    mst_edges: list[tuple[Any, Any, float]] = []
    total_weight = 0.0

    for src, dst, weight in sorted_edges:
        if uf.union(src, dst):
            mst_edges.append((src, dst, weight))
            total_weight += weight

            if len(mst_edges) == graph.num_nodes() - 1:
                break

    # Check if spanning tree exists (connected graph)
    if len(mst_edges) < graph.num_nodes() - 1:
        raise ValueError("Graph is not connected")

    return total_weight, mst_edges


def prim_mst(graph: Graph, start: Any | None = None) -> tuple[float, list[tuple[Any, Any, float]]]:
    """
    Find minimum spanning tree using Prim's algorithm.

    Grows tree from a starting node by always adding minimum weight edge.
    Time complexity: O((V + E) log V) with priority queue.

    Args:
        graph: Input undirected weighted graph.
        start: Starting node (if None, uses first node).

    Returns:
        Tuple of (total_weight, edge_list).

    Raises:
        ValueError: If graph is not connected.
    """
    if graph.graph_type == GraphType.DIRECTED:
        raise ValueError("Prim's algorithm requires undirected graph")

    if graph.num_nodes() == 0:
        return 0.0, []

    nodes = graph.nodes()
    if start is None:
        start = nodes[0]

    if start not in graph:
        raise KeyError(f"Start node {start} not found")

    in_tree = {start}
    mst_edges: list[tuple[Any, Any, float]] = []
    total_weight = 0.0

    # Priority queue: (weight, src, dst)
    heap: list[tuple[float, Any, Any]] = []

    # Add edges from start node
    for neighbor in graph.neighbors(start):
        weight = graph.get_edge_weight(start, neighbor) or 1.0
        heapq.heappush(heap, (weight, start, neighbor))

    while heap and len(in_tree) < graph.num_nodes():
        weight, src, dst = heapq.heappop(heap)

        if dst in in_tree:
            continue

        in_tree.add(dst)
        mst_edges.append((src, dst, weight))
        total_weight += weight

        # Add edges from newly added node
        for neighbor in graph.neighbors(dst):
            if neighbor not in in_tree:
                edge_weight = graph.get_edge_weight(dst, neighbor) or 1.0
                heapq.heappush(heap, (edge_weight, dst, neighbor))

    # Check if spanning tree exists
    if len(in_tree) < graph.num_nodes():
        raise ValueError("Graph is not connected")

    return total_weight, mst_edges


def boruvka_mst(graph: Graph) -> tuple[float, list[tuple[Any, Any, float]]]:
    """
    Find minimum spanning tree using Borůvka's algorithm.

    Repeatedly finds minimum edges for each component and merges.
    Time complexity: O(E log^2 V).

    Args:
        graph: Input undirected weighted graph.

    Returns:
        Tuple of (total_weight, edge_list).

    Raises:
        ValueError: If graph is not connected.
    """
    if graph.graph_type == GraphType.DIRECTED:
        raise ValueError("Borůvka's algorithm requires undirected graph")

    if graph.num_nodes() == 0:
        return 0.0, []

    # Initialize each node as its own component
    uf = UnionFind(graph.nodes())
    mst_edges: list[tuple[Any, Any, float]] = []
    total_weight = 0.0

    edges = graph.edges()

    while len(mst_edges) < graph.num_nodes() - 1:
        # Find minimum edge for each component
        min_edge_per_component: dict[Any, tuple[Any, Any, float]] = {}

        for src, dst, weight in edges:
            root_src = uf.find(src)
            root_dst = uf.find(dst)

            if root_src != root_dst:
                # Minimum edge leaving this component
                edge_key = min(root_src, root_dst)

                if edge_key not in min_edge_per_component or weight < min_edge_per_component[edge_key][2]:
                    min_edge_per_component[edge_key] = (src, dst, weight)

        if not min_edge_per_component:
            break

        # Add these edges to MST
        for src, dst, weight in min_edge_per_component.values():
            if uf.union(src, dst):
                mst_edges.append((src, dst, weight))
                total_weight += weight

    # Check if spanning tree exists
    if len(mst_edges) < graph.num_nodes() - 1:
        raise ValueError("Graph is not connected")

    return total_weight, mst_edges


def second_best_mst(graph: Graph) -> tuple[float, list[tuple[Any, Any, float]]]:
    """
    Find second-best minimum spanning tree.

    Uses MST + replacement strategy: for each edge in MST, finds best
    replacement edge not in current MST.

    Args:
        graph: Input undirected weighted graph.

    Returns:
        Tuple of (total_weight, edge_list).
    """
    if graph.graph_type == GraphType.DIRECTED:
        raise ValueError("Second-best MST requires undirected graph")

    # Find first MST
    mst_weight, mst_edges_list = kruskal_mst(graph)
    mst_set = set((min(src, dst), max(src, dst)) for src, dst, _ in mst_edges_list)

    # Try removing each MST edge and find best replacement
    best_weight = float("inf")
    best_mst = None

    for edge_to_remove in mst_edges_list:
        src_rem, dst_rem, weight_rem = edge_to_remove

        # Create graph without this edge
        temp_graph = graph.copy()
        temp_graph.remove_edge(src_rem, dst_rem)

        # Find best non-tree edge to add back
        best_replacement = None
        best_replacement_weight = float("inf")

        for src, dst, weight in graph.edges():
            edge_key = (min(src, dst), max(src, dst))
            if edge_key not in mst_set or (src_rem, dst_rem) == (src, dst) or (dst_rem, src_rem) == (src, dst):
                continue

            # Check if this edge connects the two components
            # Use BFS to check connectivity
            visited = set()
            queue = [src_rem]
            visited.add(src_rem)

            while queue:
                current = queue.pop(0)
                if current == dst_rem:
                    break
                for neighbor in temp_graph.neighbors(current):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            if dst_rem not in visited:
                # This edge would reconnect
                if weight < best_replacement_weight:
                    best_replacement = (src, dst, weight)
                    best_replacement_weight = weight

        if best_replacement:
            candidate_weight = mst_weight - weight_rem + best_replacement_weight
            if candidate_weight < best_weight:
                best_weight = candidate_weight
                best_mst = [
                    (src, dst, w)
                    for src, dst, w in mst_edges_list
                    if (src, dst) != (src_rem, dst_rem) and (dst, src) != (src_rem, dst_rem)
                ]
                best_mst.append(best_replacement)

    if best_mst is None:
        return mst_weight, mst_edges_list

    return best_weight, best_mst


def steiner_tree_approximation(graph: Graph, terminals: list[Any]) -> tuple[float, list[tuple[Any, Any, float]]]:
    """
    Approximate Steiner tree using minimum spanning tree heuristic.

    Creates MST of the terminal nodes in the original graph.

    Args:
        graph: Input undirected weighted graph.
        terminals: List of terminal (required) nodes.

    Returns:
        Tuple of (total_weight, edge_list).
    """
    if len(terminals) < 2:
        return 0.0, []

    # Create subgraph induced by terminals plus intermediate nodes
    subgraph = graph.subgraph(list(set(terminals) | set(graph.nodes())))

    try:
        weight, edges = kruskal_mst(subgraph)
        return weight, edges
    except ValueError:
        # If graph not connected, return what we can
        return 0.0, []
