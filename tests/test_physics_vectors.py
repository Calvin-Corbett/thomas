"""
Tests for physics vector types and operations.
"""

import pytest

from thomas.physics._types import Vec2, Vec3


class TestVec2:
    """Tests for 2D vector operations."""

    def test_creation(self) -> None:
        """Test vector creation."""
        v = Vec2(3, 4)
        assert v.x == 3
        assert v.y == 4

    def test_addition(self) -> None:
        """Test vector addition."""
        v1 = Vec2(1, 2)
        v2 = Vec2(3, 4)
        result = v1 + v2
        assert result == Vec2(4, 6)

    def test_subtraction(self) -> None:
        """Test vector subtraction."""
        v1 = Vec2(5, 7)
        v2 = Vec2(2, 3)
        result = v1 - v2
        assert result == Vec2(3, 4)

    def test_scalar_multiplication(self) -> None:
        """Test scalar multiplication."""
        v = Vec2(2, 3)
        result = v * 2
        assert result == Vec2(4, 6)

        result = 2 * v
        assert result == Vec2(4, 6)

    def test_scalar_division(self) -> None:
        """Test scalar division."""
        v = Vec2(6, 8)
        result = v / 2
        assert result == Vec2(3, 4)

    def test_division_by_zero(self) -> None:
        """Test division by zero raises error."""
        v = Vec2(1, 2)
        with pytest.raises(ValueError):
            v / 0

    def test_negation(self) -> None:
        """Test vector negation."""
        v = Vec2(3, -4)
        result = -v
        assert result == Vec2(-3, 4)

    def test_magnitude(self) -> None:
        """Test vector magnitude calculation."""
        v = Vec2(3, 4)
        assert v.magnitude() == 5.0

    def test_magnitude_squared(self) -> None:
        """Test squared magnitude (faster computation)."""
        v = Vec2(3, 4)
        assert v.magnitude_squared() == 25.0

    def test_normalize(self) -> None:
        """Test vector normalization."""
        v = Vec2(3, 4)
        normalized = v.normalize()
        assert abs(normalized.magnitude() - 1.0) < 1e-9
        assert abs(normalized.x - 0.6) < 1e-9
        assert abs(normalized.y - 0.8) < 1e-9

    def test_normalize_zero_vector(self) -> None:
        """Test normalizing zero vector."""
        v = Vec2(0, 0)
        normalized = v.normalize()
        assert normalized == Vec2(0, 0)

    def test_dot_product(self) -> None:
        """Test dot product."""
        v1 = Vec2(2, 3)
        v2 = Vec2(4, 5)
        assert v1.dot(v2) == 23  # 2*4 + 3*5

    def test_cross_product(self) -> None:
        """Test 2D cross product (scalar)."""
        v1 = Vec2(1, 0)
        v2 = Vec2(0, 1)
        assert v1.cross(v2) == 1.0

    def test_distance(self) -> None:
        """Test distance between vectors."""
        v1 = Vec2(0, 0)
        v2 = Vec2(3, 4)
        assert v1.distance_to(v2) == 5.0

    def test_distance_squared(self) -> None:
        """Test squared distance."""
        v1 = Vec2(0, 0)
        v2 = Vec2(3, 4)
        assert v1.distance_squared_to(v2) == 25.0

    def test_perpendicular(self) -> None:
        """Test perpendicular vector."""
        v = Vec2(1, 0)
        perp = v.perpendicular()
        assert perp == Vec2(0, 1)

    def test_lerp(self) -> None:
        """Test linear interpolation."""
        v1 = Vec2(0, 0)
        v2 = Vec2(10, 10)
        mid = v1.lerp(v2, 0.5)
        assert mid == Vec2(5, 5)

    def test_clamp_magnitude(self) -> None:
        """Test magnitude clamping."""
        v = Vec2(5, 0)
        clamped = v.clamp_magnitude(2.0)
        assert clamped.magnitude() <= 2.0
        assert clamped.magnitude() == 2.0

    def test_equality(self) -> None:
        """Test vector equality with epsilon tolerance."""
        v1 = Vec2(1.0, 2.0)
        v2 = Vec2(1.0, 2.0)
        assert v1 == v2

        v3 = Vec2(1.0 + 1e-10, 2.0)
        assert v1 == v3


