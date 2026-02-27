"""
Core type definitions for the pathfinding module.

This module defines all the fundamental data structures used throughout the pathfinding system,
including nodes, edges, graphs, grids, paths, navigation meshes, and agent configurations.
"""

import math
from dataclasses import dataclass, field
from typing import (
    Any,
    Protocol,
)


@dataclass(frozen=True)
class Node:
    """
    Represents a node in a graph.

    Attributes:
        id: Unique identifier for the node.
        x: X coordinate (for spatial nodes).
        y: Y coordinate (for spatial nodes).
        z: Z coordinate (for 3D spatial nodes).
        data: Optional arbitrary data associated with the node.
    """

    id: int | str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    data: Any | None = None

    def distance_to(self, other: "Node") -> float:
        """Calculate Euclidean distance to another node."""
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def distance_2d(self, other: "Node") -> float:
        """Calculate 2D Euclidean distance to another node."""
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)

    def manhattan_distance(self, other: "Node") -> float:
        """Calculate Manhattan distance to another node."""
        return abs(self.x - other.x) + abs(self.y - other.y) + abs(self.z - other.z)

    def chebyshev_distance(self, other: "Node") -> float:
        """Calculate Chebyshev distance to another node."""
        return max(abs(self.x - other.x), abs(self.y - other.y), abs(self.z - other.z))


@dataclass(frozen=True)
class Edge:
    """
    Represents an edge between two nodes in a graph.

    Attributes:
        from_node: Source node ID.
        to_node: Destination node ID.
        weight: Cost of traversing the edge (default 1.0).
        data: Optional arbitrary data associated with the edge.
    """

    from_node: int | str
    to_node: int | str
    weight: float = 1.0
    data: Any | None = None


@dataclass
class Graph:
    """
    Represents a weighted directed or undirected graph using adjacency list.

    Attributes:
        nodes: Dictionary mapping node IDs to Node objects.
        edges: Dictionary mapping node IDs to lists of (neighbor_id, weight) tuples.
        directed: Whether the graph is directed.
    """

    nodes: dict[int | str, Node] = field(default_factory=dict)
    edges: dict[int | str, list[tuple[int | str, float]]] = field(default_factory=dict)
    directed: bool = True

    def add_node(self, node: Node) -> None:
        """Add a node to the graph."""
        self.nodes[node.id] = node
        if node.id not in self.edges:
            self.edges[node.id] = []

    def add_edge(self, from_id: int | str, to_id: int | str, weight: float = 1.0) -> None:
        """Add an edge to the graph."""
        if from_id not in self.nodes or to_id not in self.nodes:
            raise ValueError("Both nodes must exist in graph")
        self.edges[from_id].append((to_id, weight))
        if not self.directed:
            self.edges[to_id].append((from_id, weight))

    def get_neighbors(self, node_id: int | str) -> list[tuple[int | str, float]]:
        """Get neighbors and edge weights for a node."""
        return self.edges.get(node_id, [])

    def get_node(self, node_id: int | str) -> Node | None:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def has_edge(self, from_id: int | str, to_id: int | str) -> bool:
        """Check if an edge exists."""
        for neighbor, _ in self.edges.get(from_id, []):
            if neighbor == to_id:
                return True
        return False


@dataclass(frozen=True)
class GridCell:
    """
    Represents a single cell in a 2D grid.

    Attributes:
        x: Grid column index.
        y: Grid row index.
        cost: Movement cost for this cell (1.0 = normal, > 1.0 = terrain).
        walkable: Whether the cell is traversable.
    """

    x: int
    y: int
    cost: float = 1.0
    walkable: bool = True


