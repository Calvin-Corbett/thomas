"""
Classical graph search algorithms for pathfinding.

This module implements Dijkstra, A*, Bellman-Ford, Floyd-Warshall, bidirectional
Dijkstra, iterative deepening A*, and beam search algorithms.
"""

import heapq
import math
import time

from thomas.pathfinding._exceptions import InvalidGraphError
from thomas.pathfinding._types import Graph, Path, PathResult


def dijkstra(
    graph: Graph,
    start_id: int | str,
    goal_id: int | str,
) -> PathResult:
    """
    Find shortest path using Dijkstra's algorithm with binary heap.

    Args:
        graph: The graph to search.
        start_id: Start node ID.
        goal_id: Goal node ID.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()
    nodes_expanded = 0
    nodes_generated = 1

    if start_id not in graph.nodes or goal_id not in graph.nodes:
        return PathResult(found=False)

    distances: dict[int | str, float] = {node_id: float("inf") for node_id in graph.nodes}
    distances[start_id] = 0.0
    parents: dict[int | str, int | str | None] = {node_id: None for node_id in graph.nodes}

    heap: list[tuple[float, int | str]] = [(0.0, start_id)]
    visited: set[int | str] = set()

    while heap:
        current_dist, current_id = heapq.heappop(heap)

        if current_id in visited:
            continue

        visited.add(current_id)
        nodes_expanded += 1

        if current_id == goal_id:
            path_nodes: list[int | str] = []
            node = current_id
            while node is not None:
                path_nodes.append(node)
                node = parents[node]
            path_nodes.reverse()
            path = Path(tuple(path_nodes), current_dist)
            return PathResult(
                found=True,
                path=path,
                cost=current_dist,
                nodes_expanded=nodes_expanded,
                nodes_generated=nodes_generated,
                execution_time=time.time() - start_time,
            )

        for neighbor_id, weight in graph.edges.get(current_id, []):
            if neighbor_id in visited:
                continue

            new_dist = current_dist + weight
            if new_dist < distances[neighbor_id]:
                distances[neighbor_id] = new_dist
                parents[neighbor_id] = current_id
                nodes_generated += 1
                heapq.heappush(heap, (new_dist, neighbor_id))

    return PathResult(
        found=False,
        nodes_expanded=nodes_expanded,
        nodes_generated=nodes_generated,
        execution_time=time.time() - start_time,
    )


def astar(
    graph: Graph,
    start_id: int | str,
    goal_id: int | str,
    heuristic_name: str = "euclidean",
) -> PathResult:
    """
    Find shortest path using A* algorithm.

    Args:
        graph: The graph to search.
        start_id: Start node ID.
        goal_id: Goal node ID.
        heuristic_name: Heuristic to use (euclidean, manhattan, chebyshev, octile).

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()
    nodes_expanded = 0
    nodes_generated = 1

    if start_id not in graph.nodes or goal_id not in graph.nodes:
        return PathResult(found=False)

    goal_node = graph.nodes[goal_id]

    def get_heuristic(node_id: int | str) -> float:
        node = graph.nodes[node_id]
        if heuristic_name == "manhattan":
            return node.manhattan_distance(goal_node)
        elif heuristic_name == "chebyshev":
            return node.chebyshev_distance(goal_node)
        elif heuristic_name == "octile":
            dx = abs(node.x - goal_node.x)
            dy = abs(node.y - goal_node.y)
            return max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)
        else:
            return node.distance_to(goal_node)

    g_score: dict[int | str, float] = {node_id: float("inf") for node_id in graph.nodes}
    g_score[start_id] = 0.0
    parents: dict[int | str, int | str | None] = {node_id: None for node_id in graph.nodes}

    open_set: list[tuple[float, int | str]] = [(get_heuristic(start_id), start_id)]
    visited: set[int | str] = set()

    while open_set:
        _, current_id = heapq.heappop(open_set)

        if current_id in visited:
            continue

        visited.add(current_id)
        nodes_expanded += 1

        if current_id == goal_id:
            path_nodes: list[int | str] = []
            node = current_id
            while node is not None:
                path_nodes.append(node)
                node = parents[node]
            path_nodes.reverse()
            cost = g_score[goal_id]
            path = Path(tuple(path_nodes), cost)
            return PathResult(
                found=True,
                path=path,
                cost=cost,
                nodes_expanded=nodes_expanded,
                nodes_generated=nodes_generated,
                execution_time=time.time() - start_time,
            )

        for neighbor_id, weight in graph.edges.get(current_id, []):
            if neighbor_id in visited:
                continue

            tentative_g = g_score[current_id] + weight
            if tentative_g < g_score[neighbor_id]:
                g_score[neighbor_id] = tentative_g
                parents[neighbor_id] = current_id
                f_score = tentative_g + get_heuristic(neighbor_id)
                nodes_generated += 1
                heapq.heappush(open_set, (f_score, neighbor_id))

    return PathResult(
        found=False,
        nodes_expanded=nodes_expanded,
        nodes_generated=nodes_generated,
        execution_time=time.time() - start_time,
    )


