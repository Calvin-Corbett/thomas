"""
Graph generators for creating synthetic graphs.

Implements random, scale-free, small-world, and structured graph generation.
"""

import random

from thomas.graph_analytics._types import GraphType
from thomas.graph_analytics.graph import Graph


def erdos_renyi_graph(n: int, p: float = None, m: int = None, directed: bool = False, seed: int = 42) -> Graph:
    """
    Generate Erdős-Rényi random graph.

    Two variants: G(n,p) with edge probability p, or G(n,m) with m edges.

    Args:
        n: Number of nodes.
        p: Edge probability (for G(n,p) model).
        m: Number of edges (for G(n,m) model).
        directed: Whether graph is directed.
        seed: Random seed.

    Returns:
        Generated random graph.
    """
    random.seed(seed)

    graph_type = GraphType.DIRECTED if directed else GraphType.UNDIRECTED
    g = Graph(graph_type)

    # Add nodes
    for i in range(n):
        g.add_node(i)

    if p is not None:
        # G(n,p) model
        for i in range(n):
            for j in range(i + 1 if not directed else 0, n):
                if i != j and random.random() < p:
                    g.add_edge(i, j, weight=1.0)
                    if not directed and random.random() < p:
                        g.add_edge(j, i, weight=1.0)

    elif m is not None:
        # G(n,m) model - add exactly m edges
        max_edges = n * (n - 1) // 2 if not directed else n * (n - 1)
        actual_m = min(m, max_edges)

        edges_added = 0
        attempts = 0
        max_attempts = actual_m * 10

        while edges_added < actual_m and attempts < max_attempts:
            i = random.randint(0, n - 1)
            j = random.randint(0, n - 1)

            if i != j and not g.has_edge(i, j):
                g.add_edge(i, j, weight=1.0)
                edges_added += 1

            attempts += 1

    return g


def barabasi_albert_graph(n: int, m: int = 2, seed: int = 42) -> Graph:
    """
    Generate Barabási-Albert preferential attachment graph.

    Creates scale-free network where new nodes attach to high-degree nodes.

    Args:
        n: Number of nodes.
        m: Number of edges each new node makes (must be >= 1).
        seed: Random seed.

    Returns:
        Generated scale-free graph.
    """
    random.seed(seed)

    g = Graph(GraphType.UNDIRECTED)

    # Start with complete graph of m+1 nodes
    for i in range(m + 1):
        g.add_node(i)

    for i in range(m + 1):
        for j in range(i + 1, m + 1):
            g.add_edge(i, j, weight=1.0)

    # Add remaining nodes with preferential attachment
    for new_node in range(m + 1, n):
        g.add_node(new_node)

        # Calculate degree probabilities
        total_degree = sum(g.degree(node) for node in g.nodes())

        # Preferentially attach to m nodes
        targets = set()
        attempts = 0
        while len(targets) < m and attempts < m * 10:
            # Select node proportional to degree
            r = random.random() * total_degree
            cumsum = 0
            selected = None

            for node in g.nodes():
                if node != new_node:
                    cumsum += g.degree(node)
                    if cumsum >= r:
                        selected = node
                        break

            if selected and selected not in targets:
                targets.add(selected)

            attempts += 1

        # Add edges
        for target in targets:
            g.add_edge(new_node, target, weight=1.0)

    return g


