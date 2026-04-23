"""Scene management with transitions, loading, and lifecycle."""

from collections.abc import Callable
from enum import Enum, auto
from typing import Any

from thomas.marketplace.gaming_platform._exceptions import GameEngineError
from thomas.marketplace.gaming_platform._types import Entity, Scene, Transform
from thomas.marketplace.gaming_platform.ecs import EntityComponentSystem


class TransitionType(Enum):
    """Scene transition types."""

    CUT = auto()
    FADE = auto()
    SLIDE = auto()
    WIPE = auto()


class SceneTransition:
    """Manages transition between scenes."""

    def __init__(
        self,
        transition_type: TransitionType = TransitionType.FADE,
        duration: float = 0.5,
        direction: str = "up",
    ) -> None:
        """
        Initialize scene transition.

        Args:
            transition_type: Type of transition.
            duration: Transition duration in seconds.
            direction: Direction for slide/wipe (up, down, left, right).
        """
        self.transition_type = transition_type
        self.duration = duration
        self.direction = direction
        self.elapsed = 0.0
        self.is_complete = False

    def update(self, dt: float) -> None:
        """Update transition."""
        if self.is_complete:
            return

        self.elapsed += dt
        if self.elapsed >= self.duration:
            self.elapsed = self.duration
            self.is_complete = True

    def get_progress(self) -> float:
        """Get transition progress (0-1)."""
        if self.duration == 0:
            return 1.0
        return min(1.0, self.elapsed / self.duration)


