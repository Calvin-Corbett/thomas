"""
Tests for 3D math operations.

Tests:
- Vector operations (add, sub, mul, dot, cross, normalize, length)
- Matrix operations (multiply, transpose, inverse, determinant)
- Quaternion operations (from euler, from axis-angle, slerp, nlerp)
- Transformation matrices (translate, rotate, scale, look-at)
- Projections (perspective, orthographic)
- Frustum plane extraction
"""

import math

import pytest

from thomas.marketplace.graphics3d import math3d
from thomas.marketplace.graphics3d._exceptions import MathError
from thomas.marketplace.graphics3d._types import Mat4, Quaternion, Vec2, Vec3, Vec4


class TestVec2:
    """Tests for 2D vectors."""

    def test_add(self) -> None:
        """Test vector addition."""
        v1 = Vec2(1, 2)
        v2 = Vec2(3, 4)
        result = v1 + v2
        assert result.x == 4 and result.y == 6

    def test_sub(self) -> None:
        """Test vector subtraction."""
        v1 = Vec2(5, 6)
        v2 = Vec2(2, 3)
        result = v1 - v2
        assert result.x == 3 and result.y == 3

    def test_mul_scalar(self) -> None:
        """Test scalar multiplication."""
        v = Vec2(2, 3)
        result = v * 4
        assert result.x == 8 and result.y == 12

    def test_dot(self) -> None:
        """Test dot product."""
        v1 = Vec2(1, 0)
        v2 = Vec2(0, 1)
        assert v1.dot(v2) == 0

        v1 = Vec2(1, 2)
        v2 = Vec2(3, 4)
        assert v1.dot(v2) == 11

    def test_length(self) -> None:
        """Test vector length."""
        v = Vec2(3, 4)
        assert abs(v.length() - 5.0) < 1e-6

    def test_normalize(self) -> None:
        """Test vector normalization."""
        v = Vec2(3, 4)
        n = v.normalize()
        assert abs(n.length() - 1.0) < 1e-6


class TestVec3:
    """Tests for 3D vectors."""

    def test_add(self) -> None:
        """Test vector addition."""
        v1 = Vec3(1, 2, 3)
        v2 = Vec3(4, 5, 6)
        result = v1 + v2
        assert result == Vec3(5, 7, 9)

    def test_cross(self) -> None:
        """Test cross product."""
        v1 = Vec3(1, 0, 0)
        v2 = Vec3(0, 1, 0)
        result = v1.cross(v2)
        assert result == Vec3(0, 0, 1)

    def test_dot(self) -> None:
        """Test dot product."""
        v1 = Vec3(1, 2, 3)
        v2 = Vec3(4, 5, 6)
        assert v1.dot(v2) == 32

    def test_length(self) -> None:
        """Test length computation."""
        v = Vec3(2, 3, 6)
        assert abs(v.length() - 7.0) < 1e-6

    def test_normalize(self) -> None:
        """Test normalization."""
        v = Vec3(1, 2, 2)
        n = v.normalize()
        assert abs(n.length() - 1.0) < 1e-6

    def test_lerp(self) -> None:
        """Test linear interpolation."""
        v1 = Vec3(0, 0, 0)
        v2 = Vec3(10, 10, 10)
        result = v1.lerp(v2, 0.5)
        assert result == Vec3(5, 5, 5)

    def test_equality(self) -> None:
        """Test vector equality."""
        v1 = Vec3(1, 2, 3)
        v2 = Vec3(1, 2, 3)
        assert v1 == v2


class TestVec4:
    """Tests for homogeneous 4D vectors."""

    def test_to_vec3(self) -> None:
        """Test conversion to Vec3."""
        v = Vec4(2, 4, 6, 2)
        v3 = v.to_vec3()
        assert v3 == Vec3(1, 2, 3)

    def test_normalize(self) -> None:
        """Test normalization."""
        v = Vec4(1, 2, 2, 1)
        n = v.normalize()
        assert abs(n.length() - 1.0) < 1e-6


