"""2D rendering system with sprites, layers, and batch rendering."""

from dataclasses import dataclass, field

from thomas.marketplace.gaming_platform._types import (
    Entity,
    Particle,
    Sprite,
    TileMap,
    Transform,
)
from thomas.marketplace.gaming_platform.ecs import EntityComponentSystem


@dataclass
class SpriteAtlas:
    """
    Sprite atlas for efficient texture management.

    Packs multiple sprites into a single texture for reduced draw calls.
    """

    texture_id: str
    width: int
    height: int
    sprites: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)

    def add_sprite(self, name: str, x: int, y: int, width: int, height: int) -> None:
        """
        Add sprite to atlas.

        Args:
            name: Sprite name.
            x: X position in atlas.
            y: Y position in atlas.
            width: Sprite width.
            height: Sprite height.
        """
        self.sprites[name] = (x, y, width, height)

    def get_sprite_uv(self, name: str) -> tuple[float, float, float, float] | None:
        """
        Get UV coordinates for sprite.

        Args:
            name: Sprite name.

        Returns:
            (u0, v0, u1, v1) or None if not found.
        """
        if name not in self.sprites:
            return None

        x, y, w, h = self.sprites[name]
        u0 = x / self.width
        v0 = y / self.height
        u1 = (x + w) / self.width
        v1 = (y + h) / self.height

        return (u0, v0, u1, v1)


@dataclass
class DrawCall:
    """Represents a single draw call to be batched."""

    entity: Entity
    texture_id: str
    position: tuple[float, float]
    rotation: float
    scale: tuple[float, float]
    pivot: tuple[float, float]
    tint: tuple[float, float, float, float]
    layer: int
    flip_x: bool
    flip_y: bool
    width: float
    height: float
    uv: tuple[float, float, float, float] | None = None


@dataclass
class Camera:
    """
    2D camera for viewport management.

    Attributes:
        position: Camera world position.
        zoom: Zoom level (1.0 = normal).
        rotation: Camera rotation in degrees.
        width: Viewport width in pixels.
        height: Viewport height in pixels.
        shake_intensity: Current screen shake intensity.
        shake_duration: Screen shake remaining duration.
    """

    position: tuple[float, float] = (0.0, 0.0)
    zoom: float = 1.0
    rotation: float = 0.0
    width: float = 800.0
    height: float = 600.0
    shake_intensity: float = 0.0
    shake_duration: float = 0.0

    def get_view_matrix(self) -> list[list[float]]:
        """Get 4x4 view matrix for rendering."""
        # Simplified 2D view matrix
        return [
            [1.0 / self.zoom, 0.0, 0.0, -self.position[0]],
            [0.0, 1.0 / self.zoom, 0.0, -self.position[1]],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]

    def get_shake_offset(self) -> tuple[float, float]:
        """Get current screen shake offset."""
        if self.shake_duration <= 0:
            return (0.0, 0.0)

        import random

        x = random.uniform(-self.shake_intensity, self.shake_intensity)
        y = random.uniform(-self.shake_intensity, self.shake_intensity)

        return (x, y)

    def apply_shake(self, intensity: float, duration: float) -> None:
        """
        Apply screen shake effect.

        Args:
            intensity: Shake magnitude.
            duration: Shake duration in seconds.
        """
        self.shake_intensity = intensity
        self.shake_duration = duration

    def update(self, dt: float) -> None:
        """Update camera (reduce shake duration)."""
        if self.shake_duration > 0:
            self.shake_duration -= dt

    def world_to_screen(self, world_pos: tuple[float, float]) -> tuple[float, float]:
        """Convert world position to screen position."""
        wx, wy = world_pos
        cx, cy = self.position

        # Apply camera transform
        sx = (wx - cx) * self.zoom + self.width / 2
        sy = (wy - cy) * self.zoom + self.height / 2

        return (sx, sy)

    def screen_to_world(self, screen_pos: tuple[float, float]) -> tuple[float, float]:
        """Convert screen position to world position."""
        sx, sy = screen_pos
        cx, cy = self.position

        # Inverse camera transform
        wx = (sx - self.width / 2) / self.zoom + cx
        wy = (sy - self.height / 2) / self.zoom + cy

        return (wx, wy)

    def is_in_view(self, world_pos: tuple[float, float], radius: float = 0.0) -> bool:
        """Check if world position is visible in camera."""
        wx, wy = world_pos
        cx, cy = self.position
        w = self.width / (2 * self.zoom)
        h = self.height / (2 * self.zoom)

        return abs(wx - cx) < w + radius and abs(wy - cy) < h + radius