class SceneManager:
    """
    Manages scenes, transitions, and scene stack.

    Features:
    - Scene stack (push/pop for menus over gameplay)
    - Scene transitions with various effects
    - Scene loading (async simulation)
    - Scene lifecycle (init, enter, update, render, exit)
    - Persistent scene data
    - Scene hierarchy
    """

    def __init__(self, ecs: EntityComponentSystem) -> None:
        """
        Initialize scene manager.

        Args:
            ecs: Entity component system.
        """
        self.ecs = ecs
        self.scenes: dict[str, Scene] = {}
        self.scene_stack: list[Scene] = []
        self.current_transition: SceneTransition | None = None
        self.next_scene: Scene | None = None
        self.scene_callbacks: dict[str, dict[str, list[Callable[[], None]]]] = {}
        self.loading_progress = 0.0
        self.is_loading = False

    def create_scene(self, name: str, persistent: bool = False) -> Scene:
        """
        Create a new scene.

        Args:
            name: Scene name (must be unique).
            persistent: Whether scene persists across transitions.

        Returns:
            New scene instance.

        Raises:
            GameEngineError: If scene name already exists.
        """
        if name in self.scenes:
            raise GameEngineError(f"Scene '{name}' already exists")

        scene = Scene(name=name, persistent=persistent)
        self.scenes[name] = scene

        # Initialize callback lists
        self.scene_callbacks[name] = {
            "init": [],
            "enter": [],
            "update": [],
            "render": [],
            "exit": [],
            "destroy": [],
        }

        return scene

    def load_scene(
        self,
        scene_name: str,
        transition: SceneTransition | None = None,
        async_load: bool = False,
    ) -> None:
        """
        Load scene, optionally with transition.

        Args:
            scene_name: Scene to load.
            transition: Optional transition effect.
            async_load: Whether to load asynchronously.

        Raises:
            GameEngineError: If scene doesn't exist.
        """
        if scene_name not in self.scenes:
            raise GameEngineError(f"Scene '{scene_name}' not found")

        scene = self.scenes[scene_name]

        if transition:
            self.current_transition = transition
            self.next_scene = scene
        else:
            self._unload_current_scene()
            self._load_scene_immediate(scene)

        if async_load:
            self.is_loading = True
            self.loading_progress = 0.0

    def push_scene(
        self,
        scene_name: str,
        transition: SceneTransition | None = None,
    ) -> None:
        """
        Push scene onto stack (keep current scene running underneath).

        Args:
            scene_name: Scene to push.
            transition: Optional transition effect.
        """
        if scene_name not in self.scenes:
            raise GameEngineError(f"Scene '{scene_name}' not found")

        scene = self.scenes[scene_name]

        if transition:
            self.current_transition = transition
            self.next_scene = scene
        else:
            self._load_scene_immediate(scene)
            self.scene_stack.append(scene)

    def pop_scene(
        self,
        transition: SceneTransition | None = None,
    ) -> None:
        """
        Pop scene from stack.

        Args:
            transition: Optional transition effect.
        """
        if not self.scene_stack:
            return

        if transition:
            self.current_transition = transition
            self.next_scene = None
        else:
            scene = self.scene_stack.pop()
            self._unload_scene(scene)

    def get_current_scene(self) -> Scene | None:
        """Get current active scene."""
        if self.scene_stack:
            return self.scene_stack[-1]
        return None

    def scene_exists(self, name: str) -> bool:
        """Check if scene exists."""
        return name in self.scenes

    def register_scene_callback(
        self,
        scene_name: str,
        event: str,
        callback: Callable[[], None],
    ) -> None:
        """
        Register lifecycle callback for scene.

        Args:
            scene_name: Scene name.
            event: Event type (init, enter, update, render, exit, destroy).
            callback: Callback function.
        """
        if scene_name not in self.scene_callbacks:
            return

        if event in self.scene_callbacks[scene_name]:
            self.scene_callbacks[scene_name][event].append(callback)

    def unregister_scene_callback(
        self,
        scene_name: str,
        event: str,
        callback: Callable[[], None],
    ) -> None:
        """Unregister scene callback."""
        if scene_name in self.scene_callbacks and event in self.scene_callbacks[scene_name]:
            callbacks = self.scene_callbacks[scene_name][event]
            if callback in callbacks:
                callbacks.remove(callback)

    def update(self, dt: float) -> None:
        """
        Update scene manager and active scene.

        Args:
            dt: Delta time in seconds.
        """
        # Update transition
        if self.current_transition:
            self.current_transition.update(dt)

            if self.current_transition.is_complete:
                if self.next_scene:
                    self._unload_current_scene()
                    self._load_scene_immediate(self.next_scene)
                    self.scene_stack.append(self.next_scene)
                else:
                    # Popping scene
                    if self.scene_stack:
                        scene = self.scene_stack.pop()
                        self._unload_scene(scene)

                self.current_transition = None
                self.next_scene = None

        # Update current scene
        current = self.get_current_scene()
        if current:
            current.active = True
            self._call_callbacks(current.name, "update")

        # Update loading
        if self.is_loading:
            self.loading_progress += dt * 2.0  # Simulate loading
            if self.loading_progress >= 1.0:
                self.is_loading = False
                self.loading_progress = 1.0

    def render(self) -> None:
        """Render current scene."""
        current = self.get_current_scene()
        if current:
            self._call_callbacks(current.name, "render")

    def _load_scene_immediate(self, scene: Scene) -> None:
        """Load scene immediately."""
        self._call_callbacks(scene.name, "init")
        self._call_callbacks(scene.name, "enter")
        scene.active = True

    def _unload_current_scene(self) -> None:
        """Unload current scene."""
        if self.scene_stack:
            scene = self.scene_stack[-1]
            self._unload_scene(scene)

    def _unload_scene(self, scene: Scene) -> None:
        """Unload a specific scene."""
        if not scene.persistent:
            self._call_callbacks(scene.name, "exit")
            self._call_callbacks(scene.name, "destroy")
            scene.active = False

    def _call_callbacks(self, scene_name: str, event: str) -> None:
        """Call all callbacks for scene event."""
        if scene_name in self.scene_callbacks and event in self.scene_callbacks[scene_name]:
            for callback in self.scene_callbacks[scene_name][event]:
                callback()

    def get_loading_progress(self) -> float:
        """Get scene loading progress (0-1)."""
        return self.loading_progress

    def set_scene_data(self, scene_name: str, key: str, value: Any) -> None:
        """Store persistent data in scene."""
        if scene_name in self.scenes:
            self.scenes[scene_name].user_data[key] = value

    def get_scene_data(self, scene_name: str, key: str, default: Any = None) -> Any:
        """Retrieve persistent data from scene."""
        if scene_name in self.scenes:
            return self.scenes[scene_name].user_data.get(key, default)
        return default

    def clear_scene_data(self, scene_name: str) -> None:
        """Clear all scene data."""
        if scene_name in self.scenes:
            self.scenes[scene_name].user_data.clear()

    def get_scene_list(self) -> list[str]:
        """Get list of all scene names."""
        return list(self.scenes.keys())

    def get_scene_stack_size(self) -> int:
        """Get number of scenes on stack."""
        return len(self.scene_stack)

    def instantiate_prefab_in_scene(
        self,
        scene_name: str,
        prefab_name: str,
    ) -> Entity | None:
        """
        Instantiate prefab within a scene.

        Args:
            scene_name: Target scene.
            prefab_name: Prefab name.

        Returns:
            New entity or None.
        """
        entity = self.ecs.instantiate_prefab(prefab_name)
        if entity and scene_name in self.scenes:
            scene = self.scenes[scene_name]
            if scene.root_entity is None:
                scene.root_entity = entity
            else:
                # Add as child of root
                root_transform = self.ecs.get_component(scene.root_entity, Transform)
                entity_transform = self.ecs.get_component(entity, Transform)
                if root_transform and entity_transform:
                    entity_transform.parent = scene.root_entity
                    root_transform.children.append(entity)

        return entity
