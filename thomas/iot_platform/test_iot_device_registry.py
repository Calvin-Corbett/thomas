"""
Tests for device registry module.

Tests device CRUD operations, groups, search, provisioning,
status tracking, and heartbeat monitoring.
"""

from uuid import UUID

import pytest

from thomas.iot_platform._exceptions import (
    DeviceNotFoundError,
    DuplicateDeviceError,
    InvalidDeviceError,
)
from thomas.iot_platform._types import DeviceStatus, DeviceType
from thomas.iot_platform.device_registry import DeviceRegistry


class TestDeviceRegistry:
    """Test device registry functionality."""

    @pytest.fixture
    def registry(self) -> DeviceRegistry:
        """Create a device registry instance."""
        return DeviceRegistry(heartbeat_timeout_seconds=300)

    def test_register_device(self, registry: DeviceRegistry) -> None:
        """Test basic device registration."""
        device = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        assert device.name == "Sensor-01"
        assert device.device_type == DeviceType.SENSOR
        assert device.firmware_version == "1.0.0"
        assert device.status == DeviceStatus.PROVISIONING
        assert device.provisioning_token is not None

    def test_register_device_with_properties(self, registry: DeviceRegistry) -> None:
        """Test device registration with properties."""
        props = {"location_type": "warehouse", "zone": "A1"}
        device = registry.register_device(
            name="Device-01",
            device_type=DeviceType.ACTUATOR,
            firmware_version="2.1.0",
            properties=props,
        )

        assert device.properties == props

    def test_register_device_empty_name(self, registry: DeviceRegistry) -> None:
        """Test device registration with empty name fails."""
        with pytest.raises(InvalidDeviceError):
            registry.register_device(
                name="",
                device_type=DeviceType.SENSOR,
                firmware_version="1.0.0",
            )

    def test_get_device(self, registry: DeviceRegistry) -> None:
        """Test retrieving a device."""
        registered = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        retrieved = registry.get_device(registered.device_id)

        assert retrieved.device_id == registered.device_id
        assert retrieved.name == registered.name

    def test_get_nonexistent_device(self, registry: DeviceRegistry) -> None:
        """Test retrieving nonexistent device raises error."""
        fake_id = UUID("00000000-0000-0000-0000-000000000000")

        with pytest.raises(DeviceNotFoundError):
            registry.get_device(fake_id)

    def test_provision_device(self, registry: DeviceRegistry) -> None:
        """Test device provisioning."""
        device = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        token = device.provisioning_token
        provisioned = registry.provision_device(device.device_id, token)

        assert provisioned.status == DeviceStatus.ONLINE
        assert provisioned.provisioning_token is None

    def test_provision_device_invalid_token(self, registry: DeviceRegistry) -> None:
        """Test provisioning with invalid token fails."""
        device = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        with pytest.raises(InvalidDeviceError):
            registry.provision_device(device.device_id, "invalid_token")

    def test_update_device(self, registry: DeviceRegistry) -> None:
        """Test updating device information."""
        device = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        updated = registry.update_device(
            device.device_id,
            name="Sensor-Updated",
            firmware_version="1.1.0",
        )

        assert updated.name == "Sensor-Updated"
        assert updated.firmware_version == "1.1.0"

    def test_delete_device(self, registry: DeviceRegistry) -> None:
        """Test device deletion."""
        device = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        registry.delete_device(device.device_id)

        with pytest.raises(DeviceNotFoundError):
            registry.get_device(device.device_id)

    def test_list_devices(self, registry: DeviceRegistry) -> None:
        """Test listing all devices."""
        registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )
        registry.register_device(
            name="Actuator-01",
            device_type=DeviceType.ACTUATOR,
            firmware_version="1.0.0",
        )

        devices = registry.list_devices()

        assert len(devices) == 2

    def test_search_devices_by_name(self, registry: DeviceRegistry) -> None:
        """Test searching devices by name."""
        registry.register_device(
            name="Temperature-Sensor",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )
        registry.register_device(
            name="Pressure-Sensor",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )
        registry.register_device(
            name="Relay-Controller",
            device_type=DeviceType.CONTROLLER,
            firmware_version="1.0.0",
        )

        results = registry.search_devices(name_filter="Sensor")

        assert len(results) == 2

    def test_search_devices_by_type(self, registry: DeviceRegistry) -> None:
        """Test searching devices by type."""
        registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )
        registry.register_device(
            name="Actuator-01",
            device_type=DeviceType.ACTUATOR,
            firmware_version="1.0.0",
        )

        results = registry.search_devices(device_type=DeviceType.SENSOR)

        assert len(results) == 1
        assert results[0].device_type == DeviceType.SENSOR

    def test_update_heartbeat(self, registry: DeviceRegistry) -> None:
        """Test device heartbeat update."""
        device = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        registry.provision_device(device.device_id, device.provisioning_token)
        old_last_seen = device.last_seen

        import time

        time.sleep(0.1)

        updated = registry.update_device_heartbeat(device.device_id)

        assert updated.last_seen > old_last_seen

    def test_check_offline_devices(self, registry: DeviceRegistry) -> None:
        """Test offline device detection."""
        registry_short = DeviceRegistry(heartbeat_timeout_seconds=1)

        device = registry_short.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        registry_short.provision_device(device.device_id, device.provisioning_token)

        import time

        time.sleep(1.1)

        offline = registry_short.check_offline_devices()

        assert device.device_id in offline

    def test_set_device_status(self, registry: DeviceRegistry) -> None:
        """Test manually setting device status."""
        device = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        updated = registry.set_device_status(device.device_id, DeviceStatus.ERROR)

        assert updated.status == DeviceStatus.ERROR

    def test_create_group(self, registry: DeviceRegistry) -> None:
        """Test creating device group."""
        group = registry.create_group(
            group_id="warehouse_a",
            name="Warehouse A",
            description="Devices in warehouse A",
        )

        assert group.group_id == "warehouse_a"
        assert group.name == "Warehouse A"

    def test_create_duplicate_group(self, registry: DeviceRegistry) -> None:
        """Test creating duplicate group fails."""
        registry.create_group(
            group_id="warehouse_a",
            name="Warehouse A",
            description="Devices in warehouse A",
        )

        with pytest.raises(DuplicateDeviceError):
            registry.create_group(
                group_id="warehouse_a",
                name="Warehouse A",
                description="Devices in warehouse A",
            )

    def test_add_device_to_group(self, registry: DeviceRegistry) -> None:
        """Test adding device to group."""
        device = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        registry.create_group(
            group_id="warehouse_a",
            name="Warehouse A",
            description="Devices in warehouse A",
        )

        registry.add_device_to_group(device.device_id, "warehouse_a")

        group = registry.get_group("warehouse_a")

        assert device.device_id in group.device_ids

    def test_get_group_devices(self, registry: DeviceRegistry) -> None:
        """Test getting devices in group."""
        device1 = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )
        device2 = registry.register_device(
            name="Sensor-02",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        registry.create_group(
            group_id="warehouse_a",
            name="Warehouse A",
            description="Devices in warehouse A",
        )

        registry.add_device_to_group(device1.device_id, "warehouse_a")
        registry.add_device_to_group(device2.device_id, "warehouse_a")

        devices = registry.get_group_devices("warehouse_a")

        assert len(devices) == 2

    def test_bulk_update_devices(self, registry: DeviceRegistry) -> None:
        """Test bulk updating devices."""
        device1 = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )
        device2 = registry.register_device(
            name="Sensor-02",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        updated = registry.bulk_update_devices(
            [device1.device_id, device2.device_id],
            {"firmware_version": "2.0.0"},
        )

        assert len(updated) == 2
        assert all(d.firmware_version == "2.0.0" for d in updated)

    def test_device_count(self, registry: DeviceRegistry) -> None:
        """Test getting device count."""
        registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )
        registry.register_device(
            name="Sensor-02",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        assert registry.get_device_count() == 2

    def test_get_devices_by_status(self, registry: DeviceRegistry) -> None:
        """Test getting devices by status."""
        device = registry.register_device(
            name="Sensor-01",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        online_devices = registry.get_devices_by_status(DeviceStatus.PROVISIONING)

        assert len(online_devices) == 1
        assert online_devices[0].device_id == device.device_id
