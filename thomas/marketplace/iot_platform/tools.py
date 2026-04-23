"""Tools for IoT Platform operations.

Provides tools for device management, telemetry, commands, rules,
OTA updates, and digital twin operations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from thomas.marketplace.iot_platform._types import (
    DeviceStatus,
    DeviceType,
    RolloutStrategy,
    TelemetryPoint,
)
from thomas.marketplace.iot_platform.commands import CommandManager
from thomas.marketplace.iot_platform.device_registry import DeviceRegistry
from thomas.marketplace.iot_platform.ota import OTAManager
from thomas.marketplace.iot_platform.rules_engine import RulesEngine
from thomas.marketplace.iot_platform.telemetry import TelemetryEngine
from thomas.tools.base import Tool, ToolResult


class RegisterDeviceTool(Tool):
    """Register a new IoT device in the system."""

    name = "iot_register_device"
    category = "iot_platform"
    description = "Register a new IoT device with name, type, and firmware version"
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Human-readable device name",
            },
            "device_type": {
                "type": "string",
                "enum": ["SENSOR", "ACTUATOR", "GATEWAY", "CONTROLLER"],
                "description": "Type of device",
            },
            "firmware_version": {
                "type": "string",
                "description": "Initial firmware version (e.g., '1.0.0')",
            },
            "location": {
                "type": "object",
                "properties": {
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                },
                "description": "Optional geographic coordinates",
            },
            "properties": {
                "type": "object",
                "description": "Optional device-specific properties",
            },
        },
        "required": ["name", "device_type", "firmware_version"],
    }

    def __init__(self, registry: DeviceRegistry) -> None:
        self.registry = registry

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            name = args.get("name", "")
            device_type_str = args.get("device_type", "").upper()
            firmware_version = args.get("firmware_version", "")
            properties = args.get("properties")
            location = None

            location_obj = args.get("location")
            if location_obj:
                location = (location_obj.get("latitude"), location_obj.get("longitude"))

            device_type = DeviceType[device_type_str]
            device = self.registry.register_device(
                name=name,
                device_type=device_type,
                firmware_version=firmware_version,
                properties=properties,
                location=location,
            )

            return ToolResult(
                ok=True,
                data={
                    "device_id": str(device.device_id),
                    "name": device.name,
                    "status": device.status.name,
                    "provisioning_token": device.provisioning_token,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ListDevicesTool(Tool):
    """List all registered IoT devices."""

    name = "iot_list_devices"
    category = "iot_platform"
    description = "List all registered IoT devices with their status and metadata"
    parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["PROVISIONING", "ONLINE", "OFFLINE", "ERROR"],
                "description": "Filter by device status",
            },
            "device_type": {
                "type": "string",
                "enum": ["SENSOR", "ACTUATOR", "GATEWAY", "CONTROLLER"],
                "description": "Filter by device type",
            },
        },
    }

    def __init__(self, registry: DeviceRegistry) -> None:
        self.registry = registry

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            status_filter = None
            device_type_filter = None

            if args.get("status"):
                status_filter = DeviceStatus[args["status"].upper()]
            if args.get("device_type"):
                device_type_filter = DeviceType[args["device_type"].upper()]

            devices = self.registry.search_devices(device_type=device_type_filter, status=status_filter)

            return ToolResult(
                ok=True,
                data=[
                    {
                        "device_id": str(d.device_id),
                        "name": d.name,
                        "type": d.device_type.name,
                        "status": d.status.name,
                        "firmware_version": d.firmware_version,
                        "location": d.location,
                    }
                    for d in devices
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SendCommandTool(Tool):
    """Send a command to an IoT device."""

    name = "iot_send_command"
    category = "iot_platform"
    description = "Send a command to a device (e.g., turn on/off, set value)"
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Target device UUID",
            },
            "action": {
                "type": "string",
                "description": "Action name (e.g., 'turn_on', 'set_brightness')",
            },
            "parameters": {
                "type": "object",
                "description": "Action parameters as key-value pairs",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Command timeout in seconds (default: 60)",
            },
        },
        "required": ["device_id", "action"],
    }

    def __init__(self, command_manager: CommandManager) -> None:
        self.command_manager = command_manager

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            device_id = UUID(args.get("device_id"))
            action = args.get("action", "")
            parameters = args.get("parameters")
            timeout = args.get("timeout_seconds")

            command = self.command_manager.send_command(
                target_device_id=device_id,
                action=action,
                parameters=parameters,
                timeout_seconds=timeout,
            )

            return ToolResult(
                ok=True,
                data={
                    "command_id": str(command.command_id),
                    "device_id": str(command.target_device_id),
                    "action": command.action,
                    "status": command.status.name,
                    "created_at": command.created_at.isoformat(),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class IngestTelemetryTool(Tool):
    """Ingest telemetry data from a device."""

    name = "iot_ingest_telemetry"
    category = "iot_platform"
    description = "Ingest a telemetry data point from a device"
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Device UUID",
            },
            "metric": {
                "type": "string",
                "description": "Metric name (e.g., 'temperature', 'humidity')",
            },
            "value": {
                "type": "number",
                "description": "Metric value",
            },
            "unit": {
                "type": "string",
                "description": "Unit of measurement (e.g., 'C', '%')",
            },
        },
        "required": ["device_id", "metric", "value"],
    }

    def __init__(self, telemetry_engine: TelemetryEngine) -> None:
        self.telemetry_engine = telemetry_engine

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            device_id = UUID(args.get("device_id"))
            metric = args.get("metric", "")
            value = float(args.get("value"))
            unit = args.get("unit", "")

            point = TelemetryPoint(
                device_id=device_id,
                metric=metric,
                value=value,
                unit=unit,
                timestamp=datetime.now(),
            )

            self.telemetry_engine.ingest_telemetry(point)

            return ToolResult(
                ok=True,
                data={
                    "device_id": str(device_id),
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "timestamp": point.timestamp.isoformat(),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class QueryTelemetryTool(Tool):
    """Query telemetry data for a device."""

    name = "iot_query_telemetry"
    category = "iot_platform"
    description = "Query telemetry data for a device over a time range"
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Device UUID",
            },
            "metric": {
                "type": "string",
                "description": "Metric name to query",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of points to return (default: 100)",
            },
        },
        "required": ["device_id", "metric"],
    }

    def __init__(self, telemetry_engine: TelemetryEngine) -> None:
        self.telemetry_engine = telemetry_engine

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            device_id = UUID(args.get("device_id"))
            metric = args.get("metric", "")
            limit = args.get("limit", 100)

            points = self.telemetry_engine.query_telemetry(device_id=device_id, metric=metric, limit=limit)

            return ToolResult(
                ok=True,
                data=[
                    {
                        "timestamp": p.timestamp.isoformat(),
                        "metric": p.metric,
                        "value": p.value,
                        "unit": p.unit,
                    }
                    for p in points
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CreateRuleTool(Tool):
    """Create an automation rule in the IoT platform."""

    name = "iot_create_rule"
    category = "iot_platform"
    description = "Create an automation rule with conditions and actions"
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Rule name",
            },
            "condition": {
                "type": "object",
                "description": "Condition specification (e.g., threshold, pattern, absence)",
            },
            "actions": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of actions to execute when rule triggers",
            },
            "priority": {
                "type": "integer",
                "description": "Execution priority (higher = earlier)",
            },
        },
        "required": ["name", "condition", "actions"],
    }

    def __init__(self, rules_engine: RulesEngine) -> None:
        self.rules_engine = rules_engine

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            name = args.get("name", "")
            condition = args.get("condition", {})
            actions = args.get("actions", [])
            priority = args.get("priority", 0)

            rule = self.rules_engine.create_rule(name=name, condition=condition, actions=actions, priority=priority)

            return ToolResult(
                ok=True,
                data={
                    "rule_id": str(rule.rule_id),
                    "name": rule.name,
                    "priority": rule.priority,
                    "enabled": rule.enabled,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CreateOTAUpdateTool(Tool):
    """Create a firmware over-the-air update campaign."""

    name = "iot_create_ota_update"
    category = "iot_platform"
    description = "Create an OTA firmware update campaign for devices"
    parameters = {
        "type": "object",
        "properties": {
            "firmware_version": {
                "type": "string",
                "description": "Target firmware version (e.g., '2.0.0')",
            },
            "firmware_url": {
                "type": "string",
                "description": "URL to download firmware from",
            },
            "checksum": {
                "type": "string",
                "description": "SHA256 checksum of firmware file",
            },
            "file_size": {
                "type": "integer",
                "description": "Firmware file size in bytes",
            },
            "rollout_strategy": {
                "type": "string",
                "enum": ["IMMEDIATE", "STAGED", "CANARY"],
                "description": "Update rollout strategy",
            },
            "target_groups": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Device groups to target",
            },
        },
        "required": ["firmware_version", "firmware_url", "checksum", "file_size", "rollout_strategy"],
    }

    def __init__(self, ota_manager: OTAManager) -> None:
        self.ota_manager = ota_manager

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            firmware_version = args.get("firmware_version", "")
            firmware_url = args.get("firmware_url", "")
            checksum = args.get("checksum", "")
            file_size = int(args.get("file_size", 0))
            rollout_strategy_str = args.get("rollout_strategy", "IMMEDIATE").upper()
            target_groups = args.get("target_groups")

            rollout_strategy = RolloutStrategy[rollout_strategy_str]

            update = self.ota_manager.create_update(
                firmware_version=firmware_version,
                firmware_url=firmware_url,
                checksum=checksum,
                file_size=file_size,
                rollout_strategy=rollout_strategy,
                target_groups=target_groups,
            )

            return ToolResult(
                ok=True,
                data={
                    "update_id": str(update.update_id),
                    "firmware_version": update.firmware_version,
                    "status": update.status.name,
                    "rollout_strategy": update.rollout_strategy.name,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class GetDeviceTool(Tool):
    """Get details for a specific device."""

    name = "iot_get_device"
    category = "iot_platform"
    description = "Get detailed information about a specific device"
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Device UUID",
            },
        },
        "required": ["device_id"],
    }

    def __init__(self, registry: DeviceRegistry) -> None:
        self.registry = registry

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            device_id = UUID(args.get("device_id"))
            device = self.registry.get_device(device_id)

            return ToolResult(
                ok=True,
                data={
                    "device_id": str(device.device_id),
                    "name": device.name,
                    "type": device.device_type.name,
                    "status": device.status.name,
                    "firmware_version": device.firmware_version,
                    "location": device.location,
                    "properties": device.properties,
                    "last_seen": device.last_seen.isoformat() if device.last_seen else None,
                    "created_at": device.created_at.isoformat() if device.created_at else None,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_iot_platform_tools(registry: Any) -> None:
    """Register IoT platform tools.

    Args:
        registry: ToolRegistry to add tools to.
    """
    # Create service instances (in production, these would come from dependency injection)
    device_registry = DeviceRegistry()
    telemetry_engine = TelemetryEngine()
    command_manager = CommandManager()
    rules_engine = RulesEngine()
    ota_manager = OTAManager()

    registry.register(RegisterDeviceTool(device_registry))
    registry.register(ListDevicesTool(device_registry))
    registry.register(GetDeviceTool(device_registry))
    registry.register(SendCommandTool(command_manager))
    registry.register(IngestTelemetryTool(telemetry_engine))
    registry.register(QueryTelemetryTool(telemetry_engine))
    registry.register(CreateRuleTool(rules_engine))
    registry.register(CreateOTAUpdateTool(ota_manager))