class TestVec3:
    """Tests for 3D vector operations."""

    def test_creation(self) -> None:
        """Test vector creation."""
        v = Vec3(1, 2, 3)
        assert v.x == 1
        assert v.y == 2
        assert v.z == 3

    def test_addition(self) -> None:
        """Test vector addition."""
        v1 = Vec3(1, 2, 3)
        v2 = Vec3(4, 5, 6)
        result = v1 + v2
        assert result == Vec3(5, 7, 9)

    def test_subtraction(self) -> None:
        """Test vector subtraction."""
        v1 = Vec3(5, 7, 9)
        v2 = Vec3(2, 3, 4)
        result = v1 - v2
        assert result == Vec3(3, 4, 5)

    def test_scalar_multiplication(self) -> None:
        """Test scalar multiplication."""
        v = Vec3(1, 2, 3)
        result = v * 2
        assert result == Vec3(2, 4, 6)

    def test_scalar_division(self) -> None:
        """Test scalar division."""
        v = Vec3(6, 8, 10)
        result = v / 2
        assert result == Vec3(3, 4, 5)

    def test_negation(self) -> None:
        """Test vector negation."""
        v = Vec3(1, -2, 3)
        result = -v
        assert result == Vec3(-1, 2, -3)

    def test_magnitude(self) -> None:
        """Test vector magnitude."""
        v = Vec3(1, 2, 2)
        assert v.magnitude() == 3.0

    def test_magnitude_squared(self) -> None:
        """Test squared magnitude."""
        v = Vec3(1, 2, 2)
        assert v.magnitude_squared() == 9.0

    def test_normalize(self) -> None:
        """Test vector normalization."""
        v = Vec3(1, 2, 2)
        normalized = v.normalize()
        assert abs(normalized.magnitude() - 1.0) < 1e-9

    def test_normalize_zero_vector(self) -> None:
        """Test normalizing zero vector."""
        v = Vec3(0, 0, 0)
        normalized = v.normalize()
        assert normalized == Vec3(0, 0, 0)

    def test_dot_product(self) -> None:
        """Test dot product."""
        v1 = Vec3(1, 2, 3)
        v2 = Vec3(4, 5, 6)
        assert v1.dot(v2) == 32  # 1*4 + 2*5 + 3*6

    def test_cross_product(self) -> None:
        """Test 3D cross product."""
        v1 = Vec3(1, 0, 0)
        v2 = Vec3(0, 1, 0)
        result = v1.cross(v2)
        assert result == Vec3(0, 0, 1)

    def test_cross_product_anticommutativity(self) -> None:
        """Test that a × b = -(b × a)."""
        v1 = Vec3(1, 2, 3)
        v2 = Vec3(4, 5, 6)
        cross1 = v1.cross(v2)
        cross2 = v2.cross(v1)
        assert cross1 == -cross2

    def test_distance(self) -> None:
        """Test distance between vectors."""
        v1 = Vec3(0, 0, 0)
        v2 = Vec3(1, 2, 2)
        assert v1.distance_to(v2) == 3.0

    def test_distance_squared(self) -> None:
        """Test squared distance."""
        v1 = Vec3(0, 0, 0)
        v2 = Vec3(1, 2, 2)
        assert v1.distance_squared_to(v2) == 9.0

    def test_lerp(self) -> None:
        """Test linear interpolation."""
        v1 = Vec3(0, 0, 0)
        v2 = Vec3(10, 10, 10)
        mid = v1.lerp(v2, 0.5)
        assert mid == Vec3(5, 5, 5)

    def test_clamp_magnitude(self) -> None:
        """Test magnitude clamping."""
        v = Vec3(3, 0, 4)
        clamped = v.clamp_magnitude(2.0)
        assert clamped.magnitude() <= 2.0
        assert abs(clamped.magnitude() - 2.0) < 1e-9

    def test_equality(self) -> None:
        """Test vector equality."""
        v1 = Vec3(1.0, 2.0, 3.0)
        v2 = Vec3(1.0, 2.0, 3.0)
        assert v1 == v2

    def test_operations_preserve_precision(self) -> None:
        """Test that operations maintain reasonable precision."""
        v = Vec3(0.1, 0.2, 0.3)
        result = v + v + v + v + v + v + v + v + v + v
        expected = Vec3(1.0, 2.0, 3.0)
        assert result.distance_to(expected) < 1e-9
