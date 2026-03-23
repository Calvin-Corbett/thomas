"""Tests for device registry and management."""

from datetime import datetime, timedelta

import pytest

from thomas.marketplace.smart_home._exceptions import (
    DeviceNotFoundError,
    DeviceOfflineError,
    InvalidCapabilityError,
)
from thomas.marketplace.smart_home._types import Device, DeviceCapability, DeviceState, DeviceType, Protocol
from thomas.marketplace.smart_home.devices import DeviceRegistry


class TestDeviceRegistry:
    """Test DeviceRegistry functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = DeviceRegistry()

    def test_register_device(self):
        """Test device registration."""
        device = Device(
            name="Living Room Light",
            device_type=DeviceType.LIGHT,
            room="Living Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:55",
        )

        registered = self.registry.register_device(device)

        assert registered.device_id is not None
        assert registered.name == "Living Room Light"
        assert self.registry.get_device(registered.device_id) == registered

    def test_unregister_device(self):
        """Test device unregistration."""
        device = Device(
            name="Test Light",
            device_type=DeviceType.LIGHT,
            room="Test",
            protocol=Protocol.WIFI,
            mac_address="00:11:22:33:44:55",
        )

        registered = self.registry.register_device(device)
        self.registry.unregister_device(registered.device_id)

        with pytest.raises(DeviceNotFoundError):
            self.registry.get_device(registered.device_id)

    def test_get_device_not_found(self):
        """Test getting non-existent device."""
        with pytest.raises(DeviceNotFoundError):
            self.registry.get_device("nonexistent")

    def test_get_devices_by_room(self):
        """Test filtering devices by room."""
        device1 = Device(
            name="Light 1",
            device_type=DeviceType.LIGHT,
            room="Living Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:55",
        )
        device2 = Device(
            name="Light 2",
            device_type=DeviceType.LIGHT,
            room="Bedroom",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:66",
        )

        self.registry.register_device(device1)
        self.registry.register_device(device2)

        living_room = self.registry.get_devices_by_room("Living Room")
        assert len(living_room) == 1
        assert living_room[0].name == "Light 1"

    def test_get_devices_by_type(self):
        """Test filtering devices by type."""
        light = Device(
            name="Light",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:55",
        )
        lock = Device(
            name="Lock",
            device_type=DeviceType.DOOR_LOCK,
            room="Room",
            protocol=Protocol.ZWAVE,
            mac_address="00:11:22:33:44:66",
        )

        self.registry.register_device(light)
        self.registry.register_device(lock)

        lights = self.registry.get_devices_by_type(DeviceType.LIGHT)
        assert len(lights) == 1
        assert lights[0].device_type == DeviceType.LIGHT

    def test_get_online_devices(self):
        """Test filtering online devices."""
        device1 = Device(
            name="Online Light",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:55",
            state=DeviceState.ONLINE,
        )
        device2 = Device(
            name="Offline Light",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:66",
            state=DeviceState.OFFLINE,
        )

        self.registry.register_device(device1)
        self.registry.register_device(device2)

        online = self.registry.get_online_devices()
        assert len(online) == 1
        assert online[0].state == DeviceState.ONLINE

    def test_device_pairing_flow(self):
        """Test device pairing state machine."""
        device = Device(
            name="New Device",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:55",
        )

        registered = self.registry.register_device(device)

        # Start pairing
        pairing_state = self.registry.start_pairing(registered.device_id)
        assert pairing_state.state == "pending"

        # Complete pairing
        completed = self.registry.complete_pairing(registered.device_id)
        assert completed.state == "paired"
        assert not self.registry.get_device(registered.device_id).pairing_required

    def test_pairing_failure(self):
        """Test failed pairing."""
        device = Device(
            name="Device",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:55",
        )

        registered = self.registry.register_device(device)
        self.registry.start_pairing(registered.device_id)

        failed = self.registry.fail_pairing(registered.device_id, "Timeout")
        assert failed.state == "failed"
        assert failed.error_message == "Timeout"

    def test_record_heartbeat(self):
        """Test recording device heartbeat."""
        device = Device(
            name="Device",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.WIFI,
            mac_address="00:11:22:33:44:55",
            state=DeviceState.OFFLINE,
        )

        registered = self.registry.register_device(device)

        # Device should start offline
        assert registered.state == DeviceState.OFFLINE

        # Record heartbeat
        self.registry.record_heartbeat(registered.device_id, signal_strength=-50)

        # Device should be online now
        device = self.registry.get_device(registered.device_id)
        assert device.state == DeviceState.ONLINE

    def test_device_health_check(self):
        """Test device health monitoring."""
        device = Device(
            name="Device",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.WIFI,
            mac_address="00:11:22:33:44:55",
            state=DeviceState.ONLINE,
        )

        registered = self.registry.register_device(device)
        self.registry.record_heartbeat(registered.device_id)

        health = self.registry.get_device_health(registered.device_id)
        assert health.device_id == registered.device_id
        assert health.missed_heartbeats == 0

    def test_firmware_update(self):
        """Test firmware update."""
        device = Device(
            name="Device",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.WIFI,
            mac_address="00:11:22:33:44:55",
            firmware_version="1.0.0",
            state=DeviceState.ONLINE,
        )

        registered = self.registry.register_device(device)

        self.registry.update_firmware(registered.device_id, "1.1.0", "https://example.com/fw.bin")

        updated = self.registry.get_device(registered.device_id)
        assert updated.firmware_version == "1.1.0"

    def test_firmware_update_offline_device(self):
        """Test firmware update on offline device fails."""
        device = Device(
            name="Device",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.WIFI,
            mac_address="00:11:22:33:44:55",
            state=DeviceState.OFFLINE,
        )

        registered = self.registry.register_device(device)

        with pytest.raises(DeviceOfflineError):
            self.registry.update_firmware(registered.device_id, "1.1.0", "https://example.com/fw.bin")

    def test_device_groups(self):
        """Test device grouping."""
        device1 = Device(
            name="Light 1",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:55",
        )
        device2 = Device(
            name="Light 2",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:66",
        )

        reg1 = self.registry.register_device(device1)
        reg2 = self.registry.register_device(device2)

        # Add to group
        self.registry.add_device_to_group(reg1.device_id, "living_room_lights")
        self.registry.add_device_to_group(reg2.device_id, "living_room_lights")

        # Get group
        group = self.registry.get_devices_in_group("living_room_lights")
        assert len(group) == 2

    def test_command_routing(self):
        """Test device command routing."""
        device = Device(
            name="Light",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:55",
            capabilities=[
                DeviceCapability(name="on_off", settable=True),
                DeviceCapability(name="brightness", min_value=0, max_value=255),
            ],
        )

        registered = self.registry.register_device(device)

        # Route command
        result = self.registry.route_command(registered.device_id, "on_off", True)

        assert result["status"] == "ok"
        assert result["value"] is True

    def test_command_routing_invalid_capability(self):
        """Test command routing with invalid capability."""
        device = Device(
            name="Light",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:55",
            capabilities=[DeviceCapability(name="on_off")],
        )

        registered = self.registry.register_device(device)

        with pytest.raises(InvalidCapabilityError):
            self.registry.route_command(registered.device_id, "invalid_cap", True)

    def test_capability_distribution(self):
        """Test capability distribution reporting."""
        device1 = Device(
            name="Light 1",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:55",
            capabilities=[DeviceCapability(name="on_off"), DeviceCapability(name="brightness")],
        )
        device2 = Device(
            name="Light 2",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.ZIGBEE,
            mac_address="00:11:22:33:44:66",
            capabilities=[DeviceCapability(name="on_off")],
        )

        self.registry.register_device(device1)
        self.registry.register_device(device2)

        distribution = self.registry.get_capability_distribution()

        assert distribution["on_off"] == 2
        assert distribution["brightness"] == 1

    def test_offline_handler(self):
        """Test offline device callback."""
        device = Device(
            name="Device",
            device_type=DeviceType.LIGHT,
            room="Room",
            protocol=Protocol.WIFI,
            mac_address="00:11:22:33:44:55",
            state=DeviceState.ONLINE,
        )

        registered = self.registry.register_device(device)

        offline_devices = []

        def handle_offline(device_id):
            offline_devices.append(device_id)

        self.registry.register_offline_handler(handle_offline)

        # Trigger offline condition
        self.registry.get_device_health(registered.device_id)
        # Manually set last_heartbeat to trigger timeout
        self.registry._health[registered.device_id].last_heartbeat = datetime.now() - timedelta(seconds=700)

        self.registry.check_device_health(registered.device_id)

        assert registered.device_id in offline_devices
