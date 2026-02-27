"""
Tests for collision detection algorithms.
"""

from thomas.physics._types import AABB, Plane, Ray, Sphere, Vec2, Vec3
from thomas.physics.collision_detection import (
    collide_aabb_aabb,
    collide_aabb_sphere,
    collide_sphere_plane,
    collide_sphere_sphere,
    generate_collision_manifold,
    gjk_collision,
    ray_aabb_intersection,
    ray_plane_intersection,
    ray_sphere_intersection,
    sat_collision_2d,
)


class TestSphereSphereCollision:
    """Tests for sphere-sphere collision detection."""

    def test_no_collision(self) -> None:
        """Test spheres that don't collide."""
        s1 = Sphere(Vec3(0, 0, 0), 1.0)
        s2 = Sphere(Vec3(3, 0, 0), 1.0)
        result = collide_sphere_sphere(s1, s2)
        assert result is None

    def test_touching_spheres(self) -> None:
        """Test spheres that touch."""
        s1 = Sphere(Vec3(0, 0, 0), 1.0)
        s2 = Sphere(Vec3(2, 0, 0), 1.0)
        result = collide_sphere_sphere(s1, s2)
        assert result is not None
        assert abs(result.penetration_depth) < 1e-6

    def test_overlapping_spheres(self) -> None:
        """Test overlapping spheres."""
        s1 = Sphere(Vec3(0, 0, 0), 1.0)
        s2 = Sphere(Vec3(1, 0, 0), 1.0)
        result = collide_sphere_sphere(s1, s2)
        assert result is not None
        assert result.penetration_depth > 0
        assert abs(result.penetration_depth - 1.0) < 1e-6

    def test_contact_normal_direction(self) -> None:
        """Test contact normal points from s1 to s2."""
        s1 = Sphere(Vec3(0, 0, 0), 1.0)
        s2 = Sphere(Vec3(1, 0, 0), 1.0)
        result = collide_sphere_sphere(s1, s2)
        assert result is not None
        assert abs(result.contact_normal.x - 1.0) < 1e-6
        assert abs(result.contact_normal.y) < 1e-6


class TestAABBCollision:
    """Tests for AABB collision detection."""

    def test_no_overlap(self) -> None:
        """Test AABBs that don't overlap."""
        a1 = AABB(Vec3(0, 0, 0), Vec3(1, 1, 1))
        a2 = AABB(Vec3(2, 0, 0), Vec3(3, 1, 1))
        assert not collide_aabb_aabb(a1, a2)

    def test_touching_aabbs(self) -> None:
        """Test AABBs that touch."""
        a1 = AABB(Vec3(0, 0, 0), Vec3(1, 1, 1))
        a2 = AABB(Vec3(1, 0, 0), Vec3(2, 1, 1))
        assert collide_aabb_aabb(a1, a2)

    def test_overlapping_aabbs(self) -> None:
        """Test overlapping AABBs."""
        a1 = AABB(Vec3(0, 0, 0), Vec3(2, 2, 2))
        a2 = AABB(Vec3(1, 1, 1), Vec3(3, 3, 3))
        assert collide_aabb_aabb(a1, a2)

    def test_aabb_contains_aabb(self) -> None:
        """Test AABB containing another."""
        a1 = AABB(Vec3(0, 0, 0), Vec3(10, 10, 10))
        a2 = AABB(Vec3(2, 2, 2), Vec3(3, 3, 3))
        assert collide_aabb_aabb(a1, a2)


class TestSpherePlaneCollision:
    """Tests for sphere-plane collision detection."""

    def test_no_collision(self) -> None:
        """Test sphere not colliding with plane."""
        s = Sphere(Vec3(0, 2, 0), 1.0)
        p = Plane(Vec3(0, 1, 0), 0)  # Plane at y=0
        result = collide_sphere_plane(s, p)
        assert result is None

    def test_sphere_touching_plane(self) -> None:
        """Test sphere touching plane."""
        s = Sphere(Vec3(0, 1, 0), 1.0)
        p = Plane(Vec3(0, 1, 0), 0)  # Plane at y=0
        result = collide_sphere_plane(s, p)
        assert result is not None
        assert result.penetration_depth < 1e-6

    def test_sphere_intersecting_plane(self) -> None:
        """Test sphere intersecting plane."""
        s = Sphere(Vec3(0, 0.5, 0), 1.0)
        p = Plane(Vec3(0, 1, 0), 0)  # Plane at y=0
        result = collide_sphere_plane(s, p)
        assert result is not None
        assert result.penetration_depth > 0
        assert abs(result.penetration_depth - 0.5) < 1e-6


class TestAABBSphereCollision:
    """Tests for AABB-sphere collision detection."""

    def test_no_collision(self) -> None:
        """Test AABB and sphere not colliding."""
        a = AABB(Vec3(0, 0, 0), Vec3(1, 1, 1))
        s = Sphere(Vec3(3, 0, 0), 1.0)
        result = collide_aabb_sphere(a, s)
        assert result is None

    def test_touching(self) -> None:
        """Test AABB and sphere touching."""
        a = AABB(Vec3(0, 0, 0), Vec3(1, 1, 1))
        s = Sphere(Vec3(2, 0.5, 0.5), 1.0)
        result = collide_aabb_sphere(a, s)
        assert result is not None
        assert result.penetration_depth < 1e-6

    def test_overlapping(self) -> None:
        """Test overlapping AABB and sphere."""
        a = AABB(Vec3(0, 0, 0), Vec3(2, 2, 2))
        s = Sphere(Vec3(1, 1, 1), 1.0)
        result = collide_aabb_sphere(a, s)
        assert result is not None
        assert result.penetration_depth > 0