def watts_strogatz_graph(n: int, k: int = 4, p: float = 0.5, seed: int = 42) -> Graph:
    """
    Generate Watts-Strogatz small-world graph.

    Creates ring lattice and rewires edges with probability p.

    Args:
        n: Number of nodes.
        k: Each node connected to k nearest neighbors (must be even).
        p: Rewiring probability.
        seed: Random seed.

    Returns:
        Generated small-world graph.
    """
    random.seed(seed)

    if k % 2 != 0:
        k += 1

    g = Graph(GraphType.UNDIRECTED)

    # Add nodes
    for i in range(n):
        g.add_node(i)

    # Create ring lattice
    for i in range(n):
        for j in range(1, k // 2 + 1):
            neighbor = (i + j) % n
            g.add_edge(i, neighbor, weight=1.0)

    # Rewire edges
    for i in range(n):
        for j in range(i + 1, n):
            if g.has_edge(i, j):
                if random.random() < p:
                    # Rewire this edge
                    g.remove_edge(i, j)

                    # Find new target
                    new_target = random.randint(0, n - 1)
                    attempts = 0
                    while (new_target == i or g.has_edge(i, new_target)) and attempts < 10:
                        new_target = random.randint(0, n - 1)
                        attempts += 1

                    if new_target != i and not g.has_edge(i, new_target):
                        g.add_edge(i, new_target, weight=1.0)

    return g


def complete_graph(n: int, directed: bool = False) -> Graph:
    """
    Generate complete graph K_n.

    Every pair of nodes is connected.

    Args:
        n: Number of nodes.
        directed: Whether to create directed complete graph.

    Returns:
        Complete graph.
    """
    graph_type = GraphType.DIRECTED if directed else GraphType.UNDIRECTED
    g = Graph(graph_type)

    for i in range(n):
        g.add_node(i)

    for i in range(n):
        for j in range(i + 1, n):
            g.add_edge(i, j, weight=1.0)
            if directed:
                g.add_edge(j, i, weight=1.0)

    return g


def cycle_graph(n: int, directed: bool = False) -> Graph:
    """
    Generate cycle graph C_n.

    Args:
        n: Number of nodes.
        directed: Whether to create directed cycle.

    Returns:
        Cycle graph.
    """
    graph_type = GraphType.DIRECTED if directed else GraphType.UNDIRECTED
    g = Graph(graph_type)

    for i in range(n):
        g.add_node(i)

    for i in range(n):
        next_node = (i + 1) % n
        g.add_edge(i, next_node, weight=1.0)
        if not directed:
            g.add_edge(next_node, i, weight=1.0)

    return g


def grid_graph(rows: int, cols: int, directed: bool = False) -> Graph:
    """
    Generate grid/lattice graph.

    Args:
        rows: Number of rows.
        cols: Number of columns.
        directed: Whether to create directed grid.

    Returns:
        Grid graph.
    """
    graph_type = GraphType.DIRECTED if directed else GraphType.UNDIRECTED
    g = Graph(graph_type)

    # Add nodes
    for i in range(rows):
        for j in range(cols):
            g.add_node((i, j))

    # Add edges
    for i in range(rows):
        for j in range(cols):
            # Right neighbor
            if j + 1 < cols:
                g.add_edge((i, j), (i, j + 1), weight=1.0)
                if not directed:
                    g.add_edge((i, j + 1), (i, j), weight=1.0)

            # Bottom neighbor
            if i + 1 < rows:
                g.add_edge((i, j), (i + 1, j), weight=1.0)
                if not directed:
                    g.add_edge((i + 1, j), (i, j), weight=1.0)

    return g


def star_graph(n: int, directed: bool = False) -> Graph:
    """
    Generate star graph (one central node connected to n-1 leaves).

    Args:
        n: Number of nodes.
        directed: Whether to create directed star.

    Returns:
        Star graph.
    """
    graph_type = GraphType.DIRECTED if directed else GraphType.UNDIRECTED
    g = Graph(graph_type)

    # Add center
    g.add_node(0)

    # Add leaves
    for i in range(1, n):
        g.add_node(i)
        g.add_edge(0, i, weight=1.0)
        if not directed:
            g.add_edge(i, 0, weight=1.0)

    return g


def random_tree(n: int, seed: int = 42) -> Graph:
    """
    Generate random tree using random walk method.

    Args:
        n: Number of nodes.
        seed: Random seed.

    Returns:
        Random tree.
    """
    random.seed(seed)

    g = Graph(GraphType.UNDIRECTED)

    if n <= 0:
        return g

    g.add_node(0)

    # Add remaining nodes
    for new_node in range(1, n):
        g.add_node(new_node)

        # Connect to random existing node
        existing_node = random.randint(0, new_node - 1)
        g.add_edge(existing_node, new_node, weight=1.0)

    return g


def random_bipartite_graph(
    left_size: int, right_size: int, p: float = 0.5, seed: int = 42
) -> tuple[Graph, list[int], list[int]]:
    """
    Generate random bipartite graph.

    Args:
        left_size: Number of nodes in left partition.
        right_size: Number of nodes in right partition.
        p: Edge probability between partitions.
        seed: Random seed.

    Returns:
        Tuple of (graph, left_nodes, right_nodes).
    """
    random.seed(seed)

    g = Graph(GraphType.UNDIRECTED)

    left_nodes = list(range(left_size))
    right_nodes = list(range(left_size, left_size + right_size))

    # Add all nodes
    for node in left_nodes + right_nodes:
        g.add_node(node)

    # Add edges between partitions
    for left in left_nodes:
        for right in right_nodes:
            if random.random() < p:
                g.add_edge(left, right, weight=1.0)

    return g, left_nodes, right_nodes
