"""
Tests for surface operations.
"""

import pytest

from thomas.cad._types import Point3D, Vector3D
from thomas.cad.surfaces import (
    BezierPatch,
    BSplineSurface,
    ruled_surface,
    surface_of_revolution,
)


class TestBezierPatch:
    """Tests for Bezier surface patches."""

    def test_bezier_patch_creation(self) -> None:
        """Test Bezier patch creation."""
        control_points = [
            [Point3D(0, 0, 0), Point3D(1, 0, 0)],
            [Point3D(0, 1, 0), Point3D(1, 1, 0)],
        ]

        patch = BezierPatch(control_points, degree_u=1, degree_v=1)
        assert patch.degree_u == 1
        assert patch.degree_v == 1

    def test_bezier_patch_evaluation(self) -> None:
        """Test Bezier patch evaluation."""
        control_points = [
            [Point3D(0, 0, 0), Point3D(1, 0, 1)],
            [Point3D(0, 1, 0), Point3D(1, 1, 1)],
        ]

        patch = BezierPatch(control_points, degree_u=1, degree_v=1)

        p00 = patch.evaluate(0.0, 0.0)
        p11 = patch.evaluate(1.0, 1.0)
        p_mid = patch.evaluate(0.5, 0.5)

        assert p00.x == pytest.approx(0.0)
        assert p00.y == pytest.approx(0.0)
        assert p11.x == pytest.approx(1.0)
        assert p11.y == pytest.approx(1.0)

    def test_bezier_patch_normal(self) -> None:
        """Test surface normal computation."""
        control_points = [
            [Point3D(0, 0, 0), Point3D(1, 0, 0)],
            [Point3D(0, 1, 1), Point3D(1, 1, 1)],
        ]

        patch = BezierPatch(control_points, degree_u=1, degree_v=1)

        normal = patch.normal(0.5, 0.5)
        assert normal.magnitude() > 0.9

    def test_bezier_patch_invalid_parameters(self) -> None:
        """Test invalid parameters."""
        control_points = [
            [Point3D(0, 0, 0), Point3D(1, 0, 0)],
            [Point3D(0, 1, 0), Point3D(1, 1, 0)],
        ]

        patch = BezierPatch(control_points, degree_u=1, degree_v=1)

        with pytest.raises(ValueError):
            patch.evaluate(1.5, 0.5)

        with pytest.raises(ValueError):
            patch.evaluate(0.5, -0.1)


class TestBSplineSurface:
    """Tests for B-spline surfaces."""

    def test_bspline_surface_creation(self) -> None:
        """Test B-spline surface creation."""
        control_points = [
            [Point3D(0, 0, 0), Point3D(1, 0, 0), Point3D(2, 0, 0)],
            [Point3D(0, 1, 0), Point3D(1, 1, 1), Point3D(2, 1, 0)],
            [Point3D(0, 2, 0), Point3D(1, 2, 0), Point3D(2, 2, 0)],
        ]

        knot_u = [0, 0, 0, 0.5, 1, 1, 1]
        knot_v = [0, 0, 0, 0.5, 1, 1, 1]

        surface = BSplineSurface(control_points, knot_u, knot_v, degree_u=2, degree_v=2)

        assert surface.degree_u == 2
        assert surface.degree_v == 2

    def test_bspline_surface_evaluation(self) -> None:
        """Test B-spline surface evaluation."""
        control_points = [
            [Point3D(0, 0, 0), Point3D(1, 0, 0)],
            [Point3D(0, 1, 0), Point3D(1, 1, 0)],
        ]

        knot_u = [0, 0, 1, 1]
        knot_v = [0, 0, 1, 1]

        surface = BSplineSurface(control_points, knot_u, knot_v, degree_u=1, degree_v=1)

        p = surface.evaluate(0.5, 0.5)
        assert p is not None


