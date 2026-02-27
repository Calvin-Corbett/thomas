"""
Tests for navigation mesh pathfinding algorithms.
"""

from thomas.pathfinding import NavigationMesh, NavMeshPolygon, Obstacle
from thomas.pathfinding.navmesh import (
    build_navmesh,
    closest_point_on_navmesh,
    expand_navmesh_for_agent,
    find_path_navmesh,
    funnel_algorithm,
)


class TestNavMeshPolygon:
    """Tests for NavMeshPolygon."""

    def test_polygon_creation(self) -> None:
        """Test creating a polygon."""
        vertices = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(0.5, 0.5))

        assert polygon.id == 0
        assert len(polygon.vertices) == 4
        assert polygon.center == (0.5, 0.5)

    def test_point_in_polygon(self) -> None:
        """Test point containment in polygon."""
        vertices = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(1.0, 1.0))

        assert polygon.contains_point(1.0, 1.0)
        assert not polygon.contains_point(-1.0, -1.0)
        assert not polygon.contains_point(3.0, 3.0)

    def test_polygon_distance(self) -> None:
        """Test distance calculation to polygon."""
        vertices = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(1.0, 1.0))

        dist_inside = polygon.distance_to_point(1.0, 1.0)
        assert dist_inside == 0.0

    def test_polygon_neighbors(self) -> None:
        """Test neighbor management."""
        polygon = NavMeshPolygon(id=0, vertices=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)))

        polygon.neighbors.add(1)
        polygon.neighbors.add(2)

        assert 1 in polygon.neighbors
        assert 2 in polygon.neighbors


class TestNavigationMesh:
    """Tests for NavigationMesh."""

    def test_navmesh_creation(self) -> None:
        """Test creating a navigation mesh."""
        navmesh = NavigationMesh()

        assert len(navmesh.polygons) == 0
        assert len(navmesh.portals) == 0

    def test_add_polygons(self) -> None:
        """Test adding polygons to navmesh."""
        navmesh = NavigationMesh()

        polygon = NavMeshPolygon(id=0, vertices=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)))
        navmesh.polygons[0] = polygon

        assert 0 in navmesh.polygons

    def test_containing_polygon(self) -> None:
        """Test finding polygon containing point."""
        navmesh = NavigationMesh()

        vertices = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(1.0, 1.0))
        navmesh.polygons[0] = polygon

        poly_id = navmesh.get_containing_polygon(1.0, 1.0)

        assert poly_id == 0

    def test_no_containing_polygon(self) -> None:
        """Test when point is not in any polygon."""
        navmesh = NavigationMesh()

        vertices = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(0.5, 0.5))
        navmesh.polygons[0] = polygon

        poly_id = navmesh.get_containing_polygon(5.0, 5.0)

        assert poly_id is None


class TestBuildNavmesh:
    """Tests for navmesh building."""

    def test_build_simple_navmesh(self) -> None:
        """Test building a simple navmesh."""
        obstacles = [Obstacle(5.0, 5.0, 15.0, 15.0)]

        navmesh = build_navmesh(
            obstacles,
            mesh_width=20.0,
            mesh_height=20.0,
            cell_size=10.0,
        )

        assert len(navmesh.polygons) > 0

    def test_navmesh_avoids_obstacles(self) -> None:
        """Test that navmesh doesn't include obstacle regions."""
        obstacles = [Obstacle(10.0, 10.0, 20.0, 20.0)]

        navmesh = build_navmesh(
            obstacles,
            mesh_width=30.0,
            mesh_height=30.0,
            cell_size=5.0,
        )

        containing = None
        for poly_id, polygon in navmesh.polygons.items():
            if polygon.contains_point(15.0, 15.0):
                containing = poly_id
                break

        assert containing is None


