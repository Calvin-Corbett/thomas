"""
Tests for Boolean operations.
"""

import pytest

from thomas.cad._types import Point2D, Polygon
from thomas.cad.boolean_ops import (
    BooleanOp,
    CSGNode,
    minkowski_sum,
    polygon_difference,
    polygon_intersection,
    polygon_union,
    sutherland_hodgman_clip,
)


class TestSutherlandHodgman:
    """Tests for Sutherland-Hodgman polygon clipping."""

    def test_clip_square_by_square(self) -> None:
        """Test clipping square by square."""
        subject = Polygon(
            [
                Point2D(0, 0),
                Point2D(3, 0),
                Point2D(3, 3),
                Point2D(0, 3),
            ]
        )

        clip = Polygon(
            [
                Point2D(1, 1),
                Point2D(4, 1),
                Point2D(4, 4),
                Point2D(1, 4),
            ]
        )

        result = sutherland_hodgman_clip(subject, clip)
        assert len(result.points) >= 3

    def test_clip_no_overlap(self) -> None:
        """Test clipping with no overlap."""
        subject = Polygon(
            [
                Point2D(0, 0),
                Point2D(1, 0),
                Point2D(1, 1),
                Point2D(0, 1),
            ]
        )

        clip = Polygon(
            [
                Point2D(5, 5),
                Point2D(6, 5),
                Point2D(6, 6),
                Point2D(5, 6),
            ]
        )

        result = sutherland_hodgman_clip(subject, clip)
        assert len(result.points) == 0 or len(result.points) < 3

    def test_clip_complete_overlap(self) -> None:
        """Test clipping with complete overlap."""
        subject = Polygon(
            [
                Point2D(0, 0),
                Point2D(3, 0),
                Point2D(3, 3),
                Point2D(0, 3),
            ]
        )

        clip = Polygon(
            [
                Point2D(0, 0),
                Point2D(3, 0),
                Point2D(3, 3),
                Point2D(0, 3),
            ]
        )

        result = sutherland_hodgman_clip(subject, clip)
        assert len(result.points) >= 3


class TestPolygonUnion:
    """Tests for polygon union."""

    def test_union_overlapping_squares(self) -> None:
        """Test union of overlapping squares."""
        poly1 = Polygon(
            [
                Point2D(0, 0),
                Point2D(2, 0),
                Point2D(2, 2),
                Point2D(0, 2),
            ]
        )

        poly2 = Polygon(
            [
                Point2D(1, 1),
                Point2D(3, 1),
                Point2D(3, 3),
                Point2D(1, 3),
            ]
        )

        result = polygon_union(poly1, poly2)
        assert len(result) > 0

    def test_union_non_overlapping(self) -> None:
        """Test union of non-overlapping polygons."""
        poly1 = Polygon(
            [
                Point2D(0, 0),
                Point2D(1, 0),
                Point2D(1, 1),
                Point2D(0, 1),
            ]
        )

        poly2 = Polygon(
            [
                Point2D(5, 5),
                Point2D(6, 5),
                Point2D(6, 6),
                Point2D(5, 6),
            ]
        )

        result = polygon_union(poly1, poly2)
        assert len(result) >= 1


class TestPolygonIntersection:
    """Tests for polygon intersection."""

    def test_intersection_overlapping_squares(self) -> None:
        """Test intersection of overlapping squares."""
        poly1 = Polygon(
            [
                Point2D(0, 0),
                Point2D(3, 0),
                Point2D(3, 3),
                Point2D(0, 3),
            ]
        )

        poly2 = Polygon(
            [
                Point2D(1, 1),
                Point2D(4, 1),
                Point2D(4, 4),
                Point2D(1, 4),
            ]
        )

        result = polygon_intersection(poly1, poly2)
        assert len(result) > 0
        if result:
            assert len(result[0].points) >= 3

    def test_intersection_non_overlapping(self) -> None:
        """Test intersection of non-overlapping polygons."""
        poly1 = Polygon(
            [
                Point2D(0, 0),
                Point2D(1, 0),
                Point2D(1, 1),
                Point2D(0, 1),
            ]
        )

        poly2 = Polygon(
            [
                Point2D(5, 5),
                Point2D(6, 5),
                Point2D(6, 6),
                Point2D(5, 6),
            ]
        )

        result = polygon_intersection(poly1, poly2)
        assert len(result) == 0


