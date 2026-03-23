"""
Parametric curves: Bezier, B-spline, and NURBS curves.

Includes curve evaluation (de Casteljau, Cox-de Boor), tangent/curvature,
arc length estimation, and curve-curve intersection.
"""

from __future__ import annotations

from ._exceptions import CurveError
from ._types import Point2D, Point3D, Vector2D, Vector3D

EPSILON = 1e-10


class BezierCurve2D:
    """2D Bezier curve using control points."""

    def __init__(self, control_points: list[Point2D]) -> None:
        """
        Initialize Bezier curve.

        Args:
            control_points: List of control points
        """
        if len(control_points) < 2:
            raise CurveError("Bezier curve requires at least 2 control points")

        self.control_points = control_points
        self.degree = len(control_points) - 1

    def evaluate(self, t: float) -> Point2D:
        """
        Evaluate curve at parameter t using de Casteljau algorithm.

        Args:
            t: Parameter in [0, 1]

        Returns:
            Point on curve
        """
        if t < 0 or t > 1:
            raise ValueError("Parameter t must be in [0, 1]")

        points = [p for p in self.control_points]

        for _ in range(self.degree):
            new_points = []
            for i in range(len(points) - 1):
                x = (1 - t) * points[i].x + t * points[i + 1].x
                y = (1 - t) * points[i].y + t * points[i + 1].y
                new_points.append(Point2D(x, y))
            points = new_points

        return points[0]

    def tangent(self, t: float) -> Vector2D:
        """
        Compute tangent vector at parameter t.

        Uses finite differences.

        Args:
            t: Parameter in [0, 1]

        Returns:
            Tangent vector
        """
        dt = 1e-6
        t_before = max(0, t - dt)
        t_after = min(1, t + dt)

        p_before = self.evaluate(t_before)
        p_after = self.evaluate(t_after)

        return Vector2D(p_after.x - p_before.x, p_after.y - p_before.y).normalize()

    def curvature(self, t: float) -> float:
        """
        Compute curvature at parameter t.

        Uses finite differences for derivatives.

        Args:
            t: Parameter in [0, 1]

        Returns:
            Curvature
        """
        dt = 1e-5
        t1 = max(0, t - dt)
        t2 = min(1, t + dt)

        p1 = self.evaluate(t1)
        p2 = self.evaluate(t2)
        p3 = self.evaluate(t + dt) if t + dt <= 1 else self.evaluate(t)

        dx1 = p2.x - p1.x
        dy1 = p2.y - p1.y
        dx2 = p3.x - p2.x
        dy2 = p3.y - p2.y

        num = dx1 * dy2 - dy1 * dx2
        denom = (dx1 * dx1 + dy1 * dy1) ** 1.5

        if denom < EPSILON:
            return 0.0

        return num / denom

    def subdivide(self, t: float) -> tuple[BezierCurve2D, BezierCurve2D]:
        """
        Subdivide curve at parameter t.

        Uses de Casteljau algorithm.

        Args:
            t: Division parameter

        Returns:
            Two sub-curves
        """
        points = [p for p in self.control_points]
        left_points = [points[0]]
        right_points = []

        for _ in range(self.degree):
            new_points = []
            for i in range(len(points) - 1):
                p = Point2D((1 - t) * points[i].x + t * points[i + 1].x, (1 - t) * points[i].y + t * points[i + 1].y)
                new_points.append(p)
                if i == 0:
                    left_points.append(p)

            right_points.insert(0, new_points[-1])
            points = new_points

        right_points.insert(0, points[0])
        left_points.append(points[0])

        return BezierCurve2D(left_points), BezierCurve2D(right_points)

    def arc_length(self, num_segments: int = 100) -> float:
        """
        Estimate arc length using line segments.

        Args:
            num_segments: Number of segments for approximation

        Returns:
            Arc length
        """
        length = 0.0
        prev_point = self.evaluate(0)

        for i in range(1, num_segments + 1):
            t = i / num_segments
            point = self.evaluate(t)
            length += prev_point.distance_to(point)
            prev_point = point

        return length


