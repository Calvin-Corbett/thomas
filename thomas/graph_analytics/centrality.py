"""
Centrality measures for graphs.

Computes various node importance measures: degree, betweenness, closeness,
eigenvector, PageRank, Katz, and HITS.
"""

import math
from typing import Any

from thomas.graph_analytics._types import CentralityResult
from thomas.graph_analytics.graph import Graph
from thomas.graph_analytics.shortest_path import bfs_shortest_path


def degree_centrality(graph: Graph, normalized: bool = True) -> CentralityResult:
    """
    Compute degree centrality for all nodes.

    For directed graphs, uses out-degree. Normalized by (n-1) for comparison.

    Args:
        graph: Input graph.
        normalized: Whether to normalize by (n-1).

    Returns:
        CentralityResult with centrality scores.
    """
    nodes = graph.nodes()
    n = len(nodes)

    scores: dict[Any, float] = {}
    for node in nodes:
        degree = graph.out_degree(node) if graph.graph_type.value == "directed" else graph.degree(node)
        scores[node] = float(degree)

    if normalized and n > 1:
        scores = {node: score / (n - 1) for node, score in scores.items()}

    stats = {
        "min": min(scores.values()),
        "max": max(scores.values()),
        "mean": sum(scores.values()) / len(scores),
    }

    return CentralityResult(scores=scores, measure="degree_centrality", normalized=normalized, statistics=stats)


def betweenness_centrality(graph: Graph, normalized: bool = True) -> CentralityResult:
    """
    Compute betweenness centrality using Brandes' algorithm.

    Measures how often a node lies on shortest paths between other pairs.
    Time complexity: O(VE).

    Args:
        graph: Input graph.
        normalized: Whether to normalize by (n-1)(n-2)/2.

    Returns:
        CentralityResult with centrality scores.
    """
    nodes = graph.nodes()
    n = len(nodes)
    betweenness: dict[Any, float] = {node: 0.0 for node in nodes}

    # For each node as source
    for source in nodes:
        # BFS to find all shortest paths
        result = bfs_shortest_path(graph, source)
        distances = result.distances
        predecessors = result.predecessors

        # Build predecessor lists
        pred_lists: dict[Any, list[Any]] = {node: [] for node in nodes}
        for node in nodes:
            if predecessors[node] is not None:
                pred_lists[predecessors[node]].append(node)

        # Accumulation phase (reverse topological order)
        dependency: dict[Any, float] = {node: 0.0 for node in nodes}

        # Process nodes in reverse order of distance
        nodes_by_distance = sorted(nodes, key=lambda x: -distances[x])

        for node in nodes_by_distance:
            for pred in pred_lists[node]:
                if distances[node] == distances[pred] + 1:
                    dependency[pred] += 1 + dependency[node]

            if node != source:
                betweenness[node] += dependency[node]

    # Normalize
    if normalized and n > 2:
        norm_factor = 1.0 / ((n - 1) * (n - 2) / 2.0)
        betweenness = {node: score * norm_factor for node, score in betweenness.items()}

    stats = {
        "min": min(betweenness.values()),
        "max": max(betweenness.values()),
        "mean": sum(betweenness.values()) / len(betweenness),
    }

    return CentralityResult(
        scores=betweenness, measure="betweenness_centrality", normalized=normalized, statistics=stats
    )


def closeness_centrality(graph: Graph, normalized: bool = True) -> CentralityResult:
    """
    Compute closeness centrality.

    Measures how close a node is to all other nodes on average.
    For disconnected graphs, only considers nodes in same component.

    Args:
        graph: Input graph.
        normalized: Whether to normalize.

    Returns:
        CentralityResult with centrality scores.
    """
    nodes = graph.nodes()
    n = len(nodes)
    closeness: dict[Any, float] = {}

    for source in nodes:
        result = bfs_shortest_path(graph, source)
        distances = result.distances

        # Sum of distances to reachable nodes
        reachable = sum(1 for d in distances.values() if d != float("inf"))

        if reachable > 1:
            sum_distances = sum(d for d in distances.values() if d != float("inf") and d > 0)
            if sum_distances > 0:
                closeness[source] = (reachable - 1) / sum_distances
            else:
                closeness[source] = 0.0
        else:
            closeness[source] = 0.0

    if normalized:
        norm_factor = (n - 1) / n
        closeness = {node: score * norm_factor for node, score in closeness.items()}

    stats = {
        "min": min(closeness.values()),
        "max": max(closeness.values()),
        "mean": sum(closeness.values()) / len(closeness),
    }

    return CentralityResult(scores=closeness, measure="closeness_centrality", normalized=normalized, statistics=stats)


