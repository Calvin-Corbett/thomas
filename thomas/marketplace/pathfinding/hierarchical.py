"""
Hierarchical pathfinding algorithms.

This module implements Hierarchical Pathfinding A* (HPA*) with abstract graph layers
and cluster-based decomposition for efficient pathfinding on large graphs.
"""

import time
from collections import defaultdict, deque

from thomas.marketplace.pathfinding._types import Graph, Node, Path, PathResult
from thomas.marketplace.pathfinding.classical import astar


@staticmethod
def _cluster_id_from_coords(x: int, y: int, cluster_size: int) -> tuple[int, int]:
    """Convert coordinates to cluster ID."""
    return (x // cluster_size, y // cluster_size)


class HierarchicalPathfinder:
    """
    Hierarchical Pathfinding A* (HPA*) for efficient pathfinding on large grids.

    Decomposes space into clusters and builds a hierarchy of abstract graphs.
    """

    def __init__(
        self,
        graph: Graph,
        cluster_size: int = 10,
        num_levels: int = 2,
    ) -> None:
        """
        Initialize hierarchical pathfinder.

        Args:
            graph: The base graph to partition.
            cluster_size: Size of clusters in the hierarchy.
            num_levels: Number of hierarchy levels.
        """
        self.base_graph = graph
        self.cluster_size = cluster_size
        self.num_levels = num_levels
        self.clusters: dict[tuple[int, int], set[int | str]] = defaultdict(set)
        self.abstract_graphs: list[Graph] = [graph]
        self.inter_cluster_edges: dict[tuple[int, int], list[tuple[tuple[int, int], float]]] = defaultdict(list)

        self._build_hierarchy()

    def _build_hierarchy(self) -> None:
        """Build the hierarchical structure."""
        self._partition_into_clusters()
        self._compute_inter_cluster_edges()

        for level in range(1, self.num_levels):
            self._build_abstract_level(level)

    def _partition_into_clusters(self) -> None:
        """Partition base graph nodes into clusters."""
        for node_id in self.base_graph.nodes:
            node = self.base_graph.nodes[node_id]
            cluster = _cluster_id_from_coords(
                int(node.x),
                int(node.y),
                self.cluster_size,
            )
            self.clusters[cluster].add(node_id)

    def _compute_inter_cluster_edges(self) -> None:
        """Compute edges between clusters."""
        for cluster_id, node_ids in self.clusters.items():
            for node_id in node_ids:
                for neighbor_id, weight in self.base_graph.edges.get(node_id, []):
                    neighbor_cluster = _cluster_id_from_coords(
                        int(self.base_graph.nodes[neighbor_id].x),
                        int(self.base_graph.nodes[neighbor_id].y),
                        self.cluster_size,
                    )

                    if neighbor_cluster != cluster_id:
                        found = False
                        for edge_cluster, edge_weight in self.inter_cluster_edges[cluster_id]:
                            if edge_cluster == neighbor_cluster:
                                found = True
                                break

                        if not found:
                            self.inter_cluster_edges[cluster_id].append((neighbor_cluster, weight))

    def _build_abstract_level(self, level: int) -> None:
        """Build abstract graph at given level."""
        abstract_graph = Graph(directed=self.base_graph.directed)

        cluster_nodes = {}
        for cluster_id in self.clusters:
            node_id = f"cluster_l{level}_{cluster_id[0]}_{cluster_id[1]}"
            node = Node(
                id=node_id,
                x=float(cluster_id[0] * self.cluster_size),
                y=float(cluster_id[1] * self.cluster_size),
            )
            abstract_graph.add_node(node)
            cluster_nodes[cluster_id] = node_id

        for from_cluster, neighbors in self.inter_cluster_edges.items():
            from_id = cluster_nodes.get(from_cluster)
            if from_id is None:
                continue

            for to_cluster, weight in neighbors:
                to_id = cluster_nodes.get(to_cluster)
                if to_id is not None:
                    abstract_graph.add_edge(from_id, to_id, weight)

        self.abstract_graphs.append(abstract_graph)

    def find_path(
        self,
        start_id: int | str,
        goal_id: int | str,
    ) -> PathResult:
        """
        Find path using hierarchical pathfinding.

        Args:
            start_id: Start node ID.
            goal_id: Goal node ID.

        Returns:
            PathResult containing the path and statistics.
        """
        start_time = time.time()

        start_cluster = _cluster_id_from_coords(
            int(self.base_graph.nodes[start_id].x),
            int(self.base_graph.nodes[start_id].y),
            self.cluster_size,
        )
        goal_cluster = _cluster_id_from_coords(
            int(self.base_graph.nodes[goal_id].x),
            int(self.base_graph.nodes[goal_id].y),
            self.cluster_size,
        )

        if start_cluster == goal_cluster:
            result = astar(self.base_graph, start_id, goal_id)
            result.execution_time = time.time() - start_time
            return result

        abstract_path = self._find_abstract_path(start_cluster, goal_cluster)

        if not abstract_path:
            return PathResult(
                found=False,
                execution_time=time.time() - start_time,
            )

        concrete_path = self._refine_to_concrete(
            start_id,
            goal_id,
            abstract_path,
        )

        if not concrete_path:
            return PathResult(
                found=False,
                execution_time=time.time() - start_time,
            )

        cost = sum(
            self.base_graph.nodes[concrete_path[i]].distance_to(self.base_graph.nodes[concrete_path[i - 1]])
            for i in range(1, len(concrete_path))
        )

        path = Path(tuple(concrete_path), cost)
        return PathResult(
            found=True,
            path=path,
            cost=cost,
            execution_time=time.time() - start_time,
        )

    def _find_abstract_path(
        self,
        start_cluster: tuple[int, int],
        goal_cluster: tuple[int, int],
    ) -> list[tuple[int, int]]:
        """Find path through abstract cluster graph."""
        if start_cluster == goal_cluster:
            return [start_cluster]

        queue = deque([(start_cluster, [start_cluster])])
        visited = {start_cluster}

        while queue:
            cluster_id, path = queue.popleft()

            if cluster_id == goal_cluster:
                return path

            for neighbor_cluster, _ in self.inter_cluster_edges.get(cluster_id, []):
                if neighbor_cluster not in visited:
                    visited.add(neighbor_cluster)
                    queue.append((neighbor_cluster, path + [neighbor_cluster]))

        return []

    def _refine_to_concrete(
        self,
        start_id: int | str,
        goal_id: int | str,
        abstract_path: list[tuple[int, int]],
    ) -> list[int | str]:
        """Refine abstract path to concrete path."""
        concrete_path: list[int | str] = [start_id]
        current_id = start_id

        for i in range(1, len(abstract_path)):
            current_cluster = abstract_path[i - 1]
            next_cluster = abstract_path[i]

            candidates = []
            for node_id in self.clusters[current_cluster]:
                for neighbor_id, _ in self.base_graph.edges.get(node_id, []):
                    if neighbor_id in self.clusters[next_cluster]:
                        candidates.append((node_id, neighbor_id, current_id, neighbor_id))

            if candidates:
                best_path = None
                best_cost = float("inf")

                for from_node, to_node, _, _ in candidates:
                    result = astar(
                        self.base_graph,
                        current_id,
                        to_node,
                    )
                    if result.found and result.cost < best_cost:
                        best_cost = result.cost
                        best_path = list(result.path.nodes)

                if best_path:
                    concrete_path.extend(best_path[1:])
                    current_id = best_path[-1]

        if current_id != goal_id:
            result = astar(self.base_graph, current_id, goal_id)
            if result.found:
                concrete_path.extend(list(result.path.nodes)[1:])
                return concrete_path

        return concrete_path if concrete_path[-1] == goal_id else []

    def update_obstacle(self, node_id: int | str, blocked: bool) -> None:
        """
        Update obstacle information and refresh hierarchy if needed.

        Args:
            node_id: Node to update.
            blocked: Whether the node is now blocked.
        """
        if blocked:
            node = self.base_graph.nodes.get(node_id)
            if node:
                cluster_id = _cluster_id_from_coords(
                    int(node.x),
                    int(node.y),
                    self.cluster_size,
                )
                if node_id in self.clusters[cluster_id]:
                    self.clusters[cluster_id].discard(node_id)


def build_hpa_star(
    graph: Graph,
    cluster_size: int = 10,
) -> HierarchicalPathfinder:
    """
    Build a Hierarchical Pathfinding A* (HPA*) structure.

    Args:
        graph: The graph to partition.
        cluster_size: Size of clusters.

    Returns:
        Initialized HierarchicalPathfinder.
    """
    return HierarchicalPathfinder(graph, cluster_size=cluster_size, num_levels=2)