def bellman_ford(
    graph: Graph,
    start_id: int | str,
    goal_id: int | str,
) -> PathResult:
    """
    Find shortest path using Bellman-Ford algorithm (handles negative weights).

    Args:
        graph: The graph to search.
        start_id: Start node ID.
        goal_id: Goal node ID.

    Returns:
        PathResult containing the path and statistics.

    Raises:
        InvalidGraphError: If negative cycle exists.
    """
    start_time = time.time()
    nodes_expanded = 0
    nodes_generated = len(graph.nodes)

    if start_id not in graph.nodes or goal_id not in graph.nodes:
        return PathResult(found=False)

    distances: dict[int | str, float] = {node_id: float("inf") for node_id in graph.nodes}
    distances[start_id] = 0.0
    parents: dict[int | str, int | str | None] = {node_id: None for node_id in graph.nodes}

    for _ in range(len(graph.nodes) - 1):
        for from_id, neighbors in graph.edges.items():
            for to_id, weight in neighbors:
                if distances[from_id] != float("inf"):
                    new_dist = distances[from_id] + weight
                    if new_dist < distances[to_id]:
                        distances[to_id] = new_dist
                        parents[to_id] = from_id
                        nodes_expanded += 1

    for from_id, neighbors in graph.edges.items():
        for to_id, weight in neighbors:
            if distances[from_id] != float("inf"):
                if distances[from_id] + weight < distances[to_id]:
                    raise InvalidGraphError("Negative cycle detected")

    if distances[goal_id] == float("inf"):
        return PathResult(
            found=False,
            nodes_expanded=nodes_expanded,
            nodes_generated=nodes_generated,
            execution_time=time.time() - start_time,
        )

    path_nodes: list[int | str] = []
    node = goal_id
    while node is not None:
        path_nodes.append(node)
        node = parents[node]
    path_nodes.reverse()
    path = Path(tuple(path_nodes), distances[goal_id])

    return PathResult(
        found=True,
        path=path,
        cost=distances[goal_id],
        nodes_expanded=nodes_expanded,
        nodes_generated=nodes_generated,
        execution_time=time.time() - start_time,
    )


def floyd_warshall(graph: Graph) -> tuple[list[list[float]], dict]:
    """
    Compute all-pairs shortest paths using Floyd-Warshall algorithm.

    Args:
        graph: The graph to search.

    Returns:
        Tuple of (distance matrix, node_id to index mapping).
    """
    node_list = list(graph.nodes.keys())
    n = len(node_list)
    node_to_idx = {node_id: i for i, node_id in enumerate(node_list)}

    dist: list[list[float]] = [[float("inf") for _ in range(n)] for _ in range(n)]

    for i in range(n):
        dist[i][i] = 0.0

    for from_id, neighbors in graph.edges.items():
        i = node_to_idx[from_id]
        for to_id, weight in neighbors:
            j = node_to_idx[to_id]
            dist[i][j] = min(dist[i][j], weight)

    for k in range(n):
        for i in range(n):
            for j in range(n):
                dist[i][j] = min(dist[i][j], dist[i][k] + dist[k][j])

    return dist, node_to_idx


