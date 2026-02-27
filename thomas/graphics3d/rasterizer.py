"""
Software rasterizer: triangle rasterization, clipping, and framebuffer operations.

Provides:
- Triangle rasterization (scanline and barycentric methods)
- Perspective-correct interpolation
- Depth testing (Z-buffer)
- Viewport transformation
- Clipping (Cohen-Sutherland for lines, Sutherland-Hodgman for triangles)
- Back-face culling
- Wireframe and fill modes
"""

from __future__ import annotations

from enum import Enum

from thomas.graphics3d._exceptions import RasterizerError
from thomas.graphics3d._types import (
    Color,
    FrameBuffer,
    Plane,
    Vec2,
    Vec3,
    Vec4,
)


class FillMode(Enum):
    """Rasterization fill mode."""

    SOLID = "solid"
    WIREFRAME = "wireframe"
    POINTS = "points"


class CullMode(Enum):
    """Back-face culling mode."""

    NONE = "none"
    FRONT = "front"
    BACK = "back"


def viewport_transform(*args: object) -> tuple[float, float]:
    """Transform from NDC [-1, 1] to viewport [0, width] x [0, height].

    Supports both:
    - viewport_transform(Vec4(ndc_x, ndc_y, ...), width, height)
    - viewport_transform(ndc_x, ndc_y, width, height)
    """
    ndc_x: float
    ndc_y: float
    viewport_width: int
    viewport_height: int

    if len(args) == 3 and isinstance(args[0], Vec4):
        point, width, height = args
        ndc_x = float(point.x)
        ndc_y = float(point.y)
        viewport_width = int(width)
        viewport_height = int(height)
    elif len(args) == 4:
        ndc_x, ndc_y, width, height = args
        viewport_width = int(width)
        viewport_height = int(height)
        ndc_x = float(ndc_x)
        ndc_y = float(ndc_y)
    else:
        raise TypeError("viewport_transform expects (Vec4, width, height) or " "(ndc_x, ndc_y, width, height)")

    x = (ndc_x + 1) * 0.5 * viewport_width
    y = (1 - ndc_y) * 0.5 * viewport_height
    return x, y


def barycentric_coordinates(p: Vec2, v0: Vec2, v1: Vec2, v2: Vec2) -> tuple[float, float, float] | None:
    """Compute barycentric coordinates of point p in triangle v0-v1-v2.

    Args:
        p: Point to test
        v0, v1, v2: Triangle vertices

    Returns:
        Tuple of (u, v, w) where p = u*v0 + v*v1 + w*v2, or None if degenerate
    """
    denom = (v1.y - v2.y) * (v0.x - v2.x) + (v2.x - v1.x) * (v0.y - v2.y)

    if abs(denom) < 1e-9:
        return None

    u = ((v1.y - v2.y) * (p.x - v2.x) + (v2.x - v1.x) * (p.y - v2.y)) / denom
    v = ((v2.y - v0.y) * (p.x - v2.x) + (v0.x - v2.x) * (p.y - v2.y)) / denom
    w = 1 - u - v

    return u, v, w


def edge_function(p: Vec2, a: Vec2, b: Vec2) -> float:
    """Compute edge function for scanline rasterization."""
    return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)


def should_cull_triangle(v0: Vec4, v1: Vec4, v2: Vec4, cull_mode: CullMode) -> bool:
    """Determine if triangle should be culled based on winding order.

    Args:
        v0, v1, v2: Triangle vertices in screen space
        cull_mode: Culling mode

    Returns:
        True if triangle should be culled
    """
    if cull_mode == CullMode.NONE:
        return False

    # Compute signed area (cross product of screen-space edges)
    area = ((v1.x - v0.x) * (v2.y - v0.y) - (v2.x - v0.x) * (v1.y - v0.y)) / 2

    if cull_mode == CullMode.FRONT:
        return area > 0
    elif cull_mode == CullMode.BACK:
        return area < 0

    return False