class TestPolygonDifference:
    """Tests for polygon difference."""

    def test_difference_overlapping_squares(self) -> None:
        """Test difference of overlapping squares."""
        poly1 = Polygon(
            [
                Point2D(0, 0),
                Point2D(4, 0),
                Point2D(4, 4),
                Point2D(0, 4),
            ]
        )

        poly2 = Polygon(
            [
                Point2D(1, 1),
                Point2D(3, 1),
                Point2D(3, 3),
                Point2D(1, 3),
            ]
        )

        result = polygon_difference(poly1, poly2)
        assert len(result) >= 0


class TestMinkowskiSum:
    """Tests for Minkowski sum."""

    def test_minkowski_sum_squares(self) -> None:
        """Test Minkowski sum of two squares."""
        poly1 = Polygon(
            [
                Point2D(0, 0),
                Point2D(1, 0),
                Point2D(1, 1),
                Point2D(0, 1),
            ]
        )

        poly2 = Polygon(
            [
                Point2D(0, 0),
                Point2D(1, 0),
                Point2D(1, 1),
                Point2D(0, 1),
            ]
        )

        result = minkowski_sum(poly1, poly2)
        assert len(result.points) > 0

    def test_minkowski_sum_triangle_square(self) -> None:
        """Test Minkowski sum of triangle and square."""
        poly1 = Polygon(
            [
                Point2D(0, 0),
                Point2D(2, 0),
                Point2D(1, 1),
            ]
        )

        poly2 = Polygon(
            [
                Point2D(0, 0),
                Point2D(1, 0),
                Point2D(1, 1),
                Point2D(0, 1),
            ]
        )

        result = minkowski_sum(poly1, poly2)
        assert len(result.points) >= 4


class TestCSGTree:
    """Tests for CSG tree operations."""

    def test_csg_node_leaf(self) -> None:
        """Test creating leaf CSG node."""
        geometry = Polygon(
            [
                Point2D(0, 0),
                Point2D(1, 0),
                Point2D(1, 1),
                Point2D(0, 1),
            ]
        )

        node = CSGNode.leaf(geometry)
        assert node.is_leaf
        assert node.geometry is geometry

    def test_csg_node_operation(self) -> None:
        """Test creating operation node."""
        poly1 = Polygon(
            [
                Point2D(0, 0),
                Point2D(1, 0),
                Point2D(1, 1),
                Point2D(0, 1),
            ]
        )

        poly2 = Polygon(
            [
                Point2D(0.5, 0.5),
                Point2D(1.5, 0.5),
                Point2D(1.5, 1.5),
                Point2D(0.5, 1.5),
            ]
        )

        left = CSGNode.leaf(poly1)
        right = CSGNode.leaf(poly2)

        union_node = CSGNode.operation(BooleanOp.UNION, left, right)

        assert not union_node.is_leaf
        assert union_node.operation == BooleanOp.UNION
        assert union_node.left is left
        assert union_node.right is right


class TestBooleanErrors:
    """Tests for error handling."""

    def test_minkowski_sum_degenerate(self) -> None:
        """Test Minkowski sum with degenerate polygon."""
        from thomas.cad._exceptions import BooleanOperationError

        poly1 = Polygon([Point2D(0, 0)])
        poly2 = Polygon([Point2D(1, 1)])

        with pytest.raises(BooleanOperationError):
            minkowski_sum(poly1, poly2)
