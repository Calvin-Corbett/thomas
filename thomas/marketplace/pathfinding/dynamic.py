"""
Dynamic pathfinding algorithms for replanning and moving targets.

This module implements D* Lite, Lifelong Planning A*, and real-time search
for handling dynamic obstacles and moving targets.
"""

import heapq
import time
from dataclasses import dataclass

from thomas.marketplace.pathfinding._types import Graph, Path, PathResult


@dataclass
class DStarNode:
    """Node state for D* Lite."""

    rhs: float = float("inf")
    g: float = float("inf")


class DStarLite:
    """
    D* Lite algorithm for fast replanning with dynamic obstacles.

    Incrementally repairs paths when the environment changes.
    """

    def __init__(
        self,
        graph: Graph,
        start_id: int | str,
        goal_id: int | str,
    ) -> None:
        """
        Initialize D* Lite pathfinder.

        Args:
            graph: The graph to search.
            start_id: Start node ID.
            goal_id: Goal node ID.
        """
        self.graph = graph
        self.start_id = start_id
        self.goal_id = goal_id
        self.current = start_id

        self.g: dict[int | str, float] = {}
        self.rhs: dict[int | str, float] = {}
        self.km = 0.0
        self.open_set: list[tuple[tuple[float, float], int | str]] = []
        self.last_start = start_id

        self._initialize()

    def _initialize(self) -> None:
        """Initialize the search."""
        for node_id in self.graph.nodes:
            self.g[node_id] = float("inf")
            self.rhs[node_id] = float("inf")

        self.rhs[self.goal_id] = 0.0
        self._update_vertex(self.goal_id)

    def _key(self, node_id: int | str) -> tuple[float, float]:
        """Calculate key for node."""
        g_val = self.g.get(node_id, float("inf"))
        rhs_val = self.rhs.get(node_id, float("inf"))
        heuristic = self._heuristic(node_id, self.start_id)
        k1 = min(g_val, rhs_val) + heuristic
        k2 = min(g_val, rhs_val)
        return (k1, k2)

    def _heuristic(
        self,
        from_id: int | str,
        to_id: int | str,
    ) -> float:
        """Calculate heuristic distance."""
        if from_id not in self.graph.nodes or to_id not in self.graph.nodes:
            return 0.0
        from_node = self.graph.nodes[from_id]
        to_node = self.graph.nodes[to_id]
        return from_node.distance_to(to_node)

    def _update_vertex(self, node_id: int | str) -> None:
        """Update vertex in open set."""
        if node_id != self.goal_id:
            min_rhs = float("inf")
            for neighbor_id, weight in self.graph.edges.get(node_id, []):
                rhs_candidate = self.g.get(neighbor_id, float("inf")) + weight
                min_rhs = min(min_rhs, rhs_candidate)
            self.rhs[node_id] = min_rhs

        g_val = self.g.get(node_id, float("inf"))
        rhs_val = self.rhs.get(node_id, float("inf"))

        if g_val != rhs_val:
            key = self._key(node_id)
            heapq.heappush(self.open_set, (key, node_id))
        else:
            self.open_set = [(k, nid) for k, nid in self.open_set if nid != node_id]
            heapq.heapify(self.open_set)

    def compute_shortest_path(self) -> bool:
        """Compute shortest path. Returns True if path found."""
        while True:
            if not self.open_set:
                return False

            key_min = self._key(self.start_id)
            if self.open_set[0][0] > key_min or self.rhs.get(self.start_id, float("inf")) > self.g.get(
                self.start_id,
                float("inf"),
            ):
                pass
            else:
                break

            (k_old, node_id) = heapq.heappop(self.open_set)
            k_new = self._key(node_id)

            if k_old > k_new:
                heapq.heappush(self.open_set, (k_new, node_id))
            else:
                g_val = self.g.get(node_id, float("inf"))
                rhs_val = self.rhs.get(node_id, float("inf"))

                if g_val > rhs_val:
                    self.g[node_id] = rhs_val
                    for neighbor_id in self._get_predecessors(node_id):
                        self._update_vertex(neighbor_id)
                else:
                    self.g[node_id] = float("inf")
                    self._update_vertex(node_id)
                    for neighbor_id in self._get_predecessors(node_id):
                        self._update_vertex(neighbor_id)

        return True

    def _get_predecessors(self, node_id: int | str) -> list[int | str]:
        """Get all nodes that have edges to this node."""
        predecessors = []
        for from_id, neighbors in self.graph.edges.items():
            for to_id, _ in neighbors:
                if to_id == node_id:
                    predecessors.append(from_id)
        return predecessors

    def handle_edge_cost_change(
        self,
        from_id: int | str,
        to_id: int | str,
    ) -> None:
        """
        Handle edge cost change (or removal).

        Args:
            from_id: Source node ID.
            to_id: Destination node ID.
        """
        self.km += self._heuristic(self.last_start, self.start_id)
        self.last_start = self.start_id

        self._update_vertex(from_id)
        self._update_vertex(to_id)

    def find_path(self) -> PathResult:
        """
        Find path from start to goal.

        Returns:
            PathResult containing the path.
        """
        start_time = time.time()

        if not self.compute_shortest_path():
            return PathResult(found=False)

        if self.g.get(self.start_id, float("inf")) == float("inf"):
            return PathResult(found=False)

        path_nodes: list[int | str] = [self.start_id]
        current = self.start_id

        while current != self.goal_id:
            best_neighbor = None
            best_cost = float("inf")

            for neighbor_id, weight in self.graph.edges.get(current, []):
                cost = self.g.get(neighbor_id, float("inf")) + weight
                if cost < best_cost:
                    best_cost = cost
                    best_neighbor = neighbor_id

            if best_neighbor is None:
                return PathResult(found=False)

            path_nodes.append(best_neighbor)
            current = best_neighbor

        path = Path(tuple(path_nodes), self.g.get(self.start_id, float("inf")))
        return PathResult(
            found=True,
            path=path,
            cost=path.cost,
            execution_time=time.time() - start_time,
        )


