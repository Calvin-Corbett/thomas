"""Tools for Smart Home operations.

Provides tools for device management, automation, scenes, lighting,
climate control, security, energy management, and voice control.
"""

from __future__ import annotations

from typing import Any

from thomas.smart_home._types import (
    AlarmState,
    Automation,
)
from thomas.smart_home.automation import AutomationEngine
from thomas.smart_home.climate import ThermostatScheduler
from thomas.smart_home.devices import DeviceRegistry
from thomas.smart_home.energy_mgmt import EnergyManager
from thomas.smart_home.lighting import LightingController
from thomas.smart_home.scenes import SceneManager
from thomas.smart_home.security import SecuritySystem
from thomas.smart_home.voice import VoiceController
from thomas.tools.base import Tool, ToolResult


class RegisterSmartDeviceTool(Tool):
    """Register a new smart home device."""

    name = "smart_register_device"
    category = "smart_home"
    description = "Register a new smart home device with protocol and capabilities"
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Device identifier",
            },
            "name": {
                "type": "string",
                "description": "Human-readable device name",
            },
            "device_type": {
                "type": "string",
                "enum": ["LIGHT", "SWITCH", "THERMOSTAT", "LOCK", "CAMERA", "SENSOR", "PLUG"],
                "description": "Type of smart device",
            },
            "protocol": {
                "type": "string",
                "enum": ["ZIGBEE", "ZWAVE", "WIFI", "BLUETOOTH", "THREAD"],
                "description": "Communication protocol",
            },
            "room": {
                "type": "string",
                "description": "Room name where device is located",
            },
            "capabilities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Device capabilities (e.g., 'on_off', 'brightness')",
            },
        },
        "required": ["device_id", "name", "device_type", "protocol"],
    }

    def __init__(self, device_registry: DeviceRegistry) -> None:
        self.device_registry = device_registry

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            device_id = args.get("device_id", "")
            name = args.get("name", "")
            device_type = args.get("device_type", "")
            protocol = args.get("protocol", "")
            room = args.get("room")
            capabilities = args.get("capabilities", [])

            device = self.device_registry.register_device(
                device_id=device_id,
                name=name,
                device_type=device_type,
                protocol=protocol,
                room=room,
                capabilities=capabilities,
            )

            return ToolResult(
                ok=True,
                data={
                    "device_id": device.device_id,
                    "name": device.name,
                    "type": device.device_type,
                    "protocol": device.protocol,
                    "room": device.room,
                    "online": device.online,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ListSmartDevicesTool(Tool):
    """List all registered smart home devices."""

    name = "smart_list_devices"
    category = "smart_home"
    description = "List all registered smart home devices with their status"
    parameters = {
        "type": "object",
        "properties": {
            "room": {
                "type": "string",
                "description": "Filter devices by room",
            },
            "device_type": {
                "type": "string",
                "description": "Filter devices by type",
            },
            "online_only": {
                "type": "boolean",
                "description": "Only show online devices",
            },
        },
    }

    def __init__(self, device_registry: DeviceRegistry) -> None:
        self.device_registry = device_registry

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            room_filter = args.get("room")
            device_type_filter = args.get("device_type")
            online_only = args.get("online_only", False)

            devices = self.device_registry.list_devices()

            if room_filter:
                devices = [d for d in devices if d.room == room_filter]
            if device_type_filter:
                devices = [d for d in devices if d.device_type == device_type_filter]
            if online_only:
                devices = [d for d in devices if d.online]

            return ToolResult(
                ok=True,
                data=[
                    {
                        "device_id": d.device_id,
                        "name": d.name,
                        "type": d.device_type,
                        "protocol": d.protocol,
                        "room": d.room,
                        "online": d.online,
                        "capabilities": d.capabilities,
                    }
                    for d in devices
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CreateAutomationTool(Tool):
    """Create a smart home automation rule."""

    name = "smart_create_automation"
    category = "smart_home"
    description = "Create an automation rule with triggers, conditions, and actions"
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Automation rule name",
            },
            "trigger": {
                "type": "object",
                "description": "Trigger specification (device_id, state change, time-based)",
            },
            "conditions": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of conditions that must be met",
            },
            "actions": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of actions to execute",
            },
        },
        "required": ["name", "trigger", "actions"],
    }

    def __init__(self, automation_engine: AutomationEngine) -> None:
        self.automation_engine = automation_engine

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            name = args.get("name", "")
            trigger = args.get("trigger", {})
            conditions = args.get("conditions", [])
            actions = args.get("actions", [])

            automation = Automation(
                automation_id="",
                name=name,
                trigger=trigger,
                conditions=conditions,
                actions=actions,
                enabled=True,
            )

            result = self.automation_engine.register_automation(automation)

            return ToolResult(
                ok=True,
                data={
                    "automation_id": result.automation_id,
                    "name": result.name,
                    "enabled": result.enabled,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CreateSceneTool(Tool):
    """Create a smart home scene."""

    name = "smart_create_scene"
    category = "smart_home"
    description = "Create a named scene with device state snapshots"
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Scene name",
            },
            "room": {
                "type": "string",
                "description": "Room the scene applies to",
            },
            "description": {
                "type": "string",
                "description": "Scene description",
            },
        },
        "required": ["name"],
    }

    def __init__(self, scene_manager: SceneManager) -> None:
        self.scene_manager = scene_manager

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            name = args.get("name", "")
            room = args.get("room")
            description = args.get("description")

            scene = self.scene_manager.create_scene(name=name, room=room, description=description)

            return ToolResult(
                ok=True,
                data={
                    "scene_id": scene.scene_id,
                    "name": scene.name,
                    "room": scene.room,
                    "description": scene.description,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ActivateSceneTool(Tool):
    """Activate a smart home scene."""

    name = "smart_activate_scene"
    category = "smart_home"
    description = "Activate a scene to apply saved device states"
    parameters = {
        "type": "object",
        "properties": {
            "scene_id": {
                "type": "string",
                "description": "Scene ID to activate",
            },
            "transition_seconds": {
                "type": "integer",
                "description": "Transition duration in seconds",
            },
        },
        "required": ["scene_id"],
    }

    def __init__(self, scene_manager: SceneManager) -> None:
        self.scene_manager = scene_manager

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            scene_id = args.get("scene_id", "")
            transition_seconds = args.get("transition_seconds", 0)

            result = self.scene_manager.activate_scene(scene_id=scene_id, transition_seconds=transition_seconds)

            return ToolResult(
                ok=True,
                data={
                    "scene_id": scene_id,
                    "activated": True,
                    "devices_affected": result.get("devices_affected", 0),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ControlLightTool(Tool):
    """Control a smart light."""

    name = "smart_control_light"
    category = "smart_home"
    description = "Control a light (on/off, brightness, color)"
    parameters = {
        "type": "object",
        "properties": {
            "light_id": {
                "type": "string",
                "description": "Light device ID",
            },
            "on": {
                "type": "boolean",
                "description": "Turn light on or off",
            },
            "brightness": {
                "type": "integer",
                "description": "Brightness 0-255",
            },
            "color_temp": {
                "type": "integer",
                "description": "Color temperature in Kelvin",
            },
        },
        "required": ["light_id"],
    }

    def __init__(self, lighting_controller: LightingController) -> None:
        self.lighting_controller = lighting_controller

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            light_id = args.get("light_id", "")
            on = args.get("on")
            brightness = args.get("brightness")
            color_temp = args.get("color_temp")

            if on is not None:
                self.lighting_controller.set_light_state(light_id, on=on)
            if brightness is not None:
                self.lighting_controller.set_brightness(light_id, brightness)
            if color_temp is not None:
                self.lighting_controller.set_color_temperature(light_id, color_temp)

            state = self.lighting_controller.get_light_state(light_id)

            return ToolResult(
                ok=True,
                data={
                    "light_id": light_id,
                    "on": state.on,
                    "brightness": state.brightness,
                    "color_temp": state.color_temp_kelvin,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SetThermostatTool(Tool):
    """Set thermostat temperature and mode."""

    name = "smart_set_thermostat"
    category = "smart_home"
    description = "Set thermostat target temperature and mode"
    parameters = {
        "type": "object",
        "properties": {
            "zone_id": {
                "type": "string",
                "description": "Climate zone ID",
            },
            "target_temp": {
                "type": "number",
                "description": "Target temperature in Celsius",
            },
            "mode": {
                "type": "string",
                "enum": ["heat", "cool", "auto", "off", "eco"],
                "description": "Thermostat mode",
            },
        },
        "required": ["zone_id"],
    }

    def __init__(self, thermostat_scheduler: ThermostatScheduler) -> None:
        self.thermostat_scheduler = thermostat_scheduler

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            zone_id = args.get("zone_id", "")
            target_temp = args.get("target_temp")
            mode = args.get("mode")

            if target_temp is not None:
                self.thermostat_scheduler.set_target_temperature(zone_id=zone_id, temperature=target_temp)
            if mode:
                self.thermostat_scheduler.set_mode(zone_id=zone_id, mode=mode)

            state = self.thermostat_scheduler.get_zone_state(zone_id)

            return ToolResult(
                ok=True,
                data={
                    "zone_id": zone_id,
                    "current_temp": state.current_temp,
                    "target_temp": state.target_temp,
                    "mode": mode or "unknown",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ArmSecurityTool(Tool):
    """Arm or disarm the security system."""

    name = "smart_arm_security"
    category = "smart_home"
    description = "Arm or disarm the security system"
    parameters = {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "enum": ["ARMED", "DISARMED", "ARMED_AWAY", "ARMED_HOME"],
                "description": "Target alarm state",
            },
            "code": {
                "type": "string",
                "description": "Security code for arming/disarming",
            },
        },
        "required": ["state"],
    }

    def __init__(self, security_system: SecuritySystem) -> None:
        self.security_system = security_system

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            state_str = args.get("state", "").upper()
            code = args.get("code")

            alarm_state = AlarmState[state_str]

            result = self.security_system.set_alarm_state(alarm_state, code=code)

            return ToolResult(
                ok=True,
                data={
                    "state": alarm_state.name,
                    "armed": result.get("armed", False),
                    "timestamp": result.get("timestamp"),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class GetEnergyUsageTool(Tool):
    """Get energy usage data."""

    name = "smart_get_energy_usage"
    category = "smart_home"
    description = "Get energy usage for a device or all devices"
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Device ID (optional, all if omitted)",
            },
            "period": {
                "type": "string",
                "enum": ["today", "week", "month"],
                "description": "Time period for aggregation",
            },
        },
    }

    def __init__(self, energy_manager: EnergyManager) -> None:
        self.energy_manager = energy_manager

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            device_id = args.get("device_id")
            period = args.get("period", "today")

            if device_id:
                usage = self.energy_manager.get_device_energy(device_id, period=period)
                return ToolResult(
                    ok=True,
                    data={
                        "device_id": device_id,
                        "energy_kwh": usage.get("energy_kwh", 0),
                        "cost": usage.get("cost", 0),
                        "period": period,
                    },
                )
            else:
                usage = self.energy_manager.get_total_energy(period=period)
                return ToolResult(
                    ok=True,
                    data={
                        "total_energy_kwh": usage.get("total_kwh", 0),
                        "total_cost": usage.get("total_cost", 0),
                        "period": period,
                    },
                )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ProcessVoiceCommandTool(Tool):
    """Process a voice command."""

    name = "smart_process_voice_command"
    category = "smart_home"
    description = "Process a natural language voice command"
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Voice command text",
            },
            "context": {
                "type": "object",
                "description": "Optional context (room, user, etc.)",
            },
        },
        "required": ["command"],
    }

    def __init__(self, voice_controller: VoiceController) -> None:
        self.voice_controller = voice_controller

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            command = args.get("command", "")
            context = args.get("context", {})

            intent = self.voice_controller.parse_intent(command, context=context)

            return ToolResult(
                ok=True,
                data={
                    "intent_type": intent.intent_type,
                    "confidence": intent.confidence,
                    "device_ids": intent.device_ids,
                    "entities": intent.entities,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class GetSmartDeviceStatusTool(Tool):
    """Get the current status of a smart device."""

    name = "smart_get_device_status"
    category = "smart_home"
    description = "Get detailed status of a smart home device"
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Device ID",
            },
        },
        "required": ["device_id"],
    }

    def __init__(self, device_registry: DeviceRegistry) -> None:
        self.device_registry = device_registry

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            device_id = args.get("device_id", "")

            device = self.device_registry.get_device(device_id)

            return ToolResult(
                ok=True,
                data={
                    "device_id": device.device_id,
                    "name": device.name,
                    "type": device.device_type,
                    "online": device.online,
                    "state": device.state,
                    "battery_level": device.battery_level,
                    "signal_strength": device.signal_strength,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_smart_home_tools(registry: Any) -> None:
    """Register smart home tools.

    Args:
        registry: ToolRegistry to add tools to.
    """
    # Create service instances (in production, these would come from dependency injection)
    device_registry = DeviceRegistry()
    automation_engine = AutomationEngine()
    scene_manager = SceneManager()
    lighting_controller = LightingController()
    thermostat_scheduler = ThermostatScheduler()
    security_system = SecuritySystem()
    energy_manager = EnergyManager()
    voice_controller = VoiceController()

    registry.register(RegisterSmartDeviceTool(device_registry))
    registry.register(ListSmartDevicesTool(device_registry))
    registry.register(GetSmartDeviceStatusTool(device_registry))
    registry.register(CreateAutomationTool(automation_engine))
    registry.register(CreateSceneTool(scene_manager))
    registry.register(ActivateSceneTool(scene_manager))
    registry.register(ControlLightTool(lighting_controller))
    registry.register(SetThermostatTool(thermostat_scheduler))
    registry.register(ArmSecurityTool(security_system))
    registry.register(GetEnergyUsageTool(energy_manager))
    registry.register(ProcessVoiceCommandTool(voice_controller))