class BSplineCurve2D:
    """2D B-spline curve."""

    def __init__(self, control_points: list[Point2D], knot_vector: list[float] | None = None, degree: int = 3) -> None:
        """
        Initialize B-spline curve.

        Args:
            control_points: Control points
            knot_vector: Knot vector (auto-generated if None)
            degree: Curve degree
        """
        if len(control_points) < degree + 1:
            raise CurveError(f"Need at least {degree + 1} control points for degree {degree}")

        self.control_points = control_points
        self.degree = degree

        if knot_vector is None:
            self.knot_vector = self._generate_knot_vector()
        else:
            self.knot_vector = knot_vector

    def _generate_knot_vector(self) -> list[float]:
        """Generate uniform knot vector."""
        n = len(self.control_points)
        m = n + self.degree + 1
        knots = []

        for i in range(m):
            if i < self.degree + 1:
                knots.append(0.0)
            elif i >= n:
                knots.append(1.0)
            else:
                knots.append((i - self.degree) / (n - self.degree + 1))

        return knots

    def _basis_function(self, i: int, p: int, t: float) -> float:
        """
        Compute B-spline basis function using Cox-de Boor recursion.

        Args:
            i: Control point index
            p: Degree
            t: Parameter

        Returns:
            Basis function value
        """
        if p == 0:
            if self.knot_vector[i] <= t < self.knot_vector[i + 1]:
                return 1.0
            return 0.0

        left = self._basis_function(i, p - 1, t)
        right = self._basis_function(i + 1, p - 1, t)

        denom_left = self.knot_vector[i + p] - self.knot_vector[i]
        denom_right = self.knot_vector[i + p + 1] - self.knot_vector[i + 1]

        result = 0.0

        if denom_left > EPSILON:
            result += left * (t - self.knot_vector[i]) / denom_left

        if denom_right > EPSILON:
            result += right * (self.knot_vector[i + p + 1] - t) / denom_right

        return result

    def evaluate(self, t: float) -> Point2D:
        """
        Evaluate B-spline at parameter t.

        Args:
            t: Parameter in [0, 1]

        Returns:
            Point on curve
        """
        if t < 0 or t > 1:
            raise ValueError("Parameter t must be in [0, 1]")

        x, y = 0.0, 0.0

        for i, cp in enumerate(self.control_points):
            basis = self._basis_function(i, self.degree, t)
            x += basis * cp.x
            y += basis * cp.y

        return Point2D(x, y)

    def arc_length(self, num_segments: int = 100) -> float:
        """Estimate arc length."""
        length = 0.0
        prev = self.evaluate(0)

        for i in range(1, num_segments + 1):
            curr = self.evaluate(i / num_segments)
            length += prev.distance_to(curr)
            prev = curr

        return length


class NURBSCurve2D:
    """2D NURBS (Non-Uniform Rational B-Spline) curve."""

    def __init__(
        self,
        control_points: list[Point2D],
        weights: list[float],
        knot_vector: list[float] | None = None,
        degree: int | None = None,
    ) -> None:
        """
        Initialize NURBS curve.

        Args:
            control_points: Control points
            weights: Weights for each control point
            knot_vector: Knot vector (auto-generated if None)
            degree: Curve degree. If None, uses up to cubic while staying valid
                for the number of control points.
        """
        if len(control_points) != len(weights):
            raise CurveError("Number of weights must match control points")

        effective_degree = degree
        if effective_degree is None:
            effective_degree = min(3, len(control_points) - 1)

        self.bspline = BSplineCurve2D(control_points, knot_vector, effective_degree)
        self.weights = weights

    def evaluate(self, t: float) -> Point2D:
        """
        Evaluate NURBS at parameter t.

        Args:
            t: Parameter in [0, 1]

        Returns:
            Point on curve
        """
        x_weighted, y_weighted = 0.0, 0.0
        weight_sum = 0.0

        for i, cp in enumerate(self.bspline.control_points):
            basis = self.bspline._basis_function(i, self.bspline.degree, t)
            weight = self.weights[i]

            weighted_basis = basis * weight

            x_weighted += weighted_basis * cp.x
            y_weighted += weighted_basis * cp.y
            weight_sum += weighted_basis

        if weight_sum < EPSILON:
            return Point2D(0, 0)

        return Point2D(x_weighted / weight_sum, y_weighted / weight_sum)