class LifetimePlanningAStar:
    """
    Lifelong Planning A* for continual replanning with dynamic environments.

    Maintains consistency between search iterations for efficiency.
    """

    def __init__(
        self,
        graph: Graph,
        start_id: int | str,
        goal_id: int | str,
    ) -> None:
        """
        Initialize LPA*.

        Args:
            graph: The graph to search.
            start_id: Start node ID.
            goal_id: Goal node ID.
        """
        self.graph = graph
        self.start_id = start_id
        self.goal_id = goal_id

        self.g: dict[int | str, float] = {}
        self.rhs: dict[int | str, float] = {}
        self.open_set: list[tuple[tuple[float, float], int | str]] = []

        self._initialize()

    def _initialize(self) -> None:
        """Initialize search structures."""
        for node_id in self.graph.nodes:
            self.g[node_id] = float("inf")
            self.rhs[node_id] = float("inf")

        self.rhs[self.start_id] = 0.0
        self._insert(self.start_id)

    def _key(self, node_id: int | str) -> tuple[float, float]:
        """Calculate key for node."""
        g_val = self.g.get(node_id, float("inf"))
        rhs_val = self.rhs.get(node_id, float("inf"))
        heuristic = self._heuristic(node_id, self.goal_id)
        k1 = min(g_val, rhs_val) + heuristic
        k2 = min(g_val, rhs_val)
        return (k1, k2)

    def _heuristic(
        self,
        from_id: int | str,
        to_id: int | str,
    ) -> float:
        """Calculate heuristic."""
        if from_id not in self.graph.nodes or to_id not in self.graph.nodes:
            return 0.0
        from_node = self.graph.nodes[from_id]
        to_node = self.graph.nodes[to_id]
        return from_node.distance_to(to_node)

    def _insert(self, node_id: int | str) -> None:
        """Insert node into open set."""
        key = self._key(node_id)
        heapq.heappush(self.open_set, (key, node_id))

    def _update_vertex(self, node_id: int | str) -> None:
        """Update vertex."""
        if node_id != self.start_id:
            min_rhs = float("inf")
            for neighbor_id, weight in self.graph.edges.get(node_id, []):
                rhs_candidate = self.g.get(neighbor_id, float("inf")) + weight
                min_rhs = min(min_rhs, rhs_candidate)
            self.rhs[node_id] = min_rhs

        if self.g.get(node_id, float("inf")) != self.rhs.get(node_id, float("inf")):
            self._insert(node_id)

    def compute_path(self) -> bool:
        """Compute path. Returns True if goal reachable."""
        while self.open_set and (
            self._key(self.goal_id) > (self.open_set[0][0] if self.open_set else (float("inf"), float("inf")))
            or self.rhs.get(self.goal_id, float("inf")) > self.g.get(self.goal_id, float("inf"))
        ):
            _, node_id = heapq.heappop(self.open_set)

            if self.g.get(node_id, float("inf")) > self.rhs.get(node_id, float("inf")):
                self.g[node_id] = self.rhs.get(node_id, float("inf"))
                for successor_id in self._get_successors(node_id):
                    self._update_vertex(successor_id)
            else:
                self.g[node_id] = float("inf")
                self._update_vertex(node_id)
                for successor_id in self._get_successors(node_id):
                    self._update_vertex(successor_id)

        return self.rhs.get(self.goal_id, float("inf")) != float("inf")

    def _get_successors(self, node_id: int | str) -> list[int | str]:
        """Get successor nodes."""
        successors = []
        for neighbor_id, _ in self.graph.edges.get(node_id, []):
            successors.append(neighbor_id)
        return successors

    def handle_cost_change(
        self,
        from_id: int | str,
        to_id: int | str,
    ) -> None:
        """
        Handle edge cost change.

        Args:
            from_id: Source node ID.
            to_id: Destination node ID.
        """
        self._update_vertex(from_id)

    def find_path(self) -> PathResult:
        """Find path."""
        start_time = time.time()

        if not self.compute_path():
            return PathResult(found=False)

        if self.rhs.get(self.goal_id, float("inf")) == float("inf"):
            return PathResult(found=False)

        path_nodes: list[int | str] = [self.goal_id]
        current = self.goal_id

        while current != self.start_id:
            best_predecessor = None
            best_cost = float("inf")

            for from_id, neighbors in self.graph.edges.items():
                for to_id, weight in neighbors:
                    if to_id == current:
                        cost = self.g.get(from_id, float("inf")) + weight
                        if cost < best_cost:
                            best_cost = cost
                            best_predecessor = from_id

            if best_predecessor is None:
                return PathResult(found=False)

            path_nodes.append(best_predecessor)
            current = best_predecessor

        path_nodes.reverse()
        path = Path(tuple(path_nodes), self.g.get(self.goal_id, float("inf")))

        return PathResult(
            found=True,
            path=path,
            cost=path.cost,
            execution_time=time.time() - start_time,
        )