@dataclass
class Grid2D:
    """
    Represents a 2D grid for pathfinding.

    Attributes:
        width: Grid width in cells.
        height: Grid height in cells.
        cells: 2D array of GridCell objects.
        diagonal_movement: Whether diagonal movement is allowed.
    """

    width: int
    height: int
    cells: list[list[GridCell]] = field(default_factory=list)
    diagonal_movement: bool = False

    def __post_init__(self) -> None:
        """Initialize grid cells if empty."""
        if not self.cells:
            self.cells = [[GridCell(x, y) for x in range(self.width)] for y in range(self.height)]

    def is_walkable(self, x: int, y: int) -> bool:
        """Check if a cell is walkable."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        return self.cells[y][x].walkable

    def get_neighbors(self, x: int, y: int) -> list[tuple[int, int, float]]:
        """Get walkable neighbors with costs."""
        neighbors: list[tuple[int, int, float]] = []
        directions = [(0, 1), (1, 0), (0, -1), (-1, 0)]
        if self.diagonal_movement:
            directions.extend([(1, 1), (1, -1), (-1, 1), (-1, -1)])

        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            if self.is_walkable(nx, ny):
                cost = self.cells[ny][nx].cost
                neighbors.append((nx, ny, cost))
        return neighbors

    def set_walkable(self, x: int, y: int, walkable: bool) -> None:
        """Set cell walkability."""
        if 0 <= x < self.width and 0 <= y < self.height:
            cell = self.cells[y][x]
            self.cells[y][x] = GridCell(x, y, cell.cost, walkable)

    def set_cost(self, x: int, y: int, cost: float) -> None:
        """Set cell movement cost."""
        if 0 <= x < self.width and 0 <= y < self.height:
            cell = self.cells[y][x]
            self.cells[y][x] = GridCell(x, y, cost, cell.walkable)


@dataclass(frozen=True)
class Path:
    """
    Represents a path as a sequence of nodes.

    Attributes:
        nodes: Sequence of node IDs forming the path.
        cost: Total cost of the path.
    """

    nodes: tuple[int | str, ...] = field(default_factory=tuple)
    cost: float = 0.0

    def length(self) -> int:
        """Return the number of nodes in the path."""
        return len(self.nodes)

    def is_empty(self) -> bool:
        """Check if path is empty."""
        return len(self.nodes) == 0


@dataclass
class PathResult:
    """
    Represents the result of a pathfinding query.

    Attributes:
        found: Whether a path was found.
        path: The path (empty if not found).
        cost: Total cost of the path.
        nodes_expanded: Number of nodes expanded during search.
        nodes_generated: Number of nodes generated during search.
        execution_time: Time spent searching in seconds.
    """

    found: bool
    path: Path = field(default_factory=Path)
    cost: float = 0.0
    nodes_expanded: int = 0
    nodes_generated: int = 0
    execution_time: float = 0.0


class Heuristic(Protocol):
    """
    Protocol for heuristic functions used in informed search.

    A heuristic estimates the cost from a node to the goal.
    """

    def __call__(self, node: Node, goal: Node) -> float:
        """
        Estimate cost from node to goal.

        Args:
            node: Current node.
            goal: Goal node.

        Returns:
            Estimated cost.
        """
        ...


class CostFunction(Protocol):
    """
    Protocol for cost functions used in pathfinding.

    Maps two nodes to a traversal cost.
    """

    def __call__(self, from_node: Node, to_node: Node) -> float:
        """
        Compute cost to traverse from one node to another.

        Args:
            from_node: Source node.
            to_node: Destination node.

        Returns:
            Traversal cost.
        """
        ...


@dataclass(frozen=True)
class NavMeshPolygon:
    """
    Represents a convex polygon in a navigation mesh.

    Attributes:
        id: Unique polygon identifier.
        vertices: Tuple of (x, y) vertices in order.
        center: Center point of the polygon.
        neighbors: Set of adjacent polygon IDs.
    """

    id: int
    vertices: tuple[tuple[float, float], ...] = field(default_factory=tuple)
    center: tuple[float, float] = (0.0, 0.0)
    neighbors: set[int] = field(default_factory=set)

    def contains_point(self, x: float, y: float) -> bool:
        """Check if point is inside polygon using ray casting."""
        vertices = self.vertices
        n = len(vertices)
        inside = False
        j = n - 1

        for i in range(n):
            xi, yi = vertices[i]
            xj, yj = vertices[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    def closest_point_on_edge(self, x: float, y: float) -> tuple[float, float]:
        """Find closest point on polygon boundary."""
        vertices = self.vertices
        min_dist = float("inf")
        closest = vertices[0]

        for i in range(len(vertices)):
            v1 = vertices[i]
            v2 = vertices[(i + 1) % len(vertices)]
            point = _closest_point_on_segment(x, y, v1[0], v1[1], v2[0], v2[1])
            dist = math.sqrt((point[0] - x) ** 2 + (point[1] - y) ** 2)
            if dist < min_dist:
                min_dist = dist
                closest = point

        return closest

    def distance_to_point(self, x: float, y: float) -> float:
        """Calculate distance to point."""
        if self.contains_point(x, y):
            return 0.0
        closest = self.closest_point_on_edge(x, y)
        return math.sqrt((closest[0] - x) ** 2 + (closest[1] - y) ** 2)


@dataclass(frozen=True)
class Portal:
    """
    Represents a portal (edge) between two navigation mesh polygons.

    Attributes:
        id: Unique portal identifier.
        from_poly: Source polygon ID.
        to_poly: Destination polygon ID.
        p1: First endpoint.
        p2: Second endpoint.
    """

    id: int
    from_poly: int
    to_poly: int
    p1: tuple[float, float]
    p2: tuple[float, float]

    def midpoint(self) -> tuple[float, float]:
        """Get midpoint of portal."""
        return ((self.p1[0] + self.p2[0]) / 2, (self.p1[1] + self.p2[1]) / 2)

    def length(self) -> float:
        """Get length of portal."""
        dx = self.p2[0] - self.p1[0]
        dy = self.p2[1] - self.p1[1]
        return math.sqrt(dx * dx + dy * dy)


@dataclass
class NavigationMesh:
    """
    Represents a navigation mesh for pathfinding.

    Attributes:
        polygons: Dictionary mapping polygon IDs to NavMeshPolygon objects.
        portals: List of Portal objects connecting polygons.
        agent_radius: Radius of agents navigating the mesh.
    """

    polygons: dict[int, NavMeshPolygon] = field(default_factory=dict)
    portals: list[Portal] = field(default_factory=list)
    agent_radius: float = 0.5

    def get_containing_polygon(self, x: float, y: float) -> int | None:
        """Find polygon containing point."""
        for poly_id, polygon in self.polygons.items():
            if polygon.contains_point(x, y):
                return poly_id
        return None

    def get_portals_from(self, from_poly: int) -> list[Portal]:
        """Get all portals from a polygon."""
        return [p for p in self.portals if p.from_poly == from_poly]


@dataclass(frozen=True)
class Obstacle:
    """
    Represents an axis-aligned rectangular obstacle.

    Attributes:
        x1: Left boundary.
        y1: Bottom boundary.
        x2: Right boundary.
        y2: Top boundary.
    """

    x1: float
    y1: float
    x2: float
    y2: float

    def contains_point(self, x: float, y: float) -> bool:
        """Check if point is inside obstacle."""
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def intersects_circle(self, x: float, y: float, radius: float) -> bool:
        """Check if circle overlaps obstacle."""
        closest_x = max(self.x1, min(x, self.x2))
        closest_y = max(self.y1, min(y, self.y2))
        dist = math.sqrt((x - closest_x) ** 2 + (y - closest_y) ** 2)
        return dist < radius


@dataclass
class AgentConfig:
    """
    Configuration for pathfinding agents.

    Attributes:
        radius: Agent collision radius.
        max_speed: Maximum movement speed.
        max_acceleration: Maximum acceleration.
        preferred_speed: Preferred movement speed.
        stopping_distance: Distance to stop before goal.
        view_distance: Perception/planning distance.
    """

    radius: float = 0.5
    max_speed: float = 5.0
    max_acceleration: float = 2.0
    preferred_speed: float = 3.0
    stopping_distance: float = 0.1
    view_distance: float = 50.0


def _closest_point_on_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    """Find closest point on line segment."""
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return (x1, y1)

    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return (x1 + t * dx, y1 + t * dy)