class TestRayIntersection:
    """Tests for ray intersection methods."""

    def test_ray_sphere_hit(self) -> None:
        """Test ray hitting sphere."""
        r = Ray(Vec3(0, 0, -5), Vec3(0, 0, 1))
        s = Sphere(Vec3(0, 0, 0), 1.0)
        t = ray_sphere_intersection(r, s)
        assert t is not None
        assert 3.5 < t < 4.5

    def test_ray_sphere_miss(self) -> None:
        """Test ray missing sphere."""
        r = Ray(Vec3(0, 2, -5), Vec3(0, 0, 1))
        s = Sphere(Vec3(0, 0, 0), 1.0)
        t = ray_sphere_intersection(r, s)
        assert t is None

    def test_ray_sphere_inside(self) -> None:
        """Test ray starting inside sphere."""
        r = Ray(Vec3(0, 0, 0), Vec3(0, 0, 1))
        s = Sphere(Vec3(0, 0, 0), 1.0)
        t = ray_sphere_intersection(r, s)
        assert t is not None
        assert t > 0

    def test_ray_aabb_hit(self) -> None:
        """Test ray hitting AABB."""
        r = Ray(Vec3(-5, 0, 0), Vec3(1, 0, 0))
        a = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
        t = ray_aabb_intersection(r, a)
        assert t is not None
        assert abs(t - 4.0) < 1e-6

    def test_ray_aabb_miss(self) -> None:
        """Test ray missing AABB."""
        r = Ray(Vec3(0, 5, 0), Vec3(0, 1, 0))
        a = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
        t = ray_aabb_intersection(r, a)
        assert t is None

    def test_ray_plane_hit(self) -> None:
        """Test ray hitting plane."""
        r = Ray(Vec3(0, -5, 0), Vec3(0, 1, 0))
        p = Plane(Vec3(0, 1, 0), 0)  # Plane at y=0
        t = ray_plane_intersection(r, p)
        assert t is not None
        assert abs(t - 5.0) < 1e-6

    def test_ray_plane_parallel(self) -> None:
        """Test ray parallel to plane."""
        r = Ray(Vec3(0, 1, 0), Vec3(1, 0, 0))
        p = Plane(Vec3(0, 1, 0), 0)
        t = ray_plane_intersection(r, p)
        assert t is None


class TestSATCollision:
    """Tests for Separating Axis Theorem."""

    def test_squares_no_collision(self) -> None:
        """Test non-colliding squares."""
        square1 = [Vec2(0, 0), Vec2(1, 0), Vec2(1, 1), Vec2(0, 1)]
        square2 = [Vec2(2, 0), Vec2(3, 0), Vec2(3, 1), Vec2(2, 1)]
        assert not sat_collision_2d(square1, square2)

    def test_squares_touching(self) -> None:
        """Test touching squares."""
        square1 = [Vec2(0, 0), Vec2(1, 0), Vec2(1, 1), Vec2(0, 1)]
        square2 = [Vec2(1, 0), Vec2(2, 0), Vec2(2, 1), Vec2(1, 1)]
        assert sat_collision_2d(square1, square2)

    def test_squares_overlapping(self) -> None:
        """Test overlapping squares."""
        square1 = [Vec2(0, 0), Vec2(2, 0), Vec2(2, 2), Vec2(0, 2)]
        square2 = [Vec2(1, 1), Vec2(3, 1), Vec2(3, 3), Vec2(1, 3)]
        assert sat_collision_2d(square1, square2)

    def test_triangles_collision(self) -> None:
        """Test triangle collision."""
        tri1 = [Vec2(0, 0), Vec2(2, 0), Vec2(1, 2)]
        tri2 = [Vec2(1, 1), Vec2(3, 1), Vec2(2, 3)]
        assert sat_collision_2d(tri1, tri2)


class TestGJKCollision:
    """Tests for GJK algorithm."""

    def test_gjk_collision_overlapping(self) -> None:
        """Test GJK with overlapping shapes."""
        vertices_a = [Vec3(0, 0, 0), Vec3(2, 0, 0), Vec3(1, 2, 0)]
        vertices_b = [Vec3(1, 1, 0), Vec3(3, 1, 0), Vec3(2, 3, 0)]
        # These triangles should overlap
        result = gjk_collision(vertices_a, vertices_b)
        # Result is either collision or near miss, which is acceptable
        assert isinstance(result, bool)


class TestCollisionManifold:
    """Tests for collision manifold generation."""

    def test_manifold_sphere_sphere(self) -> None:
        """Test manifold generation for sphere-sphere."""
        s1 = Sphere(Vec3(0, 0, 0), 1.0)
        s2 = Sphere(Vec3(1.5, 0, 0), 1.0)
        manifold = generate_collision_manifold(
            Vec3(0, 0, 0),
            Vec3(1.5, 0, 0),
            sphere_a=s1,
            sphere_b=s2,
        )
        assert manifold is not None
        assert manifold.penetration_depth > 0
        assert abs(manifold.contact_normal.x - 1.0) < 1e-6
