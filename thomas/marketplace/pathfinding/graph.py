"""
Graph data structures and utilities for pathfinding.

This module provides graph representations, building utilities, and graph algorithms
for analyzing graph properties.
"""

import heapq
from collections import deque

from thomas.marketplace.pathfinding._exceptions import InvalidGraphError
from thomas.marketplace.pathfinding._types import Graph, Grid2D, Node


def build_graph_from_grid(grid: Grid2D) -> Graph:
    """
    Build a graph from a 2D grid.

    Each walkable cell becomes a node, with edges connecting to walkable neighbors.

    Args:
        grid: The 2D grid to convert.

    Returns:
        A Graph with nodes for each walkable cell and edges connecting neighbors.
    """
    graph = Graph(directed=False)

    for y in range(grid.height):
        for x in range(grid.width):
            if grid.is_walkable(x, y):
                node_id = f"{x},{y}"
                node = Node(id=node_id, x=float(x), y=float(y))
                graph.add_node(node)

    for y in range(grid.height):
        for x in range(grid.width):
            if grid.is_walkable(x, y):
                from_id = f"{x},{y}"
                neighbors = grid.get_neighbors(x, y)
                for nx, ny, cost in neighbors:
                    to_id = f"{nx},{ny}"
                    if not graph.has_edge(from_id, to_id):
                        graph.add_edge(from_id, to_id, cost)

    return graph


def build_graph_from_waypoints(
    waypoints: list[tuple[float, float]],
    connect_nearby: bool = True,
    max_distance: float = float("inf"),
) -> Graph:
    """
    Build a graph from a list of waypoints.

    Args:
        waypoints: List of (x, y) tuples representing waypoints.
        connect_nearby: If True, connect waypoints within max_distance.
        max_distance: Maximum distance for connecting nearby waypoints.

    Returns:
        A Graph with waypoints as nodes.
    """
    graph = Graph(directed=False)

    for i, (x, y) in enumerate(waypoints):
        node = Node(id=i, x=x, y=y)
        graph.add_node(node)

    if connect_nearby:
        for i in range(len(waypoints)):
            for j in range(i + 1, len(waypoints)):
                x1, y1 = waypoints[i]
                x2, y2 = waypoints[j]
                dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                if dist <= max_distance:
                    graph.add_edge(i, j, dist)

    return graph


def extract_subgraph(graph: Graph, node_ids: set[int | str]) -> Graph:
    """
    Extract a subgraph containing only specified nodes and edges between them.

    Args:
        graph: The original graph.
        node_ids: Set of node IDs to include in subgraph.

    Returns:
        A new Graph containing only the specified nodes.
    """
    subgraph = Graph(directed=graph.directed)

    for node_id in node_ids:
        if node_id in graph.nodes:
            subgraph.add_node(graph.nodes[node_id])

    for from_id in node_ids:
        if from_id in graph.edges:
            for to_id, weight in graph.edges[from_id]:
                if to_id in node_ids:
                    subgraph.add_edge(from_id, to_id, weight)

    return subgraph


def serialize_graph(graph: Graph) -> dict:
    """
    Serialize a graph to a dictionary.

    Args:
        graph: The graph to serialize.

    Returns:
        Dictionary representation of the graph.
    """
    nodes_data = [
        {
            "id": node.id,
            "x": node.x,
            "y": node.y,
            "z": node.z,
        }
        for node in graph.nodes.values()
    ]

    edges_data = []
    for from_id, neighbors in graph.edges.items():
        for to_id, weight in neighbors:
            edges_data.append(
                {
                    "from": from_id,
                    "to": to_id,
                    "weight": weight,
                }
            )

    return {
        "nodes": nodes_data,
        "edges": edges_data,
        "directed": graph.directed,
    }


