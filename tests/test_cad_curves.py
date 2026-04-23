"""
Tests for curve operations.
"""

import pytest

from thomas.marketplace.cad._types import Point2D, Point3D
from thomas.marketplace.cad.curves import (
    BezierCurve2D,
    BezierCurve3D,
    BSplineCurve2D,
    NURBSCurve2D,
    curve_curve_intersection_2d,
)


class TestBezierCurve2D:
    """Tests for 2D Bezier curves."""

    def test_bezier_linear(self) -> None:
        """Test linear Bezier curve."""
        curve = BezierCurve2D([Point2D(0, 0), Point2D(10, 0)])

        p0 = curve.evaluate(0.0)
        p1 = curve.evaluate(1.0)
        p_mid = curve.evaluate(0.5)

        assert p0.x == pytest.approx(0.0)
        assert p1.x == pytest.approx(10.0)
        assert p_mid.x == pytest.approx(5.0)

    def test_bezier_quadratic(self) -> None:
        """Test quadratic Bezier curve."""
        curve = BezierCurve2D(
            [
                Point2D(0, 0),
                Point2D(5, 10),
                Point2D(10, 0),
            ]
        )

        p0 = curve.evaluate(0.0)
        p1 = curve.evaluate(1.0)
        p_mid = curve.evaluate(0.5)

        assert p0.x == pytest.approx(0.0)
        assert p0.y == pytest.approx(0.0)
        assert p1.x == pytest.approx(10.0)
        assert p1.y == pytest.approx(0.0)
        assert p_mid.y > p0.y

    def test_bezier_cubic(self) -> None:
        """Test cubic Bezier curve."""
        curve = BezierCurve2D(
            [
                Point2D(0, 0),
                Point2D(5, 10),
                Point2D(10, 10),
                Point2D(15, 0),
            ]
        )

        p0 = curve.evaluate(0.0)
        p1 = curve.evaluate(1.0)

        assert p0.x == pytest.approx(0.0)
        assert p0.y == pytest.approx(0.0)
        assert p1.x == pytest.approx(15.0)
        assert p1.y == pytest.approx(0.0)

    def test_bezier_subdivide(self) -> None:
        """Test Bezier curve subdivision."""
        curve = BezierCurve2D(
            [
                Point2D(0, 0),
                Point2D(5, 10),
                Point2D(10, 0),
            ]
        )

        left, right = curve.subdivide(0.5)

        assert len(left.control_points) >= 2
        assert len(right.control_points) >= 2

        left_end = left.evaluate(1.0)
        right_start = right.evaluate(0.0)

        assert left_end.x == pytest.approx(right_start.x, abs=1e-5)
        assert left_end.y == pytest.approx(right_start.y, abs=1e-5)

    def test_bezier_arc_length(self) -> None:
        """Test arc length computation."""
        curve = BezierCurve2D(
            [
                Point2D(0, 0),
                Point2D(10, 0),
            ]
        )

        length = curve.arc_length(num_segments=100)
        assert length == pytest.approx(10.0)

    def test_bezier_tangent(self) -> None:
        """Test tangent vector."""
        curve = BezierCurve2D(
            [
                Point2D(0, 0),
                Point2D(10, 0),
            ]
        )

        tangent = curve.tangent(0.5)
        assert tangent.x > 0


class TestBSplineCurve2D:
    """Tests for 2D B-spline curves."""

    def test_bspline_creation(self) -> None:
        """Test B-spline creation."""
        points = [Point2D(0, 0), Point2D(5, 5), Point2D(10, 0)]
        curve = BSplineCurve2D(points, degree=2)

        p0 = curve.evaluate(0.0)
        p1 = curve.evaluate(1.0)

        assert p0 is not None
        assert p1 is not None

    def test_bspline_knot_vector_generation(self) -> None:
        """Test automatic knot vector generation."""
        points = [Point2D(0, 0), Point2D(5, 5), Point2D(10, 0), Point2D(15, 5)]
        curve = BSplineCurve2D(points, degree=3)

        assert len(curve.knot_vector) == len(points) + 3 + 1


