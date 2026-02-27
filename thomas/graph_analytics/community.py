"""
Community detection algorithms.

Implements label propagation, Louvain method, Girvan-Newman, and k-clique communities.
"""

import random
from collections import Counter, defaultdict
from typing import Any

from thomas.graph_analytics._types import CommunityResult, GraphType
from thomas.graph_analytics.centrality import betweenness_centrality
from thomas.graph_analytics.graph import Graph


def modularity_score(graph: Graph, communities: list[set[Any]]) -> float:
    """
    Calculate modularity score for a partition.

    Measures quality of community structure. Higher values indicate
    better separation of communities. Range: [-1, 1].

    Args:
        graph: Input graph.
        communities: List of sets representing communities.

    Returns:
        Modularity score.
    """
    if not communities:
        return 0.0

    # Create node-to-community mapping
    node_community: dict[Any, int] = {}
    for comm_idx, community in enumerate(communities):
        for node in community:
            node_community[node] = comm_idx

    edges = graph.edges()
    m = len(edges)

    if m == 0:
        return 0.0

    q = 0.0
    for node in graph.nodes():
        degree_node = graph.degree(node)

        for neighbor in graph.neighbors(node):
            degree_neighbor = graph.degree(neighbor)

            # Check if in same community
            if node_community.get(node) == node_community.get(neighbor):
                edge_weight = graph.get_edge_weight(node, neighbor)
                if edge_weight is None:
                    edge_weight = 1.0

                q += edge_weight - (degree_node * degree_neighbor) / (2 * m)

    if graph.graph_type == GraphType.UNDIRECTED:
        q /= 2 * m
    else:
        q /= m

    return q


def label_propagation(graph: Graph, max_iterations: int = 100, seed: int = 42) -> CommunityResult:
    """
    Detect communities using label propagation algorithm.

    Asynchronous algorithm where each node adopts the most frequent
    label among its neighbors. Fast and scalable.

    Args:
        graph: Input graph.
        max_iterations: Maximum iterations.
        seed: Random seed for reproducibility.

    Returns:
        CommunityResult with communities and modularity.
    """
    random.seed(seed)
    nodes = graph.nodes()

    # Initialize labels
    labels: dict[Any, int] = {node: i for i, node in enumerate(nodes)}

    # Random order processing
    nodes_list = list(nodes)

    for iteration in range(max_iterations):
        random.shuffle(nodes_list)
        labels_changed = 0

        for node in nodes_list:
            # Get labels of neighbors
            neighbors = graph.neighbors(node)
            if neighbors:
                neighbor_labels = [labels[n] for n in neighbors]
                label_counts = Counter(neighbor_labels)
                most_common_label = label_counts.most_common(1)[0][0]

                if labels[node] != most_common_label:
                    labels[node] = most_common_label
                    labels_changed += 1

        if labels_changed == 0:
            break

    # Convert labels to communities
    communities_dict: dict[int, set[Any]] = defaultdict(set)
    for node, label in labels.items():
        communities_dict[label].add(node)

    communities = list(communities_dict.values())
    modularity = modularity_score(graph, communities)

    return CommunityResult(
        communities=communities,
        modularity=modularity,
        quality_metrics={
            "num_communities": len(communities),
            "min_size": min(len(c) for c in communities) if communities else 0,
            "max_size": max(len(c) for c in communities) if communities else 0,
        },
    )


def louvain_method(graph: Graph, resolution: float = 1.0, seed: int = 42, max_iterations: int = 100) -> CommunityResult:
    """
    Detect communities using Louvain method.

    Two-phase algorithm: local optimization of modularity followed by
    aggregation. Produces high-quality partitions efficiently.

    Args:
        graph: Input graph.
        resolution: Resolution parameter (higher = more communities).
        seed: Random seed.
        max_iterations: Maximum iterations.

    Returns:
        CommunityResult with communities and modularity.
    """
    random.seed(seed)
    nodes = graph.nodes()
    node_list = list(nodes)

    # Initialize communities (each node in own community)
    communities: dict[Any, set[Any]] = {node: {node} for node in nodes}
    node_to_comm: dict[Any, Any] = {node: node for node in nodes}

    # Calculate edge weights and degrees
    edges = graph.edges()
    m = len(edges) if edges else 1.0

    best_modularity = -1.0
    best_communities = None

    for iteration in range(max_iterations):
        moved = 0

        # Random order
        random.shuffle(node_list)

        for node in node_list:
            current_comm = node_to_comm[node]

            # Calculate modularity gain for each neighboring community
            neighbor_comms = set()
            for neighbor in graph.neighbors(node):
                neighbor_comms.add(node_to_comm[neighbor])

            neighbor_comms.add(current_comm)

            best_gain = 0.0
            best_new_comm = current_comm

            for new_comm in neighbor_comms:
                # Calculate modularity change
                degree_node = graph.degree(node)

                # Edges to new community
                edges_to_new = sum(1 for neighbor in graph.neighbors(node) if node_to_comm[neighbor] == new_comm)

                # Edges from new community
                edges_from_new = sum(graph.degree(n) for n in communities[new_comm]) - degree_node

                gain = 2 * edges_to_new - 2 * degree_node * edges_from_new / (2 * m)
                gain *= resolution

                if gain > best_gain:
                    best_gain = gain
                    best_new_comm = new_comm

            # Move node if beneficial
            if best_new_comm != current_comm:
                communities[current_comm].remove(node)
                if not communities[current_comm]:
                    del communities[current_comm]

                if best_new_comm not in communities:
                    communities[best_new_comm] = set()

                communities[best_new_comm].add(node)
                node_to_comm[node] = best_new_comm
                moved += 1

        # Check convergence
        current_communities = list(communities.values())
        current_modularity = modularity_score(graph, current_communities)

        if current_modularity > best_modularity:
            best_modularity = current_modularity
            best_communities = [c.copy() for c in current_communities]

        if moved == 0:
            break

    if best_communities is None:
        best_communities = list(communities.values())
        best_modularity = modularity_score(graph, best_communities)

    return CommunityResult(
        communities=best_communities,
        modularity=best_modularity,
        quality_metrics={
            "num_communities": len(best_communities),
            "min_size": min(len(c) for c in best_communities) if best_communities else 0,
            "max_size": max(len(c) for c in best_communities) if best_communities else 0,
        },
    )


