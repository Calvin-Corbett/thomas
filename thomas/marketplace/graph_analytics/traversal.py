"""
Graph traversal and cycle detection algorithms.

Implements BFS, DFS, topological sort, cycle detection, and component detection.
"""

from collections import deque
from typing import Any

from thomas.marketplace.graph_analytics._exceptions import CycleDetectedError
from thomas.marketplace.graph_analytics.graph import Graph


def bfs_traversal(graph: Graph, source: Any, max_depth: int | None = None) -> tuple[list[Any], dict[Any, int]]:
    """
    Breadth-first search traversal.

    Explores nodes level by level, tracking discovery order and depth.

    Args:
        graph: Input graph.
        source: Starting node ID.
        max_depth: Maximum search depth (None for unlimited).

    Returns:
        Tuple of (traversal order, depth map).

    Raises:
        KeyError: If source node doesn't exist.
    """
    if source not in graph:
        raise KeyError(f"Source node {source} not found")

    order = []
    depths: dict[Any, int] = {source: 0}
    queue = deque([source])

    while queue:
        current = queue.popleft()
        order.append(current)

        current_depth = depths[current]
        if max_depth is None or current_depth < max_depth:
            for neighbor in graph.neighbors(current):
                if neighbor not in depths:
                    depths[neighbor] = current_depth + 1
                    queue.append(neighbor)

    return order, depths


def dfs_traversal(
    graph: Graph, source: Any, max_depth: int | None = None
) -> tuple[list[Any], dict[Any, int], dict[Any, int]]:
    """
    Depth-first search traversal.

    Records discovery and finish times for each node.

    Args:
        graph: Input graph.
        source: Starting node ID.
        max_depth: Maximum search depth.

    Returns:
        Tuple of (discovery order, discovery times, finish times).

    Raises:
        KeyError: If source node doesn't exist.
    """
    if source not in graph:
        raise KeyError(f"Source node {source} not found")

    order = []
    discovery_times: dict[Any, int] = {}
    finish_times: dict[Any, int] = {}
    time_counter = [0]

    visited = set()

    def dfs_recursive(node: Any, depth: int) -> None:
        """Recursive DFS helper."""
        if max_depth is not None and depth > max_depth:
            return

        visited.add(node)
        time_counter[0] += 1
        discovery_times[node] = time_counter[0]
        order.append(node)

        for neighbor in graph.neighbors(node):
            if neighbor not in visited:
                dfs_recursive(neighbor, depth + 1)

        time_counter[0] += 1
        finish_times[node] = time_counter[0]

    dfs_recursive(source, 0)

    return order, discovery_times, finish_times


def topological_sort(graph: Graph) -> list[Any]:
    """
    Topological sort using Kahn's algorithm.

    Works for directed acyclic graphs (DAGs).

    Args:
        graph: Input directed graph.

    Returns:
        List of nodes in topological order.

    Raises:
        CycleDetectedError: If graph contains cycles.
    """
    # Calculate in-degrees
    in_degree: dict[Any, int] = {}
    for node in graph.nodes():
        in_degree[node] = graph.in_degree(node)

    # Initialize queue with nodes having in-degree 0
    queue = deque([node for node in graph.nodes() if in_degree[node] == 0])

    topo_order = []

    while queue:
        node = queue.popleft()
        topo_order.append(node)

        # Reduce in-degree for neighbors
        for neighbor in graph.neighbors(node):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Check if all nodes were processed (no cycles)
    if len(topo_order) != graph.num_nodes():
        raise CycleDetectedError("Graph contains cycles")

    return topo_order


def detect_cycle(graph: Graph) -> list[Any] | None:
    """
    Detect if graph contains a cycle and return one if found.

    Uses DFS with color marking (white, gray, black).

    Args:
        graph: Input directed graph.

    Returns:
        Cycle as list of node IDs, or None if no cycle exists.
    """
    # Color: 0=white, 1=gray, 2=black
    colors: dict[Any, int] = {node: 0 for node in graph.nodes()}
    parents: dict[Any, Any | None] = {node: None for node in graph.nodes()}

    def dfs_has_cycle(node: Any) -> list[Any] | None:
        """Check for cycle using DFS."""
        colors[node] = 1  # Mark as gray

        for neighbor in graph.neighbors(node):
            if colors[neighbor] == 1:  # Back edge found
                # Reconstruct cycle
                cycle = [neighbor]
                current = node
                while current != neighbor:
                    cycle.append(current)
                    current = parents[current]
                    if current is None:
                        break
                cycle.append(neighbor)
                return cycle
            elif colors[neighbor] == 0:  # White node
                parents[neighbor] = node
                result = dfs_has_cycle(neighbor)
                if result:
                    return result

        colors[node] = 2  # Mark as black
        return None

    for node in graph.nodes():
        if colors[node] == 0:
            result = dfs_has_cycle(node)
            if result:
                return result

    return None


