"""
Shortest path algorithms.

Implements BFS, Dijkstra, Bellman-Ford, Floyd-Warshall, A*, and bidirectional Dijkstra.
"""

import heapq
from collections import deque
from collections.abc import Callable
from typing import Any

from thomas.marketplace.graph_analytics._exceptions import GraphAnalyticsError, NegativeCycleError
from thomas.marketplace.graph_analytics._types import PathResult
from thomas.marketplace.graph_analytics.graph import Graph


def bfs_shortest_path(graph: Graph, source: Any, target: Any | None = None) -> PathResult:
    """
    Find shortest path using BFS (for unweighted graphs).

    BFS guarantees shortest path in unweighted graphs by exploring
    nodes level by level.

    Args:
        graph: Input graph.
        source: Starting node ID.
        target: Ending node ID (if None, finds distances to all nodes).

    Returns:
        PathResult with path, distance, and distances to all nodes.

    Raises:
        KeyError: If source or target node doesn't exist.
    """
    if source not in graph:
        raise KeyError(f"Source node {source} not found")
    if target is not None and target not in graph:
        raise KeyError(f"Target node {target} not found")

    # Initialize
    distances: dict[Any, float] = {node: float("inf") for node in graph.nodes()}
    distances[source] = 0
    predecessors: dict[Any, Any | None] = {node: None for node in graph.nodes()}

    queue = deque([source])
    visited = {source}

    while queue:
        current = queue.popleft()

        # Early exit if found target
        if target is not None and current == target:
            break

        for neighbor in graph.neighbors(current):
            if neighbor not in visited:
                visited.add(neighbor)
                distances[neighbor] = distances[current] + 1
                predecessors[neighbor] = current
                queue.append(neighbor)

    # Reconstruct path
    path = []
    distance = float("inf")
    if target is not None:
        if distances[target] != float("inf"):
            current = target
            while current is not None:
                path.append(current)
                current = predecessors[current]
            path.reverse()
            distance = distances[target]
    else:
        distance = 0 if source == source else float("inf")

    return PathResult(path=path, distance=distance, distances=distances, predecessors=predecessors)


def dijkstra_shortest_path(graph: Graph, source: Any, target: Any | None = None) -> PathResult:
    """
    Find shortest path using Dijkstra's algorithm.

    Works with non-negative edge weights. Uses min-heap for efficiency.
    Time complexity: O((V + E) log V).

    Args:
        graph: Input graph.
        source: Starting node ID.
        target: Ending node ID (if None, finds distances to all nodes).

    Returns:
        PathResult with path, distance, and distances to all nodes.

    Raises:
        KeyError: If source or target node doesn't exist.
        GraphAnalyticsError: If negative weights are encountered.
    """
    if source not in graph:
        raise KeyError(f"Source node {source} not found")
    if target is not None and target not in graph:
        raise KeyError(f"Target node {target} not found")

    # Check for negative weights
    for src, neighbors in graph._adjacency.items():
        for _, weight in neighbors:
            if weight < 0:
                raise GraphAnalyticsError("Dijkstra requires non-negative weights")

    # Initialize
    distances: dict[Any, float] = {node: float("inf") for node in graph.nodes()}
    distances[source] = 0
    predecessors: dict[Any, Any | None] = {node: None for node in graph.nodes()}

    # Min-heap: (distance, node)
    heap = [(0, source)]
    visited = set()

    while heap:
        current_dist, current = heapq.heappop(heap)

        if current in visited:
            continue

        visited.add(current)

        # Early exit if found target
        if target is not None and current == target:
            break

        if current_dist > distances[current]:
            continue

        for neighbor, weight in graph._adjacency[current]:
            new_dist = current_dist + weight

            if new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                predecessors[neighbor] = current
                heapq.heappush(heap, (new_dist, neighbor))

    # Reconstruct path
    path = []
    distance = float("inf")
    if target is not None:
        if distances[target] != float("inf"):
            current = target
            while current is not None:
                path.append(current)
                current = predecessors[current]
            path.reverse()
            distance = distances[target]
    else:
        distance = 0

    return PathResult(path=path, distance=distance, distances=distances, predecessors=predecessors)


