"""
Texture mapping, sampling, and filtering.

Provides:
- UV coordinate mapping
- Texture sampling (nearest, bilinear, trilinear with mipmaps)
- Mipmap generation
- Wrapping modes (repeat, clamp, mirror)
- Texture formats (RGB, RGBA, grayscale)
- Procedural textures
- Normal map application
- Cubemap sampling
"""

from __future__ import annotations

import math
from enum import Enum

from thomas.marketplace.graphics3d._exceptions import TextureError
from thomas.marketplace.graphics3d._types import (
    Color,
    Texture,
    Vec3,
)


class WrapMode(Enum):
    """Texture wrapping mode."""

    REPEAT = "repeat"
    CLAMP = "clamp"
    MIRROR = "mirror"


class FilterMode(Enum):
    """Texture filtering mode."""

    NEAREST = "nearest"
    BILINEAR = "bilinear"
    TRILINEAR = "trilinear"


def wrap_coordinate(coord: float, mode: WrapMode) -> float:
    """Apply wrapping to texture coordinate.

    Args:
        coord: Texture coordinate
        mode: Wrapping mode

    Returns:
        Wrapped coordinate in [0, 1)
    """
    if mode == WrapMode.REPEAT:
        return coord - math.floor(coord)

    elif mode == WrapMode.CLAMP:
        return max(0, min(1, coord))

    elif mode == WrapMode.MIRROR:
        coord = coord - math.floor(coord)
        if coord > 0.5:
            coord = 1 - coord
        return coord * 2

    else:
        return coord


def sample_nearest(texture: Texture, u: float, v: float, wrap_mode: WrapMode = WrapMode.REPEAT) -> Color:
    """Sample texture with nearest-neighbor filtering.

    Args:
        texture: Texture to sample
        u, v: Texture coordinates [0, 1]
        wrap_mode: Wrapping mode

    Returns:
        Sampled color
    """
    u = wrap_coordinate(u, wrap_mode)
    v = wrap_coordinate(v, wrap_mode)

    x = int(u * texture.width) % texture.width
    y = int(v * texture.height) % texture.height

    return texture.get_pixel(x, y)


def sample_bilinear(texture: Texture, u: float, v: float, wrap_mode: WrapMode = WrapMode.REPEAT) -> Color:
    """Sample texture with bilinear filtering.

    Args:
        texture: Texture to sample
        u, v: Texture coordinates [0, 1]
        wrap_mode: Wrapping mode

    Returns:
        Sampled color
    """
    u = wrap_coordinate(u, wrap_mode)
    v = wrap_coordinate(v, wrap_mode)

    # Compute texel coordinates
    u_f = u * (texture.width - 1)
    v_f = v * (texture.height - 1)

    x0 = int(math.floor(u_f))
    y0 = int(math.floor(v_f))
    x1 = min(x0 + 1, texture.width - 1)
    y1 = min(y0 + 1, texture.height - 1)

    # Fractional parts
    fx = u_f - x0
    fy = v_f - y0

    # Sample four corners
    c00 = texture.get_pixel(x0, y0)
    c10 = texture.get_pixel(x1, y0)
    c01 = texture.get_pixel(x0, y1)
    c11 = texture.get_pixel(x1, y1)

    # Bilinear interpolation
    c0 = Color(
        c00.r + fx * (c10.r - c00.r),
        c00.g + fx * (c10.g - c00.g),
        c00.b + fx * (c10.b - c00.b),
        c00.a + fx * (c10.a - c00.a),
    )

    c1 = Color(
        c01.r + fx * (c11.r - c01.r),
        c01.g + fx * (c11.g - c01.g),
        c01.b + fx * (c11.b - c01.b),
        c01.a + fx * (c11.a - c01.a),
    )

    result = Color(
        c0.r + fy * (c1.r - c0.r),
        c0.g + fy * (c1.g - c0.g),
        c0.b + fy * (c1.b - c0.b),
        c0.a + fy * (c1.a - c0.a),
    )

    return result


