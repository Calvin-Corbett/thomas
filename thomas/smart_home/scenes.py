"""Scene management for multi-device snapshots and transitions."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from thomas.smart_home._exceptions import SceneNotFoundError
from thomas.smart_home._types import Scene


@dataclass
class SceneSnapshot:
    """A snapshot of device states at a point in time."""

    scene_id: str
    """Scene ID."""
    timestamp: datetime = field(default_factory=datetime.now)
    """When snapshot was taken."""
    device_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Device states."""


class SceneManager:
    """Manages scenes with snapshots, transitions, and composition.

    Provides scene creation, activation with smooth transitions, scheduling,
    merging multiple scenes, and adaptive scenes based on context.
    """

    def __init__(self) -> None:
        """Initialize the scene manager."""
        self._scenes: dict[str, Scene] = {}
        self._snapshots: dict[str, list[SceneSnapshot]] = {}
        self._scene_callbacks: dict[str, list[Callable]] = {}
        self._transition_callbacks: dict[str, Callable] = {}
        self._time_of_day_scenes: dict[str, list[str]] = {}
        self._occupancy_based_scenes: dict[str, list[str]] = {}

    def create_scene(self, name: str, room: str | None = None, description: str | None = None) -> Scene:
        """Create a new scene.

        Args:
            name: Scene name.
            room: Optional room the scene applies to.
            description: Scene description.

        Returns:
            Created scene.
        """
        scene = Scene(scene_id=str(uuid.uuid4()), name=name, room=room, description=description)
        self._scenes[scene.scene_id] = scene
        self._snapshots[scene.scene_id] = []
        return scene

    def get_scene(self, scene_id: str) -> Scene:
        """Get a scene by ID.

        Args:
            scene_id: ID of scene.

        Returns:
            Scene object.

        Raises:
            SceneNotFoundError: If scene not found.
        """
        if scene_id not in self._scenes:
            raise SceneNotFoundError(scene_id)
        return self._scenes[scene_id]

    def delete_scene(self, scene_id: str) -> None:
        """Delete a scene.

        Args:
            scene_id: ID of scene to delete.

        Raises:
            SceneNotFoundError: If scene not found.
        """
        if scene_id not in self._scenes:
            raise SceneNotFoundError(scene_id)
        del self._scenes[scene_id]
        if scene_id in self._snapshots:
            del self._snapshots[scene_id]

    def get_all_scenes(self) -> list[Scene]:
        """Get all scenes.

        Returns:
            List of scenes.
        """
        return list(self._scenes.values())

    def get_scenes_by_room(self, room: str) -> list[Scene]:
        """Get scenes for a specific room.

        Args:
            room: Room ID or name.

        Returns:
            List of scenes in the room.
        """
        return [s for s in self._scenes.values() if s.room == room]

    def capture_scene(self, scene_id: str, device_states: dict[str, dict[str, Any]]) -> None:
        """Capture current device states to a scene.

        Args:
            scene_id: ID of scene to update.
            device_states: Device ID -> attributes dict.

        Raises:
            SceneNotFoundError: If scene not found.
        """
        if scene_id not in self._scenes:
            raise SceneNotFoundError(scene_id)

        scene = self._scenes[scene_id]
        scene.device_states = device_states.copy()
        scene.last_modified = datetime.now()

        # Store snapshot
        snapshot = SceneSnapshot(scene_id=scene_id, device_states=device_states.copy())
        self._snapshots[scene_id].append(snapshot)

    def activate_scene(self, scene_id: str, transition_duration_ms: int | None = None) -> dict[str, Any]:
        """Activate a scene, transitioning devices to scene state.

        Args:
            scene_id: ID of scene to activate.
            transition_duration_ms: Override transition duration.

        Returns:
            Activation result with device commands.

        Raises:
            SceneNotFoundError: If scene not found.
        """
        if scene_id not in self._scenes:
            raise SceneNotFoundError(scene_id)

        scene = self._scenes[scene_id]
        duration = transition_duration_ms or scene.transition_duration_ms

        result = {"scene_id": scene_id, "duration_ms": duration, "device_commands": [], "timestamp": datetime.now()}

        # Generate device commands for scene activation
        for device_id, attributes in scene.device_states.items():
            for attr_name, attr_value in attributes.items():
                result["device_commands"].append(
                    {"device_id": device_id, "attribute": attr_name, "value": attr_value, "duration_ms": duration}
                )

        # Call scene callbacks
        for callback in self._scene_callbacks.get(scene_id, []):
            try:
                callback(result)
            except Exception:  # REVIEWED: broad catch
                pass

        return result

    def register_scene_callback(self, scene_id: str, callback: Callable) -> None:
        """Register a callback for scene activation.

        Args:
            scene_id: ID of scene.
            callback: Callable(result) to call when scene activates.
        """
        if scene_id not in self._scene_callbacks:
            self._scene_callbacks[scene_id] = []
        self._scene_callbacks[scene_id].append(callback)

    def create_adaptive_scene(
        self, name: str, room: str | None = None, time_of_day: str | None = None, occupancy_based: bool = False
    ) -> Scene:
        """Create an adaptive scene that changes based on context.

        Args:
            name: Scene name.
            room: Room ID.
            time_of_day: "morning", "afternoon", "evening", "night".
            occupancy_based: Whether scene adapts to occupancy.

        Returns:
            Created adaptive scene.
        """
        scene = self.create_scene(name, room)
        scene.adaptive = True
        scene.time_of_day = time_of_day
        scene.occupancy_based = occupancy_based

        if time_of_day and room:
            if time_of_day not in self._time_of_day_scenes:
                self._time_of_day_scenes[time_of_day] = []
            self._time_of_day_scenes[time_of_day].append(scene.scene_id)

        if occupancy_based and room:
            if room not in self._occupancy_based_scenes:
                self._occupancy_based_scenes[room] = []
            self._occupancy_based_scenes[room].append(scene.scene_id)

        return scene

    def get_adaptive_scene(self, room: str, time_of_day: str, occupancy: bool = False) -> Scene | None:
        """Get adaptive scene matching conditions.

        Args:
            room: Room ID.
            time_of_day: "morning", "afternoon", "evening", "night".
            occupancy: Whether space is occupied.

        Returns:
            Best matching scene or None.
        """
        candidates = []

        # Get scenes for time of day
        for scene_id in self._time_of_day_scenes.get(time_of_day, []):
            if scene_id in self._scenes:
                scene = self._scenes[scene_id]
                if scene.room == room:
                    if occupancy and scene.occupancy_based:
                        candidates.append((2, scene))
                    elif not occupancy:
                        candidates.append((1, scene))

        if not candidates:
            return None

        # Return highest priority
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def merge_scenes(self, target_scene_id: str, source_scene_ids: list[str]) -> None:
        """Merge multiple scenes into one.

        Args:
            target_scene_id: Scene to merge into.
            source_scene_ids: Scenes to merge from.

        Raises:
            SceneNotFoundError: If any scene not found.
        """
        if target_scene_id not in self._scenes:
            raise SceneNotFoundError(target_scene_id)

        target = self._scenes[target_scene_id]

        for source_id in source_scene_ids:
            if source_id not in self._scenes:
                raise SceneNotFoundError(source_id)

            source = self._scenes[source_id]
            # Merge device states (source overrides target)
            target.device_states.update(source.device_states)

        target.last_modified = datetime.now()

    def interpolate_scenes(self, scene1_id: str, scene2_id: str, progress: float) -> dict[str, dict[str, Any]]:
        """Interpolate between two scenes based on progress.

        Handles smooth transitions between scenes.

        Args:
            scene1_id: Starting scene.
            scene2_id: Ending scene.
            progress: 0.0 to 1.0 interpolation progress.

        Returns:
            Interpolated device states.

        Raises:
            SceneNotFoundError: If scene not found.
        """
        if scene1_id not in self._scenes:
            raise SceneNotFoundError(scene1_id)
        if scene2_id not in self._scenes:
            raise SceneNotFoundError(scene2_id)

        scene1 = self._scenes[scene1_id]
        scene2 = self._scenes[scene2_id]

        result: dict[str, dict[str, Any]] = {}

        # Get all devices from both scenes
        all_devices = set(scene1.device_states.keys()) | set(scene2.device_states.keys())

        for device_id in all_devices:
            result[device_id] = {}
            attrs1 = scene1.device_states.get(device_id, {})
            attrs2 = scene2.device_states.get(device_id, {})

            # Merge attributes
            all_attrs = set(attrs1.keys()) | set(attrs2.keys())

            for attr in all_attrs:
                val1 = attrs1.get(attr)
                val2 = attrs2.get(attr)

                # Interpolate numeric values
                if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                    result[device_id][attr] = val1 + (val2 - val1) * progress
                else:
                    # Non-numeric: switch at 50%
                    result[device_id][attr] = val2 if progress >= 0.5 else val1

        return result

    def schedule_scene(self, scene_id: str, time_of_day: str, days: list[int] | None = None) -> None:
        """Schedule a scene to activate at specific times.

        Args:
            scene_id: ID of scene.
            time_of_day: "morning", "afternoon", "evening", "night".
            days: Days of week (0=Mon, 6=Sun) or None for daily.

        Raises:
            SceneNotFoundError: If scene not found.
        """
        if scene_id not in self._scenes:
            raise SceneNotFoundError(scene_id)

        # Store scheduling info in scene
        scene = self._scenes[scene_id]
        scene.time_of_day = time_of_day

    def get_scene_snapshots(self, scene_id: str) -> list[SceneSnapshot]:
        """Get all snapshots for a scene.

        Args:
            scene_id: ID of scene.

        Returns:
            List of snapshots.

        Raises:
            SceneNotFoundError: If scene not found.
        """
        if scene_id not in self._scenes:
            raise SceneNotFoundError(scene_id)
        return self._snapshots.get(scene_id, [])

    def restore_snapshot(self, snapshot: SceneSnapshot) -> None:
        """Restore a scene to a previous snapshot.

        Args:
            snapshot: Snapshot to restore.
        """
        scene = self._scenes.get(snapshot.scene_id)
        if scene:
            scene.device_states = snapshot.device_states.copy()
            scene.last_modified = datetime.now()

    def duplicate_scene(self, scene_id: str, new_name: str) -> Scene:
        """Duplicate a scene.

        Args:
            scene_id: ID of scene to duplicate.
            new_name: Name for new scene.

        Returns:
            New scene.

        Raises:
            SceneNotFoundError: If scene not found.
        """
        if scene_id not in self._scenes:
            raise SceneNotFoundError(scene_id)

        original = self._scenes[scene_id]
        new_scene = self.create_scene(new_name, room=original.room, description=original.description)
        new_scene.device_states = original.device_states.copy()
        new_scene.transition_duration_ms = original.transition_duration_ms
        return new_scene