def bidirectional_dijkstra(
    graph: Graph,
    start_id: int | str,
    goal_id: int | str,
) -> PathResult:
    """
    Find shortest path using bidirectional Dijkstra's algorithm.

    Searches from both start and goal simultaneously for efficiency.

    Args:
        graph: The graph to search.
        start_id: Start node ID.
        goal_id: Goal node ID.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()
    nodes_expanded = 0
    nodes_generated = 2

    if start_id not in graph.nodes or goal_id not in graph.nodes:
        return PathResult(found=False)

    forward_dist: dict[int | str, float] = {node_id: float("inf") for node_id in graph.nodes}
    forward_dist[start_id] = 0.0
    forward_parents: dict[int | str, int | str | None] = {node_id: None for node_id in graph.nodes}

    backward_dist: dict[int | str, float] = {node_id: float("inf") for node_id in graph.nodes}
    backward_dist[goal_id] = 0.0
    backward_parents: dict[int | str, int | str | None] = {node_id: None for node_id in graph.nodes}

    forward_heap: list[tuple[float, int | str]] = [(0.0, start_id)]
    backward_heap: list[tuple[float, int | str]] = [(0.0, goal_id)]
    forward_visited: set[int | str] = set()
    backward_visited: set[int | str] = set()

    best_path_cost = float("inf")
    meeting_point: int | str | None = None

    while forward_heap or backward_heap:
        if forward_heap and (not backward_heap or forward_heap[0][0] <= backward_heap[0][0]):
            current_dist, current_id = heapq.heappop(forward_heap)

            if current_id in forward_visited:
                continue

            forward_visited.add(current_id)
            nodes_expanded += 1

            if current_id in backward_visited:
                path_cost = forward_dist[current_id] + backward_dist[current_id]
                if path_cost < best_path_cost:
                    best_path_cost = path_cost
                    meeting_point = current_id

            for neighbor_id, weight in graph.edges.get(current_id, []):
                if neighbor_id in forward_visited:
                    continue

                new_dist = current_dist + weight
                if new_dist < forward_dist[neighbor_id]:
                    forward_dist[neighbor_id] = new_dist
                    forward_parents[neighbor_id] = current_id
                    nodes_generated += 1
                    heapq.heappush(forward_heap, (new_dist, neighbor_id))

        elif backward_heap:
            current_dist, current_id = heapq.heappop(backward_heap)

            if current_id in backward_visited:
                continue

            backward_visited.add(current_id)
            nodes_expanded += 1

            if current_id in forward_visited:
                path_cost = forward_dist[current_id] + backward_dist[current_id]
                if path_cost < best_path_cost:
                    best_path_cost = path_cost
                    meeting_point = current_id

            for neighbor_id, weight in graph.edges.get(current_id, []):
                if neighbor_id in backward_visited:
                    continue

                new_dist = current_dist + weight
                if new_dist < backward_dist[neighbor_id]:
                    backward_dist[neighbor_id] = new_dist
                    backward_parents[neighbor_id] = current_id
                    nodes_generated += 1
                    heapq.heappush(backward_heap, (new_dist, neighbor_id))

    if meeting_point is None:
        return PathResult(
            found=False,
            nodes_expanded=nodes_expanded,
            nodes_generated=nodes_generated,
            execution_time=time.time() - start_time,
        )

    path_nodes: list[int | str] = []
    node = meeting_point
    while node is not None:
        path_nodes.append(node)
        node = forward_parents[node]
    path_nodes.reverse()

    node = backward_parents[meeting_point]
    while node is not None:
        path_nodes.append(node)
        node = backward_parents[node]

    path = Path(tuple(path_nodes), best_path_cost)
    return PathResult(
        found=True,
        path=path,
        cost=best_path_cost,
        nodes_expanded=nodes_expanded,
        nodes_generated=nodes_generated,
        execution_time=time.time() - start_time,
    )


def iterative_deepening_astar(
    graph: Graph,
    start_id: int | str,
    goal_id: int | str,
    max_iterations: int = 1000,
) -> PathResult:
    """
    Find shortest path using Iterative Deepening A* (IDA*).

    Args:
        graph: The graph to search.
        start_id: Start node ID.
        goal_id: Goal node ID.
        max_iterations: Maximum search depth iterations.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()
    nodes_expanded = 0

    if start_id not in graph.nodes or goal_id not in graph.nodes:
        return PathResult(found=False)

    goal_node = graph.nodes[goal_id]

    def heuristic(node_id: int | str) -> float:
        node = graph.nodes[node_id]
        return node.distance_to(goal_node)

    threshold = heuristic(start_id)

    while True:
        visited: set[int | str] = set()
        result = _ida_search(
            graph,
            start_id,
            goal_id,
            0.0,
            threshold,
            heuristic,
            visited,
        )

        if isinstance(result, tuple):
            path_nodes, cost = result
            return PathResult(
                found=True,
                path=Path(tuple(path_nodes), cost),
                cost=cost,
                nodes_expanded=len(visited),
                nodes_generated=len(visited),
                execution_time=time.time() - start_time,
            )

        if result == float("inf"):
            return PathResult(
                found=False,
                nodes_expanded=len(visited),
                nodes_generated=len(visited),
                execution_time=time.time() - start_time,
            )

        threshold = result


