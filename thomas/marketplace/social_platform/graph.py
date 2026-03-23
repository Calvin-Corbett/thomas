"""Social graph algorithms and analysis.

This module implements friend recommendations, community detection via label
propagation, influence scoring (PageRank), shortest path, clustering coefficient,
degree distribution, and strong/weak tie classification (Granovetter).
"""

import math
from collections import defaultdict, deque
from uuid import UUID


class SocialGraphAnalyzer:
    """Analyzes social network graphs.

    Attributes:
        graph: Adjacency list representation
        reverse_graph: Reverse adjacency list
        node_data: Metadata per node
        influence_scores: PageRank scores
    """

    def __init__(self) -> None:
        """Initialize graph analyzer."""
        self.graph: dict[UUID, set[UUID]] = defaultdict(set)
        self.reverse_graph: dict[UUID, set[UUID]] = defaultdict(set)
        self.node_data: dict[UUID, dict] = {}
        self.influence_scores: dict[UUID, float] = {}

    def add_edge(self, source: UUID, target: UUID) -> None:
        """Add directed edge (source -> target).

        Args:
            source: Source node
            target: Target node
        """
        self.graph[source].add(target)
        self.reverse_graph[target].add(source)

    def remove_edge(self, source: UUID, target: UUID) -> None:
        """Remove directed edge.

        Args:
            source: Source node
            target: Target node
        """
        self.graph[source].discard(target)
        self.reverse_graph[target].discard(source)

    def get_friends_of_friends(self, user_id: UUID, mutual_only: bool = False) -> list[tuple[UUID, float]]:
        """Get friend recommendations using friends-of-friends.

        Scores by Jaccard similarity between friend sets.

        Args:
            user_id: User ID
            mutual_only: Only mutual connections

        Returns:
            List of (user_id, score) tuples sorted by score
        """
        friends = self.graph[user_id]

        if not friends:
            return []

        # Collect friends-of-friends
        candidates = defaultdict(int)
        for friend_id in friends:
            friend_friends = self.graph[friend_id]
            for fof in friend_friends:
                if fof != user_id and fof not in friends:
                    candidates[fof] += 1

        # Score using Jaccard similarity
        scores = []
        for candidate_id, mutual_count in candidates.items():
            candidate_friends = self.graph[candidate_id]

            # Jaccard similarity: intersection / union
            union = len(friends | candidate_friends)
            if union > 0:
                jaccard = mutual_count / union
                scores.append((candidate_id, jaccard))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def detect_communities(self) -> dict[UUID, int]:
        """Detect communities using label propagation.

        Returns:
            Dictionary mapping node_id to community_id
        """
        # Initialize each node with unique label
        labels: dict[UUID, int] = {node: i for i, node in enumerate(self.graph.keys())}

        # Iterate until convergence
        converged = False
        iterations = 0
        max_iterations = 50

        while not converged and iterations < max_iterations:
            converged = True
            iterations += 1

            for node in list(self.graph.keys()):
                neighbors = self.graph[node] | self.reverse_graph[node]

                if not neighbors:
                    continue

                # Find most common label among neighbors
                label_counts = defaultdict(int)
                for neighbor in neighbors:
                    label_counts[labels[neighbor]] += 1

                # Select label with highest count
                most_common_label = max(label_counts, key=label_counts.get)

                if labels[node] != most_common_label:
                    labels[node] = most_common_label
                    converged = False

        return labels

    def calculate_influence_scores(self, iterations: int = 20, damping: float = 0.85) -> dict[UUID, float]:
        """Calculate PageRank-based influence scores.

        Args:
            iterations: Number of iterations
            damping: Damping factor (0-1)

        Returns:
            Dictionary mapping user_id to influence score
        """
        if not self.graph:
            return {}

        all_nodes = set(self.graph.keys()) | set(self.reverse_graph.keys())

        # Initialize scores
        scores = {node: 1.0 / len(all_nodes) for node in all_nodes}

        # Iterate
        for _ in range(iterations):
            new_scores = {}

            for node in all_nodes:
                # Rank from incoming edges
                rank = (1 - damping) / len(all_nodes)

                incoming = self.reverse_graph[node]
                if incoming:
                    for source in incoming:
                        out_degree = len(self.graph[source])
                        if out_degree > 0:
                            rank += damping * scores[source] / out_degree

                new_scores[node] = rank

            scores = new_scores

        self.influence_scores = scores
        return scores

    def find_shortest_path(self, source: UUID, target: UUID) -> list[UUID] | None:
        """Find shortest path between two users (BFS).

        Args:
            source: Source user
            target: Target user

        Returns:
            List of user IDs in path, or None if no path
        """
        if source == target:
            return [source]

        if source not in self.graph:
            return None

        visited = {source}
        queue = deque([(source, [source])])

        while queue:
            node, path = queue.popleft()

            for neighbor in self.graph[node]:
                if neighbor == target:
                    return path + [target]

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None

    def calculate_clustering_coefficient(self, node: UUID) -> float:
        """Calculate clustering coefficient for a node.

        Fraction of possible triangles that exist.

        Args:
            node: Node ID

        Returns:
            Clustering coefficient (0-1)
        """
        neighbors = self.graph[node]

        if len(neighbors) < 2:
            return 0.0

        # Count edges between neighbors
        edges_between = 0
        for n1 in neighbors:
            for n2 in neighbors:
                if n1 != n2 and n2 in self.graph[n1]:
                    edges_between += 1

        # Total possible edges
        possible_edges = len(neighbors) * (len(neighbors) - 1)

        if possible_edges == 0:
            return 0.0

        return edges_between / possible_edges

    def get_degree_distribution(self) -> dict[int, int]:
        """Get degree distribution of graph.

        Returns:
            Dictionary mapping degree to count
        """
        distribution = defaultdict(int)

        for node in self.graph:
            degree = len(self.graph[node]) + len(self.reverse_graph[node])
            distribution[degree] += 1

        return dict(distribution)

    def classify_ties(self, source: UUID, target: UUID) -> str:
        """Classify edge as strong or weak tie (Granovetter).

        Strong ties: frequent interaction, similar friend networks
        Weak ties: infrequent, different friend networks

        Args:
            source: Source user
            target: Target user

        Returns:
            "strong" or "weak"
        """
        if target not in self.graph[source]:
            return "non_existent"

        # Calculate overlap in friend networks
        source_friends = self.graph[source]
        target_friends = self.graph[target]

        if not source_friends or not target_friends:
            return "weak"

        overlap = len(source_friends & target_friends)
        max_possible = min(len(source_friends), len(target_friends))

        if max_possible == 0:
            return "weak"

        overlap_ratio = overlap / max_possible

        # Strong tie if high overlap
        return "strong" if overlap_ratio > 0.5 else "weak"

    def get_bridge_nodes(self) -> list[tuple[UUID, float]]:
        """Find bridge nodes (high betweenness centrality).

        Nodes that connect different communities.

        Args (implied):
            None

        Returns:
            List of (node_id, betweenness) tuples
        """
        betweenness = defaultdict(float)

        all_nodes = list(self.graph.keys())

        # For each pair of nodes
        for source in all_nodes:
            for target in all_nodes:
                if source == target:
                    continue

                path = self.find_shortest_path(source, target)
                if path:
                    # Add to betweenness for all intermediate nodes
                    for node in path[1:-1]:
                        betweenness[node] += 1

        # Normalize
        n = len(all_nodes)
        if n > 2:
            normalization = 2.0 / ((n - 1) * (n - 2))
            for node in betweenness:
                betweenness[node] *= normalization

        results = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)
        return results[:10]  # Top 10 bridges

    def get_graph_density(self) -> float:
        """Calculate overall graph density.

        Returns:
            Density (0-1)
        """
        n = len(self.graph)

        if n < 2:
            return 0.0

        # Count actual edges
        edge_count = sum(len(neighbors) for neighbors in self.graph.values())

        # Maximum possible edges
        max_edges = n * (n - 1)

        if max_edges == 0:
            return 0.0

        return edge_count / max_edges

    def get_avg_clustering_coefficient(self) -> float:
        """Calculate average clustering coefficient.

        Returns:
            Average clustering coefficient
        """
        if not self.graph:
            return 0.0

        coefficients = [self.calculate_clustering_coefficient(node) for node in self.graph]

        return sum(coefficients) / len(coefficients) if coefficients else 0.0

    def find_ego_network(self, node: UUID, depth: int = 1) -> set[UUID]:
        """Find ego network (node + neighbors at given depth).

        Args:
            node: Center node
            depth: Network depth

        Returns:
            Set of nodes in ego network
        """
        network = {node}
        current_level = {node}

        for _ in range(depth):
            next_level = set()
            for current in current_level:
                next_level.update(self.graph[current])
                next_level.update(self.reverse_graph[current])

            next_level -= network
            network.update(next_level)
            current_level = next_level

        return network

    def calculate_assortativity(self) -> float:
        """Calculate network assortativity (degree correlation).

        High assortativity: hubs connect to hubs
        Low assortativity: hubs connect to periphery

        Returns:
            Assortativity coefficient (-1 to 1)
        """
        edges = []

        for source in self.graph:
            source_degree = len(self.graph[source]) + len(self.reverse_graph[source])
            for target in self.graph[source]:
                target_degree = len(self.graph[target]) + len(self.reverse_graph[target])
                edges.append((source_degree, target_degree))

        if not edges:
            return 0.0

        # Calculate correlation
        source_degrees = [e[0] for e in edges]
        target_degrees = [e[1] for e in edges]

        mean_source = sum(source_degrees) / len(source_degrees)
        mean_target = sum(target_degrees) / len(target_degrees)

        numerator = sum((sd - mean_source) * (td - mean_target) for sd, td in edges)

        source_var = sum((sd - mean_source) ** 2 for sd in source_degrees)
        target_var = sum((td - mean_target) ** 2 for td in target_degrees)

        denominator = math.sqrt(source_var * target_var)

        if denominator == 0:
            return 0.0

        return numerator / denominator

    def get_graph_metrics(self) -> dict[str, float]:
        """Get overall graph metrics.

        Returns:
            Dictionary with metrics
        """
        self.calculate_influence_scores()

        return {
            "node_count": len(self.graph),
            "edge_count": sum(len(neighbors) for neighbors in self.graph.values()),
            "density": self.get_graph_density(),
            "avg_clustering_coefficient": self.get_avg_clustering_coefficient(),
            "assortativity": self.calculate_assortativity(),
        }
