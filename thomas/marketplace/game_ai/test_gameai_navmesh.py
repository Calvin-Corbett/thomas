"""
Tests for navigation mesh system.

Tests pathfinding, string-pulling, spatial queries, and mesh operations.
"""

import unittest

from thomas.marketplace.game_ai._exceptions import PathfindingError
from thomas.marketplace.game_ai._types import NavMeshPolygon, Vec2
from thomas.marketplace.game_ai.navmesh import NavMesh, NavMeshQuery


class TestNavMeshPolygon(unittest.TestCase):
    """Test NavMeshPolygon class."""

    def test_polygon_creation(self):
        """Test creating a polygon."""
        vertices = [Vec2(0, 0), Vec2(10, 0), Vec2(10, 10), Vec2(0, 10)]
        poly = NavMeshPolygon(id=1, vertices=vertices)

        self.assertEqual(poly.id, 1)
        self.assertEqual(len(poly.vertices), 4)

    def test_polygon_center(self):
        """Test polygon center calculation."""
        vertices = [Vec2(0, 0), Vec2(10, 0), Vec2(10, 10), Vec2(0, 10)]
        poly = NavMeshPolygon(id=1, vertices=vertices)

        center = poly.center()

        self.assertEqual(center.x, 5.0)
        self.assertEqual(center.y, 5.0)

    def test_point_in_polygon(self):
        """Test point containment check."""
        vertices = [Vec2(0, 0), Vec2(10, 0), Vec2(10, 10), Vec2(0, 10)]
        poly = NavMeshPolygon(id=1, vertices=vertices)

        # Point inside
        self.assertTrue(poly.contains_point(Vec2(5, 5)))

        # Point outside
        self.assertFalse(poly.contains_point(Vec2(-1, 5)))
        self.assertFalse(poly.contains_point(Vec2(15, 5)))

    def test_point_on_edge(self):
        """Test point on edge."""
        vertices = [Vec2(0, 0), Vec2(10, 0), Vec2(10, 10), Vec2(0, 10)]
        poly = NavMeshPolygon(id=1, vertices=vertices)

        # On edge
        self.assertTrue(poly.contains_point(Vec2(5, 0)))


class TestNavMesh(unittest.TestCase):
    """Test NavMesh pathfinding."""

    def setUp(self):
        """Set up test mesh."""
        # Create simple 2x2 grid of polygons
        self.poly1 = NavMeshPolygon(id=1, vertices=[Vec2(0, 0), Vec2(10, 0), Vec2(10, 10), Vec2(0, 10)])

        self.poly2 = NavMeshPolygon(id=2, vertices=[Vec2(10, 0), Vec2(20, 0), Vec2(20, 10), Vec2(10, 10)])

        self.poly3 = NavMeshPolygon(id=3, vertices=[Vec2(0, 10), Vec2(10, 10), Vec2(10, 20), Vec2(0, 20)])

        self.poly4 = NavMeshPolygon(id=4, vertices=[Vec2(10, 10), Vec2(20, 10), Vec2(20, 20), Vec2(10, 20)])

        self.mesh = NavMesh([self.poly1, self.poly2, self.poly3, self.poly4])

    def test_find_polygon(self):
        """Test finding polygon containing point."""
        # Point in poly1
        poly_id = self.mesh.find_polygon(Vec2(5, 5))
        self.assertEqual(poly_id, 1)

        # Point in poly4
        poly_id = self.mesh.find_polygon(Vec2(15, 15))
        self.assertEqual(poly_id, 4)

    def test_find_polygon_none(self):
        """Test finding polygon when none contain point."""
        poly_id = self.mesh.find_polygon(Vec2(50, 50))
        self.assertIsNone(poly_id)

    def test_find_nearest_polygon(self):
        """Test finding nearest polygon."""
        # Point outside mesh
        nearest = self.mesh.find_nearest_polygon(Vec2(-5, -5))

        # Should find poly1 (closest)
        self.assertEqual(nearest, 1)

    def test_find_random_point(self):
        """Test generating random point on mesh."""
        point = self.mesh.find_random_point()

        self.assertIsNotNone(point)
        # Point should be on mesh
        self.assertIsNotNone(self.mesh.find_polygon(point))

    def test_adjacency_building(self):
        """Test adjacency graph construction."""
        # Poly1 should be adjacent to poly2 and poly3
        self.assertIn(2, self.poly1.edges)
        self.assertIn(3, self.poly1.edges)

        # Poly1 should not be adjacent to poly4
        self.assertNotIn(4, self.poly1.edges)

    def test_simple_path(self):
        """Test finding path in same polygon."""
        # Start and goal in same polygon
        path = self.mesh.find_path(Vec2(2, 2), Vec2(8, 8))

        self.assertEqual(len(path), 2)
        self.assertEqual(path[0], Vec2(2, 2))
        self.assertEqual(path[-1], Vec2(8, 8))

    def test_adjacent_polygon_path(self):
        """Test path between adjacent polygons."""
        # Start in poly1, goal in poly2
        path = self.mesh.find_path(Vec2(2, 5), Vec2(15, 5))

        self.assertGreater(len(path), 1)
        # Path should reach goal
        self.assertEqual(path[-1], Vec2(15, 5))

    def test_no_path_found(self):
        """Test when no path exists (disconnected components)."""
        # Create disconnected polygon
        isolated = NavMeshPolygon(id=5, vertices=[Vec2(50, 50), Vec2(60, 50), Vec2(60, 60), Vec2(50, 60)])
        self.mesh.add_polygon(isolated)

        # Path from connected to isolated should fail
        with self.assertRaises(PathfindingError):
            self.mesh.find_path(Vec2(5, 5), Vec2(55, 55))

    def test_invalid_start(self):
        """Test error when start not on mesh."""
        with self.assertRaises(PathfindingError):
            self.mesh.find_path(Vec2(-50, -50), Vec2(5, 5))

    def test_string_pulling(self):
        """Test string-pulling optimization."""
        # Create path with unnecessary waypoints
        waypoints = [
            Vec2(2, 2),
            Vec2(8, 2),
            Vec2(8, 8),
            Vec2(15, 8),
        ]

        smoothed = self.mesh._string_pull(waypoints)

        # Smoothed path should be shorter or equal
        self.assertLessEqual(len(smoothed), len(waypoints))


