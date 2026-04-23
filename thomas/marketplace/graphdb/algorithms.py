"""Graph algorithms: PageRank, community detection, centrality, clustering, etc."""

from collections import defaultdict, deque
from typing import TYPE_CHECKING

from thomas.marketplace.graphdb._exceptions import NodeNotFoundError

if TYPE_CHECKING:
    from thomas.marketplace.graphdb.storage import GraphStorage


class GraphAlgorithms:
    """Provides algorithms for analyzing graph properties."""

    def __init__(self, storage: "GraphStorage") -> None:
        """Initialize algorithms engine.

        Args:
            storage: Graph storage instance
        """
        self.storage = storage

    def pagerank(self, iterations: int = 20, damping_factor: float = 0.85, tolerance: float = 1e-6) -> dict[str, float]:
        """Compute PageRank for all nodes.

        Args:
            iterations: Number of iterations to run
            damping_factor: Damping factor (0.85 is standard)
            tolerance: Convergence tolerance

        Returns:
            Dictionary mapping node IDs to PageRank scores
        """
        nodes = list(self.storage.node_store.keys())
        if not nodes:
            return {}

        # Initialize ranks
        rank = {node_id: 1.0 / len(nodes) for node_id in nodes}
        n = len(nodes)
        converged = False

        for iteration in range(iterations):
            new_rank = {}
            old_rank = rank.copy()

            for node_id in nodes:
                # Dangling node contribution
                inbound = self.storage.get_inbound_edges(node_id)
                rank_sum = 0.0

                for edge in inbound:
                    source = edge.source
                    outbound_count = len(self.storage.get_outbound_edges(source))
                    if outbound_count > 0:
                        rank_sum += old_rank[source] / outbound_count

                new_rank[node_id] = (1 - damping_factor) / n + damping_factor * rank_sum

            rank = new_rank

            # Check convergence
            diff = sum(abs(rank[node] - old_rank[node]) for node in nodes)
            if diff < tolerance:
                converged = True
                break

        return rank

    def connected_components(self) -> list[set[str]]:
        """Find all connected components in the graph.

        Returns:
            List of sets, each containing node IDs in a component
        """
        visited: set[str] = set()
        components: list[set[str]] = []

        for node_id in self.storage.node_store.keys():
            if node_id not in visited:
                component = self._bfs_component(node_id, visited)
                components.append(component)

        return components

    def _bfs_component(self, start_id: str, visited: set[str]) -> set[str]:
        """BFS to find a single connected component."""
        component: set[str] = set()
        queue: deque[str] = deque([start_id])

        while queue:
            current = queue.popleft()
            if current in visited:
                continue

            visited.add(current)
            component.add(current)

            neighbors = self.storage.get_adjacent_nodes(current, direction="both")
            for neighbor in neighbors:
                if neighbor not in visited:
                    queue.append(neighbor)

        return component

    def strongly_connected_components(self) -> list[set[str]]:
        """Find strongly connected components using Tarjan's algorithm.

        Returns:
            List of sets, each containing node IDs in an SCC
        """
        visited: set[str] = set()
        stack: list[str] = []
        sccs: list[set[str]] = []
        ids: dict[str, int] = {}
        low: dict[str, int] = {}
        on_stack: set[str] = set()
        id_counter = [0]

        def tarjan_dfs(node_id: str) -> None:
            """Tarjan's DFS."""
            ids[node_id] = id_counter[0]
            low[node_id] = id_counter[0]
            id_counter[0] += 1
            stack.append(node_id)
            on_stack.add(node_id)

            neighbors = self.storage.get_adjacent_nodes(node_id, direction="outbound")
            for neighbor in neighbors:
                if neighbor not in ids:
                    tarjan_dfs(neighbor)
                if neighbor in on_stack:
                    low[node_id] = min(low[node_id], low[neighbor])

            if ids[node_id] == low[node_id]:
                component: set[str] = set()
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    component.add(w)
                    low[w] = ids[node_id]
                    if w == node_id:
                        break
                sccs.append(component)

        for node_id in self.storage.node_store.keys():
            if node_id not in ids:
                tarjan_dfs(node_id)

        return sccs

    def betweenness_centrality(self, normalized: bool = True) -> dict[str, float]:
        """Compute betweenness centrality for all nodes.

        Args:
            normalized: Whether to normalize the result

        Returns:
            Dictionary mapping node IDs to centrality scores
        """
        centrality: dict[str, float] = {node_id: 0.0 for node_id in self.storage.node_store.keys()}

        if not self.storage.node_store:
            return centrality

        # For each node as source
        for source in self.storage.node_store.keys():
            # BFS to find shortest paths
            distances: dict[str, int] = {source: 0}
            predecessors: dict[str, list[str]] = defaultdict(list)
            queue: deque[str] = deque([source])

            while queue:
                current = queue.popleft()
                for neighbor in self.storage.get_adjacent_nodes(current, direction="both"):
                    if neighbor not in distances:
                        distances[neighbor] = distances[current] + 1
                        queue.append(neighbor)
                    if distances[neighbor] == distances[current] + 1:
                        predecessors[neighbor].append(current)

            # Accumulate shortest path counts
            sigma: dict[str, float] = {node: 0.0 for node in self.storage.node_store.keys()}
            sigma[source] = 1.0
            delta: dict[str, float] = {node: 0.0 for node in self.storage.node_store.keys()}

            # Sum over all nodes in reverse distance order
            nodes_by_dist = sorted(self.storage.node_store.keys(), key=lambda n: distances.get(n, 0))
            for w in reversed(nodes_by_dist):
                for v in predecessors[w]:
                    delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
                if w != source:
                    centrality[w] += delta[w]

        # Normalize
        if normalized:
            n = len(self.storage.node_store)
            if n > 2:
                scale = 2.0 / ((n - 1) * (n - 2))
                for node in centrality:
                    centrality[node] *= scale

        return centrality

    def degree_centrality(self) -> dict[str, float]:
        """Compute degree centrality for all nodes.

        Returns:
            Dictionary mapping node IDs to centrality scores (0-1)
        """
        centrality: dict[str, float] = {}
        n = len(self.storage.node_store)

        if n <= 1:
            return {node_id: 0.0 for node_id in self.storage.node_store.keys()}

        for node_id in self.storage.node_store.keys():
            degree = len(self.storage.get_adjacent_nodes(node_id, direction="both"))
            centrality[node_id] = degree / (n - 1)

        return centrality

    def label_propagation(self, iterations: int = 10) -> dict[str, str]:
        """Community detection using label propagation.

        Args:
            iterations: Number of iterations

        Returns:
            Dictionary mapping node IDs to community labels
        """
        if not self.storage.node_store:
            return {}

        # Initialize each node with its own label
        labels: dict[str, str] = {node_id: node_id for node_id in self.storage.node_store.keys()}

        for _ in range(iterations):
            new_labels = labels.copy()

            for node_id in self.storage.node_store.keys():
                neighbors = self.storage.get_adjacent_nodes(node_id, direction="both")

                if neighbors:
                    # Count labels of neighbors
                    label_counts: dict[str, int] = defaultdict(int)
                    for neighbor in neighbors:
                        label_counts[labels[neighbor]] += 1

                    # Assign most common label
                    if label_counts:
                        most_common = max(label_counts.items(), key=lambda x: x[1])[0]
                        new_labels[node_id] = most_common

            labels = new_labels

        return labels

    def clustering_coefficient(self, node_id: str | None = None) -> dict[str, float]:
        """Compute clustering coefficient.

        Args:
            node_id: If specified, compute for single node; else compute for all

        Returns:
            Dictionary mapping node IDs to clustering coefficients

        Raises:
            NodeNotFoundError: If node_id specified but doesn't exist
        """
        if node_id:
            if node_id not in self.storage.node_store:
                raise NodeNotFoundError(node_id)
            return {node_id: self._clustering_coefficient_single(node_id)}

        return {node_id: self._clustering_coefficient_single(node_id) for node_id in self.storage.node_store.keys()}

    def _clustering_coefficient_single(self, node_id: str) -> float:
        """Compute clustering coefficient for a single node."""
        neighbors = self.storage.get_adjacent_nodes(node_id, direction="both")
        k = len(neighbors)

        if k < 2:
            return 0.0

        # Count edges between neighbors
        edges = 0
        for i, neighbor_a in enumerate(neighbors):
            for neighbor_b in neighbors[i + 1 :]:
                neighbors_of_a = self.storage.get_adjacent_nodes(neighbor_a, direction="both")
                if neighbor_b in neighbors_of_a:
                    edges += 1

        return 2.0 * edges / (k * (k - 1))

    def triangle_count(self, node_id: str | None = None) -> int:
        """Count triangles in the graph.

        Args:
            node_id: If specified, count triangles containing this node; else count all

        Returns:
            Number of triangles

        Raises:
            NodeNotFoundError: If node_id specified but doesn't exist
        """
        if node_id:
            if node_id not in self.storage.node_store:
                raise NodeNotFoundError(node_id)
            return self._triangle_count_for_node(node_id)

        # Count all triangles
        count = 0
        for nid in self.storage.node_store.keys():
            neighbors = self.storage.get_adjacent_nodes(nid, direction="both")
            for i, neighbor_a in enumerate(neighbors):
                for neighbor_b in neighbors[i + 1 :]:
                    neighbors_of_a = self.storage.get_adjacent_nodes(neighbor_a, direction="both")
                    if neighbor_b in neighbors_of_a:
                        count += 1

        return count // 3  # Each triangle counted 3 times

    def _triangle_count_for_node(self, node_id: str) -> int:
        """Count triangles containing a specific node."""
        neighbors = self.storage.get_adjacent_nodes(node_id, direction="both")
        count = 0

        for i, neighbor_a in enumerate(neighbors):
            for neighbor_b in neighbors[i + 1 :]:
                neighbors_of_a = self.storage.get_adjacent_nodes(neighbor_a, direction="both")
                if neighbor_b in neighbors_of_a:
                    count += 1

        return count

    def density(self) -> float:
        """Compute graph density.

        Returns:
            Density value (0.0 to 1.0)
        """
        n = len(self.storage.node_store)
        if n <= 1:
            return 0.0

        m = len(self.storage.edge_store)
        max_edges = n * (n - 1) / 2  # For undirected graph
        return 2.0 * m / (n * (n - 1))

    def diameter(self) -> float | None:
        """Compute graph diameter (longest shortest path).

        Returns:
            Diameter or None if graph is disconnected
        """
        max_diameter = 0.0

        for source in self.storage.node_store.keys():
            distances: dict[str, int] = {source: 0}
            queue: deque[str] = deque([source])

            while queue:
                current = queue.popleft()
                for neighbor in self.storage.get_adjacent_nodes(current, direction="both"):
                    if neighbor not in distances:
                        distances[neighbor] = distances[current] + 1
                        queue.append(neighbor)

            if len(distances) < len(self.storage.node_store):
                return None  # Graph is disconnected

            max_diameter = max(max_diameter, max(distances.values()))

        return max_diameter if max_diameter > 0 else 0.0
