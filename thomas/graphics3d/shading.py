"""
Shading models: Phong, Blinn-Phong, and PBR.

Provides:
- Phong illumination (ambient, diffuse, specular per light)
- Blinn-Phong optimization
- Shading modes (flat, Gouraud, Phong/per-pixel)
- Multiple light types (directional, point, spotlight)
- Shadow mapping basics
- Cook-Torrance BRDF (GGX, Smith geometry, Fresnel)
"""

from __future__ import annotations

import math
from enum import Enum

from thomas.graphics3d._types import (
    Color,
    Light,
    LightType,
    Material,
    Vec3,
)


class ShadingMode(Enum):
    """Vertex shading interpolation mode."""

    FLAT = "flat"
    GOURAUD = "gouraud"
    PHONG = "phong"


def clamp_color(color: Color) -> Color:
    """Clamp color values to [0, 1]."""
    return Color(
        max(0, min(1, color.r)),
        max(0, min(1, color.g)),
        max(0, min(1, color.b)),
        max(0, min(1, color.a)),
    )


def compute_light_direction(light: Light, surface_position: Vec3) -> Vec3:
    """Compute light direction from surface.

    Args:
        light: Light source
        surface_position: Surface position

    Returns:
        Direction from surface to light (normalized)
    """
    if light.type == LightType.DIRECTIONAL:
        return -light.direction.normalize()

    else:  # POINT or SPOTLIGHT
        return (light.position - surface_position).normalize()


def compute_light_attenuation(light: Light, surface_position: Vec3) -> float:
    """Compute light attenuation for point and spot lights.

    Args:
        light: Light source
        surface_position: Surface position

    Returns:
        Attenuation factor [0, 1]
    """
    if light.type == LightType.DIRECTIONAL:
        return 1.0

    distance = (light.position - surface_position).length()

    # Point light attenuation (inverse square law)
    if light.range > 0:
        attenuation = max(0, 1 - (distance / light.range) ** 2)
    else:
        attenuation = 1.0

    # Spotlight cone attenuation
    if light.type == LightType.SPOTLIGHT:
        light_to_surface = (surface_position - light.position).normalize()
        spot_factor = light.direction.dot(light_to_surface)

        if spot_factor < math.cos(light.cone_angle):
            attenuation = 0.0
        else:
            # Smooth edge via cone_smoothness
            margin = light.cone_smoothness * 0.1
            if spot_factor < math.cos(light.cone_angle + margin):
                smoothed = (spot_factor - math.cos(light.cone_angle + margin)) / (
                    math.cos(light.cone_angle) - math.cos(light.cone_angle + margin)
                )
                attenuation *= max(0, smoothed)

    return attenuation


def compute_phong_lighting(
    surface_position: Vec3,
    surface_normal: Vec3,
    camera_position: Vec3,
    material: Material,
    light: Light,
) -> Color:
    """Compute Phong lighting for a single light.

    Args:
        surface_position: Surface position in world space
        surface_normal: Surface normal (normalized)
        camera_position: Camera position
        material: Material properties
        light: Light source

    Returns:
        Color contribution from this light
    """
    result = Color(0, 0, 0, 1)

    light_dir = compute_light_direction(light, surface_position)
    view_dir = (camera_position - surface_position).normalize()
    reflect_dir = reflect_vector(light_dir, surface_normal)

    # Ambient
    ambient = material.ambient * light.color
    result = result + ambient

    # Diffuse
    n_dot_l = max(0, surface_normal.dot(light_dir))
    attenuation = compute_light_attenuation(light, surface_position)
    diffuse = material.diffuse * light.color * light.intensity * n_dot_l * attenuation
    result = result + diffuse

    # Specular
    r_dot_v = max(0, reflect_dir.dot(view_dir))
    specular_factor = r_dot_v**material.shininess
    specular = material.specular * light.color * light.intensity * specular_factor * attenuation
    result = result + specular

    return result