def generate_mipmaps(texture: Texture) -> list[Texture]:
    """Generate mipmap chain via box filtering.

    Args:
        texture: Base texture

    Returns:
        List of mipmaps from base to 1x1
    """
    mipmaps: list[Texture] = [texture]

    current = texture
    while current.width > 1 or current.height > 1:
        # Compute next mipmap dimensions
        next_width = max(1, current.width // 2)
        next_height = max(1, current.height // 2)

        next_data: list[Color] = []

        for y in range(next_height):
            for x in range(next_width):
                # Box filter: average 2x2 region
                src_x = x * 2
                src_y = y * 2

                colors: list[Color] = []
                for dy in range(2):
                    for dx in range(2):
                        if src_x + dx < current.width and src_y + dy < current.height:
                            colors.append(current.get_pixel(src_x + dx, src_y + dy))

                # Average colors
                if colors:
                    avg = Color(
                        sum(c.r for c in colors) / len(colors),
                        sum(c.g for c in colors) / len(colors),
                        sum(c.b for c in colors) / len(colors),
                        sum(c.a for c in colors) / len(colors),
                    )
                    next_data.append(avg)
                else:
                    next_data.append(Color(0, 0, 0, 1))

        current = Texture(next_width, next_height, next_data)
        mipmaps.append(current)

    return mipmaps


def sample_trilinear(
    texture: Texture,
    mipmaps: list[Texture],
    u: float,
    v: float,
    lod: float = 0.0,
    wrap_mode: WrapMode = WrapMode.REPEAT,
) -> Color:
    """Sample texture with trilinear filtering (bilinear + mipmap interpolation).

    Args:
        texture: Base texture
        mipmaps: Precomputed mipmaps
        u, v: Texture coordinates
        lod: Level of detail (0 = base, higher = smaller)
        wrap_mode: Wrapping mode

    Returns:
        Sampled color
    """
    lod = max(0, min(lod, len(mipmaps) - 1))

    lod_low = int(math.floor(lod))
    lod_high = min(lod_low + 1, len(mipmaps) - 1)
    lod_frac = lod - lod_low

    # Sample at two LODs
    color_low = sample_bilinear(mipmaps[lod_low], u, v, wrap_mode)
    color_high = sample_bilinear(mipmaps[lod_high], u, v, wrap_mode)

    # Interpolate
    result = Color(
        color_low.r + lod_frac * (color_high.r - color_low.r),
        color_low.g + lod_frac * (color_high.g - color_low.g),
        color_low.b + lod_frac * (color_high.b - color_low.b),
        color_low.a + lod_frac * (color_high.a - color_low.a),
    )

    return result


def compute_lod(u0: float, v0: float, u1: float, v1: float, texture_width: int) -> float:
    """Compute level of detail from texture coordinate derivatives.

    Args:
        u0, v0: Texture coordinates at fragment
        u1, v1: Texture coordinates at adjacent fragment
        texture_width: Base texture width

    Returns:
        LOD value
    """
    du = (u1 - u0) * texture_width
    dv = (v1 - v0) * texture_width

    pixel_footprint = math.sqrt(du * du + dv * dv)
    lod = math.log2(max(1, pixel_footprint))

    return max(0, lod)


def create_checkerboard(width: int = 256, height: int = 256, square_size: int = 32) -> Texture:
    """Create checkerboard procedural texture.

    Args:
        width: Texture width
        height: Texture height
        square_size: Size of checker squares

    Returns:
        Checkerboard texture
    """
    data: list[Color] = []

    for y in range(height):
        for x in range(width):
            checker_x = (x // square_size) % 2
            checker_y = (y // square_size) % 2

            if (checker_x + checker_y) % 2 == 0:
                data.append(Color(1, 1, 1, 1))
            else:
                data.append(Color(0, 0, 0, 1))

    return Texture(width, height, data)


def create_gradient(
    width: int = 256,
    height: int = 256,
    direction: str = "horizontal",
) -> Texture:
    """Create gradient procedural texture.

    Args:
        width: Texture width
        height: Texture height
        direction: Gradient direction ('horizontal', 'vertical', 'diagonal')

    Returns:
        Gradient texture
    """
    data: list[Color] = []

    for y in range(height):
        for x in range(width):
            if direction == "horizontal":
                t = x / width
            elif direction == "vertical":
                t = y / height
            else:  # diagonal
                t = (x + y) / (width + height)

            t = max(0, min(1, t))
            data.append(Color(t, t, t, 1))

    return Texture(width, height, data)


def create_perlin_noise(width: int = 256, height: int = 256, scale: float = 0.1) -> Texture:
    """Create Perlin-like noise procedural texture (simplified).

    Args:
        width: Texture width
        height: Texture height
        scale: Noise scale

    Returns:
        Noise texture
    """

    data: list[Color] = []

    for y in range(height):
        for x in range(width):
            # Simple pseudo-random based on position
            # Real Perlin noise would use proper gradient interpolation
            noise = (math.sin(x * scale) * math.cos(y * scale) + 1) / 2

            data.append(Color(noise, noise, noise, 1))

    return Texture(width, height, data)


class Cubemap:
    """Cubemap for environment mapping."""

    def __init__(self) -> None:
        """Initialize cubemap with 6 faces."""
        self.faces: dict[str, Texture] = {
            "positive_x": Texture(1, 1, [Color(1, 0, 0, 1)]),
            "negative_x": Texture(1, 1, [Color(1, 0, 0, 1)]),
            "positive_y": Texture(1, 1, [Color(0, 1, 0, 1)]),
            "negative_y": Texture(1, 1, [Color(0, 1, 0, 1)]),
            "positive_z": Texture(1, 1, [Color(0, 0, 1, 1)]),
            "negative_z": Texture(1, 1, [Color(0, 0, 1, 1)]),
        }

    def sample(self, direction: Vec3) -> Color:
        """Sample cubemap via direction vector.

        Args:
            direction: Direction vector (normalized)

        Returns:
            Sampled color
        """
        x, y, z = direction.x, direction.y, direction.z
        abs_x, abs_y, abs_z = abs(x), abs(y), abs(z)

        # Determine which face and compute UV
        if abs_x >= abs_y and abs_x >= abs_z:
            if x > 0:
                face = "positive_x"
                u = -z / abs_x
                v = y / abs_x
            else:
                face = "negative_x"
                u = z / abs_x
                v = y / abs_x
        elif abs_y >= abs_z:
            if y > 0:
                face = "positive_y"
                u = x / abs_y
                v = -z / abs_y
            else:
                face = "negative_y"
                u = x / abs_y
                v = z / abs_y
        else:
            if z > 0:
                face = "positive_z"
                u = x / abs_z
                v = y / abs_z
            else:
                face = "negative_z"
                u = -x / abs_z
                v = y / abs_z

        # Convert [-1, 1] to [0, 1]
        u = (u + 1) / 2
        v = (v + 1) / 2

        return sample_bilinear(self.faces[face], u, v, WrapMode.CLAMP)

    def set_face(self, face: str, texture: Texture) -> None:
        """Set a cubemap face.

        Args:
            face: Face name (positive_x, negative_x, etc.)
            texture: Face texture
        """
        if face in self.faces:
            self.faces[face] = texture
        else:
            raise TextureError(f"Invalid cubemap face: {face}")


def apply_normal_map(
    surface_normal: Vec3,
    normal_map_color: Color,
    tangent: Vec3,
    bitangent: Vec3,
) -> Vec3:
    """Apply normal map to surface normal (tangent space to world space).

    Args:
        surface_normal: Original surface normal
        normal_map_color: Sampled color from normal map
        tangent: Tangent vector
        bitangent: Bitangent (binormal) vector

    Returns:
        Transformed normal in world space
    """
    # Convert from [0, 1] to [-1, 1]
    normal_ts = Vec3(
        normal_map_color.r * 2 - 1,
        normal_map_color.g * 2 - 1,
        normal_map_color.b * 2 - 1,
    ).normalize()

    # Transform to world space via TBN matrix
    normal_ws = (tangent * normal_ts.x + bitangent * normal_ts.y + surface_normal * normal_ts.z).normalize()

    return normal_ws


def compute_parallax_mapping(
    height_map_color: Color,
    view_dir: Vec3,
    tangent: Vec3,
    bitangent: Vec3,
    surface_normal: Vec3,
    height_scale: float = 0.1,
) -> tuple[float, float]:
    """Compute parallax occlusion offset for texture coordinates.

    Args:
        height_map_color: Sampled height from height map
        view_dir: View direction in world space
        tangent: Tangent vector
        bitangent: Bitangent vector
        surface_normal: Surface normal
        height_scale: Parallax effect scale

    Returns:
        Offset (du, dv) for texture coordinates
    """
    # Transform view direction to tangent space
    view_tangent = Vec3(view_dir.dot(tangent), view_dir.dot(bitangent), view_dir.dot(surface_normal))

    # Compute height and offset
    height = height_map_color.r
    offset = (height - 0.5) * height_scale

    # Project onto tangent plane
    parallax = view_tangent * (offset / max(view_tangent.z, 0.1))

    return parallax.x, parallax.y