def deserialize_graph(data: dict) -> Graph:
    """
    Deserialize a graph from a dictionary.

    Args:
        data: Dictionary representation of a graph.

    Returns:
        Reconstructed Graph object.
    """
    graph = Graph(directed=data.get("directed", True))

    for node_data in data.get("nodes", []):
        node = Node(
            id=node_data["id"],
            x=node_data.get("x", 0.0),
            y=node_data.get("y", 0.0),
            z=node_data.get("z", 0.0),
        )
        graph.add_node(node)

    for edge_data in data.get("edges", []):
        graph.add_edge(
            edge_data["from"],
            edge_data["to"],
            edge_data.get("weight", 1.0),
        )

    return graph


def find_connected_components(graph: Graph) -> list[set[int | str]]:
    """
    Find all connected components in the graph using BFS.

    Args:
        graph: The graph to analyze.

    Returns:
        List of sets, each containing node IDs in a connected component.
    """
    visited: set[int | str] = set()
    components: list[set[int | str]] = []

    for start_id in graph.nodes:
        if start_id in visited:
            continue

        component: set[int | str] = set()
        queue = deque([start_id])
        visited.add(start_id)

        while queue:
            node_id = queue.popleft()
            component.add(node_id)

            for neighbor_id, _ in graph.edges.get(node_id, []):
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append(neighbor_id)

            if graph.directed:
                for from_id, neighbors in graph.edges.items():
                    for to_id, _ in neighbors:
                        if to_id == node_id and from_id not in visited:
                            visited.add(from_id)
                            queue.append(from_id)

        components.append(component)

    return components


def topological_sort(graph: Graph) -> list[int | str]:
    """
    Perform topological sort using Kahn's algorithm.

    Only works on DAGs (Directed Acyclic Graphs).

    Args:
        graph: The graph to sort (must be a DAG).

    Returns:
        List of node IDs in topological order.

    Raises:
        InvalidGraphError: If graph contains a cycle.
    """
    if not graph.directed:
        raise InvalidGraphError("Topological sort requires a directed graph")

    in_degree: dict[int | str, int] = {node_id: 0 for node_id in graph.nodes}

    for from_id, neighbors in graph.edges.items():
        for to_id, _ in neighbors:
            in_degree[to_id] += 1

    queue = deque([node_id for node_id in graph.nodes if in_degree[node_id] == 0])
    sorted_nodes: list[int | str] = []

    while queue:
        node_id = queue.popleft()
        sorted_nodes.append(node_id)

        for neighbor_id, _ in graph.edges.get(node_id, []):
            in_degree[neighbor_id] -= 1
            if in_degree[neighbor_id] == 0:
                queue.append(neighbor_id)

    if len(sorted_nodes) != len(graph.nodes):
        raise InvalidGraphError("Graph contains a cycle")

    return sorted_nodes


def build_adjacency_matrix(graph: Graph) -> tuple[list[list[float]], dict]:
    """
    Build adjacency matrix representation of the graph.

    Args:
        graph: The graph to convert.

    Returns:
        Tuple of (adjacency matrix, node_id to index mapping).
    """
    node_list = list(graph.nodes.keys())
    n = len(node_list)
    node_to_idx = {node_id: i for i, node_id in enumerate(node_list)}

    matrix: list[list[float]] = [[float("inf") for _ in range(n)] for _ in range(n)]

    for i in range(n):
        matrix[i][i] = 0.0

    for from_id, neighbors in graph.edges.items():
        i = node_to_idx[from_id]
        for to_id, weight in neighbors:
            j = node_to_idx[to_id]
            matrix[i][j] = weight

    return matrix, node_to_idx


def build_reverse_graph(graph: Graph) -> Graph:
    """
    Build the reverse graph (all edges reversed).

    Args:
        graph: The original graph.

    Returns:
        A new graph with all edges reversed.
    """
    reverse = Graph(directed=graph.directed)

    for node in graph.nodes.values():
        reverse.add_node(node)

    for from_id, neighbors in graph.edges.items():
        for to_id, weight in neighbors:
            reverse.add_edge(to_id, from_id, weight)

    return reverse


