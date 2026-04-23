"""
Exception classes for the 3D graphics engine.

Provides specialized exception types for different subsystems of the graphics
engine, enabling fine-grained error handling.
"""


class Graphics3DError(Exception):
    """Base exception for all graphics3d errors."""

    pass


class MathError(Graphics3DError):
    """Raised when 3D math operations fail.

    Typical causes:
    - Singular matrix inversion
    - Invalid vector normalization (zero vector)
    - Invalid quaternion operations
    """

    pass


class MeshError(Graphics3DError):
    """Raised when mesh operations fail.

    Typical causes:
    - Invalid vertex/index data
    - Degenerate triangles
    - Missing normals or tangents
    """

    pass


class RasterizerError(Graphics3DError):
    """Raised when rasterization fails.

    Typical causes:
    - Invalid viewport dimensions
    - Clipping failures
    - Invalid framebuffer state
    """

    pass


class ShaderError(Graphics3DError):
    """Raised when shading/lighting computations fail.

    Typical causes:
    - Invalid material properties
    - Invalid light configuration
    - Numerical instabilities in BRDF computation
    """

    pass


class TextureError(Graphics3DError):
    """Raised when texture operations fail.

    Typical causes:
    - Invalid texture coordinates
    - Invalid texture format
    - Failed mipmap generation
    """

    pass
