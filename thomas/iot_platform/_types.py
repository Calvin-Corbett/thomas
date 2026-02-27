"""
Core data types and models for the IoT platform.

Defines all domain models including devices, telemetry, commands,
rules, and configurations used throughout the platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID


class DeviceType(str, Enum):
    """Enumeration of supported device types."""

    SENSOR = "sensor"
    ACTUATOR = "actuator"
    GATEWAY = "gateway"
    CONTROLLER = "controller"
    HYBRID = "hybrid"


class DeviceStatus(str, Enum):
    """Enumeration of device operational statuses."""

    ONLINE = "online"
    OFFLINE = "offline"
    IDLE = "idle"
    ERROR = "error"
    PROVISIONING = "provisioning"
    FIRMWARE_UPDATING = "firmware_updating"
    MAINTENANCE = "maintenance"


class CommandStatus(str, Enum):
    """Enumeration of command execution statuses."""

    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class AlertSeverity(str, Enum):
    """Enumeration of alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class UpdateStatus(str, Enum):
    """Enumeration of firmware update statuses."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class RolloutStrategy(str, Enum):
    """Firmware rollout strategies."""

    IMMEDIATE = "immediate"
    CANARY = "canary"
    STAGED = "staged"


@dataclass
class Device:
    """
    Represents a physical IoT device.

    Attributes:
        device_id: Unique device identifier (UUID).
        name: Human-readable device name.
        device_type: Type classification of the device.
        status: Current operational status.
        firmware_version: Current firmware version string.
        last_seen: Timestamp of last device communication.
        properties: Custom device-specific properties.
        location: Optional geographic location.
        group_ids: Set of groups this device belongs to.
        provisioning_token: Token used for initial device registration.
        created_at: Device creation timestamp.
        updated_at: Last update timestamp.
    """

    device_id: UUID
    name: str
    device_type: DeviceType
    status: DeviceStatus
    firmware_version: str
    last_seen: datetime
    properties: dict[str, Any] = field(default_factory=dict)
    location: tuple[float, float] | None = None
    group_ids: set[str] = field(default_factory=set)
    provisioning_token: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def is_online(self, timeout_seconds: int = 300) -> bool:
        """Check if device is considered online based on last_seen timestamp."""
        return datetime.utcnow() - self.last_seen < timedelta(seconds=timeout_seconds)

    def to_dict(self) -> dict[str, Any]:
        """Convert device to dictionary representation."""
        return {
            "device_id": str(self.device_id),
            "name": self.name,
            "device_type": self.device_type.value,
            "status": self.status.value,
            "firmware_version": self.firmware_version,
            "last_seen": self.last_seen.isoformat(),
            "properties": self.properties,
            "location": self.location,
            "group_ids": list(self.group_ids),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class TelemetryPoint:
    """
    Represents a single telemetry data point from a device.

    Attributes:
        device_id: ID of the source device.
        metric: Metric name (e.g., 'temperature', 'humidity').
        value: Metric value (numeric or string).
        timestamp: When the measurement was taken.
        tags: Optional key-value tags for classification.
    """

    device_id: UUID
    metric: str
    value: float | str | int
    timestamp: datetime
    tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert telemetry point to dictionary representation."""
        return {
            "device_id": str(self.device_id),
            "metric": self.metric,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "tags": self.tags,
        }


@dataclass
class Command:
    """
    Represents a command to be executed on a device.

    Attributes:
        command_id: Unique command identifier.
        target_device_id: ID of target device.
        action: Command action name.
        parameters: Command parameters.
        status: Current execution status.
        created_at: Command creation timestamp.
        sent_at: When command was sent to device.
        completed_at: When command execution completed.
        result: Command execution result data.
        retry_count: Number of retry attempts.
        max_retries: Maximum allowed retries.
        timeout_seconds: Command execution timeout.
    """

    command_id: UUID
    target_device_id: UUID
    action: str
    parameters: dict[str, Any]
    status: CommandStatus
    created_at: datetime
    sent_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 60

    def is_expired(self) -> bool:
        """Check if command has exceeded timeout."""
        if self.sent_at is None:
            return False
        return datetime.utcnow() - self.sent_at > timedelta(seconds=self.timeout_seconds)

    def to_dict(self) -> dict[str, Any]:
        """Convert command to dictionary representation."""
        return {
            "command_id": str(self.command_id),
            "target_device_id": str(self.target_device_id),
            "action": self.action,
            "parameters": self.parameters,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
        }


