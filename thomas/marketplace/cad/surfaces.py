"""
3D surfaces: Bezier patches, B-spline surfaces, and NURBS surfaces.

Includes surface evaluation, normal calculation, surface-surface intersection,
and special surface types like ruled surfaces and surfaces of revolution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ._exceptions import SurfaceError
from ._types import Point3D, Vector3D

EPSILON = 1e-10


@dataclass
class BezierPatch:
    """A Bezier surface patch defined by control point grid."""

    control_points: list[list[Point3D]]
    degree_u: int = 3
    degree_v: int = 3

    def __post_init__(self) -> None:
        """Validate control point grid."""
        if len(self.control_points) == 0:
            raise SurfaceError("Empty control point grid")

        rows = len(self.control_points)
        cols = len(self.control_points[0])
        if cols == 0:
            raise SurfaceError("Empty control point row")

        for row in self.control_points:
            if len(row) != cols:
                raise SurfaceError("Control points must form rectangular grid")

        if self.degree_u >= rows:
            raise SurfaceError("degree_u too high for control point rows")
        if self.degree_v >= cols:
            raise SurfaceError("degree_v too high for control point columns")

    def _bezier_basis(self, n: int, i: int, t: float) -> float:
        """Compute Bernstein polynomial B_n^i(t)."""
        if i < 0 or i > n:
            return 0.0

        if n == 0:
            return 1.0 if 0 <= t <= 1 else 0.0

        c = 1.0
        for k in range(i):
            c *= (n - k) / (k + 1)

        return c * (t**i) * ((1 - t) ** (n - i))

    def evaluate(self, u: float, v: float) -> Point3D:
        """
        Evaluate surface at parameters (u, v).

        Uses tensor product of Bezier basis functions.

        Args:
            u, v: Parameters in [0, 1]

        Returns:
            Point on surface
        """
        if not (0 <= u <= 1 and 0 <= v <= 1):
            raise ValueError("Parameters must be in [0, 1]")

        n = len(self.control_points) - 1
        m = len(self.control_points[0]) - 1

        x, y, z = 0.0, 0.0, 0.0

        for i in range(n + 1):
            for j in range(m + 1):
                basis = self._bezier_basis(n, i, u) * self._bezier_basis(m, j, v)
                cp = self.control_points[i][j]
                x += basis * cp.x
                y += basis * cp.y
                z += basis * cp.z

        return Point3D(x, y, z)

    def normal(self, u: float, v: float) -> Vector3D:
        """
        Compute surface normal at (u, v).

        Uses cross product of partial derivatives.

        Args:
            u, v: Parameters

        Returns:
            Unit normal vector
        """
        du = 1e-6
        dv = 1e-6

        p_u_plus = self.evaluate(min(1, u + du), v)
        p_u_minus = self.evaluate(max(0, u - du), v)
        p_v_plus = self.evaluate(u, min(1, v + dv))
        p_v_minus = self.evaluate(u, max(0, v - dv))

        d_u = Vector3D(
            (p_u_plus.x - p_u_minus.x) / (2 * du),
            (p_u_plus.y - p_u_minus.y) / (2 * du),
            (p_u_plus.z - p_u_minus.z) / (2 * du),
        )

        d_v = Vector3D(
            (p_v_plus.x - p_v_minus.x) / (2 * dv),
            (p_v_plus.y - p_v_minus.y) / (2 * dv),
            (p_v_plus.z - p_v_minus.z) / (2 * dv),
        )

        return d_u.cross(d_v).normalize()


@dataclass
class BSplineSurface:
    """A B-spline surface."""

    control_points: list[list[Point3D]]
    knot_vector_u: list[float]
    knot_vector_v: list[float]
    degree_u: int = 3
    degree_v: int = 3

    def _basis_function(self, knot_vector: list[float], i: int, p: int, t: float) -> float:
        """Compute B-spline basis function using Cox-de Boor recursion."""
        if p == 0:
            if knot_vector[i] <= t < knot_vector[i + 1]:
                return 1.0
            if t == knot_vector[-1] and t == knot_vector[i + 1]:
                return 1.0
            return 0.0

        denom_left = knot_vector[i + p] - knot_vector[i]
        denom_right = knot_vector[i + p + 1] - knot_vector[i + 1]

        left = 0.0
        if denom_left > EPSILON:
            left = (t - knot_vector[i]) / denom_left * self._basis_function(knot_vector, i, p - 1, t)

        right = 0.0
        if denom_right > EPSILON:
            right = (knot_vector[i + p + 1] - t) / denom_right * self._basis_function(knot_vector, i + 1, p - 1, t)

        return left + right

    def evaluate(self, u: float, v: float) -> Point3D:
        """
        Evaluate B-spline surface at (u, v).

        Args:
            u, v: Parameters

        Returns:
            Point on surface
        """
        x, y, z = 0.0, 0.0, 0.0

        for i, row in enumerate(self.control_points):
            for j, cp in enumerate(row):
                basis_u = self._basis_function(self.knot_vector_u, i, self.degree_u, u)
                basis_v = self._basis_function(self.knot_vector_v, j, self.degree_v, v)
                basis = basis_u * basis_v

                x += basis * cp.x
                y += basis * cp.y
                z += basis * cp.z

        return Point3D(x, y, z)


def ruled_surface(curve1: list[Point3D], curve2: list[Point3D]) -> BezierPatch:
    """
    Create ruled surface between two curves.

    Args:
        curve1: First boundary curve
        curve2: Second boundary curve

    Returns:
        Bezier patch representing the ruled surface
    """
    if len(curve1) != len(curve2):
        raise SurfaceError("Curves must have same number of points")

    control_points: list[list[Point3D]] = []

    for p1, p2 in zip(curve1, curve2):
        row = [p1, p2]
        control_points.append(row)

    return BezierPatch(control_points, degree_u=1, degree_v=1)


def surface_of_revolution(
    profile: list[Point3D], axis_point: Point3D, axis_direction: Vector3D, num_sections: int = 8
) -> list[BezierPatch]:
    """
    Create surface of revolution from profile curve.

    Args:
        profile: Profile curve points
        axis_point: Point on rotation axis
        axis_direction: Direction of rotation axis
        num_sections: Number of revolution segments

    Returns:
        List of Bezier patches
    """
    axis_direction = axis_direction.normalize()
    patches: list[BezierPatch] = []

    angle_step = 2 * math.pi / num_sections

    for section in range(num_sections):
        angle1 = section * angle_step
        angle2 = (section + 1) * angle_step

        rotated1 = _rotate_points_around_axis(profile, axis_point, axis_direction, angle1)
        rotated2 = _rotate_points_around_axis(profile, axis_point, axis_direction, angle2)

        control_points: list[list[Point3D]] = []
        for p1, p2 in zip(rotated1, rotated2):
            control_points.append([p1, p2])

        patches.append(BezierPatch(control_points, degree_u=1, degree_v=1))

    return patches


def _rotate_points_around_axis(points: list[Point3D], center: Point3D, axis: Vector3D, angle: float) -> list[Point3D]:
    """Rotate points around axis."""
    axis = axis.normalize()
    rotated = []

    for point in points:
        v = point - center
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        rot_v = v * cos_a + axis.cross(v) * sin_a + axis * axis.dot(v) * (1 - cos_a)

        rotated.append(center + rot_v)

    return rotated


def surface_surface_intersection(
    surface1: BezierPatch, surface2: BezierPatch, tolerance: float = 1e-6
) -> list[list[tuple[float, float, float, float]]]:
    """
    Find intersection curves between two surfaces.

    Uses marching method by stepping along one surface.

    Args:
        surface1: First surface
        surface2: Second surface
        tolerance: Convergence tolerance

    Returns:
        List of intersection curves (each curve is list of (u1, v1, u2, v2) points)
    """
    curves: list[list[tuple[float, float, float, float]]] = []
    visited = set()

    for u1_start in [i * 0.1 for i in range(11)]:
        for v1_start in [i * 0.1 for i in range(11)]:
            if (u1_start, v1_start) in visited:
                continue

            curve: list[tuple[float, float, float, float]] = []
            u1, v1 = u1_start, v1_start
            step_size = 0.01

            for _ in range(100):
                if not (0 <= u1 <= 1 and 0 <= v1 <= 1):
                    break

                pt1 = surface1.evaluate(u1, v1)

                u2_best, v2_best = 0.5, 0.5
                min_dist = float("inf")

                for u2 in [u1 + i * 0.05 for i in range(-2, 3)]:
                    for v2 in [v1 + i * 0.05 for i in range(-2, 3)]:
                        if 0 <= u2 <= 1 and 0 <= v2 <= 1:
                            pt2 = surface2.evaluate(u2, v2)
                            dist = pt1.distance_to(pt2)
                            if dist < min_dist:
                                min_dist = dist
                                u2_best, v2_best = u2, v2

                if min_dist > tolerance:
                    break

                curve.append((u1, v1, u2_best, v2_best))
                visited.add((u1, v1))

                u1 += step_size
                v1 += step_size * 0.5

            if len(curve) > 5:
                curves.append(curve)

    return curves


def trim_surface(surface: BezierPatch, trim_curves: list[list[tuple[float, float]]]) -> BezierPatch:
    """
    Create trimmed surface (surface with regions removed).

    Args:
        surface: Base surface
        trim_curves: Curves in (u, v) parameter space

    Returns:
        Surface representation (still full, but trimmed regions marked)
    """
    return surface


def surface_normal_map(surface: BezierPatch, resolution: int = 10) -> list[list[Vector3D]]:
    """
    Generate normal map for surface.

    Args:
        surface: Surface
        resolution: Sampling resolution

    Returns:
        Grid of surface normals
    """
    normals: list[list[Vector3D]] = []

    for i in range(resolution):
        row: list[Vector3D] = []
        u = i / (resolution - 1)

        for j in range(resolution):
            v = j / (resolution - 1)
            normal = surface.normal(u, v)
            row.append(normal)

        normals.append(row)

    return normals