def eigenvector_centrality(graph: Graph, max_iterations: int = 100, tolerance: float = 1e-6) -> CentralityResult:
    """
    Compute eigenvector centrality using power iteration.

    Measures influence based on connections to high-influence nodes.
    Converges to principal eigenvector of adjacency matrix.

    Args:
        graph: Input graph.
        max_iterations: Maximum iterations for power method.
        tolerance: Convergence tolerance.

    Returns:
        CentralityResult with centrality scores.
    """
    nodes = graph.nodes()
    n = len(nodes)
    node_to_idx = {node: i for i, node in enumerate(nodes)}

    # Build adjacency matrix
    adj_matrix = graph.adjacency_matrix()

    # Initialize eigenvector
    x = [1.0 / n] * n

    for iteration in range(max_iterations):
        # Matrix-vector multiplication
        x_new = [0.0] * n
        for i in range(n):
            for j in range(n):
                x_new[i] += adj_matrix[i][j] * x[j]

        # Normalize
        norm = math.sqrt(sum(val**2 for val in x_new))
        if norm == 0:
            break

        x_new = [val / norm for val in x_new]

        # Check convergence
        diff = sum(abs(x_new[i] - x[i]) for i in range(n))
        x = x_new

        if diff < tolerance:
            break

    scores = {nodes[i]: x[i] for i in range(n)}

    stats = {
        "min": min(scores.values()),
        "max": max(scores.values()),
        "mean": sum(scores.values()) / len(scores),
    }

    return CentralityResult(scores=scores, measure="eigenvector_centrality", normalized=True, statistics=stats)


def pagerank(
    graph: Graph, damping_factor: float = 0.85, max_iterations: int = 100, tolerance: float = 1e-6
) -> CentralityResult:
    """
    Compute PageRank scores using iterative method.

    Models random walk with probability of jumping to random node.
    Used to rank web pages and measure node importance.

    Args:
        graph: Input graph.
        damping_factor: Probability of following link (default 0.85).
        max_iterations: Maximum iterations.
        tolerance: Convergence tolerance.

    Returns:
        CentralityResult with PageRank scores.
    """
    nodes = graph.nodes()
    n = len(nodes)

    # Initialize PageRank
    pagerank_scores: dict[Any, float] = {node: 1.0 / n for node in nodes}
    rank_jump = (1.0 - damping_factor) / n

    for iteration in range(max_iterations):
        new_scores: dict[Any, float] = {}

        for node in nodes:
            rank = rank_jump

            # Sum contributions from predecessors
            for pred in graph.nodes():
                out_degree = graph.out_degree(pred)
                if out_degree > 0 and graph.has_edge(pred, node):
                    rank += damping_factor * pagerank_scores[pred] / out_degree

            new_scores[node] = rank

        # Check convergence
        diff = sum(abs(new_scores[node] - pagerank_scores[node]) for node in nodes)
        pagerank_scores = new_scores

        if diff < tolerance:
            break

    stats = {
        "min": min(pagerank_scores.values()),
        "max": max(pagerank_scores.values()),
        "mean": sum(pagerank_scores.values()) / len(pagerank_scores),
        "sum": sum(pagerank_scores.values()),
    }

    return CentralityResult(scores=pagerank_scores, measure="pagerank", normalized=False, statistics=stats)


