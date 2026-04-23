"""
IoT Platform - A comprehensive Internet of Things management system.

Provides device management, telemetry collection, rule-based automation,
firmware updates, MQTT protocol support, and digital twin simulation.
"""

from thomas.marketplace.iot_platform._exceptions import (
    CommandError,
    DeviceNotFoundError,
    DuplicateDeviceError,
    InvalidDeviceError,
    InvalidRuleError,
    IoTException,
    MQTTError,
    OTAError,
    TelemetryError,
)
from thomas.marketplace.iot_platform._types import (
    Alert,
    AlertSeverity,
    Command,
    CommandStatus,
    Device,
    DeviceGroup,
    DeviceStatus,
    DeviceType,
    MQTTConfig,
    OTAUpdate,
    RolloutStrategy,
    Rule,
    TelemetryPoint,
    UpdateStatus,
)
from thomas.marketplace.iot_platform.commands import CommandManager
from thomas.marketplace.iot_platform.dashboard import DashboardManager
from thomas.marketplace.iot_platform.device_registry import DeviceRegistry
from thomas.marketplace.iot_platform.digital_twin import DigitalTwinManager
from thomas.marketplace.iot_platform.edge import EdgeNodeManager
from thomas.marketplace.iot_platform.mqtt import MQTTBroker
from thomas.marketplace.iot_platform.ota import OTAManager
from thomas.marketplace.iot_platform.rules_engine import RulesEngine
from thomas.marketplace.iot_platform.telemetry import TelemetryEngine

__version__ = "1.0.0"
__all__ = [
    "Device",
    "DeviceType",
    "DeviceStatus",
    "TelemetryPoint",
    "Command",
    "CommandStatus",
    "Rule",
    "Alert",
    "AlertSeverity",
    "OTAUpdate",
    "UpdateStatus",
    "DeviceGroup",
    "MQTTConfig",
    "RolloutStrategy",
    "IoTException",
    "DeviceNotFoundError",
    "InvalidDeviceError",
    "DuplicateDeviceError",
    "TelemetryError",
    "InvalidRuleError",
    "CommandError",
    "MQTTError",
    "OTAError",
    "DeviceRegistry",
    "TelemetryEngine",
    "RulesEngine",
    "CommandManager",
    "OTAManager",
    "MQTTBroker",
    "DigitalTwinManager",
    "EdgeNodeManager",
    "DashboardManager",
]