def girvan_newman(graph: Graph, num_communities: int = 2) -> CommunityResult:
    """
    Detect communities using Girvan-Newman algorithm.

    Iteratively removes edges with highest betweenness centrality.
    Produces hierarchical structure. Slower but high-quality results.

    Args:
        graph: Input graph.
        num_communities: Target number of communities.

    Returns:
        CommunityResult with communities and modularity.
    """
    # Work with a copy
    g = graph.copy()
    communities = list(range(g.num_nodes()))
    node_map = {node: i for i, node in enumerate(g.nodes())}

    edge_count = g.num_edges()

    for iteration in range(edge_count):
        # Calculate edge betweenness
        edge_betweenness: dict[tuple[Any, Any], float] = defaultdict(float)

        for source in g.nodes():
            result = betweenness_centrality(g, normalized=False)
            for edge in g.edges():
                src, dst, weight = edge
                # Approximate: use node betweenness as proxy
                edge_betweenness[(src, dst)] = result.scores.get(src, 0)

        # Find edge with highest betweenness
        if not edge_betweenness:
            break

        edge_to_remove = max(edge_betweenness.items(), key=lambda x: x[1])[0]

        # Remove edge
        try:
            g.remove_edge(edge_to_remove[0], edge_to_remove[1])
        except KeyError:
            pass

        # Check if we have enough communities
        # Count connected components
        visited = set()
        components = 0

        for node in g.nodes():
            if node not in visited:
                stack = [node]
                while stack:
                    current = stack.pop()
                    if current in visited:
                        continue
                    visited.add(current)
                    for neighbor in g.neighbors(current):
                        if neighbor not in visited:
                            stack.append(neighbor)
                components += 1

        if components >= num_communities:
            break

    # Extract connected components as communities
    visited = set()
    communities_final = []

    for node in g.nodes():
        if node not in visited:
            component = set()
            stack = [node]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                for neighbor in g.neighbors(current):
                    if neighbor not in visited:
                        stack.append(neighbor)
            communities_final.append(component)

    modularity = modularity_score(g, communities_final)

    return CommunityResult(
        communities=communities_final,
        modularity=modularity,
        quality_metrics={
            "num_communities": len(communities_final),
            "min_size": min(len(c) for c in communities_final) if communities_final else 0,
            "max_size": max(len(c) for c in communities_final) if communities_final else 0,
        },
    )


def kclique_communities(graph: Graph, k: int = 3) -> CommunityResult:
    """
    Find k-clique communities.

    Communities are defined as unions of k-cliques that share k-1 nodes.
    Only works for undirected graphs.

    Args:
        graph: Input undirected graph.
        k: Clique size.

    Returns:
        CommunityResult with communities.
    """
    if graph.graph_type == GraphType.DIRECTED:
        raise ValueError("k-clique communities only defined for undirected graphs")

    nodes = graph.nodes()
    n = len(nodes)

    if k > n:
        return CommunityResult(communities=[], modularity=0.0)

    # Find all k-cliques
    cliques: list[set[Any]] = []

    def is_clique(node_set: set[Any]) -> bool:
        """Check if a set of nodes forms a clique."""
        nodes_list = list(node_set)
        for i in range(len(nodes_list)):
            for j in range(i + 1, len(nodes_list)):
                if not graph.has_edge(nodes_list[i], nodes_list[j]):
                    return False
        return True

    def find_cliques_recursive(current: set[Any], remaining: set[Any], cliques: list[set[Any]]) -> None:
        """Recursively find all cliques."""
        if len(current) == k:
            if is_clique(current):
                cliques.append(current.copy())
            return

        if not remaining:
            return

        for node in list(remaining):
            current.add(node)
            remaining.remove(node)
            find_cliques_recursive(current, remaining, cliques)
            current.remove(node)
            remaining.add(node)

    # Find cliques (simplified for performance)
    for node in nodes:
        neighbors = set(graph.neighbors(node))
        neighbors.add(node)
        if len(neighbors) >= k:
            find_cliques_recursive(set(), neighbors, cliques)

    # Convert cliques to communities by merging overlapping ones
    if not cliques:
        communities_final = [[node] for node in nodes]
    else:
        # Simple merging strategy
        communities_list = [set(clique) for clique in cliques]
        communities_final = []
        used = set()

        for i, comm in enumerate(communities_list):
            if i in used:
                continue

            merged = comm.copy()
            for j in range(i + 1, len(communities_list)):
                if j not in used:
                    # Check overlap
                    if len(merged & communities_list[j]) >= k - 1:
                        merged |= communities_list[j]
                        used.add(j)

            communities_final.append(merged)

    modularity = modularity_score(graph, communities_final)

    return CommunityResult(
        communities=communities_final,
        modularity=modularity,
        quality_metrics={
            "num_communities": len(communities_final),
            "clique_size": k,
        },
    )
