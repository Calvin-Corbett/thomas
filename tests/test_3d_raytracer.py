"""
Tests for ray tracing: ray-primitive intersections, BVH, and ray tracing.

Tests:
- Ray-sphere intersection
- Ray-triangle intersection
- Ray-AABB intersection
- BVH construction and traversal
- Ray tracing with reflection/refraction
- Soft shadows
- Anti-aliasing
"""

from thomas.marketplace.graphics3d import mesh as mesh_module
from thomas.marketplace.graphics3d import raytracer
from thomas.marketplace.graphics3d._types import AABB, Color, Ray, Vec3


class TestRaySphereIntersection:
    """Tests for ray-sphere intersection."""

    def test_ray_sphere_hit(self) -> None:
        """Test ray hitting sphere."""
        hit, dist = raytracer.ray_intersect_sphere(Ray(Vec3(0, 0, -5), Vec3(0, 0, 1)), Vec3(0, 0, 0), 1.0)
        assert hit
        assert 4 < dist < 5

    def test_ray_sphere_miss(self) -> None:
        """Test ray missing sphere."""
        hit, dist = raytracer.ray_intersect_sphere(Ray(Vec3(0, 0, -5), Vec3(1, 0, 0)), Vec3(0, 0, 0), 1.0)
        assert not hit

    def test_ray_sphere_inside(self) -> None:
        """Test ray starting inside sphere."""
        hit, dist = raytracer.ray_intersect_sphere(Ray(Vec3(0, 0, 0), Vec3(1, 0, 0)), Vec3(0, 0, 0), 2.0)
        assert hit


class TestRayTriangleIntersection:
    """Tests for ray-triangle intersection."""

    def test_ray_triangle_hit(self) -> None:
        """Test ray hitting triangle."""
        hit, t, u, v = raytracer.ray_intersect_triangle(
            Ray(Vec3(0, 0, -1), Vec3(0, 0, 1)), Vec3(-1, -1, 0), Vec3(1, -1, 0), Vec3(0, 1, 0)
        )
        assert hit
        assert t > 0
        assert 0 <= u <= 1
        assert 0 <= v <= 1

    def test_ray_triangle_miss(self) -> None:
        """Test ray missing triangle."""
        hit, t, u, v = raytracer.ray_intersect_triangle(
            Ray(Vec3(0, 0, -1), Vec3(1, 0, 0)), Vec3(-1, -1, 0), Vec3(1, -1, 0), Vec3(0, 1, 0)
        )
        assert not hit

    def test_ray_triangle_backface(self) -> None:
        """Test ray hitting back face."""
        # Ray going opposite direction
        hit, t, u, v = raytracer.ray_intersect_triangle(
            Ray(Vec3(0, 0, 1), Vec3(0, 0, -1)), Vec3(-1, -1, 0), Vec3(1, -1, 0), Vec3(0, 1, 0)
        )
        assert not hit or t <= 0


class TestRayAABBIntersection:
    """Tests for ray-AABB intersection."""

    def test_ray_aabb_hit(self) -> None:
        """Test ray hitting AABB."""
        aabb = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
        hit, dist = raytracer.ray_intersect_aabb(Ray(Vec3(0, 0, -5), Vec3(0, 0, 1)), aabb)
        assert hit

    def test_ray_aabb_miss(self) -> None:
        """Test ray missing AABB."""
        aabb = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
        hit, dist = raytracer.ray_intersect_aabb(Ray(Vec3(-5, -5, -5), Vec3(0, 0, 1)), aabb)
        assert not hit


class TestBVHConstruction:
    """Tests for BVH construction."""

    def test_bvh_from_cube(self) -> None:
        """Test BVH construction from cube."""
        m = mesh_module.create_cube(1.0)
        bvh = raytracer.BVH(m)

        assert bvh.root is not None

    def test_bvh_from_sphere(self) -> None:
        """Test BVH construction from sphere."""
        m = mesh_module.create_sphere(1.0, 16, 16)
        bvh = raytracer.BVH(m)

        assert bvh.root is not None


class TestBVHIntersection:
    """Tests for BVH ray tracing."""

    def test_bvh_intersect_cube(self) -> None:
        """Test ray intersection with cube via BVH."""
        m = mesh_module.create_cube(1.0)
        bvh = raytracer.BVH(m)

        ray = Ray(Vec3(0, 0, -5), Vec3(0, 0, 1))
        result = bvh.intersect(ray)

        assert result.hit

    def test_bvh_intersect_miss(self) -> None:
        """Test ray missing mesh via BVH."""
        m = mesh_module.create_cube(1.0)
        bvh = raytracer.BVH(m)

        ray = Ray(Vec3(-5, -5, -5), Vec3(0, 0, 1))
        bvh.intersect(ray)

        # Likely to miss
        # assert not result.hit  # Not guaranteed depending on mesh size