def bellman_ford_shortest_path(graph: Graph, source: Any, target: Any | None = None) -> PathResult:
    """
    Find shortest path using Bellman-Ford algorithm.

    Handles negative weights and detects negative cycles.
    Time complexity: O(VE).

    Args:
        graph: Input graph.
        source: Starting node ID.
        target: Ending node ID (if None, finds distances to all nodes).

    Returns:
        PathResult with path, distance, and distances to all nodes.

    Raises:
        KeyError: If source or target node doesn't exist.
        NegativeCycleError: If negative cycle is detected.
    """
    if source not in graph:
        raise KeyError(f"Source node {source} not found")
    if target is not None and target not in graph:
        raise KeyError(f"Target node {target} not found")

    # Initialize
    nodes = graph.nodes()
    distances: dict[Any, float] = {node: float("inf") for node in nodes}
    distances[source] = 0
    predecessors: dict[Any, Any | None] = {node: None for node in nodes}

    edges = graph.edges()

    # Relax edges V-1 times
    for _ in range(len(nodes) - 1):
        for src, dst, weight in edges:
            if distances[src] != float("inf") and distances[src] + weight < distances[dst]:
                distances[dst] = distances[src] + weight
                predecessors[dst] = src

    # Check for negative cycles
    for src, dst, weight in edges:
        if distances[src] != float("inf") and distances[src] + weight < distances[dst]:
            raise NegativeCycleError("Negative cycle detected in graph")

    # Reconstruct path
    path = []
    distance = float("inf")
    if target is not None:
        if distances[target] != float("inf"):
            current = target
            while current is not None:
                path.append(current)
                current = predecessors[current]
            path.reverse()
            distance = distances[target]
    else:
        distance = 0

    return PathResult(path=path, distance=distance, distances=distances, predecessors=predecessors)


def floyd_warshall_all_pairs(graph: Graph) -> tuple[dict[Any, dict[Any, float]], dict[Any, dict[Any, Any | None]]]:
    """
    Find shortest paths between all pairs using Floyd-Warshall.

    Handles negative weights and detects negative cycles.
    Time complexity: O(V^3).

    Args:
        graph: Input graph.

    Returns:
        Tuple of (distances dict, predecessors dict).

    Raises:
        NegativeCycleError: If negative cycle is detected.
    """
    nodes = graph.nodes()
    n = len(nodes)
    node_to_idx = {node: i for i, node in enumerate(nodes)}

    # Initialize distance matrix
    dist = [[float("inf")] * n for _ in range(n)]
    pred: list[list[Any | None]] = [[None] * n for _ in range(n)]

    # Set diagonal to 0
    for i in range(n):
        dist[i][i] = 0

    # Add edges
    for src, neighbors in graph._adjacency.items():
        i = node_to_idx[src]
        for dst, weight in neighbors:
            j = node_to_idx[dst]
            dist[i][j] = weight
            pred[i][j] = src

    # Floyd-Warshall iterations
    for k in range(n):
        for i in range(n):
            for j in range(n):
                if dist[i][k] + dist[k][j] < dist[i][j]:
                    dist[i][j] = dist[i][k] + dist[k][j]
                    pred[i][j] = pred[k][j]

    # Check for negative cycles
    for i in range(n):
        if dist[i][i] < 0:
            raise NegativeCycleError("Negative cycle detected in graph")

    # Convert back to dict format
    distance_dict: dict[Any, dict[Any, float]] = {}
    predecessor_dict: dict[Any, dict[Any, Any | None]] = {}

    for i, src in enumerate(nodes):
        distance_dict[src] = {}
        predecessor_dict[src] = {}
        for j, dst in enumerate(nodes):
            distance_dict[src][dst] = dist[i][j]
            predecessor_dict[src][dst] = pred[i][j]

    return distance_dict, predecessor_dict


def astar_shortest_path(graph: Graph, source: Any, target: Any, heuristic: Callable[[Any, Any], float]) -> PathResult:
    """
    Find shortest path using A* algorithm.

    Uses a heuristic function to guide search. Heuristic must be admissible.
    Time complexity: O((V + E) log V) in best case.

    Args:
        graph: Input graph.
        source: Starting node ID.
        target: Ending node ID.
        heuristic: Function that estimates distance from node to target.

    Returns:
        PathResult with path and distance.

    Raises:
        KeyError: If source or target node doesn't exist.
        GraphAnalyticsError: If negative weights are encountered.
    """
    if source not in graph:
        raise KeyError(f"Source node {source} not found")
    if target not in graph:
        raise KeyError(f"Target node {target} not found")

    # Check for negative weights
    for src, neighbors in graph._adjacency.items():
        for _, weight in neighbors:
            if weight < 0:
                raise GraphAnalyticsError("A* requires non-negative weights")

    # Initialize
    distances: dict[Any, float] = {node: float("inf") for node in graph.nodes()}
    distances[source] = 0
    predecessors: dict[Any, Any | None] = {node: None for node in graph.nodes()}

    # Min-heap: (f_score, counter, node) where f = g + h
    heap = [(heuristic(source, target), 0, source)]
    visited = set()
    counter = 1

    while heap:
        _, _, current = heapq.heappop(heap)

        if current in visited:
            continue

        visited.add(current)

        if current == target:
            break

        for neighbor, weight in graph._adjacency[current]:
            if neighbor not in visited:
                new_dist = distances[current] + weight

                if new_dist < distances[neighbor]:
                    distances[neighbor] = new_dist
                    predecessors[neighbor] = current
                    f_score = new_dist + heuristic(neighbor, target)
                    heapq.heappush(heap, (f_score, counter, neighbor))
                    counter += 1

    # Reconstruct path
    path = []
    distance = float("inf")
    if distances[target] != float("inf"):
        current = target
        while current is not None:
            path.append(current)
            current = predecessors[current]
        path.reverse()
        distance = distances[target]

    return PathResult(path=path, distance=distance, distances=distances, predecessors=predecessors)