class Renderer:
    """
    2D rendering system with sprites, tiles, and particles.

    Features:
    - Sprite rendering with rotation, scale, flip
    - Sprite atlases for efficient texture packing
    - Tile map rendering (orthogonal and isometric)
    - Particle system rendering
    - Camera with zoom and shake
    - Render layers with depth sorting
    - Batch rendering for performance
    """

    def __init__(self, width: float = 800.0, height: float = 600.0) -> None:
        """
        Initialize renderer.

        Args:
            width: Viewport width.
            height: Viewport height.
        """
        self.camera = Camera(width=width, height=height)
        self.atlases: dict[str, SpriteAtlas] = {}
        self.draw_calls: list[DrawCall] = []
        self.batches: dict[str, list[DrawCall]] = {}
        self.render_layers: set[int] = set()

    def register_atlas(self, atlas: SpriteAtlas) -> None:
        """
        Register sprite atlas.

        Args:
            atlas: Sprite atlas instance.
        """
        self.atlases[atlas.texture_id] = atlas

    def render(self, ecs: EntityComponentSystem) -> None:
        """
        Render all visible entities.

        Args:
            ecs: Entity component system.
        """
        self.draw_calls.clear()
        self.batches.clear()
        self.render_layers.clear()

        # Update camera
        self.camera.update(0.016)  # Assume 60 FPS

        # Collect draw calls
        self._collect_sprite_calls(ecs)
        self._collect_tilemap_calls(ecs)
        self._collect_particle_calls(ecs)

        # Sort by layer and Y position
        self._sort_draw_calls()

        # Batch by texture
        self._batch_draw_calls()

        # Render batches
        self._render_batches()

    def _collect_sprite_calls(self, ecs: EntityComponentSystem) -> None:
        """Collect sprite draw calls."""
        entities = ecs.query(Transform, Sprite)

        for entity in entities:
            transform = ecs.get_component(entity, Transform)
            sprite = ecs.get_component(entity, Sprite)

            if transform is None or sprite is None or not sprite.visible:
                continue

            # Check visibility
            if not self.camera.is_in_view(transform.position, max(sprite.width, sprite.height)):
                continue

            draw_call = DrawCall(
                entity=entity,
                texture_id=sprite.texture_id,
                position=transform.position,
                rotation=transform.rotation,
                scale=transform.scale,
                pivot=sprite.pivot,
                tint=sprite.tint,
                layer=sprite.layer,
                flip_x=sprite.flip_x,
                flip_y=sprite.flip_y,
                width=sprite.width,
                height=sprite.height,
            )

            # Check atlas
            if sprite.texture_id in self.atlases:
                uv = self.atlases[sprite.texture_id].get_sprite_uv(sprite.texture_id)
                draw_call.uv = uv

            self.draw_calls.append(draw_call)
            self.render_layers.add(sprite.layer)

    def _collect_tilemap_calls(self, ecs: EntityComponentSystem) -> None:
        """Collect tile map draw calls."""
        entities = ecs.query(Transform, TileMap)

        for entity in entities:
            transform = ecs.get_component(entity, Transform)
            tilemap = ecs.get_component(entity, TileMap)

            if transform is None or tilemap is None:
                continue

            base_x, base_y = transform.position

            # Render tiles
            for y in range(tilemap.height):
                for x in range(tilemap.width):
                    tile_id = tilemap.get_tile(x, y)
                    if tile_id == 0:
                        continue

                    if tilemap.isometric:
                        # Isometric projection
                        iso_x = (x - y) * tilemap.tile_width / 2
                        iso_y = (x + y) * tilemap.tile_height / 2
                    else:
                        # Orthogonal projection
                        iso_x = x * tilemap.tile_width
                        iso_y = y * tilemap.tile_height

                    tile_pos = (base_x + iso_x, base_y + iso_y)

                    if not self.camera.is_in_view(tile_pos, tilemap.tile_width):
                        continue

                    draw_call = DrawCall(
                        entity=entity,
                        texture_id=tilemap.tileset_id,
                        position=tile_pos,
                        rotation=0.0,
                        scale=(1.0, 1.0),
                        pivot=(0.0, 0.0),
                        tint=(1.0, 1.0, 1.0, 1.0),
                        layer=0,
                        flip_x=False,
                        flip_y=False,
                        width=tilemap.tile_width,
                        height=tilemap.tile_height,
                    )

                    self.draw_calls.append(draw_call)

    def _collect_particle_calls(self, ecs: EntityComponentSystem) -> None:
        """Collect particle draw calls."""
        entities = ecs.query(Transform, Particle)

        for entity in entities:
            transform = ecs.get_component(entity, Transform)
            particle = ecs.get_component(entity, Particle)

            if transform is None or particle is None or not particle.is_alive:
                continue

            if not self.camera.is_in_view(transform.position, particle.size):
                continue

            draw_call = DrawCall(
                entity=entity,
                texture_id="particle",
                position=transform.position,
                rotation=0.0,
                scale=(particle.size, particle.size),
                pivot=(0.5, 0.5),
                tint=particle.color,
                layer=100,
                flip_x=False,
                flip_y=False,
                width=particle.size,
                height=particle.size,
            )

            self.draw_calls.append(draw_call)

    def _sort_draw_calls(self) -> None:
        """Sort draw calls by layer and Y position."""
        self.draw_calls.sort(
            key=lambda dc: (
                dc.layer,
                dc.position[1] + dc.height / 2,  # Y-sort
            )
        )

    def _batch_draw_calls(self) -> None:
        """Group draw calls by texture for batch rendering."""
        for draw_call in self.draw_calls:
            texture_id = draw_call.texture_id
            if texture_id not in self.batches:
                self.batches[texture_id] = []
            self.batches[texture_id].append(draw_call)

    def _render_batches(self) -> None:
        """Render batched draw calls."""
        # In a real implementation, this would submit draw calls to GPU
        # For now, just count them for testing
        pass

    def get_draw_call_count(self) -> int:
        """Get total number of draw calls."""
        return len(self.draw_calls)

    def get_batch_count(self) -> int:
        """Get number of batches."""
        return len(self.batches)

    def render_text(
        self,
        text: str,
        position: tuple[float, float],
        font_size: int = 16,
        color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
    ) -> None:
        """
        Render text at position.

        Args:
            text: Text to render.
            position: Screen position.
            font_size: Font size in pixels.
            color: RGBA color.
        """
        # In a real implementation, this would render text using a font
        pass

    def render_rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
        filled: bool = True,
    ) -> None:
        """
        Render rectangle shape.

        Args:
            x: X position.
            y: Y position.
            width: Rectangle width.
            height: Rectangle height.
            color: RGBA color.
            filled: Whether to fill or outline.
        """
        # In a real implementation, this would draw a rectangle
        pass

    def render_circle(
        self,
        x: float,
        y: float,
        radius: float,
        color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
        filled: bool = True,
    ) -> None:
        """
        Render circle shape.

        Args:
            x: Center X position.
            y: Center Y position.
            radius: Circle radius.
            color: RGBA color.
            filled: Whether to fill or outline.
        """
        # In a real implementation, this would draw a circle
        pass

    def render_line(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
        thickness: float = 1.0,
    ) -> None:
        """
        Render line.

        Args:
            x0: Start X.
            y0: Start Y.
            x1: End X.
            y1: End Y.
            color: RGBA color.
            thickness: Line thickness.
        """
        # In a real implementation, this would draw a line
        pass

    def set_viewport(self, x: float, y: float, width: float, height: float) -> None:
        """
        Set viewport.

        Args:
            x: Viewport X offset.
            y: Viewport Y offset.
            width: Viewport width.
            height: Viewport height.
        """
        self.camera.width = width
        self.camera.height = height

    def take_screenshot(self, filename: str) -> None:
        """
        Take screenshot and save to file.

        Args:
            filename: Output filename.
        """
        # In a real implementation, this would capture framebuffer
        pass
