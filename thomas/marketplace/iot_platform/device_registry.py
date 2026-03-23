"""
Device registry for managing IoT devices.

Handles device CRUD operations, device groups, search/filtering,
provisioning, status tracking, and heartbeat monitoring.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from thomas.marketplace.iot_platform._exceptions import (
    DeviceNotFoundError,
    DuplicateDeviceError,
    InvalidDeviceError,
)
from thomas.marketplace.iot_platform._types import Device, DeviceGroup, DeviceStatus, DeviceType


class DeviceRegistry:
    """
    Manages device registration, lifecycle, and group management.

    Provides CRUD operations, device search, provisioning,
    status tracking, and offline detection.
    """

    def __init__(self, heartbeat_timeout_seconds: int = 300) -> None:
        """
        Initialize the device registry.

        Args:
            heartbeat_timeout_seconds: Seconds before device marked offline.
        """
        self._devices: dict[UUID, Device] = {}
        self._groups: dict[str, DeviceGroup] = {}
        self._heartbeat_timeout = heartbeat_timeout_seconds
        self._status_handlers: list[Callable[[UUID, DeviceStatus], None]] = []
        self._lock = threading.RLock()

    def register_device(
        self,
        name: str,
        device_type: DeviceType,
        firmware_version: str,
        properties: dict[str, any] | None = None,
        location: tuple[float, float] | None = None,
    ) -> Device:
        """
        Register a new device in the registry.

        Args:
            name: Human-readable device name.
            device_type: Type of device.
            firmware_version: Initial firmware version.
            properties: Optional device properties.
            location: Optional geographic coordinates (lat, lon).

        Returns:
            Registered Device instance.

        Raises:
            InvalidDeviceError: If device parameters are invalid.
        """
        if not name or len(name.strip()) == 0:
            raise InvalidDeviceError("Device name cannot be empty")

        with self._lock:
            device_id = uuid4()
            device = Device(
                device_id=device_id,
                name=name,
                device_type=device_type,
                status=DeviceStatus.PROVISIONING,
                firmware_version=firmware_version,
                last_seen=datetime.utcnow(),
                properties=properties or {},
                location=location,
                provisioning_token=self._generate_provisioning_token(),
            )
            self._devices[device_id] = device
            return device

    def _generate_provisioning_token(self) -> str:
        """Generate a secure provisioning token for device registration."""
        return secrets.token_urlsafe(32)

    def provision_device(self, device_id: UUID, token: str) -> Device:
        """
        Provision a device using its provisioning token.

        Args:
            device_id: ID of device to provision.
            token: Provisioning token for verification.

        Returns:
            Provisioned Device instance.

        Raises:
            DeviceNotFoundError: If device not found.
            InvalidDeviceError: If token is invalid.
        """
        with self._lock:
            device = self._get_device_locked(device_id)

            if device.provisioning_token != token:
                raise InvalidDeviceError("Invalid provisioning token")

            device.status = DeviceStatus.ONLINE
            device.provisioning_token = None
            device.updated_at = datetime.utcnow()
            return device

    def update_device(
        self,
        device_id: UUID,
        name: str | None = None,
        properties: dict[str, any] | None = None,
        firmware_version: str | None = None,
        location: tuple[float, float] | None = None,
    ) -> Device:
        """
        Update device information.

        Args:
            device_id: ID of device to update.
            name: New device name.
            properties: Updated properties.
            firmware_version: Updated firmware version.
            location: Updated location coordinates.

        Returns:
            Updated Device instance.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        with self._lock:
            device = self._get_device_locked(device_id)

            if name is not None:
                if not name or len(name.strip()) == 0:
                    raise InvalidDeviceError("Device name cannot be empty")
                device.name = name

            if properties is not None:
                device.properties.update(properties)

            if firmware_version is not None:
                device.firmware_version = firmware_version

            if location is not None:
                device.location = location

            device.updated_at = datetime.utcnow()
            return device

    def get_device(self, device_id: UUID) -> Device:
        """
        Retrieve a device by ID.

        Args:
            device_id: ID of device to retrieve.

        Returns:
            Device instance.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        with self._lock:
            return self._get_device_locked(device_id)

    def _get_device_locked(self, device_id: UUID) -> Device:
        """Internal method to get device (assumes lock is held)."""
        if device_id not in self._devices:
            raise DeviceNotFoundError(f"Device {device_id} not found")
        return self._devices[device_id]

    def delete_device(self, device_id: UUID) -> None:
        """
        Delete a device from the registry.

        Args:
            device_id: ID of device to delete.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        with self._lock:
            if device_id not in self._devices:
                raise DeviceNotFoundError(f"Device {device_id} not found")

            device = self._devices[device_id]
            del self._devices[device_id]

            # Remove from groups
            for group in self._groups.values():
                group.device_ids.discard(device_id)

    def list_devices(self) -> list[Device]:
        """
        List all registered devices.

        Returns:
            List of all Device instances.
        """
        with self._lock:
            return list(self._devices.values())

    def search_devices(
        self,
        name_filter: str | None = None,
        device_type: DeviceType | None = None,
        status: DeviceStatus | None = None,
        group_id: str | None = None,
    ) -> list[Device]:
        """
        Search devices with filters.

        Args:
            name_filter: Partial name match filter.
            device_type: Filter by device type.
            status: Filter by device status.
            group_id: Filter by device group.

        Returns:
            List of matching devices.
        """
        with self._lock:
            results = list(self._devices.values())

            if name_filter:
                name_lower = name_filter.lower()
                results = [d for d in results if name_lower in d.name.lower()]

            if device_type:
                results = [d for d in results if d.device_type == device_type]

            if status:
                results = [d for d in results if d.status == status]

            if group_id:
                if group_id not in self._groups:
                    return []
                group_devices = self._groups[group_id].device_ids
                results = [d for d in results if d.device_id in group_devices]

            return results

    def update_device_heartbeat(self, device_id: UUID) -> Device:
        """
        Update device heartbeat timestamp.

        Args:
            device_id: ID of device sending heartbeat.

        Returns:
            Updated Device instance.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        with self._lock:
            device = self._get_device_locked(device_id)
            old_status = device.status
            device.last_seen = datetime.utcnow()

            if old_status == DeviceStatus.OFFLINE:
                device.status = DeviceStatus.ONLINE
                self._notify_status_change(device_id, DeviceStatus.ONLINE)

            return device

    def check_offline_devices(self) -> list[UUID]:
        """
        Check for devices that have exceeded heartbeat timeout.

        Returns:
            List of device IDs that are now offline.
        """
        timeout_delta = timedelta(seconds=self._heartbeat_timeout)
        now = datetime.utcnow()
        offline_devices: list[UUID] = []

        with self._lock:
            for device in self._devices.values():
                if device.status == DeviceStatus.ONLINE:
                    if now - device.last_seen > timeout_delta:
                        device.status = DeviceStatus.OFFLINE
                        offline_devices.append(device.device_id)
                        self._notify_status_change(device.device_id, DeviceStatus.OFFLINE)

        return offline_devices

    def set_device_status(self, device_id: UUID, status: DeviceStatus) -> Device:
        """
        Manually set device status.

        Args:
            device_id: ID of device.
            status: New status value.

        Returns:
            Updated Device instance.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        with self._lock:
            device = self._get_device_locked(device_id)
            old_status = device.status
            device.status = status
            device.updated_at = datetime.utcnow()

            if old_status != status:
                self._notify_status_change(device_id, status)

            return device

    def create_group(self, group_id: str, name: str, description: str) -> DeviceGroup:
        """
        Create a device group.

        Args:
            group_id: Unique group identifier.
            name: Group name.
            description: Group description.

        Returns:
            Created DeviceGroup instance.

        Raises:
            DuplicateDeviceError: If group already exists.
        """
        with self._lock:
            if group_id in self._groups:
                raise DuplicateDeviceError(f"Group {group_id} already exists")

            group = DeviceGroup(group_id=group_id, name=name, description=description)
            self._groups[group_id] = group
            return group

    def add_device_to_group(self, device_id: UUID, group_id: str) -> None:
        """
        Add a device to a group.

        Args:
            device_id: ID of device to add.
            group_id: ID of target group.

        Raises:
            DeviceNotFoundError: If device or group not found.
        """
        with self._lock:
            if device_id not in self._devices:
                raise DeviceNotFoundError(f"Device {device_id} not found")

            if group_id not in self._groups:
                raise DeviceNotFoundError(f"Group {group_id} not found")

            device = self._devices[device_id]
            group = self._groups[group_id]

            device.group_ids.add(group_id)
            group.device_ids.add(device_id)

    def remove_device_from_group(self, device_id: UUID, group_id: str) -> None:
        """
        Remove a device from a group.

        Args:
            device_id: ID of device to remove.
            group_id: ID of source group.

        Raises:
            DeviceNotFoundError: If device or group not found.
        """
        with self._lock:
            if device_id not in self._devices:
                raise DeviceNotFoundError(f"Device {device_id} not found")

            if group_id not in self._groups:
                raise DeviceNotFoundError(f"Group {group_id} not found")

            device = self._devices[device_id]
            group = self._groups[group_id]

            device.group_ids.discard(group_id)
            group.device_ids.discard(device_id)

    def get_group(self, group_id: str) -> DeviceGroup:
        """
        Get a device group by ID.

        Args:
            group_id: ID of group to retrieve.

        Returns:
            DeviceGroup instance.

        Raises:
            DeviceNotFoundError: If group not found.
        """
        with self._lock:
            if group_id not in self._groups:
                raise DeviceNotFoundError(f"Group {group_id} not found")
            return self._groups[group_id]

    def list_groups(self) -> list[DeviceGroup]:
        """
        List all device groups.

        Returns:
            List of all DeviceGroup instances.
        """
        with self._lock:
            return list(self._groups.values())

    def get_group_devices(self, group_id: str) -> list[Device]:
        """
        Get all devices in a group.

        Args:
            group_id: ID of group.

        Returns:
            List of devices in group.

        Raises:
            DeviceNotFoundError: If group not found.
        """
        with self._lock:
            if group_id not in self._groups:
                raise DeviceNotFoundError(f"Group {group_id} not found")

            group = self._groups[group_id]
            return [self._devices[device_id] for device_id in group.device_ids]

    def bulk_update_devices(
        self,
        device_ids: list[UUID],
        updates: dict[str, any],
    ) -> list[Device]:
        """
        Update multiple devices with same properties.

        Args:
            device_ids: List of device IDs to update.
            updates: Dictionary of properties to update.

        Returns:
            List of updated devices.

        Raises:
            DeviceNotFoundError: If any device not found.
        """
        updated_devices: list[Device] = []

        with self._lock:
            for device_id in device_ids:
                device = self._get_device_locked(device_id)

                if "properties" in updates:
                    device.properties.update(updates["properties"])

                if "firmware_version" in updates:
                    device.firmware_version = updates["firmware_version"]

                device.updated_at = datetime.utcnow()
                updated_devices.append(device)

        return updated_devices

    def register_status_handler(self, handler: Callable[[UUID, DeviceStatus], None]) -> None:
        """
        Register a callback for device status changes.

        Args:
            handler: Callable accepting (device_id, new_status).
        """
        with self._lock:
            self._status_handlers.append(handler)

    def _notify_status_change(self, device_id: UUID, status: DeviceStatus) -> None:
        """Notify registered handlers of status change (assumes lock is held)."""
        for handler in self._status_handlers:
            try:
                handler(device_id, status)
            except Exception:  # REVIEWED: broad catch
                pass  # Silently ignore handler errors

    def get_device_count(self) -> int:
        """Get total number of registered devices."""
        with self._lock:
            return len(self._devices)

    def get_devices_by_status(self, status: DeviceStatus) -> list[Device]:
        """
        Get all devices with a specific status.

        Args:
            status: Device status to filter by.

        Returns:
            List of devices with matching status.
        """
        with self._lock:
            return [d for d in self._devices.values() if d.status == status]
