"""Thomas Gaming Platform - A complete game engine framework with ECS, physics, and more."""

from thomas.gaming_platform._exceptions import (
    AudioError,
    ComponentError,
    EntityError,
    GameEngineError,
    InputError,
    NetworkingError,
    PhysicsError,
    RenderingError,
    SystemError,
)
from thomas.gaming_platform._types import (
    AnimationClip,
    AudioSource,
    Collider,
    CollisionEvent,
    Component,
    Entity,
    Event,
    GameState,
    InputEvent,
    Particle,
    RigidBody,
    Scene,
    Sprite,
    System,
    TileMap,
    Timer,
    Transform,
    World,
)
from thomas.gaming_platform.animation import AnimationEngine
from thomas.gaming_platform.audio import AudioEngine
from thomas.gaming_platform.ecs import EntityComponentSystem
from thomas.gaming_platform.input import InputManager
from thomas.gaming_platform.networking import NetworkManager
from thomas.gaming_platform.physics2d import Physics2D
from thomas.gaming_platform.rendering import Renderer
from thomas.gaming_platform.scenes import SceneManager
from thomas.gaming_platform.ui import UIManager

__version__ = "1.0.0"
__all__ = [
    "Entity",
    "Component",
    "System",
    "World",
    "Event",
    "InputEvent",
    "CollisionEvent",
    "GameState",
    "Transform",
    "Sprite",
    "Collider",
    "RigidBody",
    "AudioSource",
    "Particle",
    "TileMap",
    "AnimationClip",
    "Timer",
    "Scene",
    "EntityComponentSystem",
    "Physics2D",
    "InputManager",
    "Renderer",
    "AnimationEngine",
    "AudioEngine",
    "SceneManager",
    "UIManager",
    "NetworkManager",
]