def bidirectional_dijkstra(graph: Graph, source: Any, target: Any) -> PathResult:
    """
    Find shortest path using bidirectional Dijkstra.

    Searches from both source and target simultaneously, typically faster
    than unidirectional Dijkstra. Time complexity: O((V + E) log V).

    Args:
        graph: Input graph.
        source: Starting node ID.
        target: Ending node ID.

    Returns:
        PathResult with path and distance.

    Raises:
        KeyError: If source or target node doesn't exist.
        GraphAnalyticsError: If negative weights are encountered.
    """
    if source not in graph:
        raise KeyError(f"Source node {source} not found")
    if target not in graph:
        raise KeyError(f"Target node {target} not found")

    # Check for negative weights
    for src, neighbors in graph._adjacency.items():
        for _, weight in neighbors:
            if weight < 0:
                raise GraphAnalyticsError("Bidirectional Dijkstra requires non-negative weights")

    # If source == target
    if source == target:
        return PathResult(path=[source], distance=0)

    # Forward search
    forward_dist: dict[Any, float] = {node: float("inf") for node in graph.nodes()}
    forward_dist[source] = 0
    forward_pred: dict[Any, Any | None] = {node: None for node in graph.nodes()}
    forward_heap = [(0, source)]
    forward_visited = set()

    # Backward search
    backward_dist: dict[Any, float] = {node: float("inf") for node in graph.nodes()}
    backward_dist[target] = 0
    backward_pred: dict[Any, Any | None] = {node: None for node in graph.nodes()}
    backward_heap = [(0, target)]
    backward_visited = set()

    best_distance = float("inf")
    best_meeting_point = None

    while forward_heap or backward_heap:
        # Forward step
        if forward_heap:
            fd, fu = heapq.heappop(forward_heap)
            if fu not in forward_visited:
                forward_visited.add(fu)

                for neighbor, weight in graph._adjacency[fu]:
                    new_dist = fd + weight
                    if new_dist < forward_dist[neighbor]:
                        forward_dist[neighbor] = new_dist
                        forward_pred[neighbor] = fu
                        heapq.heappush(forward_heap, (new_dist, neighbor))

                    # Check if meeting point
                    if neighbor in backward_visited:
                        meeting_dist = forward_dist[neighbor] + backward_dist[neighbor]
                        if meeting_dist < best_distance:
                            best_distance = meeting_dist
                            best_meeting_point = neighbor

        # Backward step
        if backward_heap:
            bd, bu = heapq.heappop(backward_heap)
            if bu not in backward_visited:
                backward_visited.add(bu)

                for neighbor, weight in graph._reverse_adjacency[bu]:
                    new_dist = bd + weight
                    if new_dist < backward_dist[neighbor]:
                        backward_dist[neighbor] = new_dist
                        backward_pred[neighbor] = bu
                        heapq.heappush(backward_heap, (new_dist, neighbor))

                    # Check if meeting point
                    if neighbor in forward_visited:
                        meeting_dist = forward_dist[neighbor] + backward_dist[neighbor]
                        if meeting_dist < best_distance:
                            best_distance = meeting_dist
                            best_meeting_point = neighbor

        # Early termination
        if best_meeting_point is not None:
            if forward_heap and forward_heap[0][0] + backward_heap[0][0] >= best_distance:
                break
            if backward_heap and forward_heap and forward_heap[0][0] + backward_heap[0][0] >= best_distance:
                break

    # Reconstruct path
    path = []
    if best_meeting_point is not None:
        # Forward path
        current = best_meeting_point
        forward_path = []
        while current is not None:
            forward_path.append(current)
            current = forward_pred[current]
        forward_path.reverse()

        # Backward path
        current = backward_pred[best_meeting_point]
        backward_path = []
        while current is not None:
            backward_path.append(current)
            current = backward_pred[current]

        path = forward_path + backward_path

    return PathResult(path=path, distance=best_distance, distances=forward_dist, predecessors=forward_pred)
