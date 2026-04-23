"""
Tests for shading models: Phong, Blinn-Phong, PBR, and shadow mapping.

Tests:
- Phong illumination model
- Blinn-Phong optimization
- PBR (Cook-Torrance BRDF)
- Shadow mapping
- Fresnel effect
"""

import math

from thomas.marketplace.graphics3d import shading
from thomas.marketplace.graphics3d._types import Color, Light, LightType, Material, Vec3


class TestPhongLighting:
    """Tests for Phong illumination."""

    def test_phong_ambient_only(self) -> None:
        """Test Phong with just ambient light."""
        position = Vec3(0, 0, 0)
        normal = Vec3(0, 1, 0)
        camera_pos = Vec3(0, 0, 5)
        material = Material(ambient=Color(0.2, 0.2, 0.2, 1))
        light = Light(
            type=LightType.DIRECTIONAL,
            direction=Vec3(0, -1, 0),
            color=Color(1, 1, 1, 1),
            intensity=0.0,  # No intensity except ambient
        )

        color = shading.compute_phong_lighting(position, normal, camera_pos, material, light)
        assert color.r > 0
        assert color.g > 0
        assert color.b > 0

    def test_phong_directional_light(self) -> None:
        """Test Phong with directional light."""
        position = Vec3(0, 0, 0)
        normal = Vec3(0, 1, 0)
        camera_pos = Vec3(0, 0, 5)
        material = Material()
        light = Light(type=LightType.DIRECTIONAL, direction=Vec3(0, -1, 0), color=Color(1, 1, 1, 1), intensity=1.0)

        color = shading.compute_phong_lighting(position, normal, camera_pos, material, light)
        # Should have non-zero color
        assert color.r > 0 or color.g > 0 or color.b > 0

    def test_phong_point_light(self) -> None:
        """Test Phong with point light."""
        position = Vec3(0, 0, 0)
        normal = Vec3(0, 1, 0)
        camera_pos = Vec3(0, 0, 5)
        material = Material()
        light = Light(type=LightType.POINT, position=Vec3(1, 1, 1), color=Color(1, 1, 1, 1), intensity=1.0, range=100.0)

        color = shading.compute_phong_lighting(position, normal, camera_pos, material, light)
        assert color.r >= 0 and color.r <= 1

    def test_phong_spotlight(self) -> None:
        """Test Phong with spotlight."""
        position = Vec3(0, 0, 0)
        normal = Vec3(0, 1, 0)
        camera_pos = Vec3(0, 0, 5)
        material = Material()
        light = Light(
            type=LightType.SPOTLIGHT,
            position=Vec3(0, 5, 0),
            direction=Vec3(0, -1, 0),
            color=Color(1, 1, 1, 1),
            intensity=1.0,
            cone_angle=math.pi / 4,
        )

        color = shading.compute_phong_lighting(position, normal, camera_pos, material, light)
        assert color.r >= 0


class TestBlinnPhongLighting:
    """Tests for Blinn-Phong illumination."""

    def test_blinn_phong_directional(self) -> None:
        """Test Blinn-Phong with directional light."""
        position = Vec3(0, 0, 0)
        normal = Vec3(0, 1, 0)
        camera_pos = Vec3(0, 0, 5)
        material = Material()
        light = Light(type=LightType.DIRECTIONAL, direction=Vec3(0, -1, 0), color=Color(1, 1, 1, 1), intensity=1.0)

        color = shading.compute_blinn_phong_lighting(position, normal, camera_pos, material, light)
        assert color.r >= 0 and color.r <= 2  # Might exceed 1 before clamping

    def test_blinn_phong_vs_phong(self) -> None:
        """Test that Blinn-Phong produces valid output."""
        position = Vec3(1, 2, 3)
        normal = Vec3(0, 1, 0).normalize()
        camera_pos = Vec3(5, 5, 5)
        material = Material(specular=Color(1, 1, 1, 1), shininess=64)
        light = Light(
            type=LightType.DIRECTIONAL, direction=Vec3(-1, -1, -1).normalize(), color=Color(1, 1, 1, 1), intensity=1.0
        )

        bp_color = shading.compute_blinn_phong_lighting(position, normal, camera_pos, material, light)

        # Should be valid color values
        assert bp_color.r >= 0
        assert bp_color.g >= 0
        assert bp_color.b >= 0