class TestRuledSurface:
    """Tests for ruled surfaces."""

    def test_ruled_surface_creation(self) -> None:
        """Test ruled surface creation."""
        curve1 = [Point3D(0, 0, 0), Point3D(1, 0, 0), Point3D(2, 0, 0)]
        curve2 = [Point3D(0, 1, 1), Point3D(1, 1, 1), Point3D(2, 1, 1)]

        surface = ruled_surface(curve1, curve2)

        assert surface is not None
        assert len(surface.control_points) == 3

    def test_ruled_surface_evaluation(self) -> None:
        """Test ruled surface evaluation."""
        curve1 = [Point3D(0, 0, 0), Point3D(1, 0, 0)]
        curve2 = [Point3D(0, 1, 0), Point3D(1, 1, 0)]

        surface = ruled_surface(curve1, curve2)

        p = surface.evaluate(0.5, 0.5)
        assert p is not None
        assert p.y == pytest.approx(0.5)

    def test_ruled_surface_mismatched_curves(self) -> None:
        """Test ruled surface with mismatched curves."""
        from thomas.cad._exceptions import SurfaceError

        curve1 = [Point3D(0, 0, 0), Point3D(1, 0, 0)]
        curve2 = [Point3D(0, 1, 0), Point3D(1, 1, 0), Point3D(2, 1, 0)]

        with pytest.raises(SurfaceError):
            ruled_surface(curve1, curve2)


class TestSurfaceOfRevolution:
    """Tests for surfaces of revolution."""

    def test_surface_of_revolution_creation(self) -> None:
        """Test surface of revolution creation."""
        profile = [
            Point3D(2, 0, 0),
            Point3D(3, 0, 1),
            Point3D(2, 0, 2),
        ]

        axis_point = Point3D(0, 0, 0)
        axis_direction = Vector3D(0, 0, 1)

        patches = surface_of_revolution(profile, axis_point, axis_direction, num_sections=4)

        assert len(patches) == 4

    def test_surface_of_revolution_evaluation(self) -> None:
        """Test surface of revolution evaluation."""
        profile = [Point3D(1, 0, 0), Point3D(1, 0, 1)]

        axis_point = Point3D(0, 0, 0)
        axis_direction = Vector3D(0, 0, 1)

        patches = surface_of_revolution(profile, axis_point, axis_direction, num_sections=4)

        if patches:
            p = patches[0].evaluate(0.5, 0.5)
            assert p is not None

    def test_surface_of_revolution_sections(self) -> None:
        """Test surface of revolution with different section counts."""
        profile = [Point3D(1, 0, 0), Point3D(1, 0, 1)]

        axis_point = Point3D(0, 0, 0)
        axis_direction = Vector3D(0, 0, 1)

        for num_sections in [4, 8, 16]:
            patches = surface_of_revolution(profile, axis_point, axis_direction, num_sections=num_sections)

            assert len(patches) == num_sections


class TestSurfaceNormalMap:
    """Tests for surface normal mapping."""

    def test_surface_normal_map_generation(self) -> None:
        """Test normal map generation."""
        from thomas.cad.surfaces import surface_normal_map

        control_points = [
            [Point3D(0, 0, 0), Point3D(1, 0, 0)],
            [Point3D(0, 1, 0), Point3D(1, 1, 1)],
        ]

        patch = BezierPatch(control_points, degree_u=1, degree_v=1)

        normals = surface_normal_map(patch, resolution=5)

        assert len(normals) == 5
        assert len(normals[0]) == 5
        assert all(isinstance(n, Vector3D) for row in normals for n in row)

    def test_surface_normal_map_resolution(self) -> None:
        """Test normal map at different resolutions."""
        from thomas.cad.surfaces import surface_normal_map

        control_points = [
            [Point3D(0, 0, 0), Point3D(1, 0, 0)],
            [Point3D(0, 1, 0), Point3D(1, 1, 0)],
        ]

        patch = BezierPatch(control_points, degree_u=1, degree_v=1)

        for resolution in [3, 5, 10]:
            normals = surface_normal_map(patch, resolution=resolution)
            assert len(normals) == resolution
            assert len(normals[0]) == resolution


class TestSurfaceErrors:
    """Tests for error handling."""

    def test_bezier_patch_empty_grid(self) -> None:
        """Test Bezier patch with empty control grid."""
        from thomas.cad._exceptions import SurfaceError

        with pytest.raises(SurfaceError):
            BezierPatch([], degree_u=1, degree_v=1)

    def test_bspline_surface_invalid_knots(self) -> None:
        """Test B-spline with invalid knot vectors."""
        control_points = [
            [Point3D(0, 0, 0), Point3D(1, 0, 0)],
            [Point3D(0, 1, 0), Point3D(1, 1, 0)],
        ]

        knot_u = [0, 1]
        knot_v = [0, 1]

        surface = BSplineSurface(control_points, knot_u, knot_v, degree_u=1, degree_v=1)

        assert surface is not None