@dataclass
class Rule:
    """
    Represents an IoT automation rule.

    Attributes:
        rule_id: Unique rule identifier.
        name: Human-readable rule name.
        condition: Rule condition specification.
        actions: List of actions to execute when condition is met.
        enabled: Whether rule is active.
        priority: Rule execution priority (higher = earlier).
        created_at: Rule creation timestamp.
    """

    rule_id: UUID
    name: str
    condition: dict[str, Any]
    actions: list[dict[str, Any]]
    enabled: bool = True
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert rule to dictionary representation."""
        return {
            "rule_id": str(self.rule_id),
            "name": self.name,
            "condition": self.condition,
            "actions": self.actions,
            "enabled": self.enabled,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Alert:
    """
    Represents an alert generated by the system.

    Attributes:
        alert_id: Unique alert identifier.
        device_id: Device that triggered the alert.
        rule_id: Rule that generated the alert.
        severity: Alert severity level.
        message: Human-readable alert message.
        details: Detailed alert information.
        triggered_at: When alert was triggered.
        acknowledged_at: When alert was acknowledged.
        acknowledged_by: User who acknowledged the alert.
    """

    alert_id: UUID
    device_id: UUID
    rule_id: UUID
    severity: AlertSeverity
    message: str
    details: dict[str, Any]
    triggered_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert alert to dictionary representation."""
        return {
            "alert_id": str(self.alert_id),
            "device_id": str(self.device_id),
            "rule_id": str(self.rule_id),
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
            "triggered_at": self.triggered_at.isoformat(),
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "acknowledged_by": self.acknowledged_by,
        }


@dataclass
class OTAUpdate:
    """
    Represents a firmware over-the-air update campaign.

    Attributes:
        update_id: Unique update identifier.
        firmware_version: Target firmware version.
        firmware_url: URL to download firmware.
        checksum: SHA256 checksum for validation.
        file_size: Firmware file size in bytes.
        rollout_strategy: Update rollout strategy.
        target_groups: Device groups to target.
        target_device_ids: Specific devices to target.
        current_status: Current update status.
        progress_percentage: Overall rollout progress.
        created_at: Update creation timestamp.
        device_statuses: Status per device.
    """

    update_id: UUID
    firmware_version: str
    firmware_url: str
    checksum: str
    file_size: int
    rollout_strategy: RolloutStrategy
    target_groups: list[str] = field(default_factory=list)
    target_device_ids: list[UUID] = field(default_factory=list)
    current_status: UpdateStatus = UpdateStatus.PENDING
    progress_percentage: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    device_statuses: dict[str, UpdateStatus] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert OTA update to dictionary representation."""
        return {
            "update_id": str(self.update_id),
            "firmware_version": self.firmware_version,
            "firmware_url": self.firmware_url,
            "checksum": self.checksum,
            "file_size": self.file_size,
            "rollout_strategy": self.rollout_strategy.value,
            "target_groups": self.target_groups,
            "target_device_ids": [str(d) for d in self.target_device_ids],
            "current_status": self.current_status.value,
            "progress_percentage": self.progress_percentage,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class DeviceGroup:
    """
    Represents a logical group of devices.

    Attributes:
        group_id: Unique group identifier.
        name: Group name.
        description: Group description.
        device_ids: Set of devices in this group.
        created_at: Group creation timestamp.
    """

    group_id: str
    name: str
    description: str
    device_ids: set[UUID] = field(default_factory=set)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert device group to dictionary representation."""
        return {
            "group_id": self.group_id,
            "name": self.name,
            "description": self.description,
            "device_ids": [str(d) for d in self.device_ids],
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class MQTTConfig:
    """
    Configuration for MQTT broker connection.

    Attributes:
        broker_host: MQTT broker hostname or IP.
        broker_port: MQTT broker port.
        username: Optional authentication username.
        password: Optional authentication password.
        client_id: MQTT client identifier.
        use_tls: Whether to use TLS/SSL.
        qos_default: Default QoS level (0, 1, or 2).
        keep_alive_seconds: Keep-alive interval.
    """

    broker_host: str
    broker_port: int
    username: str | None = None
    password: str | None = None
    client_id: str = "iot_platform"
    use_tls: bool = False
    qos_default: int = 1
    keep_alive_seconds: int = 60

    def to_dict(self) -> dict[str, Any]:
        """Convert MQTT config to dictionary representation."""
        return {
            "broker_host": self.broker_host,
            "broker_port": self.broker_port,
            "username": self.username,
            "client_id": self.client_id,
            "use_tls": self.use_tls,
            "qos_default": self.qos_default,
            "keep_alive_seconds": self.keep_alive_seconds,
        }