class TestLightAttenuation:
    """Tests for light attenuation."""

    def test_directional_no_attenuation(self) -> None:
        """Test directional light has no attenuation."""
        position = Vec3(1000, 1000, 1000)
        light = Light(type=LightType.DIRECTIONAL)

        attenuation = shading.compute_light_attenuation(light, position)
        assert attenuation == 1.0

    def test_point_light_attenuation(self) -> None:
        """Test point light attenuation."""
        position = Vec3(0, 0, 0)
        light = Light(type=LightType.POINT, position=Vec3(1, 0, 0), range=10.0)

        attenuation = shading.compute_light_attenuation(light, position)
        assert 0 <= attenuation <= 1

    def test_point_light_far_away(self) -> None:
        """Test point light far away."""
        position = Vec3(0, 0, 0)
        light = Light(type=LightType.POINT, position=Vec3(100, 0, 0), range=10.0)

        attenuation = shading.compute_light_attenuation(light, position)
        assert attenuation == 0

    def test_spotlight_within_cone(self) -> None:
        """Test spotlight within cone."""
        position = Vec3(0, 0, 0)
        light = Light(
            type=LightType.SPOTLIGHT,
            position=Vec3(0, 1, 0),
            direction=Vec3(0, -1, 0),
            cone_angle=math.pi / 4,
            range=10.0,
        )

        attenuation = shading.compute_light_attenuation(light, position)
        assert attenuation > 0


class TestReflectionRefraction:
    """Tests for reflection and refraction."""

    def test_reflect_vector(self) -> None:
        """Test reflection vector computation."""
        incident = Vec3(1, -1, 0).normalize()
        normal = Vec3(0, 1, 0)

        reflected = shading.reflect_vector(incident, normal)
        assert reflected.length() > 0

    def test_fresnel_schlick(self) -> None:
        """Test Fresnel-Schlick approximation."""
        # At 0 degrees (normal incidence), should return f0
        f = shading.fresnel_schlick(1.0, 0.04)
        assert abs(f - 0.04) < 1e-6

        # At 90 degrees (grazing angle), should return 1
        f = shading.fresnel_schlick(0.0, 0.04)
        assert abs(f - 1.0) < 1e-6

        # In between
        f = shading.fresnel_schlick(0.5, 0.04)
        assert 0.04 < f < 1.0


class TestCookTorranceBRDF:
    """Tests for Cook-Torrance BRDF."""

    def test_cook_torrance_brdf(self) -> None:
        """Test Cook-Torrance BRDF computation."""
        light_dir = Vec3(1, 1, 0).normalize()
        view_dir = Vec3(0, 1, 0).normalize()
        normal = Vec3(0, 1, 0)
        material = Material(roughness=0.5, metallic=0.0)

        brdf = shading.compute_brdf_cook_torrance(light_dir, view_dir, normal, material)

        assert brdf.r >= 0
        assert brdf.g >= 0
        assert brdf.b >= 0

    def test_cook_torrance_smooth_surface(self) -> None:
        """Test BRDF with smooth surface."""
        light_dir = Vec3(0, 1, 0)
        view_dir = Vec3(0, 1, 0)
        normal = Vec3(0, 1, 0)
        material = Material(roughness=0.1, metallic=0.0)

        brdf = shading.compute_brdf_cook_torrance(light_dir, view_dir, normal, material)

        # Smooth surface should have higher specular
        assert brdf.r > 0

    def test_cook_torrance_rough_surface(self) -> None:
        """Test BRDF with rough surface."""
        light_dir = Vec3(1, 1, 0).normalize()
        view_dir = Vec3(-1, 1, 0).normalize()
        normal = Vec3(0, 1, 0)
        material = Material(roughness=0.9, metallic=0.0)

        brdf = shading.compute_brdf_cook_torrance(light_dir, view_dir, normal, material)

        # Rough surface should have lower specular
        assert brdf.r >= 0