def compute_blinn_phong_lighting(
    surface_position: Vec3,
    surface_normal: Vec3,
    camera_position: Vec3,
    material: Material,
    light: Light,
) -> Color:
    """Compute Blinn-Phong lighting (optimized with half-vector).

    Args:
        surface_position: Surface position in world space
        surface_normal: Surface normal (normalized)
        camera_position: Camera position
        material: Material properties
        light: Light source

    Returns:
        Color contribution from this light
    """
    result = Color(0, 0, 0, 1)

    light_dir = compute_light_direction(light, surface_position)
    view_dir = (camera_position - surface_position).normalize()
    half_vec = (light_dir + view_dir).normalize()

    # Ambient
    ambient = material.ambient * light.color
    result = result + ambient

    # Diffuse
    n_dot_l = max(0, surface_normal.dot(light_dir))
    attenuation = compute_light_attenuation(light, surface_position)
    diffuse = material.diffuse * light.color * light.intensity * n_dot_l * attenuation
    result = result + diffuse

    # Specular (Blinn-Phong uses half-vector)
    n_dot_h = max(0, surface_normal.dot(half_vec))
    specular_factor = n_dot_h**material.shininess
    specular = material.specular * light.color * light.intensity * specular_factor * attenuation
    result = result + specular

    return result


def reflect_vector(incident: Vec3, normal: Vec3) -> Vec3:
    """Compute reflection vector.

    Args:
        incident: Incident direction (should point toward surface)
        normal: Surface normal

    Returns:
        Reflection direction
    """
    return incident - normal * (2 * incident.dot(normal))


def fresnel_schlick(cos_theta: float, f0: float) -> float:
    """Compute Fresnel reflectance using Schlick approximation."""
    cos_theta = max(0.0, min(1.0, cos_theta))
    return f0 + (1 - f0) * ((1 - cos_theta) ** 5)


def compute_brdf_cook_torrance(
    light_dir: Vec3,
    view_dir: Vec3,
    normal: Vec3,
    material: Material,
) -> Color:
    """Compute Cook-Torrance BRDF.

    Uses:
    - GGX normal distribution (Trowbridge-Reitz)
    - Smith geometry function
    - Schlick Fresnel approximation

    Args:
        light_dir: Direction toward light
        view_dir: Direction toward viewer
        normal: Surface normal
        material: Material with metallic/roughness

    Returns:
        Specular BRDF value
    """
    half_vec = (light_dir + view_dir).normalize()

    n_dot_l = max(0.001, normal.dot(light_dir))
    n_dot_v = max(0.001, normal.dot(view_dir))
    n_dot_h = max(0.001, normal.dot(half_vec))
    h_dot_v = max(0.001, half_vec.dot(view_dir))

    # Roughness remap
    alpha = material.roughness * material.roughness
    alpha = alpha * alpha

    # GGX normal distribution (Trowbridge-Reitz)
    alpha_sq = alpha * alpha
    denom = n_dot_h * n_dot_h * (alpha_sq - 1) + 1
    d = alpha_sq / (3.14159 * denom * denom)

    # Smith geometry function
    def smith_g1(cos_theta: float) -> float:
        k = (material.roughness + 1) * (material.roughness + 1) / 8
        return cos_theta / (cos_theta * (1 - k) + k)

    g = smith_g1(n_dot_l) * smith_g1(n_dot_v)

    # Schlick Fresnel (F0 depends on metallic)
    f0 = 0.04 if material.metallic < 0.5 else material.diffuse.r
    f = fresnel_schlick(h_dot_v, f0)

    # Combine: (D * F * G) / (4 * (N.L) * (N.V))
    kSpecular = (d * f * g) / (4 * n_dot_l * n_dot_v)

    return Color(kSpecular, kSpecular, kSpecular, 1.0)


def compute_pbr_lighting(
    surface_position: Vec3,
    surface_normal: Vec3,
    camera_position: Vec3,
    material: Material,
    lights: list[Light],
) -> Color:
    """Compute PBR lighting from multiple lights.

    Args:
        surface_position: Surface position
        surface_normal: Surface normal
        camera_position: Camera position
        material: PBR material
        lights: List of lights

    Returns:
        Final shaded color
    """
    result = Color(0, 0, 0, 1)

    view_dir = (camera_position - surface_position).normalize()

    for light in lights:
        light_dir = compute_light_direction(light, surface_position)
        attenuation = compute_light_attenuation(light, surface_position)

        # Fresnel effect (viewing angle)
        brdf = compute_brdf_cook_torrance(light_dir, view_dir, surface_normal, material)

        # Diffuse contribution (Lambertian)
        n_dot_l = max(0, surface_normal.dot(light_dir))
        diffuse = material.diffuse * light.color * light.intensity * n_dot_l

        # Specular contribution
        specular = brdf * light.color * light.intensity * n_dot_l

        # Combine (simple additive for now)
        contribution = (diffuse + specular) * attenuation
        result = result + contribution

    return clamp_color(result)