class TestNavMeshQuery(unittest.TestCase):
    """Test NavMeshQuery interface."""

    def setUp(self):
        """Set up test mesh."""
        poly1 = NavMeshPolygon(id=1, vertices=[Vec2(0, 0), Vec2(10, 0), Vec2(10, 10), Vec2(0, 10)])

        poly2 = NavMeshPolygon(id=2, vertices=[Vec2(10, 0), Vec2(20, 0), Vec2(20, 10), Vec2(10, 10)])

        self.mesh = NavMesh([poly1, poly2])
        self.query = NavMeshQuery(self.mesh)

    def test_find_path(self):
        """Test query find_path."""
        path = self.query.find_path(Vec2(2, 2), Vec2(15, 5))

        self.assertGreater(len(path), 0)

    def test_find_random_point(self):
        """Test query find_random_point."""
        point = self.query.find_random_point()

        self.assertIsNotNone(point)

    def test_find_nearest_point(self):
        """Test query find_nearest_point."""
        nearest = self.query.find_nearest_point(Vec2(-5, -5))

        self.assertIsNotNone(nearest)

    def test_is_reachable(self):
        """Test query is_reachable."""
        # Reachable points
        self.assertTrue(self.query.is_reachable(Vec2(2, 2), Vec2(15, 5)))

        # Unreachable (outside mesh)
        self.assertFalse(self.query.is_reachable(Vec2(2, 2), Vec2(-50, -50)))


class TestNavMeshComplexShapes(unittest.TestCase):
    """Test navmesh with complex polygon shapes."""

    def test_triangle_mesh(self):
        """Test mesh with triangular polygons."""
        poly1 = NavMeshPolygon(id=1, vertices=[Vec2(0, 0), Vec2(10, 0), Vec2(5, 10)])

        poly2 = NavMeshPolygon(id=2, vertices=[Vec2(10, 0), Vec2(20, 0), Vec2(15, 10)])

        mesh = NavMesh([poly1, poly2])

        # Path in triangle
        path = mesh.find_path(Vec2(2, 2), Vec2(8, 8))
        self.assertGreater(len(path), 0)

    def test_convex_mesh(self):
        """Test mesh with convex polygons."""
        # Pentagon
        import math

        vertices = []
        for i in range(5):
            angle = 2 * math.pi * i / 5
            vertices.append(Vec2(10 + 5 * math.cos(angle), 10 + 5 * math.sin(angle)))

        poly = NavMeshPolygon(id=1, vertices=vertices)
        mesh = NavMesh([poly])

        # Point in center
        self.assertIsNotNone(mesh.find_polygon(Vec2(10, 10)))


if __name__ == "__main__":
    unittest.main()
