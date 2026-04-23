"""
Integration tests for the IoT platform.

Tests end-to-end workflows combining multiple components
like device registration, telemetry ingestion, rule evaluation,
command execution, and firmware updates.
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from thomas.marketplace.iot_platform._types import (
    DeviceStatus,
    DeviceType,
    MQTTConfig,
    TelemetryPoint,
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


class TestIoTPlatformIntegration:
    """Integration tests for complete IoT workflows."""

    @pytest.fixture
    def platform(self):
        """Create a complete IoT platform instance."""
        return {
            "registry": DeviceRegistry(),
            "telemetry": TelemetryEngine(),
            "rules": RulesEngine(),
            "commands": CommandManager(),
            "ota": OTAManager(),
            "mqtt": MQTTBroker(
                MQTTConfig(
                    broker_host="localhost",
                    broker_port=1883,
                )
            ),
            "twin": DigitalTwinManager(),
            "edge": EdgeNodeManager(),
            "dashboard": DashboardManager(),
        }

    def test_device_registration_and_provisioning(self, platform) -> None:
        """Test full device registration and provisioning workflow."""
        registry = platform["registry"]

        # Register device
        device = registry.register_device(
            name="Temperature Sensor",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        assert device.status == DeviceStatus.PROVISIONING
        assert device.provisioning_token is not None

        # Provision device
        provisioned = registry.provision_device(
            device.device_id,
            device.provisioning_token,
        )

        assert provisioned.status == DeviceStatus.ONLINE
        assert provisioned.provisioning_token is None

    def test_telemetry_ingestion_and_querying(self, platform) -> None:
        """Test telemetry collection and querying."""
        device = platform["registry"].register_device(
            name="Sensor",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        # Ingest telemetry
        telemetry = platform["telemetry"]

        for i in range(10):
            point = TelemetryPoint(
                device_id=device.device_id,
                metric="temperature",
                value=20.0 + i,
                timestamp=datetime.utcnow() - timedelta(minutes=10 - i),
            )
            telemetry.ingest_telemetry(point)

        # Query telemetry
        results = telemetry.query(device.device_id, metric="temperature")

        assert len(results) == 10

        # Get statistics
        stats = telemetry.get_statistics(device.device_id, "temperature")

        assert stats["count"] == 10.0
        assert stats["min"] == 20.0
        assert stats["max"] == 29.0

    def test_rule_evaluation_on_telemetry(self, platform) -> None:
        """Test rule evaluation triggered by telemetry."""
        device = platform["registry"].register_device(
            name="Sensor",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        # Create rule
        rules = platform["rules"]
        rule = rules.create_rule(
            name="High Temperature Alert",
            condition={
                "type": "threshold",
                "device_id": device.device_id,
                "metric": "temperature",
                "operator": ">",
                "value": 25.0,
            },
            actions=[
                {
                    "type": "alert",
                    "severity": "warning",
                    "message": "Temperature too high",
                }
            ],
        )

        # Ingest telemetry that triggers rule
        point = TelemetryPoint(
            device_id=device.device_id,
            metric="temperature",
            value=30.0,
            timestamp=datetime.utcnow(),
        )

        alerts = rules.evaluate_telemetry(point)

        assert len(alerts) == 1
        assert alerts[0].message == "Temperature too high"

    def test_mqtt_device_communication(self, platform) -> None:
        """Test MQTT communication between device and cloud."""
        device = platform["registry"].register_device(
            name="MQTT Device",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        mqtt = platform["mqtt"]

        # Device connects to MQTT
        mqtt.connect(str(device.device_id))

        # Device publishes telemetry
        mqtt.publish_device_telemetry(
            device_id=device.device_id,
            metric="temperature",
            value=22.5,
            timestamp=datetime.utcnow(),
        )

        # Cloud subscribes to telemetry
        messages = []

        def handler(topic: str, payload: str, qos: int) -> None:
            messages.append((topic, payload))

        mqtt.connect("cloud_client")
        mqtt.subscribe(
            client_id="cloud_client",
            topic=f"devices/{device.device_id}/telemetry",
            handler=handler,
        )

        mqtt.publish_device_telemetry(
            device_id=device.device_id,
            metric="temperature",
            value=25.0,
            timestamp=datetime.utcnow(),
        )

        assert len(messages) > 0

    def test_command_execution_workflow(self, platform) -> None:
        """Test complete command execution workflow."""
        device = platform["registry"].register_device(
            name="Controllable Device",
            device_type=DeviceType.ACTUATOR,
            firmware_version="1.0.0",
        )

        commands = platform["commands"]

        # Send command
        cmd = commands.send_command(
            target_device_id=device.device_id,
            action="set_parameter",
            parameters={"param": "value"},
        )

        assert cmd.status.value == "pending"

        # Device dequeues command
        queued = commands.dequeue_command(device.device_id)

        assert queued.command_id == cmd.command_id

        # Device executes and acknowledges
        commands.update_command_status(cmd.command_id, commands._commands[cmd.command_id].status.__class__.SENT)

        # Complete command
        commands.complete_command(
            cmd.command_id,
            result={"success": True, "new_value": "value"},
        )

        completed = commands.get_command(cmd.command_id)

        assert completed.status.value == "completed"

    def test_firmware_update_workflow(self, platform) -> None:
        """Test firmware update campaign."""
        # Register devices
        device1 = platform["registry"].register_device(
            name="Device 1",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )
        device2 = platform["registry"].register_device(
            name="Device 2",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        # Create update campaign
        ota = platform["ota"]
        update = ota.create_update(
            firmware_version="2.0.0",
            firmware_url="https://example.com/firmware-2.0.0.bin",
            checksum="a" * 64,
            file_size=1024000,
            rollout_strategy=platform["ota"].RolloutStrategy.IMMEDIATE,
        )

        # Start update
        started = ota.start_update(
            update.update_id,
            [device1.device_id, device2.device_id],
        )

        assert started.current_status.value == "in_progress"

        # Update device 1
        ota.update_device_status(
            update.update_id,
            device1.device_id,
            platform["ota"].UpdateStatus.COMPLETED,
        )

        # Update device 2
        ota.update_device_status(
            update.update_id,
            device2.device_id,
            platform["ota"].UpdateStatus.COMPLETED,
        )

        status = ota.get_rollout_status(update.update_id)

        assert status["completed"] == 2

    def test_digital_twin_state_sync(self, platform) -> None:
        """Test digital twin state synchronization."""
        device = platform["registry"].register_device(
            name="Twin Test Device",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        twin_manager = platform["twin"]

        # Create twin
        twin = twin_manager.create_twin(device.device_id)

        assert twin["device_id"] == device.device_id

        # Update twin from telemetry
        state_update = {
            "temperature": 22.5,
            "humidity": 65.0,
            "status": "active",
        }

        updated_twin = twin_manager.update_twin_state(
            device.device_id,
            state_update,
        )

        assert updated_twin["state"]["temperature"] == 22.5

        # Compare states
        comparison = twin_manager.compare_states(device.device_id)

        assert comparison["is_synchronized"] is True

    def test_edge_node_local_processing(self, platform) -> None:
        """Test edge node local data processing."""
        edge = platform["edge"]

        # Create edge node
        node = edge.create_edge_node(
            node_id="edge_1",
            location="Warehouse A",
            capacity_mb=100,
        )

        assert node["node_id"] == "edge_1"

        # Add local rule
        rule = edge.add_local_rule(
            "edge_1",
            {
                "condition": {
                    "type": "threshold",
                    "metric": "temperature",
                    "operator": ">",
                    "value": 30.0,
                },
                "actions": [{"type": "alert", "severity": "warning"}],
            },
        )

        assert rule["edge_node_id"] == "edge_1"

        # Connect node
        edge.connect_edge_node("edge_1")

        # Process telemetry locally
        device_id = uuid4()
        point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=35.0,
            timestamp=datetime.utcnow(),
        )

        actions = edge.process_telemetry_local("edge_1", point)

        assert len(actions) > 0

    def test_dashboard_creation_and_widgets(self, platform) -> None:
        """Test dashboard creation and widget management."""
        device = platform["registry"].register_device(
            name="Monitored Device",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        dashboard_mgr = platform["dashboard"]

        # Create dashboard
        dashboard = dashboard_mgr.create_dashboard(
            name="Main Dashboard",
            description="Main monitoring dashboard",
        )

        assert dashboard["name"] == "Main Dashboard"

        # Add gauge widget
        gauge = dashboard_mgr.create_gauge_widget(
            dashboard_id=dashboard["dashboard_id"],
            title="Temperature",
            device_id=device.device_id,
            metric="temperature",
            min_value=0,
            max_value=50,
        )

        assert gauge["type"] == "gauge"

        # Add chart widget
        chart = dashboard_mgr.create_chart_widget(
            dashboard_id=dashboard["dashboard_id"],
            title="Temperature Trend",
            device_id=device.device_id,
            metrics=["temperature", "humidity"],
        )

        assert chart["type"] == "chart"

        # Save as template
        template = dashboard_mgr.save_as_template(
            dashboard_id=dashboard["dashboard_id"],
            template_name="Sensor Dashboard",
            description="Template for sensor monitoring",
        )

        assert template["name"] == "Sensor Dashboard"

    def test_complete_monitoring_flow(self, platform) -> None:
        """Test complete monitoring flow from device to dashboard."""
        registry = platform["registry"]
        telemetry = platform["telemetry"]
        rules = platform["rules"]
        dashboard_mgr = platform["dashboard"]

        # Register device
        device = registry.register_device(
            name="Living Room Sensor",
            device_type=DeviceType.SENSOR,
            firmware_version="1.0.0",
        )

        registry.provision_device(device.device_id, device.provisioning_token)

        # Create monitoring rule
        rule = rules.create_rule(
            name="High Temperature Alert",
            condition={
                "type": "threshold",
                "device_id": device.device_id,
                "metric": "temperature",
                "operator": ">",
                "value": 28.0,
            },
            actions=[
                {
                    "type": "alert",
                    "severity": "warning",
                    "message": "Room temperature high",
                }
            ],
        )

        # Create dashboard
        dashboard = dashboard_mgr.create_dashboard(
            name="Home Monitoring",
            description="Home environment monitoring",
        )

        dashboard_mgr.create_gauge_widget(
            dashboard_id=dashboard["dashboard_id"],
            title="Living Room Temperature",
            device_id=device.device_id,
            metric="temperature",
        )

        # Simulate device sending telemetry
        temperatures = [18.0, 20.0, 22.0, 25.0, 29.0, 30.0]
        alerts_generated = 0

        for temp in temperatures:
            point = TelemetryPoint(
                device_id=device.device_id,
                metric="temperature",
                value=temp,
                timestamp=datetime.utcnow(),
            )

            telemetry.ingest_telemetry(point)
            alerts = rules.evaluate_telemetry(point)
            alerts_generated += len(alerts)

        # Verify results
        assert telemetry.get_data_point_count() == len(temperatures)
        assert alerts_generated == 2  # Last two values should trigger

        stats = telemetry.get_statistics(device.device_id, "temperature")

        assert stats["max"] == 30.0
        assert stats["min"] == 18.0

    def test_group_management_and_bulk_operations(self, platform) -> None:
        """Test device group management and bulk operations."""
        registry = platform["registry"]

        # Create device group
        group = registry.create_group(
            group_id="warehouse_a",
            name="Warehouse A",
            description="Devices in warehouse A",
        )

        # Register devices
        devices = []
        for i in range(3):
            device = registry.register_device(
                name=f"Sensor-{i}",
                device_type=DeviceType.SENSOR,
                firmware_version="1.0.0",
            )
            devices.append(device)
            registry.add_device_to_group(device.device_id, group.group_id)

        # Get group devices
        group_devices = registry.get_group_devices(group.group_id)

        assert len(group_devices) == 3

        # Bulk update
        updated = registry.bulk_update_devices(
            [d.device_id for d in devices],
            {"firmware_version": "1.1.0"},
        )

        assert all(d.firmware_version == "1.1.0" for d in updated)
