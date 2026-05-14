"""Graph traversal algorithms: BFS, DFS, shortest path, and more."""

import heapq
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING

from thomas.marketplace.graphdb._exceptions import NodeNotFoundError
from thomas.marketplace.graphdb._types import Path, TraversalDirection

if TYPE_CHECKING:
    from thomas.marketplace.graphdb.storage import GraphStorage


class GraphTraversal:
    """Provides traversal algorithms for a graph storage engine."""

    def __init__(self, storage: "GraphStorage") -> None:
        """Initialize traversal engine.

        Args:
            storage: Graph storage instance
        """
        self.storage = storage

    def bfs(
        self,
        start_node_id: str,
        max_depth: int | None = None,
        direction: TraversalDirection = TraversalDirection.BOTH,
        edge_type_filter: str | None = None,
    ) -> dict[str, int]:
        """Breadth-first search from a starting node.

        Args:
            start_node_id: Starting node ID
            max_depth: Maximum depth to traverse (None = unlimited)
            direction: Direction of traversal
            edge_type_filter: Filter by edge type

        Returns:
            Dictionary mapping node IDs to their distance from start

        Raises:
            NodeNotFoundError: If start node doesn't exist
        """
        if start_node_id not in self.storage.node_store:
            raise NodeNotFoundError(start_node_id)

        distances: dict[str, int] = {start_node_id: 0}
        queue: deque[str] = deque([start_node_id])

        while queue:
            current = queue.popleft()
            current_depth = distances[current]

            if max_depth is not None and current_depth >= max_depth:
                continue

            neighbors = self.storage.get_adjacent_nodes(
                current, direction=direction.value, edge_type_filter=edge_type_filter
            )

            for neighbor in neighbors:
                if neighbor not in distances:
                    distances[neighbor] = current_depth + 1
                    queue.append(neighbor)

        return distances

    def dfs(
        self,
        start_node_id: str,
        max_depth: int | None = None,
        direction: TraversalDirection = TraversalDirection.BOTH,
        edge_type_filter: str | None = None,
    ) -> dict[str, int]:
        """Depth-first search from a starting node.

        Args:
            start_node_id: Starting node ID
            max_depth: Maximum depth to traverse
            direction: Direction of traversal
            edge_type_filter: Filter by edge type

        Returns:
            Dictionary mapping node IDs to their depth from start

        Raises:
            NodeNotFoundError: If start node doesn't exist
        """
        if start_node_id not in self.storage.node_store:
            raise NodeNotFoundError(start_node_id)

        depths: dict[str, int] = {}
        stack: list[tuple[str, int]] = [(start_node_id, 0)]

        while stack:
            current, depth = stack.pop()

            if current in depths:
                continue

            depths[current] = depth

            if max_depth is not None and depth >= max_depth:
                continue

            neighbors = self.storage.get_adjacent_nodes(
                current, direction=direction.value, edge_type_filter=edge_type_filter
            )

            for neighbor in reversed(neighbors):
                if neighbor not in depths:
                    stack.append((neighbor, depth + 1))

        return depths

    def dijkstra(
        self,
        start_node_id: str,
        end_node_id: str | None = None,
        weight_fn: Callable[[str], float] | None = None,
        direction: TraversalDirection = TraversalDirection.BOTH,
    ) -> tuple[dict[str, float], dict[str, str | None]]:
        """Dijkstra's shortest path algorithm.

        Args:
            start_node_id: Starting node ID
            end_node_id: Optional target node (for early termination)
            weight_fn: Function to compute edge weight (default: 1.0 for all edges)
            direction: Direction of traversal

        Returns:
            Tuple of (distances dict, predecessors dict)

        Raises:
            NodeNotFoundError: If start node doesn't exist
        """
        if start_node_id not in self.storage.node_store:
            raise NodeNotFoundError(start_node_id)

        if weight_fn is None:
            weight_fn = lambda _: 1.0

        distances: dict[str, float] = {start_node_id: 0.0}
        predecessors: dict[str, str | None] = {start_node_id: None}
        visited: set[str] = set()
        heap: list[tuple[float, str]] = [(0.0, start_node_id)]

        while heap:
            current_dist, current = heapq.heappop(heap)

            if current in visited:
                continue

            visited.add(current)

            if end_node_id and current == end_node_id:
                break

            neighbors = self.storage.get_adjacent_nodes(current, direction=direction.value)

            for neighbor in neighbors:
                if neighbor not in visited:
                    edge_weight = weight_fn(neighbor)
                    new_dist = current_dist + edge_weight

                    if neighbor not in distances or new_dist < distances[neighbor]:
                        distances[neighbor] = new_dist
                        predecessors[neighbor] = current
                        heapq.heappush(heap, (new_dist, neighbor))

        return distances, predecessors

    def shortest_path(
        self,
        start_node_id: str,
        end_node_id: str,
        weight_fn: Callable[[str], float] | None = None,
        direction: TraversalDirection = TraversalDirection.BOTH,
    ) -> Path | None:
        """Find shortest path between two nodes.

        Args:
            start_node_id: Starting node ID
            end_node_id: Target node ID
            weight_fn: Edge weight function
            direction: Direction of traversal

        Returns:
            Path object or None if no path exists

        Raises:
            NodeNotFoundError: If start or end node doesn't exist
        """
        if start_node_id not in self.storage.node_store:
            raise NodeNotFoundError(start_node_id)
        if end_node_id not in self.storage.node_store:
            raise NodeNotFoundError(end_node_id)

        distances, predecessors = self.dijkstra(start_node_id, end_node_id, weight_fn, direction)

        if end_node_id not in distances:
            return None

        # Reconstruct path
        path = Path()
        current = end_node_id

        while current is not None:
            path.nodes.insert(0, current)
            current = predecessors.get(current)

        return path

    def all_shortest_paths(
        self,
        start_node_id: str,
        end_node_id: str,
        direction: TraversalDirection = TraversalDirection.BOTH,
    ) -> list[Path]:
        """Find all shortest paths between two nodes.

        Args:
            start_node_id: Starting node ID
            end_node_id: Target node ID
            direction: Direction of traversal

        Returns:
            List of Path objects

        Raises:
            NodeNotFoundError: If start or end node doesn't exist
        """
        if start_node_id not in self.storage.node_store:
            raise NodeNotFoundError(start_node_id)
        if end_node_id not in self.storage.node_store:
            raise NodeNotFoundError(end_node_id)

        distances, _ = self.dijkstra(start_node_id, None, None, direction)

        if end_node_id not in distances:
            return []

        distances[end_node_id]
        paths: list[Path] = []

        def dfs_all_paths(current: str, path: list[str], current_dist: float) -> None:
            """Recursive DFS to find all shortest paths."""
            if current == end_node_id:
                paths.append(Path(nodes=path.copy()))
                return

            neighbors = self.storage.get_adjacent_nodes(current, direction=direction.value)

            for neighbor in neighbors:
                if neighbor in distances and distances[neighbor] == current_dist + 1:
                    if neighbor not in path:  # Avoid cycles
                        path.append(neighbor)
                        dfs_all_paths(neighbor, path, current_dist + 1)
                        path.pop()

        dfs_all_paths(start_node_id, [start_node_id], 0.0)
        return paths

    def variable_length_path(
        self,
        start_node_id: str,
        min_length: int = 1,
        max_length: int = 10,
        direction: TraversalDirection = TraversalDirection.BOTH,
        edge_type_filter: str | None = None,
    ) -> list[Path]:
        """Find all paths of variable length between start and reachable nodes.

        Args:
            start_node_id: Starting node ID
            min_length: Minimum path length
            max_length: Maximum path length
            direction: Direction of traversal
            edge_type_filter: Filter by edge type

        Returns:
            List of Path objects

        Raises:
            NodeNotFoundError: If start node doesn't exist
        """
        if start_node_id not in self.storage.node_store:
            raise NodeNotFoundError(start_node_id)

        paths: list[Path] = []

        def dfs_paths(current: str, path: list[str], depth: int, visited: set[str]) -> None:
            """Recursive DFS to find variable-length paths."""
            if depth >= min_length:
                paths.append(Path(nodes=path.copy()))

            if depth < max_length:
                neighbors = self.storage.get_adjacent_nodes(
                    current, direction=direction.value, edge_type_filter=edge_type_filter
                )

                for neighbor in neighbors:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        path.append(neighbor)
                        dfs_paths(neighbor, path, depth + 1, visited)
                        path.pop()
                        visited.discard(neighbor)

        visited: set[str] = {start_node_id}
        dfs_paths(start_node_id, [start_node_id], 0, visited)

        return paths

    def bidirectional_search(
        self,
        start_node_id: str,
        end_node_id: str,
        direction: TraversalDirection = TraversalDirection.BOTH,
    ) -> Path | None:
        """Bidirectional BFS for finding shortest path.

        Args:
            start_node_id: Starting node ID
            end_node_id: Target node ID
            direction: Direction of traversal

        Returns:
            Path object or None if no path exists

        Raises:
            NodeNotFoundError: If start or end node doesn't exist
        """
        if start_node_id not in self.storage.node_store:
            raise NodeNotFoundError(start_node_id)
        if end_node_id not in self.storage.node_store:
            raise NodeNotFoundError(end_node_id)

        if start_node_id == end_node_id:
            return Path(nodes=[start_node_id])

        # BFS from both ends
        forward_queue: deque[str] = deque([start_node_id])
        backward_queue: deque[str] = deque([end_node_id])
        forward_visited: dict[str, str] = {start_node_id: None}
        backward_visited: dict[str, str] = {end_node_id: None}

        while forward_queue and backward_queue:
            # Expand from smaller frontier
            if len(forward_queue) <= len(backward_queue):
                current = forward_queue.popleft()
                neighbors = self.storage.get_adjacent_nodes(current, direction=direction.value)

                for neighbor in neighbors:
                    if neighbor in backward_visited:
                        # Path found
                        forward_path = []
                        node: str | None = neighbor
                        while node is not None:
                            forward_path.insert(0, node)
                            node = backward_visited[node]

                        backward_path = []
                        node = current
                        while node is not None:
                            backward_path.append(node)
                            node = forward_visited[node]

                        combined_path = backward_path + forward_path
                        return Path(nodes=combined_path)

                    if neighbor not in forward_visited:
                        forward_visited[neighbor] = current
                        forward_queue.append(neighbor)
            else:
                current = backward_queue.popleft()
                neighbors = self.storage.get_adjacent_nodes(current, direction=direction.value)

                for neighbor in neighbors:
                    if neighbor in forward_visited:
                        # Path found
                        forward_path = []
                        node: str | None = current
                        while node is not None:
                            forward_path.insert(0, node)
                            node = forward_visited[node]

                        backward_path = []
                        node: str | None = neighbor
                        while node is not None:
                            backward_path.append(node)
                            node = backward_visited[node]

                        combined_path = forward_path + backward_path
                        return Path(nodes=combined_path)

                    if neighbor not in backward_visited:
                        backward_visited[neighbor] = current
                        backward_queue.append(neighbor)

        return None

    def connected_component_nodes(self, start_node_id: str) -> set[str]:
        """Find all nodes in the connected component containing start node.

        Args:
            start_node_id: Starting node ID

        Returns:
            Set of node IDs in the connected component

        Raises:
            NodeNotFoundError: If start node doesn't exist
        """
        if start_node_id not in self.storage.node_store:
            raise NodeNotFoundError(start_node_id)

        visited: set[str] = set()
        queue: deque[str] = deque([start_node_id])

        while queue:
            current = queue.popleft()
            if current in visited:
                continue

            visited.add(current)
            neighbors = self.storage.get_adjacent_nodes(current, direction="both")

            for neighbor in neighbors:
                if neighbor not in visited:
                    queue.append(neighbor)

        return visited
