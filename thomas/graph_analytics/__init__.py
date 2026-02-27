"""
Graph Analytics Module

A comprehensive graph analysis library providing algorithms for shortest paths,
centrality measures, community detection, network flow, and more.

Public API exports core classes and functions for common tasks.
"""

from thomas.graph_analytics._exceptions import (
    GraphAnalyticsError,
    GraphNotConnectedError,
    NegativeCycleError,
)
from thomas.graph_analytics._types import (
    AnalyticsConfig,
    CentralityResult,
    CommunityResult,
    Edge,
    GraphType,
    Node,
    PathResult,
)
from thomas.graph_analytics.centrality import (
    betweenness_centrality,
    closeness_centrality,
    degree_centrality,
    eigenvector_centrality,
    hits,
    katz_centrality,
    pagerank,
)
from thomas.graph_analytics.community import (
    girvan_newman,
    kclique_communities,
    label_propagation,
    louvain_method,
    modularity_score,
)
from thomas.graph_analytics.flow import (
    max_flow_edmonds_karp,
    maximum_bipartite_matching,
    min_cost_flow,
    min_cut,
)
from thomas.graph_analytics.generators import (
    barabasi_albert_graph,
    complete_graph,
    cycle_graph,
    erdos_renyi_graph,
    grid_graph,
    random_bipartite_graph,
    random_tree,
    star_graph,
    watts_strogatz_graph,
)
from thomas.graph_analytics.graph import Graph
from thomas.graph_analytics.partitioning import (
    balanced_partitioning,
    kernighan_lin_partitioning,
    spectral_partitioning,
)
from thomas.graph_analytics.shortest_path import (
    astar_shortest_path,
    bellman_ford_shortest_path,
    bfs_shortest_path,
    bidirectional_dijkstra,
    dijkstra_shortest_path,
    floyd_warshall_all_pairs,
)
from thomas.graph_analytics.spanning_tree import (
    boruvka_mst,
    kruskal_mst,
    prim_mst,
)
from thomas.graph_analytics.traversal import (
    bfs_traversal,
    connected_components,
    detect_cycle,
    dfs_traversal,
    eulerian_path_exists,
    hamiltonian_path_backtrack,
    strongly_connected_components,
    topological_sort,
)

__version__ = "1.0.0"
__author__ = "Graph Analytics"

__all__ = [
    # Types
    "Graph",
    "Node",
    "Edge",
    "GraphType",
    "PathResult",
    "CommunityResult",
    "CentralityResult",
    "AnalyticsConfig",
    # Exceptions
    "GraphAnalyticsError",
    "GraphNotConnectedError",
    "NegativeCycleError",
    # Shortest Path
    "bfs_shortest_path",
    "dijkstra_shortest_path",
    "bellman_ford_shortest_path",
    "floyd_warshall_all_pairs",
    "astar_shortest_path",
    "bidirectional_dijkstra",
    # Centrality
    "degree_centrality",
    "betweenness_centrality",
    "closeness_centrality",
    "eigenvector_centrality",
    "pagerank",
    "katz_centrality",
    "hits",
    # Community
    "label_propagation",
    "louvain_method",
    "girvan_newman",
    "kclique_communities",
    "modularity_score",
    # Traversal
    "bfs_traversal",
    "dfs_traversal",
    "topological_sort",
    "detect_cycle",
    "connected_components",
    "strongly_connected_components",
    "eulerian_path_exists",
    "hamiltonian_path_backtrack",
    # Flow
    "max_flow_edmonds_karp",
    "min_cut",
    "maximum_bipartite_matching",
    "min_cost_flow",
    # Spanning Tree
    "kruskal_mst",
    "prim_mst",
    "boruvka_mst",
    # Partitioning
    "spectral_partitioning",
    "kernighan_lin_partitioning",
    "balanced_partitioning",
    # Generators
    "erdos_renyi_graph",
    "barabasi_albert_graph",
    "watts_strogatz_graph",
    "complete_graph",
    "cycle_graph",
    "grid_graph",
    "star_graph",
    "random_tree",
    "random_bipartite_graph",
]
