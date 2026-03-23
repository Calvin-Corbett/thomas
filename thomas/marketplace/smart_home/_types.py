"""Type definitions and data models for the smart home system."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any


class Protocol(Enum):
    """Supported communication protocols for IoT devices."""

    ZIGBEE = "zigbee"
    ZWAVE = "zwave"
    WIFI = "wifi"
    BLUETOOTH = "bluetooth"
    MATTER = "matter"
    THREAD = "thread"


class DeviceType(Enum):
    """Types of smart home devices."""

    LIGHT = "light"
    THERMOSTAT = "thermostat"
    DOOR_LOCK = "door_lock"
    MOTION_SENSOR = "motion_sensor"
    DOOR_SENSOR = "door_sensor"
    TEMPERATURE_SENSOR = "temperature_sensor"
    HUMIDITY_SENSOR = "humidity_sensor"
    SMOKE_DETECTOR = "smoke_detector"
    CO_DETECTOR = "co_detector"
    OUTLET = "outlet"
    SWITCH = "switch"
    SPEAKER = "speaker"
    CAMERA = "camera"
    BLINDS = "blinds"
    PLUG = "plug"
    VALVE = "valve"
    FAN = "fan"
    WATER_HEATER = "water_heater"


class TriggerType(Enum):
    """Types of automation triggers."""

    STATE_CHANGE = "state_change"
    TIME = "time"
    SUNRISE = "sunrise"
    SUNSET = "sunset"
    GEOFENCE = "geofence"
    WEBHOOK = "webhook"
    MANUAL = "manual"


class ConditionOperator(Enum):
    """Logical operators for conditions."""

    AND = "and"
    OR = "or"
    NOT = "not"


class ComparisonOperator(Enum):
    """Comparison operators for condition values."""

    EQ = "=="
    NEQ = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    IN = "in"
    NOT_IN = "not_in"


class DeviceState(Enum):
    """Device operational states."""

    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"
    UNAVAILABLE = "unavailable"
    UPDATING = "updating"


class AlarmState(Enum):
    """Security system alarm states."""

    DISARMED = "disarmed"
    ARMED_HOME = "armed_home"
    ARMED_AWAY = "armed_away"
    ARMED_NIGHT = "armed_night"
    TRIGGERED = "triggered"
    PENDING = "pending"


@dataclass
class DeviceCapability:
    """Represents a capability of a device."""

    name: str
    """Capability name (e.g., 'on_off', 'brightness', 'color_temp')."""
    supported_values: list[Any] | None = None
    """Discrete values supported, if applicable."""
    min_value: float | None = None
    """Minimum value for continuous properties."""
    max_value: float | None = None
    """Maximum value for continuous properties."""
    unit: str | None = None
    """Unit of measurement (e.g., 'C', '%', 'lux')."""
    settable: bool = True
    """Whether this capability can be set."""

    def __hash__(self) -> int:
        """Return hash of capability."""
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        """Check equality of capabilities."""
        if not isinstance(other, DeviceCapability):
            return NotImplemented
        return self.name == other.name


@dataclass
class SensorReading:
    """A sensor reading from a device."""

    device_id: str
    """ID of the device that produced the reading."""
    capability: str
    """Capability name being read."""
    value: Any
    """The sensor value."""
    timestamp: datetime
    """When the reading was taken."""
    unit: str | None = None
    """Unit of measurement."""


@dataclass
class EnergyUsage:
    """Energy usage statistics."""

    device_id: str
    """Device ID."""
    power_watts: float
    """Current power consumption in watts."""
    energy_kwh_day: float
    """Daily energy consumption in kWh."""
    energy_kwh_month: float
    """Monthly energy consumption in kWh."""
    cost_currency: float | None = None
    """Estimated cost in the user's currency."""
    timestamp: datetime = field(default_factory=datetime.now)
    """When this reading was taken."""


