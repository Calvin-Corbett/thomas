"""
thomas.graphics3d: A complete 3D graphics/rendering engine.

This module provides a software-based 3D graphics pipeline including:
- 3D math primitives (vectors, matrices, quaternions)
- Mesh generation and manipulation
- Software rasterization
- Shading models (Phong, Blinn-Phong, PBR)
- Texture mapping and filtering
- Scene graph management
- Ray tracing
- Skeletal animation
- Complete rendering pipeline

Example:
    >>> from thomas.marketplace.graphics3d import Vec3, Mat4, Camera, Mesh
    >>> v = Vec3(1, 2, 3)
    >>> m = Mat4.identity()
    >>> cam = Camera(position=Vec3(0, 0, 5))
"""

__version__ = "1.0.0"
__all__ = [
    "Vec2",
    "Vec3",
    "Vec4",
    "Mat3",
    "Mat4",
    "Quaternion",
    "Ray",
    "AABB",
    "Sphere",
    "Plane",
    "Triangle",
    "Vertex",
    "Mesh",
    "Material",
    "Color",
    "Light",
    "Camera",
    "Viewport",
    "FrameBuffer",
    "Texture",
    "UV",
    "Graphics3DError",
    "MathError",
    "MeshError",
    "RasterizerError",
    "ShaderError",
    "TextureError",
]

from thomas.marketplace.graphics3d._exceptions import (
    Graphics3DError,
    MathError,
    MeshError,
    RasterizerError,
    ShaderError,
    TextureError,
)
from thomas.marketplace.graphics3d._graphics_types import (
    Camera,
    Color,
    FrameBuffer,
    Light,
    Material,
    Mesh,
    Texture,
    Vertex,
    Viewport,
)
from thomas.marketplace.graphics3d._types import (
    AABB,
    UV,
    Mat3,
    Mat4,
    Plane,
    Quaternion,
    Ray,
    Sphere,
    Triangle,
    Vec2,
    Vec3,
    Vec4,
)