class DynamicPathfinder:
    """
    General dynamic pathfinder handling obstacles and moving targets.

    Adapts paths in real-time as the environment changes.
    """

    def __init__(
        self,
        graph: Graph,
        start_id: int | str,
        goal_id: int | str,
    ) -> None:
        """
        Initialize dynamic pathfinder.

        Args:
            graph: The graph to search.
            start_id: Start node ID.
            goal_id: Goal node ID.
        """
        self.graph = graph
        self.start_id = start_id
        self.goal_id = goal_id
        self.blocked_edges: set[tuple[int | str, int | str]] = set()
        self.last_path: list[int | str] | None = None
        self.replanning_count = 0

    def block_edge(
        self,
        from_id: int | str,
        to_id: int | str,
    ) -> None:
        """
        Block an edge in the graph.

        Args:
            from_id: Source node ID.
            to_id: Destination node ID.
        """
        self.blocked_edges.add((from_id, to_id))

    def unblock_edge(
        self,
        from_id: int | str,
        to_id: int | str,
    ) -> None:
        """
        Unblock a previously blocked edge.

        Args:
            from_id: Source node ID.
            to_id: Destination node ID.
        """
        self.blocked_edges.discard((from_id, to_id))

    def find_path(self) -> PathResult:
        """
        Find path avoiding blocked edges.

        Returns:
            PathResult containing the path.
        """
        start_time = time.time()
        nodes_expanded = 0

        def get_neighbors(
            node_id: int | str,
        ) -> list[tuple[int | str, float]]:
            neighbors = []
            for to_id, weight in self.graph.edges.get(node_id, []):
                if (node_id, to_id) not in self.blocked_edges:
                    neighbors.append((to_id, weight))
            return neighbors

        open_set: list[tuple[float, int | str]] = []
        g_score: dict[int | str, float] = {node_id: float("inf") for node_id in self.graph.nodes}
        g_score[self.start_id] = 0.0
        parents: dict[int | str, int | str | None] = {node_id: None for node_id in self.graph.nodes}

        def heuristic(node_id: int | str) -> float:
            if node_id not in self.graph.nodes or self.goal_id not in self.graph.nodes:
                return 0.0
            return self.graph.nodes[node_id].distance_to(self.graph.nodes[self.goal_id])

        heapq.heappush(open_set, (heuristic(self.start_id), self.start_id))
        visited: set[int | str] = set()

        while open_set:
            _, current_id = heapq.heappop(open_set)

            if current_id in visited:
                continue

            visited.add(current_id)
            nodes_expanded += 1

            if current_id == self.goal_id:
                path_nodes: list[int | str] = []
                node = current_id
                while node is not None:
                    path_nodes.append(node)
                    node = parents[node]
                path_nodes.reverse()
                self.last_path = path_nodes
                cost = g_score[self.goal_id]
                self.replanning_count += 1
                path = Path(tuple(path_nodes), cost)
                return PathResult(
                    found=True,
                    path=path,
                    cost=cost,
                    nodes_expanded=nodes_expanded,
                    execution_time=time.time() - start_time,
                )

            for neighbor_id, weight in get_neighbors(current_id):
                if neighbor_id in visited:
                    continue

                new_g = g_score[current_id] + weight
                if new_g < g_score[neighbor_id]:
                    g_score[neighbor_id] = new_g
                    parents[neighbor_id] = current_id
                    f = new_g + heuristic(neighbor_id)
                    heapq.heappush(open_set, (f, neighbor_id))

        return PathResult(
            found=False,
            nodes_expanded=nodes_expanded,
            execution_time=time.time() - start_time,
        )