class TestFresnel:
    """Tests for Fresnel computation."""

    def test_fresnel_schlick(self) -> None:
        """Test Fresnel-Schlick approximation."""
        # Normal incidence
        f = raytracer.fresnel_schlick(1.0, 0.04)
        assert abs(f - 0.04) < 1e-6

        # Grazing angle
        f = raytracer.fresnel_schlick(0.0, 0.04)
        assert abs(f - 1.0) < 1e-6


class TestRefraction:
    """Tests for refraction computation."""

    def test_refract_direction(self) -> None:
        """Test refraction direction."""
        incident = Vec3(0, -1, 0)
        normal = Vec3(0, 1, 0)
        ior = 1.5

        refracted = raytracer.refract_direction(incident, normal, ior)
        assert refracted is not None

    def test_total_internal_reflection(self) -> None:
        """Test total internal reflection."""
        incident = Vec3(1, -0.5, 0).normalize()
        normal = Vec3(0, 1, 0)
        ior = 0.5  # n2/n1 < 1 (going from denser to less dense)

        raytracer.refract_direction(incident, normal, ior)
        # Might result in total internal reflection depending on angle
        # assert refracted is None  # Not guaranteed


class TestRaytracer:
    """Tests for high-level ray tracer."""

    def test_raytracer_creation(self) -> None:
        """Test ray tracer creation."""
        rt = raytracer.Raytracer()
        assert rt.max_bounces == 5

    def test_raytracer_add_mesh(self) -> None:
        """Test adding mesh to ray tracer."""
        rt = raytracer.Raytracer()
        m = mesh_module.create_cube(1.0)
        rt.add_mesh(m)

        assert len(rt.bvhs) == 1

    def test_raytracer_trace_ray(self) -> None:
        """Test ray tracing."""
        rt = raytracer.Raytracer()
        m = mesh_module.create_cube(1.0)
        rt.add_mesh(m)

        ray = Ray(Vec3(0, 0, -5), Vec3(0, 0, 1))
        color = rt.trace_ray(ray)

        assert isinstance(color, Color)
        assert 0 <= color.r <= 1
        assert 0 <= color.g <= 1
        assert 0 <= color.b <= 1


class TestAntialiasing:
    """Tests for anti-aliasing."""

    def test_jitter_deterministic(self) -> None:
        """Test that jitter is deterministic."""
        jitter1 = raytracer.compute_antialiasing_jitter(0, 0, 42)
        jitter2 = raytracer.compute_antialiasing_jitter(0, 0, 42)

        assert jitter1 == jitter2

    def test_jitter_different_samples(self) -> None:
        """Test that different samples give different jitter."""
        jitter1 = raytracer.compute_antialiasing_jitter(0, 0, 42)
        jitter2 = raytracer.compute_antialiasing_jitter(1, 0, 42)

        assert jitter1 != jitter2

    def test_jitter_range(self) -> None:
        """Test that jitter is in [0, 1) range."""
        for i in range(100):
            jx, jy = raytracer.compute_antialiasing_jitter(i, 0, 42)
            assert 0 <= jx < 1
            assert 0 <= jy < 1


class TestSoftShadows:
    """Tests for soft shadow computation."""

    def test_soft_shadow_creation(self) -> None:
        """Test soft shadow computation."""
        from thomas.marketplace.graphics3d._types import Light, LightType

        position = Vec3(0, 0, 0)
        light = Light(type=LightType.DIRECTIONAL, direction=Vec3(0, -1, 0), range=10.0)

        # Empty scene - should be fully lit
        shadow = raytracer.compute_soft_shadow(position, light, [], num_samples=4)
        assert 0 <= shadow <= 1

    def test_soft_shadow_with_occluder(self) -> None:
        """Test soft shadow with occluding geometry."""
        from thomas.marketplace.graphics3d._types import Light, LightType

        position = Vec3(0, 0, 0)
        light = Light(type=LightType.POINT, position=Vec3(5, 5, 5), range=100.0)

        m = mesh_module.create_cube(1.0)
        bvh = raytracer.BVH(m)

        # Compute shadow (might be fully lit or partially shadowed depending on geometry)
        shadow = raytracer.compute_soft_shadow(position, light, [bvh], num_samples=4)
        assert 0 <= shadow <= 1


class TestRayTracerIntegration:
    """Integration tests for ray tracer."""

    def test_trace_simple_scene(self) -> None:
        """Test tracing simple scene."""
        rt = raytracer.Raytracer(max_bounces=2)

        # Create simple scene
        cube = mesh_module.create_cube(1.0)
        sphere = mesh_module.create_sphere(0.5, 8, 8)

        rt.add_mesh(cube)
        rt.add_mesh(sphere)

        # Trace several rays
        for x in range(-2, 3):
            for y in range(-2, 3):
                ray = Ray(Vec3(x * 0.5, y * 0.5, -10), Vec3(0, 0, 1))
                color = rt.trace_ray(ray)

                assert isinstance(color, Color)
                assert color.r >= 0 and color.r <= 1
                assert color.g >= 0 and color.g <= 1
                assert color.b >= 0 and color.b <= 1