def is_strongly_connected(graph: Graph) -> bool:
    """
    Check if a directed graph is strongly connected.

    Args:
        graph: The graph to check.

    Returns:
        True if every node can reach every other node.
    """
    if not graph.directed:
        components = find_connected_components(graph)
        return len(components) == 1

    reverse = build_reverse_graph(graph)

    def dfs_visit(
        graph_edges: dict,
        node_id: int | str,
        visited: set[int | str],
    ) -> None:
        visited.add(node_id)
        for neighbor_id, _ in graph_edges.get(node_id, []):
            if neighbor_id not in visited:
                dfs_visit(graph_edges, neighbor_id, visited)

    for start_id in graph.nodes:
        visited: set[int | str] = set()
        dfs_visit(graph.edges, start_id, visited)
        if len(visited) != len(graph.nodes):
            return False

        visited = set()
        dfs_visit(reverse.edges, start_id, visited)
        if len(visited) != len(graph.nodes):
            return False

    return True


def detect_cycles(graph: Graph) -> bool:
    """
    Detect if the graph contains any cycles.

    Args:
        graph: The graph to check.

    Returns:
        True if any cycles exist.
    """
    if not graph.directed:
        visited: set[int | str] = set()
        rec_stack: set[int | str] = set()

        def has_cycle(
            node_id: int | str,
        ) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)

            for neighbor_id, _ in graph.edges.get(node_id, []):
                if neighbor_id not in visited:
                    if has_cycle(neighbor_id):
                        return True
                elif neighbor_id in rec_stack:
                    return True

            rec_stack.remove(node_id)
            return False

        for node_id in graph.nodes:
            if node_id not in visited:
                if has_cycle(node_id):
                    return True
        return False
    else:
        return False


def graph_density(graph: Graph) -> float:
    """
    Calculate the density of the graph.

    Density = (2 * edges) / (nodes * (nodes - 1)) for undirected graphs.

    Args:
        graph: The graph to analyze.

    Returns:
        Graph density between 0 and 1.
    """
    n = len(graph.nodes)
    if n <= 1:
        return 0.0

    edge_count = sum(len(neighbors) for neighbors in graph.edges.values())
    if graph.directed:
        max_edges = n * (n - 1)
    else:
        edge_count = edge_count // 2
        max_edges = n * (n - 1) // 2

    return edge_count / max_edges if max_edges > 0 else 0.0


def shortest_path_distances(graph: Graph, start_id: int | str) -> dict[int | str, float]:
    """
    Compute shortest path distances from a node using Dijkstra's algorithm.

    Args:
        graph: The graph.
        start_id: Start node ID.

    Returns:
        Dictionary mapping node IDs to shortest distances.
    """
    distances: dict[int | str, float] = {node_id: float("inf") for node_id in graph.nodes}
    distances[start_id] = 0.0

    heap: list[tuple[float, int | str]] = [(0.0, start_id)]

    while heap:
        current_dist, current_id = heapq.heappop(heap)

        if current_dist > distances[current_id]:
            continue

        for neighbor_id, weight in graph.edges.get(current_id, []):
            new_dist = current_dist + weight
            if new_dist < distances[neighbor_id]:
                distances[neighbor_id] = new_dist
                heapq.heappush(heap, (new_dist, neighbor_id))

    return distances


def diameter(graph: Graph) -> float:
    """
    Compute the diameter of the graph (longest shortest path).

    Args:
        graph: The graph to analyze.

    Returns:
        The diameter, or infinity if graph is disconnected.
    """
    max_dist = 0.0

    for node_id in graph.nodes:
        distances = shortest_path_distances(graph, node_id)
        for dist in distances.values():
            if dist == float("inf"):
                return float("inf")
            max_dist = max(max_dist, dist)

    return max_dist