def katz_centrality(
    graph: Graph, alpha: float = 0.1, beta: float = 1.0, max_iterations: int = 100, tolerance: float = 1e-6
) -> CentralityResult:
    """
    Compute Katz centrality.

    Generalization of eigenvector centrality that includes a bias term.
    Higher alpha means more weight on direct connections.

    Args:
        graph: Input graph.
        alpha: Attenuation factor (must be < 1/λ_max for convergence).
        beta: Bias term weight.
        max_iterations: Maximum iterations.
        tolerance: Convergence tolerance.

    Returns:
        CentralityResult with Katz centrality scores.
    """
    nodes = graph.nodes()
    n = len(nodes)

    # Initialize scores
    katz_scores: dict[Any, float] = {node: 0.0 for node in nodes}

    for iteration in range(max_iterations):
        new_scores: dict[Any, float] = {}

        for node in nodes:
            score = beta

            # Sum contributions from predecessors
            for pred in nodes:
                if graph.has_edge(pred, node):
                    score += alpha * katz_scores[pred]

            new_scores[node] = score

        # Check convergence
        diff = sum(abs(new_scores[node] - katz_scores[node]) for node in nodes)
        katz_scores = new_scores

        if diff < tolerance:
            break

    # Normalize
    norm = math.sqrt(sum(score**2 for score in katz_scores.values()))
    if norm > 0:
        katz_scores = {node: score / norm for node, score in katz_scores.items()}

    stats = {
        "min": min(katz_scores.values()),
        "max": max(katz_scores.values()),
        "mean": sum(katz_scores.values()) / len(katz_scores),
    }

    return CentralityResult(scores=katz_scores, measure="katz_centrality", normalized=True, statistics=stats)


def hits(graph: Graph, max_iterations: int = 100, tolerance: float = 1e-6) -> tuple[CentralityResult, CentralityResult]:
    """
    Compute HITS (Hubs and Authorities) scores.

    Identifies hub nodes (good sources) and authority nodes (good references).
    Typically used on directed graphs like web graphs.

    Args:
        graph: Input graph.
        max_iterations: Maximum iterations.
        tolerance: Convergence tolerance.

    Returns:
        Tuple of (hub_scores, authority_scores) as CentralityResult objects.
    """
    nodes = graph.nodes()
    n = len(nodes)

    # Initialize scores
    hub_scores: dict[Any, float] = {node: 1.0 / n for node in nodes}
    auth_scores: dict[Any, float] = {node: 1.0 / n for node in nodes}

    for iteration in range(max_iterations):
        # Update authorities
        new_auth: dict[Any, float] = {node: 0.0 for node in nodes}
        for node in nodes:
            for pred in nodes:
                if graph.has_edge(pred, node):
                    new_auth[node] += hub_scores[pred]

        # Update hubs
        new_hub: dict[Any, float] = {node: 0.0 for node in nodes}
        for node in nodes:
            for succ in graph.neighbors(node):
                new_hub[node] += new_auth[succ]

        # Normalize authorities
        auth_norm = math.sqrt(sum(val**2 for val in new_auth.values()))
        if auth_norm > 0:
            new_auth = {node: val / auth_norm for node, val in new_auth.items()}

        # Normalize hubs
        hub_norm = math.sqrt(sum(val**2 for val in new_hub.values()))
        if hub_norm > 0:
            new_hub = {node: val / hub_norm for node, val in new_hub.items()}

        # Check convergence
        auth_diff = sum(abs(new_auth[node] - auth_scores[node]) for node in nodes)
        hub_diff = sum(abs(new_hub[node] - hub_scores[node]) for node in nodes)

        hub_scores = new_hub
        auth_scores = new_auth

        if auth_diff < tolerance and hub_diff < tolerance:
            break

    hub_stats = {
        "min": min(hub_scores.values()),
        "max": max(hub_scores.values()),
        "mean": sum(hub_scores.values()) / len(hub_scores),
    }

    auth_stats = {
        "min": min(auth_scores.values()),
        "max": max(auth_scores.values()),
        "mean": sum(auth_scores.values()) / len(auth_scores),
    }

    return (
        CentralityResult(scores=hub_scores, measure="hits_hub", normalized=True, statistics=hub_stats),
        CentralityResult(scores=auth_scores, measure="hits_authority", normalized=True, statistics=auth_stats),
    )
