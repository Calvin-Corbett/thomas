"""
Tests for rasterization: triangle rasterization, clipping, and framebuffer operations.

Tests:
- Triangle rasterization
- Barycentric coordinates
- Depth testing
- Clipping algorithms
- Back-face culling
- Line rasterization
"""

from thomas.graphics3d import rasterizer
from thomas.graphics3d._types import Color, FrameBuffer, Vec2, Vec4


class TestViewportTransform:
    """Tests for viewport transformation."""

    def test_viewport_transform_center(self) -> None:
        """Test viewport transform at NDC center."""
        x, y = rasterizer.viewport_transform(0.0, 0.0, 800, 600)
        assert x == 400
        assert y == 300

    def test_viewport_transform_corners(self) -> None:
        """Test viewport transform at NDC corners."""
        x, y = rasterizer.viewport_transform(-1.0, -1.0, 800, 600)
        assert x == 0
        assert y == 600

        x, y = rasterizer.viewport_transform(1.0, 1.0, 800, 600)
        assert x == 800
        assert y == 0


class TestBarycentricCoordinates:
    """Tests for barycentric coordinate computation."""

    def test_barycentric_inside_triangle(self) -> None:
        """Test barycentric coordinates for point inside triangle."""
        p = Vec2(0, 0)
        v0 = Vec2(-1, -1)
        v1 = Vec2(1, -1)
        v2 = Vec2(0, 1)

        bary = rasterizer.barycentric_coordinates(p, v0, v1, v2)
        assert bary is not None

        u, v, w = bary
        assert u >= 0 and v >= 0 and w >= 0
        assert abs(u + v + w - 1.0) < 1e-6

    def test_barycentric_outside_triangle(self) -> None:
        """Test barycentric for point outside triangle."""
        p = Vec2(10, 10)
        v0 = Vec2(-1, -1)
        v1 = Vec2(1, -1)
        v2 = Vec2(0, 1)

        bary = rasterizer.barycentric_coordinates(p, v0, v1, v2)
        if bary is not None:
            u, v, w = bary
            # Should have at least one negative coordinate
            assert u < 0 or v < 0 or w < 0

    def test_barycentric_vertex(self) -> None:
        """Test barycentric for point at vertex."""
        v0 = Vec2(0, 0)
        v1 = Vec2(1, 0)
        v2 = Vec2(0, 1)

        bary = rasterizer.barycentric_coordinates(v0, v0, v1, v2)
        assert bary is not None
        u, v, w = bary
        assert abs(u - 1.0) < 1e-6


class TestEdgeFunction:
    """Tests for edge function."""

    def test_edge_function_positive(self) -> None:
        """Test edge function on positive side."""
        p = Vec2(0.5, 0.5)
        a = Vec2(0, 0)
        b = Vec2(1, 0)

        result = rasterizer.edge_function(p, a, b)
        assert result > 0

    def test_edge_function_negative(self) -> None:
        """Test edge function on negative side."""
        p = Vec2(0.5, -0.5)
        a = Vec2(0, 0)
        b = Vec2(1, 0)

        result = rasterizer.edge_function(p, a, b)
        assert result < 0


class TestCullMode:
    """Tests for back-face culling."""

    def test_cull_front(self) -> None:
        """Test front-face culling."""
        v0 = Vec4(0, 0, 0, 1)
        v1 = Vec4(1, 0, 0, 1)
        v2 = Vec4(0, 1, 0, 1)

        # Counter-clockwise (front-facing)
        assert rasterizer.should_cull_triangle(v0, v1, v2, rasterizer.CullMode.FRONT)

    def test_cull_back(self) -> None:
        """Test back-face culling."""
        v0 = Vec4(0, 0, 0, 1)
        v1 = Vec4(0, 1, 0, 1)
        v2 = Vec4(1, 0, 0, 1)

        # Clockwise (back-facing)
        assert rasterizer.should_cull_triangle(v0, v1, v2, rasterizer.CullMode.BACK)

    def test_cull_none(self) -> None:
        """Test with no culling."""
        v0 = Vec4(0, 0, 0, 1)
        v1 = Vec4(1, 0, 0, 1)
        v2 = Vec4(0, 1, 0, 1)

        assert not rasterizer.should_cull_triangle(v0, v1, v2, rasterizer.CullMode.NONE)


class TestLineRasterization:
    """Tests for line rasterization."""

    def test_rasterize_horizontal_line(self) -> None:
        """Test rasterizing horizontal line."""
        fb = FrameBuffer(100, 100)
        fb.clear(Color(0, 0, 0, 1))

        p0 = Vec2(10, 50)
        p1 = Vec2(90, 50)
        color = Color(1, 1, 1, 1)

        rasterizer.rasterize_line(fb, p0, p1, color)

        # Check that pixels along line were drawn
        assert fb.get_pixel(50, 50) == color

    def test_rasterize_vertical_line(self) -> None:
        """Test rasterizing vertical line."""
        fb = FrameBuffer(100, 100)
        fb.clear(Color(0, 0, 0, 1))

        p0 = Vec2(50, 10)
        p1 = Vec2(50, 90)
        color = Color(1, 1, 1, 1)

        rasterizer.rasterize_line(fb, p0, p1, color)

        assert fb.get_pixel(50, 50) == color


