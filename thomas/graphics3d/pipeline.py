"""
Rendering pipeline: complete vertex-to-pixel processing.

Provides:
- Vertex processing (transform, lighting)
- Primitive assembly and clipping
- Rasterization
- Fragment processing and blending
- Post-processing effects
- Frame statistics and profiling
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from thomas.graphics3d import math3d, rasterizer
from thomas.graphics3d._types import (
    Camera,
    Color,
    FrameBuffer,
    Mat4,
    Material,
    Mesh,
    Vec4,
    Viewport,
)


class PostProcessEffect(Enum):
    """Post-processing effect types."""

    NONE = "none"
    GRAYSCALE = "grayscale"
    SEPIA = "sepia"
    VIGNETTE = "vignette"
    BLOOM = "bloom"
    INVERT = "invert"


@dataclass
class FrameStats:
    """Frame rendering statistics."""

    frame_time: float = 0.0
    vertices_processed: int = 0
    triangles_processed: int = 0
    triangles_drawn: int = 0
    pixels_drawn: int = 0

    def reset(self) -> None:
        """Reset statistics."""
        self.frame_time = 0.0
        self.vertices_processed = 0
        self.triangles_processed = 0
        self.triangles_drawn = 0
        self.pixels_drawn = 0


class RenderPass:
    """Single render pass configuration."""

    def __init__(self, name: str = "Pass") -> None:
        """Initialize render pass.

        Args:
            name: Pass name
        """
        self.name = name
        self.enabled: bool = True
        self.clear_color: Color = Color(0, 0, 0, 1)
        self.clear_depth: float = float("inf")


class Pipeline:
    """Main rendering pipeline."""

    def __init__(self, framebuffer: FrameBuffer) -> None:
        """Initialize pipeline.

        Args:
            framebuffer: Target framebuffer
        """
        self.framebuffer = framebuffer
        self.viewport = Viewport(0, 0, framebuffer.width, framebuffer.height)
        self.camera: Camera | None = None
        self.render_passes: list[RenderPass] = [RenderPass("Default")]
        self.stats = FrameStats()
        self.post_effects: list[PostProcessEffect] = []
        self.fill_mode = rasterizer.FillMode.SOLID
        self.cull_mode = rasterizer.CullMode.BACK

    def set_viewport(self, viewport: Viewport) -> None:
        """Set viewport."""
        self.viewport = viewport

    def set_camera(self, camera: Camera) -> None:
        """Set camera."""
        self.camera = camera

    def add_post_effect(self, effect: PostProcessEffect) -> None:
        """Add post-processing effect."""
        if effect not in self.post_effects:
            self.post_effects.append(effect)

    def render_mesh(
        self,
        mesh: Mesh,
        model_transform: Mat4,
        material: Material | None = None,
    ) -> None:
        """Render mesh to framebuffer.

        Args:
            mesh: Mesh to render
            model_transform: Model transformation matrix
            material: Material (uses default if None)
        """
        if self.camera is None:
            return

        if material is None:
            material = Material()

        # Vertex processing
        view_matrix = math3d.matrix_look_at(self.camera.position, self.camera.target, self.camera.up)

        proj_matrix = math3d.matrix_perspective(
            self.camera.fov,
            self.camera.aspect,
            self.camera.near,
            self.camera.far,
        )

        model_view_matrix = view_matrix * model_transform
        normal_matrix = view_matrix * model_transform  # Simplified

        # Transform vertices
        transformed_vertices: list[Vec4] = []
        vertex_colors: list[Color] = []

        for vertex in mesh.vertices:
            # Transform to clip space
            pos_world = model_transform * Vec4(vertex.position.x, vertex.position.y, vertex.position.z, 1)
            pos_view = view_matrix * pos_world
            pos_clip = proj_matrix * pos_view

            transformed_vertices.append(pos_clip)

            # Simple lighting per vertex (Gouraud shading)
            normal_world = math3d.vector_transform_direction(vertex.normal, model_transform)

            # Ambient
            color = material.ambient

            # Placeholder for light contribution
            # In full implementation, would iterate lights and accumulate
            color = color + material.diffuse * 0.8

            vertex_colors.append(color.clamp())

            self.stats.vertices_processed += 1

        # Primitive assembly and rasterization
        r = rasterizer.Rasterizer(self.framebuffer, self.fill_mode, self.cull_mode)

        for i in range(0, len(mesh.indices), 3):
            i0 = mesh.indices[i]
            i1 = mesh.indices[i + 1]
            i2 = mesh.indices[i + 2]

            v0 = transformed_vertices[i0]
            v1 = transformed_vertices[i1]
            v2 = transformed_vertices[i2]

            self.stats.triangles_processed += 1

            # Perspective divide (NDC)
            v0_ndc = v0.to_vec3() * (1 / v0.w)
            v1_ndc = v1.to_vec3() * (1 / v1.w)
            v2_ndc = v2.to_vec3() * (1 / v2.w)

            # Viewport transform
            x0, y0 = rasterizer.viewport_transform(v0_ndc.x, v0_ndc.y, self.viewport.width, self.viewport.height)
            x1, y1 = rasterizer.viewport_transform(v1_ndc.x, v1_ndc.y, self.viewport.width, self.viewport.height)
            x2, y2 = rasterizer.viewport_transform(v2_ndc.x, v2_ndc.y, self.viewport.width, self.viewport.height)

            # Convert back to Vec4 for rasterizer
            v0_screen = Vec4(x0, y0, v0_ndc.z, v0.w)
            v1_screen = Vec4(x1, y1, v1_ndc.z, v1.w)
            v2_screen = Vec4(x2, y2, v2_ndc.z, v2.w)

            # Average color of triangle
            avg_color = Color(
                (vertex_colors[i0].r + vertex_colors[i1].r + vertex_colors[i2].r) / 3,
                (vertex_colors[i0].g + vertex_colors[i1].g + vertex_colors[i2].g) / 3,
                (vertex_colors[i0].b + vertex_colors[i1].b + vertex_colors[i2].b) / 3,
                (vertex_colors[i0].a + vertex_colors[i1].a + vertex_colors[i2].a) / 3,
            )

            r.draw_triangle(v0_screen, v1_screen, v2_screen, avg_color)
            self.stats.triangles_drawn += 1

    def clear(self, color: Color = None, depth: float = float("inf")) -> None:
        """Clear framebuffer."""
        if color is None:
            color = self.render_passes[0].clear_color
        self.framebuffer.clear(color, depth)

    def apply_post_processing(self) -> None:
        """Apply post-processing effects to framebuffer."""
        if not self.post_effects:
            return

        for effect in self.post_effects:
            if effect == PostProcessEffect.GRAYSCALE:
                self._apply_grayscale()

            elif effect == PostProcessEffect.SEPIA:
                self._apply_sepia()

            elif effect == PostProcessEffect.VIGNETTE:
                self._apply_vignette()

            elif effect == PostProcessEffect.BLOOM:
                self._apply_bloom()

            elif effect == PostProcessEffect.INVERT:
                self._apply_invert()

    def _apply_grayscale(self) -> None:
        """Apply grayscale post-processing."""
        for i in range(len(self.framebuffer.color_buffer)):
            color = self.framebuffer.color_buffer[i]
            gray = 0.299 * color.r + 0.587 * color.g + 0.114 * color.b
            self.framebuffer.color_buffer[i] = Color(gray, gray, gray, color.a)

    def _apply_sepia(self) -> None:
        """Apply sepia tone post-processing."""
        for i in range(len(self.framebuffer.color_buffer)):
            color = self.framebuffer.color_buffer[i]
            gray = 0.299 * color.r + 0.587 * color.g + 0.114 * color.b

            r = min(1, gray * 1.2)
            g = gray
            b = max(0, gray * 0.8)

            self.framebuffer.color_buffer[i] = Color(r, g, b, color.a)

    def _apply_vignette(self) -> None:
        """Apply vignette post-processing."""
        width = self.framebuffer.width
        height = self.framebuffer.height
        center_x = width / 2
        center_y = height / 2
        max_dist = ((width * width + height * height) ** 0.5) / 2

        for y in range(height):
            for x in range(width):
                dist = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                vignette = 1 - (dist / max_dist) * 0.5
                vignette = max(0, min(1, vignette))

                idx = y * width + x
                color = self.framebuffer.color_buffer[idx]
                self.framebuffer.color_buffer[idx] = Color(
                    color.r * vignette,
                    color.g * vignette,
                    color.b * vignette,
                    color.a,
                )

    def _apply_bloom(self) -> None:
        """Apply bloom post-processing (simple approximation)."""
        width = self.framebuffer.width
        height = self.framebuffer.height

        # Find bright pixels
        bloom_buffer = [Color(0, 0, 0, 1) for _ in range(width * height)]

        threshold = 0.8
        for i in range(len(self.framebuffer.color_buffer)):
            color = self.framebuffer.color_buffer[i]
            brightness = max(color.r, color.g, color.b)

            if brightness > threshold:
                bloom_buffer[i] = color * (brightness - threshold)

        # Simple blur (3x3)
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                idx = y * width + x

                bloom_sum = Color(0, 0, 0, 1)
                for dy in [-1, 0, 1]:
                    for dx in [-1, 0, 1]:
                        bloom_sum = bloom_sum + bloom_buffer[(y + dy) * width + (x + dx)]

                bloom_sum = bloom_sum * (1.0 / 9.0)

                original = self.framebuffer.color_buffer[idx]
                self.framebuffer.color_buffer[idx] = (original + bloom_sum * 0.3).clamp()

    def _apply_invert(self) -> None:
        """Apply color inversion post-processing."""
        for i in range(len(self.framebuffer.color_buffer)):
            color = self.framebuffer.color_buffer[i]
            self.framebuffer.color_buffer[i] = Color(1 - color.r, 1 - color.g, 1 - color.b, color.a)

    def render_frame(self, render_items: list) -> FrameStats:
        """Render complete frame.

        Args:
            render_items: List of (mesh, transform, material) to render

        Returns:
            Frame statistics
        """
        start_time = time.time()
        self.stats.reset()

        # Clear
        self.clear()

        # Render items
        for item in render_items:
            mesh, transform, material = item
            self.render_mesh(mesh, transform, material)

        # Post-processing
        self.apply_post_processing()

        self.stats.frame_time = time.time() - start_time
        self.stats.pixels_drawn = self.framebuffer.width * self.framebuffer.height

        return self.stats


def compute_matrix_mvp(model: Mat4, view: Mat4, projection: Mat4) -> Mat4:
    """Compute model-view-projection matrix."""
    return projection * view * model


def compute_normal_matrix(model: Mat4) -> Mat4:
    """Compute normal matrix (inverse transpose of model)."""
    return model.inverse().transpose()


def clip_to_frustum(vertices: list[Vec4], planes: list) -> list[Vec4]:
    """Clip vertex list to frustum.

    This is a simplified version; full Sutherland-Hodgman would
    operate on triangles.

    Args:
        vertices: Vertices in clip space
        planes: Frustum planes

    Returns:
        Clipped vertices
    """
    result = list(vertices)

    # Simple clipping: remove vertices outside frustum
    for v in vertices:
        v_ndc = v.to_vec3() * (1 / v.w)

        inside = True
        if abs(v_ndc.x) > 1 or abs(v_ndc.y) > 1 or v_ndc.z < -1 or v_ndc.z > 1:
            inside = False

        if not inside and v in result:
            result.remove(v)

    return result