class BezierCurve3D:
    """3D Bezier curve."""

    def __init__(self, control_points: list[Point3D]) -> None:
        """
        Initialize 3D Bezier curve.

        Args:
            control_points: Control points
        """
        if len(control_points) < 2:
            raise CurveError("Bezier curve requires at least 2 control points")

        self.control_points = control_points
        self.degree = len(control_points) - 1

    def evaluate(self, t: float) -> Point3D:
        """
        Evaluate curve at parameter t.

        Args:
            t: Parameter in [0, 1]

        Returns:
            Point on curve
        """
        if t < 0 or t > 1:
            raise ValueError("Parameter t must be in [0, 1]")

        points = [p for p in self.control_points]

        for _ in range(self.degree):
            new_points = []
            for i in range(len(points) - 1):
                p = Point3D(
                    (1 - t) * points[i].x + t * points[i + 1].x,
                    (1 - t) * points[i].y + t * points[i + 1].y,
                    (1 - t) * points[i].z + t * points[i + 1].z,
                )
                new_points.append(p)
            points = new_points

        return points[0]

    def tangent(self, t: float) -> Vector3D:
        """Compute tangent at parameter t."""
        dt = 1e-6
        t_before = max(0, t - dt)
        t_after = min(1, t + dt)

        p_before = self.evaluate(t_before)
        p_after = self.evaluate(t_after)

        return Vector3D(p_after.x - p_before.x, p_after.y - p_before.y, p_after.z - p_before.z).normalize()

    def arc_length(self, num_segments: int = 100) -> float:
        """Estimate arc length."""
        length = 0.0
        prev = self.evaluate(0)

        for i in range(1, num_segments + 1):
            curr = self.evaluate(i / num_segments)
            length += prev.distance_to(curr)
            prev = curr

        return length


def curve_curve_intersection_2d(
    curve1: BezierCurve2D, curve2: BezierCurve2D, tolerance: float = 1e-6
) -> list[tuple[float, float]]:
    """
    Find intersections between two 2D Bezier curves.

    Uses recursive subdivision method.

    Args:
        curve1: First curve
        curve2: Second curve
        tolerance: Convergence tolerance

    Returns:
        List of (t1, t2) parameter pairs for intersections
    """
    intersections: list[tuple[float, float]] = []

    # Approximate each curve as a polyline with bounded complexity, then
    # intersect line segments to avoid exponential recursive subdivision.
    segments = 60
    curve1_pts = [curve1.evaluate(i / segments) for i in range(segments + 1)]
    curve2_pts = [curve2.evaluate(i / segments) for i in range(segments + 1)]

    for i in range(segments):
        p1 = curve1_pts[i]
        p2 = curve1_pts[i + 1]
        r_x = p2.x - p1.x
        r_y = p2.y - p1.y

        for j in range(segments):
            q1 = curve2_pts[j]
            q2 = curve2_pts[j + 1]
            s_x = q2.x - q1.x
            s_y = q2.y - q1.y

            denom = r_x * s_y - r_y * s_x
            if abs(denom) < EPSILON:
                continue

            qmp_x = q1.x - p1.x
            qmp_y = q1.y - p1.y
            u = (qmp_x * r_y - qmp_y * r_x) / denom
            t = (qmp_x * s_y - qmp_y * s_x) / denom

            if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                t1 = (i + t) / segments
                t2 = (j + u) / segments

                if all(
                    abs(existing_t1 - t1) > tolerance or abs(existing_t2 - t2) > tolerance
                    for existing_t1, existing_t2 in intersections
                ):
                    intersections.append((t1, t2))

    return intersections
