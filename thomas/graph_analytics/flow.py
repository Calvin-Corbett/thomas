"""
Network flow algorithms.

Implements max flow (Edmonds-Karp), minimum cut, bipartite matching, and min-cost flow.
"""

from collections import defaultdict, deque
from typing import Any

from thomas.graph_analytics._types import GraphType
from thomas.graph_analytics.graph import Graph


def max_flow_edmonds_karp(graph: Graph, source: Any, sink: Any) -> tuple[float, dict[tuple[Any, Any], float]]:
    """
    Find maximum flow using Edmonds-Karp algorithm (BFS-based Ford-Fulkerson).

    Time complexity: O(VE^2).

    Args:
        graph: Input directed graph with edge capacities as weights.
        source: Source node ID.
        sink: Sink node ID.

    Returns:
        Tuple of (max_flow_value, flow_dict) where flow_dict maps (src, dst) to flow.

    Raises:
        KeyError: If source or sink doesn't exist.
    """
    if source not in graph:
        raise KeyError(f"Source node {source} not found")
    if sink not in graph:
        raise KeyError(f"Sink node {sink} not found")

    # Build capacity graph
    capacity: dict[tuple[Any, Any], float] = {}
    for src, dst, weight in graph.edges():
        capacity[(src, dst)] = weight
        capacity[(dst, src)] = 0  # Reverse edge

    # Flow graph
    flow: dict[tuple[Any, Any], float] = defaultdict(float)

    def bfs_find_path(source: Any, sink: Any) -> list[Any] | None:
        """Find augmenting path using BFS."""
        parent: dict[Any, Any] = {source: None}
        visited = {source}
        queue = deque([source])

        while queue:
            current = queue.popleft()

            if current == sink:
                path = []
                while parent[current] is not None:
                    path.append((parent[current], current))
                    current = parent[current]
                path.reverse()
                return path

            for neighbor in graph.neighbors(current):
                if neighbor not in visited:
                    cap_available = capacity.get((current, neighbor), 0) - flow[(current, neighbor)]
                    if cap_available > 0:
                        visited.add(neighbor)
                        parent[neighbor] = current
                        queue.append(neighbor)

        return None

    max_flow = 0.0

    # Find augmenting paths
    while True:
        path = bfs_find_path(source, sink)
        if not path:
            break

        # Find bottleneck
        bottleneck = float("inf")
        for src, dst in path:
            bottleneck = min(bottleneck, capacity.get((src, dst), 0) - flow[(src, dst)])

        # Update flow
        for src, dst in path:
            flow[(src, dst)] += bottleneck
            flow[(dst, src)] -= bottleneck

        max_flow += bottleneck

    return max_flow, dict(flow)


def min_cut(graph: Graph, source: Any, sink: Any) -> tuple[float, tuple[set[Any], set[Any]]]:
    """
    Find minimum cut using max flow (Max-flow Min-cut theorem).

    Returns the cut value and the partition.

    Args:
        graph: Input directed graph.
        source: Source node ID.
        sink: Sink node ID.

    Returns:
        Tuple of (cut_value, (source_partition, sink_partition)).
    """
    max_flow_value, flow_dict = max_flow_edmonds_karp(graph, source, sink)

    # Find reachable nodes from source in residual graph
    reachable = set()
    queue = deque([source])
    reachable.add(source)

    while queue:
        current = queue.popleft()

        for neighbor in graph.neighbors(current):
            if neighbor not in reachable:
                residual_capacity = graph.get_edge_weight(current, neighbor) or 0
                residual_capacity -= flow_dict.get((current, neighbor), 0)

                if residual_capacity > 0:
                    reachable.add(neighbor)
                    queue.append(neighbor)

    source_partition = reachable
    sink_partition = set(graph.nodes()) - reachable

    return max_flow_value, (source_partition, sink_partition)


def maximum_bipartite_matching(graph: Graph, left_nodes: list[Any], right_nodes: list[Any]) -> dict[Any, Any]:
    """
    Find maximum bipartite matching using augmenting paths.

    Args:
        graph: Input undirected bipartite graph.
        left_nodes: Nodes in left partition.
        right_nodes: Nodes in right partition.

    Returns:
        Dictionary mapping left nodes to matched right nodes.
    """
    matching: dict[Any, Any] = {}
    match_right: dict[Any, Any] = {}

    def dfs_augment(node: Any, visited: set[Any]) -> bool:
        """Find augmenting path using DFS."""
        for neighbor in graph.neighbors(node):
            if neighbor in visited:
                continue
            visited.add(neighbor)

            if neighbor not in match_right or dfs_augment(match_right[neighbor], visited):
                matching[node] = neighbor
                match_right[neighbor] = node
                return True

        return False

    # Try to find augmenting paths
    for left_node in left_nodes:
        visited: set[Any] = set()
        dfs_augment(left_node, visited)

    return matching