class TestMat4:
    """Tests for 4x4 matrices."""

    def test_identity(self) -> None:
        """Test identity matrix."""
        m = Mat4.identity()
        v = Vec4(1, 2, 3, 1)
        result = m * v
        assert result == v

    def test_multiply_matrices(self) -> None:
        """Test matrix multiplication."""
        m1 = Mat4.identity()
        m2 = Mat4.identity()
        result = m1 * m2
        assert result == m1

    def test_multiply_vector(self) -> None:
        """Test matrix-vector multiplication."""
        m = Mat4.identity()
        v = Vec4(5, 6, 7, 1)
        result = m * v
        assert result == v

    def test_transpose(self) -> None:
        """Test matrix transpose."""
        m = Mat4.identity()
        t = m.transpose()
        assert t == m

    def test_determinant(self) -> None:
        """Test determinant computation."""
        m = Mat4.identity()
        det = m.determinant()
        assert abs(det - 1.0) < 1e-6

    def test_inverse(self) -> None:
        """Test matrix inverse."""
        m = Mat4.identity()
        inv = m.inverse()
        assert inv == m

    def test_inverse_translation(self) -> None:
        """Test inverse of translation matrix."""
        m = math3d.matrix_translate(Vec3(5, 10, 15))
        inv = m.inverse()

        v = Vec4(0, 0, 0, 1)
        result = inv * (m * v)
        assert abs(result.x - 0) < 1e-6
        assert abs(result.y - 0) < 1e-6
        assert abs(result.z - 0) < 1e-6

    def test_singular_inverse(self) -> None:
        """Test inverse of singular matrix."""
        m = Mat4([[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])
        with pytest.raises(ValueError):
            m.inverse()


class TestQuaternion:
    """Tests for quaternions."""

    def test_from_axis_angle(self) -> None:
        """Test quaternion from axis-angle."""
        q = Quaternion.from_axis_angle(Vec3(0, 0, 1), math.pi / 2)
        assert abs(q.length() - 1.0) < 1e-6

    def test_from_euler(self) -> None:
        """Test quaternion from Euler angles."""
        q = Quaternion.from_euler(0, 0, 0)
        assert q == Quaternion(1, 0, 0, 0)

    def test_to_rotation_matrix(self) -> None:
        """Test conversion to rotation matrix."""
        q = Quaternion.from_axis_angle(Vec3(0, 1, 0), math.pi / 2)
        m = q.to_rotation_matrix()

        v = Vec4(1, 0, 0, 0)
        result = m * v
        # Should rotate 90 degrees around Y
        assert abs(result.x) < 1e-6
        assert abs(result.z + 1) < 1e-6

    def test_slerp(self) -> None:
        """Test spherical linear interpolation."""
        q1 = Quaternion(1, 0, 0, 0)
        q2 = Quaternion(0, 1, 0, 0)

        result = q1.slerp(q2, 0.5)
        assert abs(result.length() - 1.0) < 1e-6

    def test_nlerp(self) -> None:
        """Test normalized linear interpolation."""
        q1 = Quaternion(1, 0, 0, 0)
        q2 = Quaternion(0, 1, 0, 0)

        result = q1.nlerp(q2, 0.5)
        assert abs(result.length() - 1.0) < 1e-6

    def test_conjugate(self) -> None:
        """Test quaternion conjugate."""
        q = Quaternion(1, 2, 3, 4)
        conj = q.conjugate()
        assert conj == Quaternion(1, -2, -3, -4)


class TestTransformationMatrices:
    """Tests for transformation matrices."""

    def test_translate(self) -> None:
        """Test translation matrix."""
        m = math3d.matrix_translate(Vec3(1, 2, 3))
        v = Vec4(0, 0, 0, 1)
        result = m * v
        assert result == Vec4(1, 2, 3, 1)

    def test_scale(self) -> None:
        """Test scale matrix."""
        m = math3d.matrix_scale(Vec3(2, 3, 4))
        v = Vec4(1, 1, 1, 1)
        result = m * v
        assert result == Vec4(2, 3, 4, 1)

    def test_rotate(self) -> None:
        """Test rotation matrix."""
        m = math3d.matrix_rotate(Vec3(0, 0, 1), math.pi / 2)
        v = Vec4(1, 0, 0, 1)
        result = m * v
        assert abs(result.x) < 1e-6
        assert abs(result.y - 1) < 1e-6

    def test_look_at(self) -> None:
        """Test look-at matrix."""
        eye = Vec3(0, 0, 5)
        target = Vec3(0, 0, 0)
        up = Vec3(0, 1, 0)

        m = math3d.matrix_look_at(eye, target, up)
        # Matrix should exist and be valid
        assert m is not None

    def test_perspective(self) -> None:
        """Test perspective projection."""
        fov = math.pi / 4  # 45 degrees
        aspect = 1.0
        near = 0.1
        far = 100.0

        m = math3d.matrix_perspective(fov, aspect, near, far)
        assert m is not None

    def test_orthographic(self) -> None:
        """Test orthographic projection."""
        m = math3d.matrix_orthographic(-1, 1, -1, 1, 0.1, 100)
        assert m is not None

    def test_perspective_invalid(self) -> None:
        """Test perspective with invalid parameters."""
        with pytest.raises(MathError):
            math3d.matrix_perspective(math.pi / 4, 1, 10, 10)

    def test_orthographic_invalid(self) -> None:
        """Test orthographic with invalid parameters."""
        with pytest.raises(MathError):
            math3d.matrix_orthographic(-1, -1, -1, 1, 0.1, 100)


class TestRayIntersection:
    """Tests for ray-primitive intersections."""

    def test_ray_sphere_intersection(self) -> None:
        """Test ray-sphere intersection."""
        hit, dist = math3d.ray_intersect_sphere(Vec3(0, 0, -5), Vec3(0, 0, 1), Vec3(0, 0, 0), 1.0)
        assert hit
        assert 4 < dist < 5

    def test_ray_sphere_no_intersection(self) -> None:
        """Test ray-sphere with no intersection."""
        hit, dist = math3d.ray_intersect_sphere(Vec3(0, 0, -5), Vec3(1, 0, 0), Vec3(0, 0, 0), 1.0)
        assert not hit

    def test_ray_triangle_intersection(self) -> None:
        """Test ray-triangle intersection."""
        hit, t, u, v = math3d.ray_intersect_triangle(
            Vec3(0, 0, -1), Vec3(0, 0, 1), Vec3(-1, -1, 0), Vec3(1, -1, 0), Vec3(0, 1, 0)
        )
        assert hit
        assert t > 0

    def test_ray_aabb_intersection(self) -> None:
        """Test ray-AABB intersection."""
        from thomas.marketplace.graphics3d._types import AABB

        aabb = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
        hit, dist = math3d.ray_intersect_aabb(Vec3(0, 0, -5), Vec3(0, 0, 1), aabb)
        assert hit


class TestFrustumPlanes:
    """Tests for frustum plane extraction."""

    def test_extract_frustum_planes(self) -> None:
        """Test frustum plane extraction."""
        proj = math3d.matrix_perspective(math.pi / 4, 1.0, 0.1, 100)
        view = math3d.matrix_look_at(Vec3(0, 0, 5), Vec3(0, 0, 0), Vec3(0, 1, 0))
        pv = proj * view

        planes = math3d.extract_frustum_planes(pv)
        assert len(planes) == 6

        # All planes should have normalized normals
        for plane in planes:
            length = plane.normal.length()
            assert abs(length - 1.0) < 1e-6


class TestAABB:
    """Tests for axis-aligned bounding boxes."""

    def test_aabb_contains_point(self) -> None:
        """Test point-in-AABB test."""
        from thomas.marketplace.graphics3d._types import AABB

        aabb = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
        assert aabb.contains_point(Vec3(0, 0, 0))
        assert not aabb.contains_point(Vec3(2, 0, 0))

    def test_aabb_intersect(self) -> None:
        """Test AABB-AABB intersection."""
        aabb1 = math3d.aabb_from_points([Vec3(-1, -1, -1), Vec3(1, 1, 1)])
        aabb2 = math3d.aabb_from_points([Vec3(0, 0, 0), Vec3(2, 2, 2)])
        assert math3d.aabb_intersect(aabb1, aabb2)

    def test_aabb_merge(self) -> None:
        """Test AABB merging."""
        aabb1 = math3d.aabb_from_points([Vec3(0, 0, 0), Vec3(1, 1, 1)])
        aabb2 = math3d.aabb_from_points([Vec3(2, 2, 2), Vec3(3, 3, 3)])
        merged = math3d.aabb_merge(aabb1, aabb2)
        assert merged.min == Vec3(0, 0, 0)
        assert merged.max == Vec3(3, 3, 3)