def connected_components(graph: Graph) -> list[set[Any]]:
    """
    Find all connected components in an undirected graph.

    Args:
        graph: Input undirected graph.

    Returns:
        List of sets, each representing a connected component.
    """
    visited = set()
    components = []

    for node in graph.nodes():
        if node not in visited:
            component = set()
            stack = [node]

            while stack:
                current = stack.pop()
                if current in visited:
                    continue

                visited.add(current)
                component.add(current)

                for neighbor in graph.neighbors(current):
                    if neighbor not in visited:
                        stack.append(neighbor)

            components.append(component)

    return components


def strongly_connected_components(graph: Graph) -> list[set[Any]]:
    """
    Find strongly connected components in a directed graph using Tarjan's algorithm.

    Args:
        graph: Input directed graph.

    Returns:
        List of sets, each representing a strongly connected component.
    """
    index_counter = [0]
    stack: list[Any] = []
    lowlinks: dict[Any, int] = {}
    index: dict[Any, int] = {}
    on_stack: dict[Any, bool] = {node: False for node in graph.nodes()}
    sccs: list[set[Any]] = []

    def strongconnect(node: Any) -> None:
        """Tarjan's algorithm helper."""
        index[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True

        for neighbor in graph.neighbors(node):
            if neighbor not in index:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif on_stack[neighbor]:
                lowlinks[node] = min(lowlinks[node], index[neighbor])

        if lowlinks[node] == index[node]:
            component = set()
            while True:
                w = stack.pop()
                on_stack[w] = False
                component.add(w)
                if w == node:
                    break
            sccs.append(component)

    for node in graph.nodes():
        if node not in index:
            strongconnect(node)

    return sccs


def eulerian_path_exists(graph: Graph) -> bool:
    """
    Check if an Eulerian path or circuit exists.

    For undirected: all vertices have even degree (circuit) or
    exactly 2 vertices have odd degree (path).
    For directed: all vertices have equal in/out degree (circuit) or
    one vertex has out-degree = in-degree + 1 and one has in-degree = out-degree + 1.

    Args:
        graph: Input graph.

    Returns:
        True if Eulerian path or circuit exists.
    """
    if graph.graph_type.value == "directed":
        in_degrees = {}
        out_degrees = {}

        for node in graph.nodes():
            in_degrees[node] = graph.in_degree(node)
            out_degrees[node] = graph.out_degree(node)

        # Check for Eulerian circuit
        circuit = all(in_degrees[n] == out_degrees[n] for n in graph.nodes())
        if circuit:
            return True

        # Check for Eulerian path
        unbalanced = []
        for node in graph.nodes():
            diff = out_degrees[node] - in_degrees[node]
            if diff != 0:
                unbalanced.append((node, diff))

        if len(unbalanced) == 2:
            return unbalanced[0][1] == 1 and unbalanced[1][1] == -1

        return False
    else:
        # Undirected
        odd_degree_nodes = [n for n in graph.nodes() if graph.degree(n) % 2 == 1]

        # Eulerian circuit: all even degrees
        if len(odd_degree_nodes) == 0:
            return True

        # Eulerian path: exactly 2 odd degree nodes
        return len(odd_degree_nodes) == 2


def hamiltonian_path_backtrack(graph: Graph, source: Any | None = None, max_paths: int = 1) -> list[list[Any]]:
    """
    Find Hamiltonian paths using backtracking.

    Explores all possible paths visiting each node exactly once.
    Exponential time complexity - suitable for small graphs only.

    Args:
        graph: Input graph.
        source: Starting node (if None, try from all nodes).
        max_paths: Maximum number of paths to find.

    Returns:
        List of Hamiltonian paths found.
    """
    paths = []
    nodes = graph.nodes()
    n = len(nodes)

    def backtrack(current: Any, path: list[Any], visited: set[Any]) -> None:
        """Backtracking helper."""
        if len(paths) >= max_paths:
            return

        if len(path) == n:
            paths.append(path.copy())
            return

        for neighbor in graph.neighbors(current):
            if neighbor not in visited:
                visited.add(neighbor)
                path.append(neighbor)
                backtrack(neighbor, path, visited)
                path.pop()
                visited.remove(neighbor)

    if source is not None:
        if source not in graph:
            raise KeyError(f"Source node {source} not found")
        visited = {source}
        backtrack(source, [source], visited)
    else:
        for start_node in nodes:
            if len(paths) >= max_paths:
                break
            visited = {start_node}
            backtrack(start_node, [start_node], visited)

    return paths