@dataclass
class Device:
    """Represents a smart home device."""

    name: str
    """Human-readable device name."""
    device_type: DeviceType
    """Type of device."""
    room: str
    """Room where the device is located."""
    protocol: Protocol
    """Communication protocol."""
    mac_address: str
    """MAC address of the device."""
    device_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique device identifier."""
    ip_address: str | None = None
    """IP address if applicable."""
    firmware_version: str = "0.0.0"
    """Current firmware version."""
    capabilities: list[DeviceCapability] = field(default_factory=list)
    """List of device capabilities."""
    state: DeviceState = DeviceState.OFFLINE
    """Current device state."""
    attributes: dict[str, Any] = field(default_factory=dict)
    """Current attribute values (on/off, brightness, temp, etc.)."""
    last_seen: datetime | None = None
    """Last time the device communicated with hub."""
    pairing_required: bool = False
    """Whether device needs pairing."""
    model: str | None = None
    """Device model identifier."""
    manufacturer: str | None = None
    """Device manufacturer."""
    groups: set[str] = field(default_factory=set)
    """Device groups this device belongs to."""


@dataclass
class Room:
    """A room in the house."""

    room_id: str
    """Unique room identifier."""
    name: str
    """Room name."""
    devices: list[str] = field(default_factory=list)
    """Device IDs in this room."""
    zone_id: str | None = None
    """Associated zone ID."""
    area_sqm: float | None = None
    """Room area in square meters."""
    ambient_light_lux: float | None = None
    """Current ambient light level."""


@dataclass
class Zone:
    """A zone containing multiple rooms."""

    zone_id: str
    """Unique zone identifier."""
    name: str
    """Zone name."""
    rooms: list[str] = field(default_factory=list)
    """Room IDs in this zone."""
    devices: list[str] = field(default_factory=list)
    """Device IDs assigned directly to zone."""


@dataclass
class Schedule:
    """Scheduling information for automations or scenes."""

    enabled: bool = True
    """Whether the schedule is active."""
    start_time: time | None = None
    """Start time if time-based."""
    end_time: time | None = None
    """End time if time-based."""
    days_of_week: list[int] | None = None
    """Days 0-6 (Mon-Sun) to run on."""
    cron_expression: str | None = None
    """Cron expression for complex scheduling."""
    timezone: str = "UTC"
    """Timezone for schedule evaluation."""


@dataclass
class Trigger:
    """Automation trigger definition."""

    trigger_id: str
    """Unique trigger identifier."""
    trigger_type: TriggerType
    """Type of trigger."""
    device_id: str | None = None
    """Device ID if device-based trigger."""
    capability: str | None = None
    """Capability name if state-change trigger."""
    state_value: Any | None = None
    """Expected state value."""
    time_of_day: time | None = None
    """Time if time-based trigger."""
    offset_minutes: int = 0
    """Offset in minutes for sunrise/sunset."""
    geofence_location: tuple[float, float] | None = None
    """GPS location for geofence trigger."""
    geofence_radius_m: float = 100.0
    """Radius in meters for geofence."""
    webhook_url: str | None = None
    """Webhook URL for webhook triggers."""


@dataclass
class Condition:
    """Condition for automation execution."""

    attribute: str
    """Attribute to check."""
    operator: ComparisonOperator
    """Comparison operator."""
    value: Any
    """Expected value."""
    device_id: str | None = None
    """Device to check, if device-specific."""
    negate: bool = False
    """Negate the condition."""


@dataclass
class Action:
    """Action to execute in an automation."""

    action_id: str
    """Unique action identifier."""
    action_type: str
    """Type of action (set_device_attr, call_service, etc.)."""
    device_id: str | None = None
    """Target device ID."""
    capability: str | None = None
    """Target capability."""
    value: Any = None
    """Value to set."""
    delay_seconds: float = 0.0
    """Delay before executing action."""
    service: str | None = None
    """Service to call if service action."""
    scene_id: str | None = None
    """Scene to activate if scene action."""


@dataclass
class Automation:
    """An automation rule."""

    name: str
    """Human-readable name."""
    automation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique automation identifier."""
    enabled: bool = True
    """Whether automation is active."""
    triggers: list[Trigger] = field(default_factory=list)
    """List of triggers (OR'd together)."""
    conditions: list[Condition] = field(default_factory=list)
    """Conditions to check (AND'd together)."""
    actions: list[Action] = field(default_factory=list)
    """Actions to execute."""
    schedule: Schedule | None = None
    """Optional schedule for the automation."""
    priority: int = 50
    """Priority 0-100 for conflict resolution."""
    conflict_resolution: str = "first_match"
    """How to resolve conflicts: first_match, highest_priority, all."""
    description: str | None = None
    """Description of the automation."""


@dataclass
class Scene:
    """A scene snapshot of device states."""

    name: str
    """Human-readable name."""
    scene_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique scene identifier."""
    description: str | None = None
    """Description of the scene."""
    room: str | None = None
    """Room this scene applies to."""
    device_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Device ID -> attribute dict for scene state."""
    transition_duration_ms: int = 1000
    """Duration to transition to scene in milliseconds."""
    adaptive: bool = False
    """Whether scene should adapt based on context."""
    time_of_day: str | None = None
    """Time context (morning, afternoon, evening, night)."""
    occupancy_based: bool = False
    """Whether scene adapts based on occupancy."""
    icon: str | None = None
    """Icon identifier."""
    created_at: datetime = field(default_factory=datetime.now)
    """When scene was created."""
    last_modified: datetime = field(default_factory=datetime.now)
    """When scene was last modified."""