class TestFunnelAlgorithm:
    """Tests for funnel algorithm."""

    def test_funnel_simple_path(self) -> None:
        """Test funnel algorithm on simple path."""
        waypoints = [
            (0.0, 0.0),
            (1.0, 1.0),
            (2.0, 2.0),
            (3.0, 3.0),
        ]

        result = funnel_algorithm(waypoints)

        assert len(result) <= len(waypoints)

    def test_funnel_removes_unnecessary_waypoints(self) -> None:
        """Test that funnel removes collinear waypoints."""
        waypoints = [
            (0.0, 0.0),
            (1.0, 0.0),
            (2.0, 0.0),
            (3.0, 0.0),
        ]

        result = funnel_algorithm(waypoints)

        assert len(result) <= 2

    def test_funnel_keeps_necessary_waypoints(self) -> None:
        """Test that funnel keeps necessary waypoints."""
        waypoints = [
            (0.0, 0.0),
            (1.0, 1.0),
            (2.0, 0.0),
        ]

        result = funnel_algorithm(waypoints)

        assert len(result) >= 2

    def test_funnel_two_points(self) -> None:
        """Test funnel with just two points."""
        waypoints = [(0.0, 0.0), (1.0, 1.0)]

        result = funnel_algorithm(waypoints)

        assert len(result) == 2


class TestFindPathNavmesh:
    """Tests for pathfinding on navmesh."""

    def test_path_within_polygon(self) -> None:
        """Test finding path within single polygon."""
        navmesh = NavigationMesh()

        vertices = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(5.0, 5.0))
        navmesh.polygons[0] = polygon

        result = find_path_navmesh(navmesh, 1.0, 1.0, 8.0, 8.0)

        assert result.found

    def test_path_not_found_outside_mesh(self) -> None:
        """Test when start or goal outside mesh."""
        navmesh = NavigationMesh()

        vertices = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(5.0, 5.0))
        navmesh.polygons[0] = polygon

        result = find_path_navmesh(navmesh, -5.0, -5.0, 5.0, 5.0)

        assert not result.found


class TestClosestPointOnNavmesh:
    """Tests for closest point computation."""

    def test_closest_point_inside_polygon(self) -> None:
        """Test closest point when inside polygon."""
        navmesh = NavigationMesh()

        vertices = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(5.0, 5.0))
        navmesh.polygons[0] = polygon

        closest = closest_point_on_navmesh(navmesh, 5.0, 5.0)

        assert closest is not None

    def test_closest_point_outside_polygon(self) -> None:
        """Test closest point when outside polygon."""
        navmesh = NavigationMesh()

        vertices = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(5.0, 5.0))
        navmesh.polygons[0] = polygon

        closest = closest_point_on_navmesh(navmesh, 15.0, 15.0)

        assert closest is not None
        assert closest[0] <= 10.0
        assert closest[1] <= 10.0


class TestExpandNavmeshForAgent:
    """Tests for agent-aware navmesh expansion."""

    def test_expand_navmesh(self) -> None:
        """Test expanding navmesh for agent radius."""
        navmesh = NavigationMesh()

        vertices = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(5.0, 5.0))
        navmesh.polygons[0] = polygon

        expanded = expand_navmesh_for_agent(navmesh, agent_radius=1.0)

        assert len(expanded.polygons) > 0
        assert expanded.agent_radius == 1.0

    def test_expanded_navmesh_different_vertices(self) -> None:
        """Test that expanded navmesh has different vertices."""
        navmesh = NavigationMesh()

        vertices = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(5.0, 5.0))
        navmesh.polygons[0] = polygon

        expanded = expand_navmesh_for_agent(navmesh, agent_radius=1.0)

        if 0 in expanded.polygons:
            assert expanded.polygons[0].vertices != vertices


class TestNavmeshMetrics:
    """Test metrics from navmesh pathfinding."""

    def test_execution_time_recorded(self) -> None:
        """Test that execution time is recorded."""
        navmesh = NavigationMesh()

        vertices = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(5.0, 5.0))
        navmesh.polygons[0] = polygon

        result = find_path_navmesh(navmesh, 1.0, 1.0, 8.0, 8.0)

        assert result.execution_time >= 0.0

    def test_nodes_expanded_tracked(self) -> None:
        """Test that nodes expanded is tracked."""
        navmesh = NavigationMesh()

        vertices = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        polygon = NavMeshPolygon(id=0, vertices=vertices, center=(5.0, 5.0))
        navmesh.polygons[0] = polygon

        result = find_path_navmesh(navmesh, 1.0, 1.0, 8.0, 8.0)

        if result.found:
            assert result.nodes_expanded > 0
