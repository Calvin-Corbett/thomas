"""
Comprehensive pathfinding and navigation module.

This module provides multiple pathfinding algorithms including classical graph search,
grid-based search, navigation meshes, hierarchical pathfinding, flow fields, sampling-based
planning, steering behaviors, and dynamic pathfinding.
"""

from thomas.marketplace.pathfinding._exceptions import (
    InfiniteLoopError,
    InvalidGraphError,
    InvalidPositionError,
    NoPathFoundError,
    PathfindingException,
)
from thomas.marketplace.pathfinding._types import (
    AgentConfig,
    Edge,
    Graph,
    Grid2D,
    GridCell,
    NavigationMesh,
    NavMeshPolygon,
    Node,
    Obstacle,
    Path,
    PathResult,
    Portal,
)
from thomas.marketplace.pathfinding.classical import (
    astar,
    beam_search,
    bellman_ford,
    bidirectional_dijkstra,
    dijkstra,
    floyd_warshall,
    iterative_deepening_astar,
)
from thomas.marketplace.pathfinding.dynamic import (
    DStarLite,
    DynamicPathfinder,
    LifetimePlanningAStar,
)
from thomas.marketplace.pathfinding.flow_field import (
    FlowFieldCache,
    compute_flow_field,
    compute_integration_field,
    portal_flow_field,
    sample_flow_field,
    sector_based_flow,
)
from thomas.marketplace.pathfinding.graph import (
    build_adjacency_matrix,
    build_graph_from_grid,
    build_graph_from_waypoints,
    build_reverse_graph,
    deserialize_graph,
    detect_cycles,
    diameter,
    extract_subgraph,
    find_connected_components,
    graph_density,
    is_strongly_connected,
    serialize_graph,
    shortest_path_distances,
    topological_sort,
)
from thomas.marketplace.pathfinding.grid_search import (
    grid_search_astar,
    jump_point_search,
    theta_star,
)
from thomas.marketplace.pathfinding.hierarchical import (
    HierarchicalPathfinder,
    build_hpa_star,
)
from thomas.marketplace.pathfinding.navmesh import (
    build_navmesh,
    closest_point_on_navmesh,
    expand_navmesh_for_agent,
    find_path_navmesh,
    funnel_algorithm,
)
from thomas.marketplace.pathfinding.rrt import (
    informed_rrt_star,
    probabilistic_roadmap,
    rrt,
    rrt_connect,
    rrt_star,
)
from thomas.marketplace.pathfinding.steering import (
    Boid,
    arrive,
    evade,
    flee,
    flocking,
    flow_field_following,
    group_movement,
    obstacle_avoidance,
    path_following,
    pursue,
    seek,
    wander,
)

__all__ = [
    # Types
    "Node",
    "Edge",
    "Graph",
    "GridCell",
    "Grid2D",
    "Path",
    "PathResult",
    "NavigationMesh",
    "NavMeshPolygon",
    "Portal",
    "Obstacle",
    "AgentConfig",
    # Exceptions
    "PathfindingException",
    "NoPathFoundError",
    "InvalidGraphError",
    "InvalidPositionError",
    "InfiniteLoopError",
    # Graph utilities
    "build_graph_from_grid",
    "build_graph_from_waypoints",
    "extract_subgraph",
    "serialize_graph",
    "deserialize_graph",
    "find_connected_components",
    "topological_sort",
    "build_adjacency_matrix",
    "build_reverse_graph",
    "is_strongly_connected",
    "detect_cycles",
    "graph_density",
    "shortest_path_distances",
    "diameter",
    # Classical algorithms
    "dijkstra",
    "astar",
    "bellman_ford",
    "floyd_warshall",
    "bidirectional_dijkstra",
    "iterative_deepening_astar",
    "beam_search",
    # Grid search
    "jump_point_search",
    "theta_star",
    "grid_search_astar",
    # Navigation mesh
    "build_navmesh",
    "find_path_navmesh",
    "funnel_algorithm",
    "closest_point_on_navmesh",
    "expand_navmesh_for_agent",
    # Hierarchical
    "HierarchicalPathfinder",
    "build_hpa_star",
    # Flow fields
    "compute_integration_field",
    "compute_flow_field",
    "sample_flow_field",
    "FlowFieldCache",
    "portal_flow_field",
    "sector_based_flow",
    # RRT/PRM
    "rrt",
    "rrt_star",
    "rrt_connect",
    "informed_rrt_star",
    "probabilistic_roadmap",
    # Steering
    "Boid",
    "seek",
    "flee",
    "arrive",
    "pursue",
    "evade",
    "wander",
    "obstacle_avoidance",
    "flocking",
    "path_following",
    "group_movement",
    "flow_field_following",
    # Dynamic
    "DStarLite",
    "LifetimePlanningAStar",
    "DynamicPathfinder",
]

__version__ = "1.0.0"
