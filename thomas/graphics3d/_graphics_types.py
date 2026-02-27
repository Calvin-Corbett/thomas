"""
Graphics-specific type definitions for 3D graphics engine.

Provides:
- Vertex and mesh structures
- Material properties
- Color management
- Light definitions
- Camera parameters
- Framebuffer and texture storage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from thomas.graphics3d._types import UV, Vec3


@dataclass
class Vertex:
    """Vertex with position, normal, texcoord, tangent."""

    position: Vec3
    normal: Vec3 = field(default_factory=lambda: Vec3(0, 1, 0))
    texcoord: UV = field(default_factory=lambda: UV(0, 0))
    tangent: Vec3 = field(default_factory=lambda: Vec3(1, 0, 0))

    def __eq__(self, other: Any) -> bool:
        """Check equality."""
        if not isinstance(other, Vertex):
            return False
        return (
            self.position == other.position
            and self.normal == other.normal
            and self.texcoord == other.texcoord
            and self.tangent == other.tangent
        )


@dataclass
class Mesh:
    """Triangle mesh with vertices and indices."""

    vertices: list[Vertex] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)

    def triangle_count(self) -> int:
        """Get number of triangles."""
        return len(self.indices) // 3

    def vertex_count(self) -> int:
        """Get number of vertices."""
        return len(self.vertices)


@dataclass
class Color:
    """RGBA color."""

    r: float = 1.0
    g: float = 1.0
    b: float = 1.0
    a: float = 1.0

    def __mul__(self, other: Color | float) -> Color:
        """Multiply colors or by scalar."""
        if isinstance(other, Color):
            return Color(self.r * other.r, self.g * other.g, self.b * other.b, self.a * other.a)
        return Color(self.r * other, self.g * other, self.b * other, self.a * other)

    def __rmul__(self, scalar: float) -> Color:
        """Multiply by scalar."""
        return Color(self.r * scalar, self.g * scalar, self.b * scalar, self.a * scalar)

    def __add__(self, other: Color) -> Color:
        """Add colors."""
        return Color(self.r + other.r, self.g + other.g, self.b + other.b, self.a + other.a)

    def clamp(self) -> Color:
        """Clamp values to [0, 1]."""
        return Color(
            max(0, min(1, self.r)),
            max(0, min(1, self.g)),
            max(0, min(1, self.b)),
            max(0, min(1, self.a)),
        )


class LightType(Enum):
    """Light type enumeration."""

    DIRECTIONAL = "directional"
    POINT = "point"
    SPOTLIGHT = "spotlight"


@dataclass
class Light:
    """Light source."""

    type: LightType = LightType.DIRECTIONAL
    position: Vec3 = field(default_factory=lambda: Vec3(0, 1, 0))
    direction: Vec3 = field(default_factory=lambda: Vec3(0, -1, 0))
    color: Color = field(default_factory=lambda: Color(1, 1, 1, 1))
    intensity: float = 1.0
    range: float = 100.0
    cone_angle: float = 0.785  # 45 degrees in radians
    cone_smoothness: float = 1.0


@dataclass
class Material:
    """Material properties for shading."""

    ambient: Color = field(default_factory=lambda: Color(0.2, 0.2, 0.2, 1.0))
    diffuse: Color = field(default_factory=lambda: Color(0.8, 0.8, 0.8, 1.0))
    specular: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0, 1.0))
    shininess: float = 32.0
    metallic: float = 0.0
    roughness: float = 0.5
    ior: float = 1.5


@dataclass
class Camera:
    """Camera with position, orientation, and projection."""

    position: Vec3 = field(default_factory=lambda: Vec3(0, 0, 5))
    target: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    up: Vec3 = field(default_factory=lambda: Vec3(0, 1, 0))
    fov: float = 1.0472  # 60 degrees in radians
    aspect: float = 1.0
    near: float = 0.1
    far: float = 1000.0

    def forward(self) -> Vec3:
        """Get forward direction."""
        return (self.target - self.position).normalize()

    def right(self) -> Vec3:
        """Get right direction."""
        return self.forward().cross(self.up).normalize()

    def actual_up(self) -> Vec3:
        """Get actual up direction."""
        return self.right().cross(self.forward()).normalize()


@dataclass
class Viewport:
    """Viewport for rendering."""

    x: int = 0
    y: int = 0
    width: int = 800
    height: int = 600

    def aspect_ratio(self) -> float:
        """Get aspect ratio."""
        if self.height == 0:
            return 1.0
        return self.width / self.height


@dataclass
class Texture:
    """2D texture data."""

    width: int = 1
    height: int = 1
    data: list[Color] = field(default_factory=lambda: [Color()])

    def get_pixel(self, x: int, y: int) -> Color:
        """Get pixel at (x, y)."""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return Color(0, 0, 0, 0)
        return self.data[y * self.width + x]

    def set_pixel(self, x: int, y: int, color: Color) -> None:
        """Set pixel at (x, y)."""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return
        self.data[y * self.width + x] = color


@dataclass
class FrameBuffer:
    """Frame buffer with color and depth."""

    width: int = 800
    height: int = 600
    color_buffer: list[Color] = field(default_factory=list)
    depth_buffer: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize buffers."""
        if not self.color_buffer:
            self.color_buffer = [Color(0, 0, 0, 1) for _ in range(self.width * self.height)]
        if not self.depth_buffer:
            self.depth_buffer = [float("inf") for _ in range(self.width * self.height)]

    def clear(self, color: Color = None, depth: float = float("inf")) -> None:
        """Clear frame buffer."""
        if color is None:
            color = Color(0, 0, 0, 1)
        for i in range(len(self.color_buffer)):
            self.color_buffer[i] = color
            self.depth_buffer[i] = depth

    def get_pixel(self, x: int, y: int) -> Color:
        """Get pixel color."""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return Color(0, 0, 0, 0)
        return self.color_buffer[y * self.width + x]

    def set_pixel(self, x: int, y: int, color: Color) -> None:
        """Set pixel color."""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return
        self.color_buffer[y * self.width + x] = color

    def get_depth(self, x: int, y: int) -> float:
        """Get depth value."""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return float("inf")
        return self.depth_buffer[y * self.width + x]

    def set_depth(self, x: int, y: int, depth: float) -> None:
        """Set depth value."""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return
        self.depth_buffer[y * self.width + x] = depth
