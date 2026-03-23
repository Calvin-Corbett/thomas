"""Core type definitions for the game engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ecs import EntityComponentSystem


# ============================================================================
# Entity and Component System Types
# ============================================================================


class Entity:
    """
    Represents an entity in the game world.

    Uses generational indices for efficient ID recycling. Each entity
    has a generation counter to detect use-after-free bugs.

    Attributes:
        index (int): The slot index in the entity pool.
        generation (int): The generation counter for this entity.
    """

    def __init__(self, index: int, generation: int) -> None:
        """Initialize an entity with index and generation."""
        self.index: int = index
        self.generation: int = generation

    def __eq__(self, other: Any) -> bool:
        """Check equality based on index and generation."""
        if not isinstance(other, Entity):
            return False
        return self.index == other.index and self.generation == other.generation

    def __hash__(self) -> int:
        """Hash based on index and generation."""
        return hash((self.index, self.generation))

    def __repr__(self) -> str:
        """String representation."""
        return f"Entity({self.index}, gen={self.generation})"


class Component(ABC):
    """
    Base class for all components.

    Components are data containers attached to entities. They should
    be lightweight and not contain game logic (logic goes in Systems).
    """

    @abstractmethod
    def clone(self) -> Component:
        """Create a deep copy of this component."""
        pass


class System(ABC):
    """
    Base class for game systems.

    Systems contain the game logic and operate on entities with
    specific component combinations.
    """

    def __init__(self, world: World, priority: int = 0) -> None:
        """
        Initialize a system.

        Args:
            world: The ECS world.
            priority: Execution priority (higher = earlier execution).
        """
        self.world: World = world
        self.priority: int = priority
        self.enabled: bool = True

    @abstractmethod
    def update(self, dt: float) -> None:
        """
        Update the system.

        Args:
            dt: Delta time since last update in seconds.
        """
        pass


class World:
    """
    Represents the game world containing entities and components.

    This is the central hub for the ECS system.
    """

    def __init__(self) -> None:
        """Initialize an empty world."""
        pass


# ============================================================================
# Event System Types
# ============================================================================


@dataclass
class Event:
    """
    Base event class.

    Events are fired by systems and listened to by other systems.
    All events should be immutable.
    """

    timestamp: float = 0.0
    event_type: str = ""


@dataclass
class InputEvent(Event):
    """Event triggered by user input."""

    action: str = ""
    pressed: bool = False
    consumed: bool = False


@dataclass
class CollisionEvent(Event):
    """Event triggered by collision between two entities."""

    entity_a: Entity = field(default_factory=lambda: Entity(0, 0))
    entity_b: Entity = field(default_factory=lambda: Entity(0, 0))
    contact_point: tuple[float, float] = (0.0, 0.0)
    normal: tuple[float, float] = (0.0, 0.0)
    impulse: float = 0.0


# ============================================================================
# Game State and Data Types
# ============================================================================


class GameState(Enum):
    """Enumeration of game states."""

    MENU = auto()
    LOADING = auto()
    PLAYING = auto()
    PAUSED = auto()
    CUTSCENE = auto()
    GAME_OVER = auto()


# ============================================================================
# Transform Component
# ============================================================================


@dataclass
class Transform(Component):
    """
    Represents position, rotation, and scale in 2D space.

    Attributes:
        position: (x, y) position in world space.
        rotation: Rotation angle in degrees (0-360).
        scale: (x, y) scale factors.
        velocity: (x, y) velocity for physics integration.
        parent: Optional parent entity for hierarchical transforms.
        children: List of child entities.
    """

    position: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)
    velocity: tuple[float, float] = (0.0, 0.0)
    parent: Entity | None = None
    children: list[Entity] = field(default_factory=list)

    def clone(self) -> Transform:
        """Create a deep copy of this transform."""
        return Transform(
            position=self.position,
            rotation=self.rotation,
            scale=self.scale,
            velocity=self.velocity,
            parent=self.parent,
            children=self.children.copy(),
        )

    def get_world_position(self, ecs: EntityComponentSystem) -> tuple[float, float]:
        """
        Calculate world position accounting for parent transforms.

        Args:
            ecs: The ECS system for parent lookups.

        Returns:
            World position as (x, y) tuple.
        """
        if self.parent is None:
            return self.position

        parent_transform = ecs.get_component(self.parent, Transform)
        if parent_transform is None:
            return self.position

        parent_world = parent_transform.get_world_position(ecs)
        return (
            parent_world[0] + self.position[0],
            parent_world[1] + self.position[1],
        )


# ============================================================================
# Rendering Components
# ============================================================================


@dataclass
class Sprite(Component):
    """
    Renders a 2D sprite.

    Attributes:
        texture_id: Identifier for the sprite texture.
        width: Sprite width in pixels.
        height: Sprite height in pixels.
        pivot: (x, y) pivot point for rotation/scaling (0-1 normalized).
        tint: (r, g, b, a) color tint (0-1 range).
        flip_x: Mirror horizontally.
        flip_y: Mirror vertically.
        layer: Render layer for depth sorting.
        visible: Whether the sprite is rendered.
    """

    texture_id: str = ""
    width: float = 32.0
    height: float = 32.0
    pivot: tuple[float, float] = (0.5, 0.5)
    tint: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    flip_x: bool = False
    flip_y: bool = False
    layer: int = 0
    visible: bool = True

    def clone(self) -> Sprite:
        """Create a deep copy of this sprite."""
        return Sprite(
            texture_id=self.texture_id,
            width=self.width,
            height=self.height,
            pivot=self.pivot,
            tint=self.tint,
            flip_x=self.flip_x,
            flip_y=self.flip_y,
            layer=self.layer,
            visible=self.visible,
        )


@dataclass
class TileMap(Component):
    """
    Represents a tile-based map.

    Attributes:
        tile_width: Width of each tile in pixels.
        tile_height: Height of each tile in pixels.
        width: Map width in tiles.
        height: Map height in tiles.
        tiles: Flat list of tile IDs (row-major order).
        tileset_id: Identifier for the tileset texture.
        isometric: Whether to use isometric rendering.
    """

    tile_width: float = 32.0
    tile_height: float = 32.0
    width: int = 10
    height: int = 10
    tiles: list[int] = field(default_factory=list)
    tileset_id: str = ""
    isometric: bool = False

    def clone(self) -> TileMap:
        """Create a deep copy of this tile map."""
        return TileMap(
            tile_width=self.tile_width,
            tile_height=self.tile_height,
            width=self.width,
            height=self.height,
            tiles=self.tiles.copy(),
            tileset_id=self.tileset_id,
            isometric=self.isometric,
        )

    def get_tile(self, x: int, y: int) -> int:
        """
        Get tile ID at grid position.

        Args:
            x: Grid x coordinate.
            y: Grid y coordinate.

        Returns:
            Tile ID or 0 if out of bounds.
        """
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.tiles[y * self.width + x]
        return 0

    def set_tile(self, x: int, y: int, tile_id: int) -> None:
        """
        Set tile ID at grid position.

        Args:
            x: Grid x coordinate.
            y: Grid y coordinate.
            tile_id: Tile ID to set.
        """
        if 0 <= x < self.width and 0 <= y < self.height:
            self.tiles[y * self.width + x] = tile_id


# ============================================================================
# Physics Components
# ============================================================================


@dataclass
class Collider(Component):
    """
    Collision shape for an entity.

    Attributes:
        shape_type: "aabb" for axis-aligned box, "circle" for circle.
        width: Width for AABB.
        height: Height for AABB.
        radius: Radius for circle.
        offset: Offset from transform position.
        is_trigger: If True, doesn't affect physics but triggers events.
        active: If False, not checked for collisions.
    """

    shape_type: str = "aabb"
    width: float = 32.0
    height: float = 32.0
    radius: float = 16.0
    offset: tuple[float, float] = (0.0, 0.0)
    is_trigger: bool = False
    active: bool = True

    def clone(self) -> Collider:
        """Create a deep copy of this collider."""
        return Collider(
            shape_type=self.shape_type,
            width=self.width,
            height=self.height,
            radius=self.radius,
            offset=self.offset,
            is_trigger=self.is_trigger,
            active=self.active,
        )


@dataclass
class RigidBody(Component):
    """
    Physics body for an entity.

    Attributes:
        mass: Body mass in kg (0 = infinite/static).
        gravity_scale: Gravity multiplier (0 = no gravity).
        drag: Linear velocity damping (0-1).
        angular_drag: Rotational velocity damping (0-1).
        restitution: Bounciness (0-1).
        friction: Surface friction (0-1).
        is_dynamic: If False, body doesn't move.
        angular_velocity: Rotation speed in degrees/second.
    """

    mass: float = 1.0
    gravity_scale: float = 1.0
    drag: float = 0.0
    angular_drag: float = 0.0
    restitution: float = 0.5
    friction: float = 0.5
    is_dynamic: bool = True
    angular_velocity: float = 0.0

    def clone(self) -> RigidBody:
        """Create a deep copy of this rigid body."""
        return RigidBody(
            mass=self.mass,
            gravity_scale=self.gravity_scale,
            drag=self.drag,
            angular_drag=self.angular_drag,
            restitution=self.restitution,
            friction=self.friction,
            is_dynamic=self.is_dynamic,
            angular_velocity=self.angular_velocity,
        )

    @property
    def inverse_mass(self) -> float:
        """Get inverse mass (1/mass or 0 for static)."""
        if self.mass == 0 or not self.is_dynamic:
            return 0.0
        return 1.0 / self.mass


# ============================================================================
# Audio Components
# ============================================================================


@dataclass
class AudioSource(Component):
    """
    Audio playback for an entity.

    Attributes:
        clip_id: Identifier for the audio clip.
        volume: Volume level (0-1).
        pitch: Playback speed (0.5-2.0).
        looping: Whether to loop the audio.
        is_playing: Current playback state.
        channel: Audio channel (0 = auto-allocate).
        is_3d: Use 3D positional audio.
        min_distance: Min distance for volume attenuation.
        max_distance: Max distance for volume attenuation.
    """

    clip_id: str = ""
    volume: float = 1.0
    pitch: float = 1.0
    looping: bool = False
    is_playing: bool = False
    channel: int = 0
    is_3d: bool = True
    min_distance: float = 1.0
    max_distance: float = 100.0

    def clone(self) -> AudioSource:
        """Create a deep copy of this audio source."""
        return AudioSource(
            clip_id=self.clip_id,
            volume=self.volume,
            pitch=self.pitch,
            looping=self.looping,
            is_playing=self.is_playing,
            channel=self.channel,
            is_3d=self.is_3d,
            min_distance=self.min_distance,
            max_distance=self.max_distance,
        )


# ============================================================================
# Particle System Components
# ============================================================================


@dataclass
class Particle(Component):
    """
    A single particle for particle systems.

    Attributes:
        lifetime: Total lifetime in seconds.
        age: Current age in seconds.
        velocity: Particle velocity.
        acceleration: Particle acceleration.
        size: Particle size (can change over lifetime).
        color: Particle color (r, g, b, a).
    """

    lifetime: float = 1.0
    age: float = 0.0
    velocity: tuple[float, float] = (0.0, 0.0)
    acceleration: tuple[float, float] = (0.0, 0.0)
    size: float = 1.0
    color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)

    def clone(self) -> Particle:
        """Create a deep copy of this particle."""
        return Particle(
            lifetime=self.lifetime,
            age=self.age,
            velocity=self.velocity,
            acceleration=self.acceleration,
            size=self.size,
            color=self.color,
        )

    @property
    def is_alive(self) -> bool:
        """Check if particle is still alive."""
        return self.age < self.lifetime

    @property
    def life_ratio(self) -> float:
        """Get normalized lifetime (0-1)."""
        if self.lifetime == 0:
            return 0.0
        return self.age / self.lifetime


# ============================================================================
# Animation Components
# ============================================================================


@dataclass
class AnimationClip(Component):
    """
    Animation clip with frame data.

    Attributes:
        name: Name of the animation.
        frames: List of texture IDs for each frame.
        frame_rate: Frames per second.
        looping: Whether the animation loops.
        events: Dict mapping frame index to event callbacks.
    """

    name: str = "animation"
    frames: list[str] = field(default_factory=list)
    frame_rate: float = 10.0
    looping: bool = True
    events: dict[int, list[Callable[[], None]]] = field(default_factory=dict)

    def clone(self) -> AnimationClip:
        """Create a deep copy of this animation clip."""
        return AnimationClip(
            name=self.name,
            frames=self.frames.copy(),
            frame_rate=self.frame_rate,
            looping=self.looping,
            events={k: v.copy() for k, v in self.events.items()},
        )

    @property
    def duration(self) -> float:
        """Get total animation duration in seconds."""
        if self.frame_rate == 0:
            return 0.0
        return len(self.frames) / self.frame_rate


# ============================================================================
# Timer Component
# ============================================================================


@dataclass
class Timer(Component):
    """
    A timer that counts down and triggers callbacks.

    Attributes:
        duration: Total duration in seconds.
        elapsed: Elapsed time in seconds.
        looping: Whether timer repeats.
        on_complete: Callback when timer finishes.
    """

    duration: float = 1.0
    elapsed: float = 0.0
    looping: bool = False
    on_complete: Callable[[], None] | None = None

    def clone(self) -> Timer:
        """Create a deep copy of this timer."""
        return Timer(
            duration=self.duration,
            elapsed=self.elapsed,
            looping=self.looping,
            on_complete=self.on_complete,
        )

    @property
    def is_finished(self) -> bool:
        """Check if timer has finished."""
        return self.elapsed >= self.duration

    @property
    def progress(self) -> float:
        """Get normalized progress (0-1)."""
        if self.duration == 0:
            return 0.0
        return min(1.0, self.elapsed / self.duration)


# ============================================================================
# Scene Component
# ============================================================================


@dataclass
class Scene:
    """
    Represents a game scene (level, menu, etc).

    Attributes:
        name: Unique scene name.
        root_entity: Root entity for scene hierarchy.
        active: Whether scene is currently active.
        persistent: Whether scene survives scene transitions.
        user_data: Custom data dict for scenes.
    """

    name: str = "scene"
    root_entity: Entity | None = None
    active: bool = False
    persistent: bool = False
    user_data: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        """Hash based on name."""
        return hash(self.name)