class TestFramebuffer:
    """Tests for framebuffer operations."""

    def test_framebuffer_creation(self) -> None:
        """Test framebuffer creation."""
        fb = FrameBuffer(512, 512)
        assert fb.width == 512
        assert fb.height == 512
        assert len(fb.color_buffer) == 512 * 512

    def test_framebuffer_clear(self) -> None:
        """Test framebuffer clearing."""
        fb = FrameBuffer(100, 100)
        clear_color = Color(0.5, 0.5, 0.5, 1.0)
        fb.clear(clear_color)

        for i in range(len(fb.color_buffer)):
            assert fb.color_buffer[i] == clear_color

    def test_framebuffer_set_pixel(self) -> None:
        """Test setting pixel."""
        fb = FrameBuffer(100, 100)
        fb.clear(Color(0, 0, 0, 1))

        color = Color(1, 0, 0, 1)
        fb.set_pixel(50, 50, color)

        assert fb.get_pixel(50, 50) == color

    def test_framebuffer_bounds_check(self) -> None:
        """Test framebuffer bounds checking."""
        fb = FrameBuffer(100, 100)

        # Should not crash on out-of-bounds access
        fb.set_pixel(-1, 0, Color(1, 0, 0, 1))
        fb.set_pixel(100, 0, Color(1, 0, 0, 1))
        fb.set_pixel(0, -1, Color(1, 0, 0, 1))
        fb.set_pixel(0, 100, Color(1, 0, 0, 1))

    def test_framebuffer_depth(self) -> None:
        """Test depth buffer."""
        fb = FrameBuffer(100, 100)
        fb.set_depth(50, 50, 0.5)

        assert fb.get_depth(50, 50) == 0.5


class TestRasterizer:
    """Tests for high-level rasterizer."""

    def test_rasterizer_creation(self) -> None:
        """Test rasterizer creation."""
        fb = FrameBuffer(800, 600)
        r = rasterizer.Rasterizer(fb)

        assert r.framebuffer is fb

    def test_rasterizer_clear(self) -> None:
        """Test rasterizer clear."""
        fb = FrameBuffer(100, 100)
        r = rasterizer.Rasterizer(fb)

        clear_color = Color(0.2, 0.2, 0.2, 1.0)
        r.clear(clear_color)

        # Check that buffer was cleared
        for color in fb.color_buffer:
            assert color == clear_color

    def test_rasterizer_triangle(self) -> None:
        """Test drawing a triangle."""
        fb = FrameBuffer(100, 100)
        r = rasterizer.Rasterizer(fb)
        r.clear(Color(0, 0, 0, 1))

        v0 = Vec4(10, 10, 0, 1)
        v1 = Vec4(90, 10, 0, 1)
        v2 = Vec4(50, 90, 0, 1)
        color = Color(1, 1, 1, 1)

        r.draw_triangle(v0, v1, v2, color)

        # Check that some pixels were drawn
        pixels_drawn = sum(1 for c in fb.color_buffer if c.r > 0 or c.g > 0 or c.b > 0)
        assert pixels_drawn > 0


class TestColorBlending:
    """Tests for color blending."""

    def test_blend_over(self) -> None:
        """Test alpha over blending."""
        src = Color(1, 0, 0, 0.5)
        dst = Color(0, 0, 1, 1)

        result = rasterizer.blend_colors(dst, src, "over")
        assert result.a > 0

    def test_blend_add(self) -> None:
        """Test additive blending."""
        src = Color(0.5, 0, 0, 1)
        dst = Color(0.5, 0, 0, 1)

        result = rasterizer.blend_colors(dst, src, "add")
        assert result.r == 1.0

    def test_blend_multiply(self) -> None:
        """Test multiplicative blending."""
        src = Color(0.5, 0.5, 0.5, 1)
        dst = Color(0.5, 0.5, 0.5, 1)

        result = rasterizer.blend_colors(dst, src, "multiply")
        assert abs(result.r - 0.25) < 1e-6


class TestLineClipping:
    """Tests for line clipping."""

    def test_line_inside_bounds(self) -> None:
        """Test line entirely inside bounds."""
        p0 = Vec2(10, 10)
        p1 = Vec2(90, 90)
        bounds = (0, 0, 100, 100)

        result = rasterizer.clip_line_cohen_sutherland(p0, p1, bounds)
        assert result is not None

    def test_line_outside_bounds(self) -> None:
        """Test line entirely outside bounds."""
        p0 = Vec2(-10, -10)
        p1 = Vec2(-5, -5)
        bounds = (0, 0, 100, 100)

        result = rasterizer.clip_line_cohen_sutherland(p0, p1, bounds)
        assert result is None

    def test_line_partial_clip(self) -> None:
        """Test line partially inside bounds."""
        p0 = Vec2(-10, 50)
        p1 = Vec2(110, 50)
        bounds = (0, 0, 100, 100)

        result = rasterizer.clip_line_cohen_sutherland(p0, p1, bounds)
        assert result is not None
