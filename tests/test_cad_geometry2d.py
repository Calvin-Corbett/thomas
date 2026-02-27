"""
Tests for 2D geometry operations.
"""

import math

import pytest

from thomas.cad import geometry2d
from thomas.cad._types import Circle, Line, Point2D, Polygon, Vector2D


class TestPointAndVector:
    """Tests for Point2D and Vector2D."""

    def test_point_distance(self) -> None:
        """Test point distance calculation."""
        p1 = Point2D(0, 0)
        p2 = Point2D(3, 4)
        assert p1.distance_to(p2) == pytest.approx(5.0)

    def test_point_add_vector(self) -> None:
        """Test adding vector to point."""
        p = Point2D(1, 2)
        v = Vector2D(3, 4)
        result = p + v
        assert result.x == pytest.approx(4.0)
        assert result.y == pytest.approx(6.0)

    def test_vector_magnitude(self) -> None:
        """Test vector magnitude."""
        v = Vector2D(3, 4)
        assert v.magnitude() == pytest.approx(5.0)

    def test_vector_normalize(self) -> None:
        """Test vector normalization."""
        v = Vector2D(3, 4)
        normalized = v.normalize()
        assert normalized.magnitude() == pytest.approx(1.0)
        assert normalized.x == pytest.approx(0.6)
        assert normalized.y == pytest.approx(0.8)

    def test_vector_perpendicular(self) -> None:
        """Test perpendicular vector."""
        v = Vector2D(1, 0)
        perp = v.perpendicular()
        assert perp.x == pytest.approx(0)
        assert perp.y == pytest.approx(1)


class TestLineIntersection:
    """Tests for line intersection."""

    def test_line_line_intersection_cross(self) -> None:
        """Test intersection of crossing lines."""
        line1 = Line(Point2D(0, 0), Point2D(2, 2))
        line2 = Line(Point2D(0, 2), Point2D(2, 0))

        intersection = geometry2d.line_line_intersection(line1, line2)
        assert intersection is not None
        assert intersection.x == pytest.approx(1.0)
        assert intersection.y == pytest.approx(1.0)

    def test_line_line_no_intersection(self) -> None:
        """Test non-intersecting lines."""
        line1 = Line(Point2D(0, 0), Point2D(1, 0))
        line2 = Line(Point2D(0, 1), Point2D(1, 1))

        intersection = geometry2d.line_line_intersection(line1, line2)
        assert intersection is None

    def test_line_line_parallel(self) -> None:
        """Test parallel lines."""
        line1 = Line(Point2D(0, 0), Point2D(1, 0))
        line2 = Line(Point2D(0, 1), Point2D(1, 1))

        intersection = geometry2d.line_line_intersection(line1, line2)
        assert intersection is None


class TestLineCircleIntersection:
    """Tests for line-circle intersection."""

    def test_line_circle_intersection_two_points(self) -> None:
        """Test line intersecting circle at two points."""
        circle = Circle(Point2D(0, 0), 2.0)
        line = Line(Point2D(-3, 0), Point2D(3, 0))

        intersections = geometry2d.line_circle_intersection(line, circle)
        assert len(intersections) == 2
        assert intersections[0].x == pytest.approx(-2.0)
        assert intersections[1].x == pytest.approx(2.0)

    def test_line_circle_tangent(self) -> None:
        """Test line tangent to circle."""
        circle = Circle(Point2D(0, 0), 2.0)
        line = Line(Point2D(-3, 2), Point2D(3, 2))

        intersections = geometry2d.line_circle_intersection(line, circle)
        assert len(intersections) <= 2

    def test_line_circle_no_intersection(self) -> None:
        """Test line not intersecting circle."""
        circle = Circle(Point2D(0, 0), 1.0)
        line = Line(Point2D(0, 3), Point2D(1, 3))

        intersections = geometry2d.line_circle_intersection(line, circle)
        assert len(intersections) == 0


class TestCircleCircleIntersection:
    """Tests for circle-circle intersection."""

    def test_circle_circle_two_intersections(self) -> None:
        """Test two circles intersecting at two points."""
        c1 = Circle(Point2D(0, 0), 2.0)
        c2 = Circle(Point2D(3, 0), 2.0)

        intersections = geometry2d.circle_circle_intersection(c1, c2)
        assert len(intersections) == 2

    def test_circle_circle_tangent(self) -> None:
        """Test two circles tangent."""
        c1 = Circle(Point2D(0, 0), 1.0)
        c2 = Circle(Point2D(2, 0), 1.0)

        intersections = geometry2d.circle_circle_intersection(c1, c2)
        assert len(intersections) == 1

    def test_circle_circle_no_intersection(self) -> None:
        """Test non-intersecting circles."""
        c1 = Circle(Point2D(0, 0), 1.0)
        c2 = Circle(Point2D(5, 0), 1.0)

        intersections = geometry2d.circle_circle_intersection(c1, c2)
        assert len(intersections) == 0

    def test_circle_circle_same(self) -> None:
        """Test identical circles."""
        c1 = Circle(Point2D(0, 0), 2.0)
        c2 = Circle(Point2D(0, 0), 2.0)

        intersections = geometry2d.circle_circle_intersection(c1, c2)
        assert len(intersections) == 0


