"""
Navigation mesh pathfinding system.

Provides polygonal navigation mesh with A* pathfinding, string-pulling
(funnel algorithm) for smooth paths, and spatial queries.
"""

import heapq
import logging
import random
from dataclasses import dataclass

from thomas.marketplace.game_ai._exceptions import PathfindingError
from thomas.marketplace.game_ai._types import NavMeshPolygon, Vec2

logger = logging.getLogger(__name__)


@dataclass
class _NavMeshNode:
    """Internal node for A* search on navmesh."""

    polygon_id: int
    g_score: float
    h_score: float

    @property
    def f_score(self) -> float:
        """f = g + h for A* priority."""
        return self.g_score + self.h_score

    def __lt__(self, other: "_NavMeshNode") -> bool:
        """Compare by f-score for heap ordering."""
        return self.f_score < other.f_score


class NavMesh:
    """Navigation mesh for pathfinding on polygon-based terrain."""

    def __init__(self, polygons: list[NavMeshPolygon] | None = None) -> None:
        """Initialize navigation mesh.

        Args:
            polygons: List of NavMeshPolygon objects defining walkable areas
        """
        self.polygons: dict[int, NavMeshPolygon] = {}
        self._agent_radius = 0.0

        if polygons:
            for poly in polygons:
                self.add_polygon(poly)

        self._build_adjacency()

    def add_polygon(self, polygon: NavMeshPolygon) -> None:
        """Add polygon to mesh.

        Args:
            polygon: NavMeshPolygon to add
        """
        self.polygons[polygon.id] = polygon

    def add_polygons(self, polygons: list[NavMeshPolygon]) -> None:
        """Add multiple polygons to mesh.

        Args:
            polygons: List of NavMeshPolygon objects
        """
        for poly in polygons:
            self.add_polygon(poly)
        self._build_adjacency()

    def set_agent_radius(self, radius: float) -> None:
        """Set agent radius for collision handling.

        Args:
            radius: Agent radius in world units
        """
        self._agent_radius = radius

    def _build_adjacency(self) -> None:
        """Build adjacency graph by finding shared edges."""
        # Reset edges
        for poly in self.polygons.values():
            poly.edges.clear()

        # For each polygon pair, check if they share an edge
        poly_list = list(self.polygons.values())
        for i, poly1 in enumerate(poly_list):
            for poly2 in poly_list[i + 1 :]:
                if self._polygons_share_edge(poly1, poly2):
                    poly1.edges.append(poly2.id)
                    poly2.edges.append(poly1.id)

    def _polygons_share_edge(self, poly1: NavMeshPolygon, poly2: NavMeshPolygon) -> bool:
        """Check if two polygons share an edge.

        Args:
            poly1: First polygon
            poly2: Second polygon

        Returns:
            True if polygons share an edge
        """
        # Count matching adjacent vertices
        shared_vertices = 0
        for v1 in poly1.vertices:
            for v2 in poly2.vertices:
                if v1 == v2:
                    shared_vertices += 1

        # Two shared vertices means shared edge
        return shared_vertices >= 2

    def find_polygon(self, point: Vec2) -> int | None:
        """Find polygon containing point.

        Args:
            point: World position to search for

        Returns:
            Polygon ID if found, None otherwise
        """
        for poly_id, poly in self.polygons.items():
            if poly.contains_point(point):
                return poly_id

        return None

    def find_nearest_polygon(self, point: Vec2) -> int | None:
        """Find nearest polygon to point.

        Args:
            point: World position

        Returns:
            Nearest polygon ID, or None if mesh is empty
        """
        if not self.polygons:
            return None

        nearest_id = None
        nearest_dist = float("inf")

        for poly_id, poly in self.polygons.items():
            center = poly.center()
            dist = point.distance_to(center)

            if dist < nearest_dist:
                nearest_dist = dist
                nearest_id = poly_id

        return nearest_id

    def find_random_point(self) -> Vec2 | None:
        """Find random point on navmesh.

        Args:
            Returns random point on navmesh, or None if empty

        Returns:
            Random Vec2 position, or None
        """
        if not self.polygons:
            return None

        # Pick random polygon
        poly = random.choice(list(self.polygons.values()))

        # Pick random point in polygon using barycentric coordinates
        if len(poly.vertices) < 3:
            return poly.center()

        # Simple method: pick random triangle in polygon
        v1, v2, v3 = poly.vertices[0], poly.vertices[1], poly.vertices[2]

        # Random barycentric coordinates
        r1, r2 = random.random(), random.random()
        if r1 + r2 > 1:
            r1, r2 = 1 - r1, 1 - r2

        point = Vec2(
            v1.x * (1 - r1 - r2) + v2.x * r1 + v3.x * r2,
            v1.y * (1 - r1 - r2) + v2.y * r1 + v3.y * r2,
        )

        return point

    def find_path(self, start: Vec2, goal: Vec2) -> list[Vec2]:
        """Find path from start to goal on navmesh.

        Uses A* search on polygon centers then string-pulling (funnel algorithm)
        to create smooth path.

        Args:
            start: Starting world position
            goal: Goal world position

        Returns:
            List of Vec2 waypoints, or empty list if no path found

        Raises:
            PathfindingError: If start or goal not on navmesh
        """
        # Find containing polygons
        start_poly = self.find_polygon(start)
        goal_poly = self.find_polygon(goal)

        # Fall back to nearest if not exactly on mesh
        if start_poly is None:
            start_poly = self.find_nearest_polygon(start)
        if goal_poly is None:
            goal_poly = self.find_nearest_polygon(goal)

        if start_poly is None or goal_poly is None:
            raise PathfindingError("Start or goal not on navmesh")

        if start_poly == goal_poly:
            return [start, goal]

        # A* search on polygon graph
        polygon_path = self._find_polygon_path(start_poly, goal_poly)

        if not polygon_path:
            return []

        # Build waypoint path through polygon centers
        waypoints = [start]

        for i in range(len(polygon_path) - 1):
            from_poly = self.polygons[polygon_path[i]]
            to_poly = self.polygons[polygon_path[i + 1]]

            # Find portal (shared edge) between polygons
            portal = self._find_portal(from_poly, to_poly)
            if portal:
                # Use midpoint of portal
                waypoints.append(portal)

        waypoints.append(goal)

        # String-pulling (funnel algorithm)
        return self._string_pull(waypoints)

    def _find_polygon_path(self, start: int, goal: int) -> list[int]:
        """A* search on polygon graph.

        Args:
            start: Starting polygon ID
            goal: Goal polygon ID

        Returns:
            List of polygon IDs from start to goal
        """
        open_set: list[tuple] = []
        counter = 0

        start_node = _NavMeshNode(start, 0, self._heuristic(start, goal))
        heapq.heappush(open_set, (start_node.f_score, counter, start_node))
        counter += 1

        closed_set: set[int] = set()
        g_scores: dict[int, float] = {start: 0}
        parents: dict[int, int] = {}

        while open_set:
            _, _, current_node = heapq.heappop(open_set)
            current_id = current_node.polygon_id

            if current_id in closed_set:
                continue

            if current_id == goal:
                # Reconstruct path
                path = []
                node = goal
                while node in parents:
                    path.append(node)
                    node = parents[node]
                path.append(start)
                return path[::-1]

            closed_set.add(current_id)

            current_poly = self.polygons[current_id]

            # Explore neighbors
            for neighbor_id in current_poly.edges:
                if neighbor_id in closed_set:
                    continue

                tentative_g = g_scores[current_id] + 1.0

                if neighbor_id not in g_scores or tentative_g < g_scores[neighbor_id]:
                    g_scores[neighbor_id] = tentative_g
                    h = self._heuristic(neighbor_id, goal)
                    f = tentative_g + h

                    parents[neighbor_id] = current_id
                    node = _NavMeshNode(neighbor_id, tentative_g, h)
                    heapq.heappush(open_set, (f, counter, node))
                    counter += 1

        return []

    def _heuristic(self, from_id: int, to_id: int) -> float:
        """Heuristic for A* (straight-line distance between polygon centers)."""
        if from_id not in self.polygons or to_id not in self.polygons:
            return 0.0

        from_center = self.polygons[from_id].center()
        to_center = self.polygons[to_id].center()

        return from_center.distance_to(to_center)

    def _find_portal(self, poly1: NavMeshPolygon, poly2: NavMeshPolygon) -> Vec2 | None:
        """Find portal (shared edge midpoint) between two polygons."""
        # Find shared vertices
        shared = []
        for v1 in poly1.vertices:
            for v2 in poly2.vertices:
                if v1 == v2:
                    shared.append(v1)

        if len(shared) >= 2:
            # Return midpoint of portal
            mid = (shared[0] + shared[1]) * 0.5
            return mid

        return None

    def _string_pull(self, waypoints: list[Vec2]) -> list[Vec2]:
        """String-pulling algorithm (funnel algorithm) for smooth paths.

        Args:
            waypoints: Initial waypoint path

        Returns:
            Smoothed path with unnecessary waypoints removed
        """
        if len(waypoints) <= 2:
            return waypoints

        smoothed = [waypoints[0]]
        current = 0

        while current < len(waypoints) - 1:
            # Try to skip to the farthest waypoint we can reach
            farthest = current + 1

            for next_idx in range(current + 2, len(waypoints)):
                # Check if we can line-of-sight to this waypoint
                if not self._path_blocked(waypoints[current], waypoints[next_idx]):
                    farthest = next_idx
                else:
                    break

            smoothed.append(waypoints[farthest])
            current = farthest

        return smoothed

    def _path_blocked(self, start: Vec2, end: Vec2) -> bool:
        """Check if direct path between two points is blocked by polygon boundaries.

        Simple implementation: return False (allow all paths).
        In a more complete implementation, this would check polygon boundaries.

        Args:
            start: Start position
            end: End position

        Returns:
            True if path is blocked
        """
        # Simplified: for now, allow all paths
        # A full implementation would check obstacle polygons
        return False