class TestNURBSCurve2D:
    """Tests for 2D NURBS curves."""

    def test_nurbs_creation(self) -> None:
        """Test NURBS creation."""
        points = [Point2D(0, 0), Point2D(5, 5), Point2D(10, 0)]
        weights = [1.0, 1.0, 1.0]

        curve = NURBSCurve2D(points, weights)

        p0 = curve.evaluate(0.0)
        p1 = curve.evaluate(1.0)

        assert p0 is not None
        assert p1 is not None

    def test_nurbs_unequal_weights(self) -> None:
        """Test NURBS with unequal weights."""
        points = [Point2D(0, 0), Point2D(5, 5), Point2D(10, 0)]
        weights = [1.0, 2.0, 1.0]

        curve = NURBSCurve2D(points, weights)

        p_mid = curve.evaluate(0.5)
        assert p_mid is not None


class TestBezierCurve3D:
    """Tests for 3D Bezier curves."""

    def test_bezier3d_linear(self) -> None:
        """Test linear 3D Bezier curve."""
        curve = BezierCurve3D(
            [
                Point3D(0, 0, 0),
                Point3D(10, 0, 0),
            ]
        )

        p0 = curve.evaluate(0.0)
        p1 = curve.evaluate(1.0)

        assert p0.x == pytest.approx(0.0)
        assert p1.x == pytest.approx(10.0)

    def test_bezier3d_cubic(self) -> None:
        """Test cubic 3D Bezier curve."""
        curve = BezierCurve3D(
            [
                Point3D(0, 0, 0),
                Point3D(5, 10, 0),
                Point3D(10, 10, 5),
                Point3D(15, 0, 0),
            ]
        )

        p_mid = curve.evaluate(0.5)
        assert p_mid.z > 0

    def test_bezier3d_arc_length(self) -> None:
        """Test 3D arc length."""
        curve = BezierCurve3D(
            [
                Point3D(0, 0, 0),
                Point3D(10, 0, 0),
            ]
        )

        length = curve.arc_length()
        assert length == pytest.approx(10.0)


class TestCurveCurveIntersection:
    """Tests for curve-curve intersection."""

    def test_curve_intersection_crossing(self) -> None:
        """Test intersecting curves."""
        curve1 = BezierCurve2D(
            [
                Point2D(0, 0),
                Point2D(10, 10),
            ]
        )

        curve2 = BezierCurve2D(
            [
                Point2D(0, 10),
                Point2D(10, 0),
            ]
        )

        intersections = curve_curve_intersection_2d(curve1, curve2)
        assert len(intersections) > 0

    def test_curve_intersection_no_intersection(self) -> None:
        """Test non-intersecting curves."""
        curve1 = BezierCurve2D(
            [
                Point2D(0, 0),
                Point2D(5, 5),
            ]
        )

        curve2 = BezierCurve2D(
            [
                Point2D(10, 0),
                Point2D(15, 5),
            ]
        )

        intersections = curve_curve_intersection_2d(curve1, curve2)
        assert len(intersections) == 0


class TestBezierErrors:
    """Tests for error conditions."""

    def test_bezier_invalid_parameter(self) -> None:
        """Test invalid parameter."""
        curve = BezierCurve2D([Point2D(0, 0), Point2D(10, 0)])

        with pytest.raises(ValueError):
            curve.evaluate(1.5)

    def test_bspline_insufficient_points(self) -> None:
        """Test insufficient control points."""
        with pytest.raises(Exception):
            BSplineCurve2D([Point2D(0, 0)], degree=3)

    def test_nurbs_mismatched_weights(self) -> None:
        """Test mismatched weights."""
        points = [Point2D(0, 0), Point2D(5, 5), Point2D(10, 0)]
        weights = [1.0, 1.0]

        with pytest.raises(Exception):
            NURBSCurve2D(points, weights)