class TestPointOnLine:
    """Tests for point-on-line testing."""

    def test_point_on_line_true(self) -> None:
        """Test point on line."""
        line = Line(Point2D(0, 0), Point2D(10, 0))
        point = Point2D(5, 0)

        assert geometry2d.point_on_line(point, line)

    def test_point_not_on_line(self) -> None:
        """Test point not on line."""
        line = Line(Point2D(0, 0), Point2D(10, 0))
        point = Point2D(5, 5)

        assert not geometry2d.point_on_line(point, line)

    def test_point_on_line_distance(self) -> None:
        """Test perpendicular distance from point to line."""
        line = Line(Point2D(0, 0), Point2D(10, 0))
        point = Point2D(5, 3)

        distance = geometry2d.point_on_line_distance(point, line)
        assert distance == pytest.approx(3.0)


class TestPolygonOperations:
    """Tests for polygon operations."""

    def test_polygon_area_triangle(self) -> None:
        """Test triangle area."""
        triangle = Polygon([Point2D(0, 0), Point2D(4, 0), Point2D(0, 3)])
        area = geometry2d.polygon_area(triangle)
        assert area == pytest.approx(6.0)

    def test_polygon_area_square(self) -> None:
        """Test square area."""
        square = Polygon(
            [
                Point2D(0, 0),
                Point2D(5, 0),
                Point2D(5, 5),
                Point2D(0, 5),
            ]
        )
        area = geometry2d.polygon_area(square)
        assert area == pytest.approx(25.0)

    def test_polygon_centroid(self) -> None:
        """Test polygon centroid."""
        square = Polygon(
            [
                Point2D(0, 0),
                Point2D(4, 0),
                Point2D(4, 4),
                Point2D(0, 4),
            ]
        )
        centroid = geometry2d.polygon_centroid(square)
        assert centroid.x == pytest.approx(2.0)
        assert centroid.y == pytest.approx(2.0)

    def test_convex_hull(self) -> None:
        """Test convex hull."""
        points = [
            Point2D(0, 0),
            Point2D(1, 0),
            Point2D(1, 1),
            Point2D(0, 1),
            Point2D(0.5, 0.5),
        ]

        hull = geometry2d.convex_hull(points)
        assert len(hull) >= 3

    def test_point_in_polygon_inside(self) -> None:
        """Test point inside polygon."""
        polygon = Polygon(
            [
                Point2D(0, 0),
                Point2D(4, 0),
                Point2D(4, 4),
                Point2D(0, 4),
            ]
        )

        point = Point2D(2, 2)
        assert geometry2d.point_in_polygon(point, polygon)

    def test_point_in_polygon_outside(self) -> None:
        """Test point outside polygon."""
        polygon = Polygon(
            [
                Point2D(0, 0),
                Point2D(4, 0),
                Point2D(4, 4),
                Point2D(0, 4),
            ]
        )

        point = Point2D(5, 5)
        assert not geometry2d.point_in_polygon(point, polygon)


class TestOffsetPolygon:
    """Tests for polygon offsetting."""

    def test_offset_polygon_outward(self) -> None:
        """Test outward polygon offset."""
        polygon = Polygon(
            [
                Point2D(0, 0),
                Point2D(10, 0),
                Point2D(10, 10),
                Point2D(0, 10),
            ]
        )

        offset = geometry2d.offset_polygon(polygon, 1.0)
        assert len(offset.points) >= 3


class TestAngleBetweenLines:
    """Tests for angle between lines."""

    def test_angle_perpendicular_lines(self) -> None:
        """Test perpendicular lines."""
        line1 = Line(Point2D(0, 0), Point2D(1, 0))
        line2 = Line(Point2D(0, 0), Point2D(0, 1))

        angle = geometry2d.angle_between_lines(line1, line2)
        assert angle == pytest.approx(math.pi / 2)

    def test_angle_parallel_lines(self) -> None:
        """Test parallel lines."""
        line1 = Line(Point2D(0, 0), Point2D(1, 0))
        line2 = Line(Point2D(0, 1), Point2D(1, 1))

        angle = geometry2d.angle_between_lines(line1, line2)
        assert angle == pytest.approx(0.0)