def rasterize_triangle(
    framebuffer: FrameBuffer,
    v0: Vec4,
    v1: Vec4,
    v2: Vec4,
    color: Color,
    fill_mode: FillMode = FillMode.SOLID,
    cull_mode: CullMode = CullMode.BACK,
) -> None:
    """Rasterize triangle to framebuffer.

    Args:
        framebuffer: Target framebuffer
        v0, v1, v2: Triangle vertices (in screen/NDC space)
        color: Triangle color
        fill_mode: Fill mode (solid, wireframe, points)
        cull_mode: Back-face culling mode
    """
    # Convert to screen space
    screen_v0 = Vec2(v0.x, v0.y)
    screen_v1 = Vec2(v1.x, v1.y)
    screen_v2 = Vec2(v2.x, v2.y)

    # Check culling
    if should_cull_triangle(v0, v1, v2, cull_mode):
        return

    if fill_mode == FillMode.POINTS:
        # Render as points
        for v in [screen_v0, screen_v1, screen_v2]:
            x, y = int(v.x), int(v.y)
            if 0 <= x < framebuffer.width and 0 <= y < framebuffer.height:
                framebuffer.set_pixel(x, y, color)

    elif fill_mode == FillMode.WIREFRAME:
        # Render as wireframe
        rasterize_line(framebuffer, screen_v0, screen_v1, color)
        rasterize_line(framebuffer, screen_v1, screen_v2, color)
        rasterize_line(framebuffer, screen_v2, screen_v0, color)

    else:  # SOLID
        # Rasterize filled triangle using barycentric coordinates
        # Compute bounding box
        min_x = max(0, int(min(screen_v0.x, screen_v1.x, screen_v2.x)))
        max_x = min(framebuffer.width - 1, int(max(screen_v0.x, screen_v1.x, screen_v2.x)))
        min_y = max(0, int(min(screen_v0.y, screen_v1.y, screen_v2.y)))
        max_y = min(framebuffer.height - 1, int(max(screen_v0.y, screen_v1.y, screen_v2.y)))

        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                p = Vec2(float(x) + 0.5, float(y) + 0.5)

                bary = barycentric_coordinates(p, screen_v0, screen_v1, screen_v2)
                if bary is None:
                    continue

                u, v, w = bary

                # Check if point is inside triangle
                if u >= 0 and v >= 0 and w >= 0:
                    # Perspective-correct interpolation of depth
                    z = (u * (v0.z / v0.w) + v * (v1.z / v1.w) + w * (v2.z / v2.w)) / (u / v0.w + v / v1.w + w / v2.w)

                    # Depth test
                    if z < framebuffer.get_depth(x, y):
                        framebuffer.set_pixel(x, y, color)
                        framebuffer.set_depth(x, y, z)


def rasterize_line(
    framebuffer: FrameBuffer,
    p0: Vec2,
    p1: Vec2,
    color: Color,
) -> None:
    """Rasterize line using Bresenham's algorithm.

    Args:
        framebuffer: Target framebuffer
        p0, p1: Line endpoints
        color: Line color
    """
    x0, y0 = int(p0.x), int(p0.y)
    x1, y1 = int(p1.x), int(p1.y)

    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1

    if dx > dy:
        error = dx / 2
        y = y0
        for x in range(x0, x1 + sx, sx):
            if 0 <= x < framebuffer.width and 0 <= y < framebuffer.height:
                framebuffer.set_pixel(x, y, color)
            error -= dy
            if error < 0:
                y += sy
                error += dx
    else:
        error = dy / 2
        x = x0
        for y in range(y0, y1 + sy, sy):
            if 0 <= x < framebuffer.width and 0 <= y < framebuffer.height:
                framebuffer.set_pixel(x, y, color)
            error -= dx
            if error < 0:
                x += sx
                error += dy


def clip_line_cohen_sutherland(
    p0: Vec2, p1: Vec2, bounds: tuple[float, float, float, float]
) -> tuple[Vec2, Vec2] | None:
    """Clip line segment using Cohen-Sutherland algorithm.

    Args:
        p0, p1: Line endpoints
        bounds: Clipping bounds (xmin, ymin, xmax, ymax)

    Returns:
        Clipped line segment or None if entirely outside
    """
    xmin, ymin, xmax, ymax = bounds

    def compute_code(x: float, y: float) -> int:
        code = 0
        if x < xmin:
            code |= 1  # Left
        if x > xmax:
            code |= 2  # Right
        if y < ymin:
            code |= 4  # Bottom
        if y > ymax:
            code |= 8  # Top
        return code

    code0 = compute_code(p0.x, p0.y)
    code1 = compute_code(p1.x, p1.y)

    x0, y0 = p0.x, p0.y
    x1, y1 = p1.x, p1.y

    while True:
        if code0 == 0 and code1 == 0:
            # Both endpoints inside
            return Vec2(x0, y0), Vec2(x1, y1)

        if code0 & code1:
            # Both endpoints share a region (outside)
            return None

        # Clip
        code_out = code0 if code0 != 0 else code1

        if code_out & 1:  # Left
            y = y0 + (y1 - y0) * (xmin - x0) / (x1 - x0)
            x = xmin
        elif code_out & 2:  # Right
            y = y0 + (y1 - y0) * (xmax - x0) / (x1 - x0)
            x = xmax
        elif code_out & 4:  # Bottom
            x = x0 + (x1 - x0) * (ymin - y0) / (y1 - y0)
            y = ymin
        elif code_out & 8:  # Top
            x = x0 + (x1 - x0) * (ymax - y0) / (y1 - y0)
            y = ymax

        if code_out == code0:
            x0, y0 = x, y
            code0 = compute_code(x0, y0)
        else:
            x1, y1 = x, y
            code1 = compute_code(x1, y1)


