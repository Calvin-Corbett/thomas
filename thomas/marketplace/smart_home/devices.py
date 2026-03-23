"""Device registry and management."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from thomas.marketplace.smart_home._exceptions import (
    DeviceNotFoundError,
    DeviceOfflineError,
    FirmwareUpdateError,
    InvalidCapabilityError,
    PairingError,
)
from thomas.marketplace.smart_home._types import (
    Device,
    DeviceState,
    DeviceType,
    Protocol,
)


@dataclass
class DevicePairingState:
    """Represents pairing state of a device."""

    device_id: str
    """Device ID being paired."""
    state: str
    """Pairing state: 'pending', 'in_progress', 'paired', 'failed'."""
    started_at: datetime = field(default_factory=datetime.now)
    """When pairing started."""
    last_update: datetime = field(default_factory=datetime.now)
    """Last state update time."""
    pin_code: str | None = None
    """PIN code for pairing if applicable."""
    error_message: str | None = None
    """Error message if pairing failed."""


@dataclass
class DeviceHealth:
    """Device health information."""

    device_id: str
    """Device ID."""
    last_heartbeat: datetime = field(default_factory=datetime.now)
    """Last time device sent heartbeat."""
    heartbeat_interval_seconds: int = 300
    """Expected interval between heartbeats."""
    missed_heartbeats: int = 0
    """Number of missed heartbeats."""
    signal_strength: int = -100
    """Signal strength in dBm (WiFi/BLE)."""
    battery_level: float | None = None
    """Battery level percentage if battery-powered."""
    error_count_24h: int = 0
    """Errors in last 24 hours."""
    uptime_seconds: int = 0
    """Device uptime."""


class DeviceRegistry:
    """Manages device registry with capability discovery and health monitoring.

    Provides device registration, pairing state machine, health monitoring
    with heartbeat tracking, firmware management, and device grouping.
    """

    def __init__(self) -> None:
        """Initialize the device registry."""
        self._devices: dict[str, Device] = {}
        self._pairing_states: dict[str, DevicePairingState] = {}
        self._health: dict[str, DeviceHealth] = {}
        self._groups: dict[str, set[str]] = {}
        self._command_handlers: dict[str, Callable] = {}
        self._offline_handlers: list[Callable] = []
        self._heartbeat_timeout = timedelta(seconds=600)

    def register_device(self, device: Device) -> Device:
        """Register a device in the registry.

        Args:
            device: Device object to register.

        Returns:
            Registered device.
        """
        if not device.device_id:
            device.device_id = str(uuid.uuid4())
        self._devices[device.device_id] = device
        self._health[device.device_id] = DeviceHealth(device_id=device.device_id)
        return device

    def unregister_device(self, device_id: str) -> None:
        """Unregister a device from the registry.

        Args:
            device_id: ID of device to unregister.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)
        del self._devices[device_id]
        if device_id in self._health:
            del self._health[device_id]
        if device_id in self._pairing_states:
            del self._pairing_states[device_id]

    def get_device(self, device_id: str) -> Device:
        """Get a device by ID.

        Args:
            device_id: ID of the device.

        Returns:
            Device object.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)
        return self._devices[device_id]

    def get_devices_by_room(self, room: str) -> list[Device]:
        """Get all devices in a room.

        Args:
            room: Room name or ID.

        Returns:
            List of devices in the room.
        """
        return [d for d in self._devices.values() if d.room == room]

    def get_devices_by_type(self, device_type: DeviceType) -> list[Device]:
        """Get all devices of a specific type.

        Args:
            device_type: Type of device.

        Returns:
            List of devices of that type.
        """
        return [d for d in self._devices.values() if d.device_type == device_type]

    def get_devices_by_protocol(self, protocol: Protocol) -> list[Device]:
        """Get all devices using a protocol.

        Args:
            protocol: Communication protocol.

        Returns:
            List of devices using that protocol.
        """
        return [d for d in self._devices.values() if d.protocol == protocol]

    def get_online_devices(self) -> list[Device]:
        """Get all online devices.

        Returns:
            List of online devices.
        """
        return [d for d in self._devices.values() if d.state == DeviceState.ONLINE]

    def get_offline_devices(self) -> list[Device]:
        """Get all offline devices.

        Returns:
            List of offline devices.
        """
        return [d for d in self._devices.values() if d.state == DeviceState.OFFLINE]

    def start_pairing(self, device_id: str, pin_code: str | None = None) -> DevicePairingState:
        """Start device pairing process.

        Args:
            device_id: ID of device to pair.
            pin_code: PIN code if required.

        Returns:
            Pairing state.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)

        state = DevicePairingState(device_id=device_id, state="pending", pin_code=pin_code)
        self._pairing_states[device_id] = state
        device = self._devices[device_id]
        device.pairing_required = True
        return state

    def complete_pairing(self, device_id: str) -> DevicePairingState:
        """Complete device pairing.

        Args:
            device_id: ID of device that was paired.

        Returns:
            Updated pairing state.

        Raises:
            DeviceNotFoundError: If device not found.
            PairingError: If pairing failed.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)

        if device_id not in self._pairing_states:
            raise PairingError(f"No pairing in progress for {device_id}")

        state = self._pairing_states[device_id]
        state.state = "paired"
        state.last_update = datetime.now()

        device = self._devices[device_id]
        device.pairing_required = False
        device.state = DeviceState.ONLINE

        return state

    def fail_pairing(self, device_id: str, error: str) -> DevicePairingState:
        """Mark pairing as failed.

        Args:
            device_id: ID of device.
            error: Error message.

        Returns:
            Failed pairing state.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)

        state = self._pairing_states.get(device_id)
        if not state:
            state = DevicePairingState(device_id=device_id, state="failed")
            self._pairing_states[device_id] = state

        state.state = "failed"
        state.error_message = error
        state.last_update = datetime.now()
        return state

    def get_pairing_state(self, device_id: str) -> DevicePairingState | None:
        """Get current pairing state for a device.

        Args:
            device_id: ID of device.

        Returns:
            Pairing state or None if not being paired.
        """
        return self._pairing_states.get(device_id)

    def record_heartbeat(self, device_id: str, signal_strength: int = -100, battery_level: float | None = None) -> None:
        """Record a heartbeat from a device.

        Args:
            device_id: ID of device.
            signal_strength: Signal strength in dBm.
            battery_level: Battery level percentage if applicable.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)

        device = self._devices[device_id]
        health = self._health[device_id]

        health.last_heartbeat = datetime.now()
        health.missed_heartbeats = 0
        health.signal_strength = signal_strength
        if battery_level is not None:
            health.battery_level = battery_level

        if device.state != DeviceState.ONLINE:
            device.state = DeviceState.ONLINE
            device.last_seen = datetime.now()

    def check_device_health(self, device_id: str) -> DeviceHealth:
        """Check health status of a device.

        Args:
            device_id: ID of device.

        Returns:
            Health status.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)

        device = self._devices[device_id]
        health = self._health[device_id]

        # Mark offline if no heartbeat
        time_since_heartbeat = datetime.now() - health.last_heartbeat
        if time_since_heartbeat > self._heartbeat_timeout:
            health.missed_heartbeats += 1
            if device.state == DeviceState.ONLINE:
                device.state = DeviceState.OFFLINE
                self._call_offline_handlers(device_id)

        return health

    def get_device_health(self, device_id: str) -> DeviceHealth:
        """Get health information for a device.

        Args:
            device_id: ID of device.

        Returns:
            Health information.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)
        return self._health[device_id]

    def update_firmware(self, device_id: str, version: str, url: str) -> None:
        """Update device firmware.

        Args:
            device_id: ID of device.
            version: New firmware version.
            url: URL to firmware file.

        Raises:
            DeviceNotFoundError: If device not found.
            DeviceOfflineError: If device is offline.
            FirmwareUpdateError: If update fails.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)

        device = self._devices[device_id]
        if device.state != DeviceState.ONLINE:
            raise DeviceOfflineError(device_id)

        device.state = DeviceState.UPDATING
        try:
            # Simulate firmware update
            device.firmware_version = version
            device.state = DeviceState.ONLINE
        except Exception as e:
            device.state = DeviceState.ERROR
            raise FirmwareUpdateError(f"Update failed: {e}")

    def add_device_to_group(self, device_id: str, group_name: str) -> None:
        """Add device to a group.

        Args:
            device_id: ID of device.
            group_name: Name of group.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)

        if group_name not in self._groups:
            self._groups[group_name] = set()

        self._groups[group_name].add(device_id)
        self._devices[device_id].groups.add(group_name)

    def remove_device_from_group(self, device_id: str, group_name: str) -> None:
        """Remove device from a group.

        Args:
            device_id: ID of device.
            group_name: Name of group.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)

        if group_name in self._groups:
            self._groups[group_name].discard(device_id)

        self._devices[device_id].groups.discard(group_name)

    def get_devices_in_group(self, group_name: str) -> list[Device]:
        """Get all devices in a group.

        Args:
            group_name: Name of group.

        Returns:
            List of devices in the group.
        """
        if group_name not in self._groups:
            return []
        return [self._devices[did] for did in self._groups[group_name] if did in self._devices]

    def register_command_handler(self, device_id: str, handler: Callable) -> None:
        """Register a command handler for a device.

        Args:
            device_id: ID of device.
            handler: Callable that handles device commands.
        """
        self._command_handlers[device_id] = handler

    def route_command(self, device_id: str, capability: str, value: Any) -> Any:
        """Route a command to a device.

        Args:
            device_id: ID of target device.
            capability: Capability to set.
            value: Value to set.

        Returns:
            Command result.

        Raises:
            DeviceNotFoundError: If device not found.
            InvalidCapabilityError: If capability not supported.
            DeviceOfflineError: If device offline.
        """
        if device_id not in self._devices:
            raise DeviceNotFoundError(device_id)

        device = self._devices[device_id]
        if device.state == DeviceState.OFFLINE:
            raise DeviceOfflineError(device_id)

        # Check capability
        cap_names = {c.name for c in device.capabilities}
        if capability not in cap_names:
            raise InvalidCapabilityError(device_id, capability)

        # Call registered handler if exists
        if device_id in self._command_handlers:
            return self._command_handlers[device_id](capability, value)

        # Update device state
        device.attributes[capability] = value
        return {"status": "ok", "device_id": device_id, "capability": capability, "value": value}

    def register_offline_handler(self, handler: Callable) -> None:
        """Register a handler to call when devices go offline.

        Args:
            handler: Callable(device_id) to call when device goes offline.
        """
        self._offline_handlers.append(handler)

    def _call_offline_handlers(self, device_id: str) -> None:
        """Call all offline handlers for a device.

        Args:
            device_id: ID of device that went offline.
        """
        for handler in self._offline_handlers:
            try:
                handler(device_id)
            except Exception:  # REVIEWED: broad catch
                pass

    def get_all_devices(self) -> list[Device]:
        """Get all registered devices.

        Returns:
            List of all devices.
        """
        return list(self._devices.values())

    def get_capability_distribution(self) -> dict[str, int]:
        """Get count of devices supporting each capability.

        Returns:
            Capability name -> count mapping.
        """
        distribution: dict[str, int] = {}
        for device in self._devices.values():
            for cap in device.capabilities:
                distribution[cap.name] = distribution.get(cap.name, 0) + 1
        return distribution