class TestPBRLighting:
    """Tests for PBR lighting."""

    def test_pbr_single_light(self) -> None:
        """Test PBR with single light."""
        position = Vec3(0, 0, 0)
        normal = Vec3(0, 1, 0)
        camera_pos = Vec3(0, 0, 5)
        material = Material(roughness=0.5, metallic=0.0)
        light = Light(type=LightType.DIRECTIONAL, direction=Vec3(0, -1, 0), color=Color(1, 1, 1, 1), intensity=1.0)

        color = shading.compute_pbr_lighting(position, normal, camera_pos, material, [light])

        assert color.r >= 0 and color.r <= 1
        assert color.g >= 0 and color.g <= 1
        assert color.b >= 0 and color.b <= 1

    def test_pbr_multiple_lights(self) -> None:
        """Test PBR with multiple lights."""
        position = Vec3(0, 0, 0)
        normal = Vec3(0, 1, 0)
        camera_pos = Vec3(0, 0, 5)
        material = Material(roughness=0.5, metallic=0.0)

        lights = [
            Light(
                type=LightType.DIRECTIONAL,
                direction=Vec3(-1, -1, 0).normalize(),
                color=Color(1, 0, 0, 1),
                intensity=1.0,
            ),
            Light(type=LightType.POINT, position=Vec3(5, 5, 5), color=Color(0, 0, 1, 1), intensity=1.0),
        ]

        color = shading.compute_pbr_lighting(position, normal, camera_pos, material, lights)

        assert color.r >= 0
        assert color.g >= 0
        assert color.b >= 0


class TestShadowMap:
    """Tests for shadow mapping."""

    def test_shadowmap_creation(self) -> None:
        """Test shadow map creation."""
        sm = shading.ShadowMap(512, 512)
        assert sm.width == 512
        assert sm.height == 512

    def test_shadowmap_set_get_depth(self) -> None:
        """Test setting and getting depth."""
        sm = shading.ShadowMap(256, 256)
        sm.set_depth(128, 128, 0.5)

        depth = sm.get_depth(128, 128)
        assert depth == 0.5

    def test_shadowmap_test_shadow(self) -> None:
        """Test shadow testing."""
        sm = shading.ShadowMap(256, 256)

        # Set a depth value
        sm.set_depth(128, 128, 0.5)

        # Test point in front of shadow
        in_shadow = sm.test_shadow(Vec3(0.5, 0.5, 0.3))
        assert in_shadow == 1.0  # Not in shadow

    def test_shadowmap_pcf(self) -> None:
        """Test percentage-closer filtering."""
        sm = shading.ShadowMap(256, 256)

        # Set some depth values
        for x in range(100, 150):
            for y in range(100, 150):
                sm.set_depth(x, y, 0.5)

        result = sm.test_shadow_pcf(Vec3(0.5, 0.5, 0.3), kernel_size=3)
        assert 0 <= result <= 1


class TestColorClamping:
    """Tests for color clamping."""

    def test_clamp_color(self) -> None:
        """Test color clamping."""
        color = Color(1.5, -0.5, 0.5, 2.0)
        clamped = shading.clamp_color(color)

        assert clamped.r == 1.0
        assert clamped.g == 0.0
        assert clamped.b == 0.5
        assert clamped.a == 1.0

    def test_clamp_valid_color(self) -> None:
        """Test that valid color is unchanged."""
        color = Color(0.5, 0.5, 0.5, 1.0)
        clamped = shading.clamp_color(color)

        assert clamped == color