class NavMeshQuery:
    """Query interface for navigation mesh operations."""

    def __init__(self, navmesh: NavMesh) -> None:
        """Initialize query interface.

        Args:
            navmesh: NavMesh to query
        """
        self.navmesh = navmesh

    def find_path(self, start: Vec2, goal: Vec2) -> list[Vec2]:
        """Find path between two points.

        Args:
            start: Starting position
            goal: Goal position

        Returns:
            List of waypoints
        """
        return self.navmesh.find_path(start, goal)

    def find_random_point(self) -> Vec2 | None:
        """Get random point on navmesh.

        Returns:
            Random Vec2 position
        """
        return self.navmesh.find_random_point()

    def find_nearest_point(self, point: Vec2) -> Vec2 | None:
        """Find nearest point on navmesh to given position.

        Args:
            point: Reference position

        Returns:
            Nearest point on navmesh, or None
        """
        poly_id = self.navmesh.find_nearest_polygon(point)
        if poly_id is None:
            return None

        poly = self.navmesh.polygons[poly_id]
        return poly.center()

    def is_reachable(self, start: Vec2, goal: Vec2) -> bool:
        """Check if goal is reachable from start.

        Args:
            start: Starting position
            goal: Goal position

        Returns:
            True if path exists
        """
        try:
            path = self.navmesh.find_path(start, goal)
            return len(path) > 0
        except PathfindingError:
            return False