def _ida_search(
    graph: Graph,
    node_id: int | str,
    goal_id: int | str,
    g: float,
    threshold: float,
    heuristic: callable,
    visited: set[int | str],
) -> tuple[list[int | str], float] | float:
    """Helper for IDA* search."""
    f = g + heuristic(node_id)

    if f > threshold:
        return f

    if node_id == goal_id:
        return ([node_id], g)

    visited.add(node_id)
    min_threshold = float("inf")

    for neighbor_id, weight in graph.edges.get(node_id, []):
        if neighbor_id not in visited:
            result = _ida_search(
                graph,
                neighbor_id,
                goal_id,
                g + weight,
                threshold,
                heuristic,
                visited,
            )

            if isinstance(result, tuple):
                path_nodes, cost = result
                return ([node_id] + path_nodes, cost)

            if result < min_threshold:
                min_threshold = result

    return min_threshold


def beam_search(
    graph: Graph,
    start_id: int | str,
    goal_id: int | str,
    beam_width: int = 5,
) -> PathResult:
    """
    Find path using Beam Search (greedy best-first with limited width).

    Args:
        graph: The graph to search.
        start_id: Start node ID.
        goal_id: Goal node ID.
        beam_width: Maximum number of nodes to expand per level.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()
    nodes_expanded = 0
    nodes_generated = 1

    if start_id not in graph.nodes or goal_id not in graph.nodes:
        return PathResult(found=False)

    goal_node = graph.nodes[goal_id]

    def heuristic(node_id: int | str) -> float:
        node = graph.nodes[node_id]
        return node.distance_to(goal_node)

    current_level = {start_id: (0.0, None)}
    visited: set[int | str] = {start_id}

    while current_level:
        next_level: dict[int | str, tuple[float, int | str | None]] = {}

        for node_id, (cost, parent) in current_level.items():
            if node_id == goal_id:
                path_nodes: list[int | str] = []
                current = node_id
                while current is not None:
                    path_nodes.append(current)
                    current = current_level[current][1]
                    if current == node_id:
                        break
                path_nodes.reverse()
                path = Path(tuple(path_nodes), cost)
                return PathResult(
                    found=True,
                    path=path,
                    cost=cost,
                    nodes_expanded=nodes_expanded,
                    nodes_generated=nodes_generated,
                    execution_time=time.time() - start_time,
                )

            nodes_expanded += 1

            for neighbor_id, weight in graph.edges.get(node_id, []):
                if neighbor_id not in visited:
                    new_cost = cost + weight
                    h = heuristic(neighbor_id)
                    f = new_cost + h
                    next_level[neighbor_id] = (new_cost, node_id)
                    visited.add(neighbor_id)
                    nodes_generated += 1

        sorted_next = sorted(
            next_level.items(),
            key=lambda x: x[1][0] + heuristic(x[0]),
        )
        current_level = {node_id: (cost, parent) for node_id, (cost, parent) in sorted_next[:beam_width]}

    return PathResult(
        found=False,
        nodes_expanded=nodes_expanded,
        nodes_generated=nodes_generated,
        execution_time=time.time() - start_time,
    )