def clip_polygon_sutherland_hodgman(vertices: list[Vec3], planes: list[Plane]) -> list[Vec3]:
    """Clip polygon against frustum planes using Sutherland-Hodgman algorithm.

    Args:
        vertices: Polygon vertices
        planes: Clipping planes

    Returns:
        Clipped polygon vertices
    """
    output = list(vertices)

    for plane in planes:
        if not output:
            break

        input_list = output
        output = []

        if not input_list:
            continue

        prev_vertex = input_list[-1]
        prev_inside = plane.signed_distance_to_point(prev_vertex) >= 0

        for vertex in input_list:
            curr_inside = plane.signed_distance_to_point(vertex) >= 0

            if curr_inside:
                if not prev_inside:
                    # Entering: interpolate intersection
                    t = compute_plane_intersection_t(prev_vertex, vertex, plane)
                    if t is not None:
                        intersection = prev_vertex + (vertex - prev_vertex) * t
                        output.append(intersection)

                output.append(vertex)

            elif prev_inside:
                # Exiting: interpolate intersection
                t = compute_plane_intersection_t(prev_vertex, vertex, plane)
                if t is not None:
                    intersection = prev_vertex + (vertex - prev_vertex) * t
                    output.append(intersection)

            prev_vertex = vertex
            prev_inside = curr_inside

    return output


def compute_plane_intersection_t(p0: Vec3, p1: Vec3, plane: Plane) -> float | None:
    """Compute intersection parameter t of line segment with plane."""
    dir_vec = p1 - p0
    denom = plane.normal.dot(dir_vec)

    if abs(denom) < 1e-9:
        return None

    t = (plane.distance - plane.normal.dot(p0)) / denom

    if 0 <= t <= 1:
        return t

    return None


def blend_colors(dst: Color, src: Color, blend_mode: str = "over") -> Color:
    """Blend two colors.

    Args:
        dst: Destination color
        src: Source color
        blend_mode: Blending mode ('over', 'add', 'multiply')

    Returns:
        Blended color
    """
    if blend_mode == "over":
        # Alpha over blending
        alpha = src.a
        return Color(
            src.r * alpha + dst.r * (1 - alpha),
            src.g * alpha + dst.g * (1 - alpha),
            src.b * alpha + dst.b * (1 - alpha),
            1.0,
        )

    elif blend_mode == "add":
        return Color(src.r + dst.r, src.g + dst.g, src.b + dst.b, src.a + dst.a)

    elif blend_mode == "multiply":
        return Color(src.r * dst.r, src.g * dst.g, src.b * dst.b, src.a * dst.a)

    else:
        raise RasterizerError(f"Unknown blend mode: {blend_mode}")


class Rasterizer:
    """High-level rasterizer interface."""

    def __init__(
        self,
        framebuffer: FrameBuffer,
        fill_mode: FillMode = FillMode.SOLID,
        cull_mode: CullMode = CullMode.BACK,
    ) -> None:
        """Initialize rasterizer.

        Args:
            framebuffer: Target framebuffer
            fill_mode: Rasterization fill mode
            cull_mode: Back-face culling mode
        """
        self.framebuffer = framebuffer
        self.fill_mode = fill_mode
        self.cull_mode = cull_mode

    def clear(self, color: Color = None, depth: float = float("inf")) -> None:
        """Clear framebuffer."""
        if color is None:
            color = Color(0, 0, 0, 1)
        self.framebuffer.clear(color, depth)

    def draw_triangle(self, v0: Vec4, v1: Vec4, v2: Vec4, color: Color) -> None:
        """Draw a triangle."""
        rasterize_triangle(
            self.framebuffer,
            v0,
            v1,
            v2,
            color,
            self.fill_mode,
            self.cull_mode,
        )

    def draw_line(self, p0: Vec2, p1: Vec2, color: Color) -> None:
        """Draw a line."""
        rasterize_line(self.framebuffer, p0, p1, color)
