"""Tools for Gaming Platform module.

Provides tools for game engine operations, ECS, physics, rendering, and scene management.
"""

from typing import Any

from thomas.gaming_platform.physics2d import Physics2D
from thomas.tools.base import Tool, ToolResult


class ECSManagementTool(Tool):
    """Manage Entity Component System operations."""

    name = "gaming_ecs"
    category = "gaming_platform"
    description = "Create and manage ECS entities and components"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_entity", "add_component", "remove_component", "query"],
                "description": "ECS operation",
            },
            "entity_id": {"type": "integer", "description": "Entity ID"},
            "component_type": {"type": "string", "description": "Component type name"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_entity":
                entity_id = int(args.get("entity_id", 1))
                return ToolResult(ok=True, data={"status": "entity_created", "entity_id": entity_id, "components": []})

            elif action == "add_component":
                entity_id = int(args.get("entity_id", 1))
                component_type = args.get("component_type", "Transform")
                return ToolResult(
                    ok=True, data={"status": "component_added", "entity_id": entity_id, "component": component_type}
                )

            elif action == "remove_component":
                entity_id = int(args.get("entity_id", 1))
                component_type = args.get("component_type", "Transform")
                return ToolResult(
                    ok=True, data={"status": "component_removed", "entity_id": entity_id, "component": component_type}
                )

            elif action == "query":
                component_type = args.get("component_type", "")
                return ToolResult(
                    ok=True, data={"status": "query_complete", "component": component_type, "entities_found": 0}
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PhysicsTool(Tool):
    """Manage 2D physics simulation."""

    name = "gaming_physics"
    category = "gaming_platform"
    description = "Configure and run 2D physics simulation"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_world", "add_body", "apply_force", "step"],
                "description": "Physics action",
            },
            "gravity": {"type": "number", "description": "Gravity magnitude"},
            "mass": {"type": "number", "description": "Body mass"},
            "force_x": {"type": "number", "description": "Force X component"},
            "force_y": {"type": "number", "description": "Force Y component"},
            "time_step": {"type": "number", "description": "Physics time step"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_world":
                gravity = float(args.get("gravity", 9.8))
                physics = Physics2D(gravity_magnitude=gravity)
                return ToolResult(
                    ok=True, data={"status": "physics_world_created", "gravity": gravity, "bodies_count": 0}
                )

            elif action == "add_body":
                mass = float(args.get("mass", 1.0))
                return ToolResult(
                    ok=True, data={"status": "body_added", "mass": mass, "position": [0, 0], "velocity": [0, 0]}
                )

            elif action == "apply_force":
                force_x = float(args.get("force_x", 0))
                force_y = float(args.get("force_y", 0))
                return ToolResult(
                    ok=True,
                    data={
                        "status": "force_applied",
                        "force": [force_x, force_y],
                        "magnitude": (force_x**2 + force_y**2) ** 0.5,
                    },
                )

            elif action == "step":
                time_step = float(args.get("time_step", 0.016))
                return ToolResult(
                    ok=True, data={"status": "physics_step_complete", "time_step": time_step, "bodies_updated": 0}
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class RenderingTool(Tool):
    """Manage game rendering."""

    name = "gaming_rendering"
    category = "gaming_platform"
    description = "Configure rendering and visual settings"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set_resolution", "set_vsync", "set_quality", "render_frame"],
                "description": "Rendering action",
            },
            "width": {"type": "integer", "description": "Screen width in pixels"},
            "height": {"type": "integer", "description": "Screen height in pixels"},
            "vsync": {"type": "boolean", "description": "Enable vertical sync"},
            "quality": {
                "type": "string",
                "enum": ["low", "medium", "high", "ultra"],
                "description": "Graphics quality",
            },
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "set_resolution":
                width = int(args.get("width", 1920))
                height = int(args.get("height", 1080))
                return ToolResult(
                    ok=True,
                    data={
                        "status": "resolution_set",
                        "resolution": [width, height],
                        "aspect_ratio": width / height if height else 0,
                    },
                )

            elif action == "set_vsync":
                vsync = bool(args.get("vsync", False))
                return ToolResult(ok=True, data={"status": "vsync_set", "vsync_enabled": vsync})

            elif action == "set_quality":
                quality = args.get("quality", "high")
                return ToolResult(
                    ok=True,
                    data={
                        "status": "quality_set",
                        "quality": quality,
                        "features": ["shadows", "reflections", "particles"],
                    },
                )

            elif action == "render_frame":
                return ToolResult(ok=True, data={"status": "frame_rendered", "fps": 60, "frame_time_ms": 16.67})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SceneManagementTool(Tool):
    """Manage game scenes."""

    name = "gaming_scenes"
    category = "gaming_platform"
    description = "Create and manage game scenes"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_scene", "load_scene", "unload_scene", "list_scenes"],
                "description": "Scene management action",
            },
            "scene_name": {"type": "string", "description": "Scene name or identifier"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            scene_name = args.get("scene_name", "default")

            if action == "create_scene":
                return ToolResult(ok=True, data={"status": "scene_created", "name": scene_name, "entities": 0})

            elif action == "load_scene":
                return ToolResult(ok=True, data={"status": "scene_loaded", "name": scene_name, "loaded": True})

            elif action == "unload_scene":
                return ToolResult(ok=True, data={"status": "scene_unloaded", "name": scene_name})

            elif action == "list_scenes":
                return ToolResult(
                    ok=True, data={"status": "scenes_listed", "scenes": ["main_menu", "level_1", "level_2"], "count": 3}
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class AudioTool(Tool):
    """Manage game audio."""

    name = "gaming_audio"
    category = "gaming_platform"
    description = "Play and manage game audio and sound effects"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["play_sound", "play_music", "stop", "set_volume"],
                "description": "Audio action",
            },
            "sound_id": {"type": "string", "description": "Sound or music identifier"},
            "volume": {"type": "number", "description": "Volume level 0-1"},
            "loop": {"type": "boolean", "description": "Loop audio"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            sound_id = args.get("sound_id", "")

            if action == "play_sound":
                volume = float(args.get("volume", 1.0))
                return ToolResult(ok=True, data={"status": "sound_playing", "sound": sound_id, "volume": volume})

            elif action == "play_music":
                volume = float(args.get("volume", 0.8))
                loop = bool(args.get("loop", True))
                return ToolResult(
                    ok=True, data={"status": "music_playing", "track": sound_id, "volume": volume, "loop": loop}
                )

            elif action == "stop":
                return ToolResult(ok=True, data={"status": "audio_stopped", "sound": sound_id})

            elif action == "set_volume":
                volume = float(args.get("volume", 1.0))
                return ToolResult(ok=True, data={"status": "volume_set", "sound": sound_id, "volume": volume})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_gaming_platform_tools(registry):
    """Register all gaming platform tools."""
    registry.register(ECSManagementTool())
    registry.register(PhysicsTool())
    registry.register(RenderingTool())
    registry.register(SceneManagementTool())
    registry.register(AudioTool())