class ShadowMap:
    """Simple shadow map for shadow mapping."""

    def __init__(self, width: int = 1024, height: int = 1024) -> None:
        """Initialize shadow map.

        Args:
            width: Shadow map width
            height: Shadow map height
        """
        self.width = width
        self.height = height
        self.depth_values: list[list[float]] = [[float("inf") for _ in range(width)] for _ in range(height)]

    def set_depth(self, x: int, y: int, depth: float) -> None:
        """Set depth value in shadow map."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self.depth_values[y][x] = depth

    def get_depth(self, x: int, y: int) -> float:
        """Get depth value from shadow map."""
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.depth_values[y][x]
        return float("inf")

    def test_shadow(self, light_space_position: Vec3, bias: float = 0.005) -> float:
        """Test if point is in shadow.

        Args:
            light_space_position: Position in light's coordinate space
            bias: Depth bias to prevent shadow acne

        Returns:
            Shadow factor [0, 1] (0=fully shadowed, 1=fully lit)
        """
        # Convert to shadow map coordinates
        x = int(light_space_position.x * self.width)
        y = int(light_space_position.y * self.height)
        z = light_space_position.z

        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return 1.0

        # Simple hard shadows
        shadow_depth = self.get_depth(x, y)

        if z <= shadow_depth + bias:
            return 1.0
        else:
            return 0.0

    def test_shadow_pcf(self, light_space_position: Vec3, kernel_size: int = 3, bias: float = 0.005) -> float:
        """Test shadow with percentage-closer filtering (PCF).

        Args:
            light_space_position: Position in light's coordinate space
            kernel_size: Filter kernel size (must be odd)
            bias: Depth bias

        Returns:
            Shadow factor [0, 1]
        """
        x_f = light_space_position.x * self.width
        y_f = light_space_position.y * self.height
        z = light_space_position.z

        radius = kernel_size // 2
        lit_count = 0
        total = 0

        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                x = int(x_f) + dx
                y = int(y_f) + dy

                if 0 <= x < self.width and 0 <= y < self.height:
                    shadow_depth = self.get_depth(x, y)
                    if z <= shadow_depth + bias:
                        lit_count += 1
                    total += 1

        return lit_count / total if total > 0 else 1.0


def compute_parallax_occlusion(
    view_dir: Vec3,
    normal: Vec3,
    height_map_value: float,
    height_scale: float = 0.1,
) -> Vec3:
    """Compute parallax occlusion offset for texture coordinates.

    Args:
        view_dir: View direction
        normal: Surface normal
        height_map_value: Height from height map [0, 1]
        height_scale: Parallax scale

    Returns:
        Offset for texture coordinates
    """
    # Simplified: just use height map to offset normals
    # Full implementation would iterate for better accuracy
    height = height_map_value - 0.5
    offset = height * height_scale * (normal - view_dir * normal.dot(view_dir))

    return offset


def compute_normal_from_height_map(height_values: list[list[float]], x: int, y: int) -> Vec3:
    """Compute normal from height map via Sobel filter.

    Args:
        height_values: Height map
        x, y: Texel coordinates

    Returns:
        Normal vector
    """
    width = len(height_values[0]) if height_values else 1
    height = len(height_values)

    # Sample neighbors with wrapping
    h_l = height_values[y][(x - 1) % width] if height_values else 0.5
    h_r = height_values[y][(x + 1) % width] if height_values else 0.5
    h_u = height_values[(y - 1) % height][x] if height_values else 0.5
    h_d = height_values[(y + 1) % height][x] if height_values else 0.5

    # Sobel filter
    normal_x = h_l - h_r
    normal_z = h_u - h_d
    normal_y = 1.0

    return Vec3(normal_x, normal_y, normal_z).normalize()