def min_cost_flow(
    graph: Graph, source: Any, sink: Any, required_flow: float, max_iterations: int = 1000
) -> tuple[float, dict[tuple[Any, Any], float]]:
    """
    Find minimum cost flow using successive shortest paths.

    Args:
        graph: Input directed graph with edge weights as costs.
        source: Source node ID.
        sink: Sink node ID.
        required_flow: Amount of flow to send.
        max_iterations: Maximum iterations.

    Returns:
        Tuple of (total_cost, flow_dict).
    """
    # Build cost and capacity graphs
    cost: dict[tuple[Any, Any], float] = {}
    capacity: dict[tuple[Any, Any], float] = {}

    for src, dst, weight in graph.edges():
        cost[(src, dst)] = weight
        capacity[(src, dst)] = float("inf")

    flow: dict[tuple[Any, Any], float] = defaultdict(float)
    total_cost = 0.0
    sent_flow = 0.0

    for iteration in range(max_iterations):
        if sent_flow >= required_flow:
            break

        # Build residual graph
        residual_graph = Graph(GraphType.DIRECTED)
        for node in graph.nodes():
            residual_graph.add_node(node)

        for (src, dst), cap in capacity.items():
            if cap > flow[(src, dst)]:
                residual_capacity = cap - flow[(src, dst)]
                edge_cost = cost.get((src, dst), 0)
                residual_graph.add_edge(src, dst, residual_capacity)

        # Find shortest path
        try:
            from thomas.graph_analytics.shortest_path import dijkstra_shortest_path

            path_result = dijkstra_shortest_path(residual_graph, source, sink)

            if not path_result.has_path():
                break

            path = path_result.path
            path_cost = sum(cost.get((path[i], path[i + 1]), 0) for i in range(len(path) - 1))

            # Find bottleneck
            bottleneck = required_flow - sent_flow
            for i in range(len(path) - 1):
                src, dst = path[i], path[i + 1]
                available = capacity.get((src, dst), 0) - flow[(src, dst)]
                bottleneck = min(bottleneck, available)

            # Update flow
            for i in range(len(path) - 1):
                src, dst = path[i], path[i + 1]
                flow[(src, dst)] += bottleneck
                total_cost += bottleneck * cost.get((src, dst), 0)

            sent_flow += bottleneck

        except ImportError:
            break

    return total_cost, dict(flow)


def residual_graph(graph: Graph, flow: dict[tuple[Any, Any], float]) -> Graph:
    """
    Build residual graph from original graph and flow.

    Args:
        graph: Original directed graph.
        flow: Flow dictionary mapping (src, dst) to flow value.

    Returns:
        New graph representing residual capacities.
    """
    residual = Graph(GraphType.DIRECTED)

    # Add all nodes
    for node in graph.nodes():
        residual.add_node(node)

    # Add edges with residual capacities
    for src, dst, capacity in graph.edges():
        current_flow = flow.get((src, dst), 0)
        residual_cap = capacity - current_flow

        if residual_cap > 0:
            residual.add_edge(src, dst, residual_cap)

        # Add reverse edge if flow > 0
        if current_flow > 0:
            if not residual.has_edge(dst, src):
                residual.add_edge(dst, src, current_flow)
            else:
                residual.add_edge(dst, src, current_flow)

    return residual


def flow_decomposition(graph: Graph, flow: dict[tuple[Any, Any], float]) -> list[tuple[list[Any], float]]:
    """
    Decompose flow into simple paths.

    Args:
        graph: Original directed graph.
        flow: Flow dictionary.

    Returns:
        List of (path, flow_amount) tuples.
    """

    # Copy flow
    remaining_flow = {edge: f for edge, f in flow.items() if f > 0}
    paths: list[tuple[list[Any], float]] = []

    while remaining_flow:
        # Find a path with flow
        start_node = None
        for (src, dst), f in remaining_flow.items():
            start_node = src
            break

        if start_node is None:
            break

        # Find path greedily
        path = [start_node]
        current = start_node
        min_flow = float("inf")

        while True:
            # Find next node with flow
            next_node = None
            for (src, dst), f in remaining_flow.items():
                if src == current and f > 0:
                    next_node = dst
                    min_flow = min(min_flow, f)
                    break

            if next_node is None:
                break

            path.append(next_node)
            current = next_node

        # Record path and reduce flow
        if len(path) > 1:
            for i in range(len(path) - 1):
                edge = (path[i], path[i + 1])
                if edge in remaining_flow:
                    remaining_flow[edge] -= min_flow
                    if remaining_flow[edge] <= 0:
                        del remaining_flow[edge]

            paths.append((path, min_flow))
        else:
            break

    return paths
