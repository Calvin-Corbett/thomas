"""Smart home automation and IoT control module.

This module provides a comprehensive framework for managing smart home devices,
automations, scenes, and climate control with support for multiple protocols.
"""

from thomas.smart_home._exceptions import (
    AutomationError,
    DeviceError,
    ProtocolError,
    SecurityError,
    SmartHomeException,
)
from thomas.smart_home._types import (
    Action,
    Automation,
    Condition,
    Device,
    DeviceCapability,
    DeviceState,
    EnergyUsage,
    Protocol,
    Room,
    Scene,
    Schedule,
    SensorReading,
    Trigger,
    Zone,
)
from thomas.smart_home.automation import AutomationEngine
from thomas.smart_home.climate import ThermostatScheduler
from thomas.smart_home.devices import DeviceRegistry
from thomas.smart_home.energy_mgmt import EnergyManager
from thomas.smart_home.lighting import LightingController
from thomas.smart_home.protocols import ProtocolBridge
from thomas.smart_home.scenes import SceneManager
from thomas.smart_home.security import SecuritySystem
from thomas.smart_home.voice import VoiceController

__all__ = [
    # Types
    "Device",
    "Room",
    "Zone",
    "Scene",
    "Automation",
    "Trigger",
    "Action",
    "Condition",
    "Schedule",
    "SensorReading",
    "DeviceCapability",
    "Protocol",
    "DeviceState",
    "EnergyUsage",
    # Exceptions
    "SmartHomeException",
    "DeviceError",
    "ProtocolError",
    "AutomationError",
    "SecurityError",
    # Core classes
    "DeviceRegistry",
    "AutomationEngine",
    "SceneManager",
    "ProtocolBridge",
    "ThermostatScheduler",
    "LightingController",
    "SecuritySystem",
    "EnergyManager",
    "VoiceController",
]

__version__ = "0.1.0"
