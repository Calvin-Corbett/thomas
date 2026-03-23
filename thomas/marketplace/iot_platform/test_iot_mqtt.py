"""
Tests for MQTT broker module.

Tests topic subscriptions, message routing, QoS levels,
retained messages, and topic wildcards.
"""

from datetime import datetime
from uuid import uuid4

import pytest

from thomas.marketplace.iot_platform._exceptions import MQTTError
from thomas.marketplace.iot_platform._types import MQTTConfig
from thomas.marketplace.iot_platform.mqtt import MQTTBroker


class TestMQTTBroker:
    """Test MQTT broker functionality."""

    @pytest.fixture
    def config(self) -> MQTTConfig:
        """Create MQTT configuration."""
        return MQTTConfig(
            broker_host="localhost",
            broker_port=1883,
            client_id="test_client",
        )

    @pytest.fixture
    def broker(self, config: MQTTConfig) -> MQTTBroker:
        """Create an MQTT broker instance."""
        return MQTTBroker(config)

    def test_connect_client(self, broker: MQTTBroker) -> None:
        """Test client connection."""
        result = broker.connect("client_1")

        assert result is True
        assert "client_1" in broker.get_connected_clients()

    def test_connect_duplicate_client(self, broker: MQTTBroker) -> None:
        """Test connecting already connected client fails."""
        broker.connect("client_1")

        result = broker.connect("client_1")

        assert result is False

    def test_disconnect_client(self, broker: MQTTBroker) -> None:
        """Test client disconnection."""
        broker.connect("client_1")

        result = broker.disconnect("client_1")

        assert result is True
        assert "client_1" not in broker.get_connected_clients()

    def test_subscribe_to_topic(self, broker: MQTTBroker) -> None:
        """Test subscribing to topic."""
        broker.connect("client_1")

        received_messages = []

        def handler(topic: str, payload: str, qos: int) -> None:
            received_messages.append((topic, payload, qos))

        result = broker.subscribe(
            client_id="client_1",
            topic="devices/+/telemetry",
            handler=handler,
        )

        assert result is True

    def test_publish_message(self, broker: MQTTBroker) -> None:
        """Test publishing message."""
        count = broker.publish(
            topic="devices/sensor1/telemetry",
            payload="temp=22.5",
        )

        assert isinstance(count, int)

    def test_publish_empty_topic(self, broker: MQTTBroker) -> None:
        """Test publishing with empty topic fails."""
        with pytest.raises(MQTTError):
            broker.publish(
                topic="",
                payload="test",
            )

    def test_publish_invalid_qos(self, broker: MQTTBroker) -> None:
        """Test publishing with invalid QoS fails."""
        with pytest.raises(MQTTError):
            broker.publish(
                topic="test/topic",
                payload="test",
                qos=5,
            )

    def test_message_routing(self, broker: MQTTBroker) -> None:
        """Test message routing to subscribers."""
        broker.connect("client_1")

        received_messages = []

        def handler(topic: str, payload: str, qos: int) -> None:
            received_messages.append((topic, payload, qos))

        broker.subscribe(
            client_id="client_1",
            topic="devices/+/telemetry",
            handler=handler,
        )

        broker.publish(
            topic="devices/sensor1/telemetry",
            payload='{"temp": 22.5}',
        )

        assert len(received_messages) == 1
        assert received_messages[0][0] == "devices/sensor1/telemetry"

    def test_single_level_wildcard(self, broker: MQTTBroker) -> None:
        """Test single-level wildcard subscription."""
        broker.connect("client_1")

        messages = []

        def handler(topic: str, payload: str, qos: int) -> None:
            messages.append(topic)

        broker.subscribe(
            client_id="client_1",
            topic="devices/+/status",
            handler=handler,
        )

        broker.publish(topic="devices/sensor1/status", payload="online")
        broker.publish(topic="devices/sensor2/status", payload="offline")
        broker.publish(topic="devices/other/telemetry", payload="data")

        assert len(messages) == 2

    def test_multi_level_wildcard(self, broker: MQTTBroker) -> None:
        """Test multi-level wildcard subscription."""
        broker.connect("client_1")

        messages = []

        def handler(topic: str, payload: str, qos: int) -> None:
            messages.append(topic)

        broker.subscribe(
            client_id="client_1",
            topic="devices/#",
            handler=handler,
        )

        broker.publish(topic="devices/sensor1/telemetry", payload="data")
        broker.publish(topic="devices/sensor2/status", payload="online")
        broker.publish(topic="other/topic", payload="data")

        assert len(messages) == 2

    def test_retained_message(self, broker: MQTTBroker) -> None:
        """Test retained message storage."""
        broker.publish(
            topic="devices/sensor1/status",
            payload="online",
            retain=True,
        )

        retained = broker.get_retained_message("devices/sensor1/status")

        assert retained is not None
        assert retained[0] == "online"

    def test_clear_retained_message(self, broker: MQTTBroker) -> None:
        """Test clearing retained message."""
        broker.publish(
            topic="devices/sensor1/status",
            payload="online",
            retain=True,
        )

        result = broker.clear_retained_message("devices/sensor1/status")

        assert result is True

        retained = broker.get_retained_message("devices/sensor1/status")

        assert retained is None

    def test_publish_device_telemetry(self, broker: MQTTBroker) -> None:
        """Test publishing device telemetry."""
        device_id = uuid4()

        count = broker.publish_device_telemetry(
            device_id=device_id,
            metric="temperature",
            value=22.5,
            timestamp=datetime.utcnow(),
        )

        assert count >= 0

    def test_publish_device_status(self, broker: MQTTBroker) -> None:
        """Test publishing device status."""
        device_id = uuid4()

        count = broker.publish_device_status(
            device_id=device_id,
            status="online",
        )

        assert count >= 0

    def test_publish_command(self, broker: MQTTBroker) -> None:
        """Test publishing command."""
        device_id = uuid4()
        command_id = uuid4()

        count = broker.publish_command(
            device_id=device_id,
            command_id=command_id,
            action="set_temperature",
            parameters={"value": 25.0},
        )

        assert count >= 0

    def test_get_message_history(self, broker: MQTTBroker) -> None:
        """Test getting message history."""
        broker.publish(topic="devices/sensor1/telemetry", payload="data1")
        broker.publish(topic="devices/sensor1/status", payload="online")
        broker.publish(topic="devices/sensor2/telemetry", payload="data2")

        history = broker.get_message_history(limit=10)

        assert len(history) == 3

    def test_get_subscription_count(self, broker: MQTTBroker) -> None:
        """Test getting subscription count."""
        broker.connect("client_1")
        broker.connect("client_2")

        def handler(topic: str, payload: str, qos: int) -> None:
            pass

        broker.subscribe("client_1", "devices/+/telemetry", handler)
        broker.subscribe("client_2", "devices/+/status", handler)

        count = broker.get_subscription_count()

        assert count == 2

    def test_get_client_subscriptions(self, broker: MQTTBroker) -> None:
        """Test getting client subscriptions."""
        broker.connect("client_1")

        def handler(topic: str, payload: str, qos: int) -> None:
            pass

        broker.subscribe("client_1", "devices/+/telemetry", handler)
        broker.subscribe("client_1", "devices/+/status", handler)

        subs = broker.get_client_subscriptions("client_1")

        assert len(subs) == 2

    def test_set_last_will(self, broker: MQTTBroker) -> None:
        """Test setting Last Will and Testament."""
        broker.connect("client_1")

        result = broker.set_last_will(
            client_id="client_1",
            topic="devices/client1/status",
            message="offline",
        )

        assert result is True

    def test_parse_device_message(self, broker: MQTTBroker) -> None:
        """Test parsing device message."""
        payload = '{"metric": "temperature", "value": 22.5}'

        parsed = broker.parse_device_message(payload)

        assert parsed["metric"] == "temperature"
        assert parsed["value"] == 22.5

    def test_parse_invalid_message(self, broker: MQTTBroker) -> None:
        """Test parsing invalid message fails."""
        with pytest.raises(MQTTError):
            broker.parse_device_message("invalid json {")

    def test_qos_levels(self, broker: MQTTBroker) -> None:
        """Test QoS level handling."""
        for qos in [0, 1, 2]:
            count = broker.publish(
                topic="test/qos",
                payload=f"qos_{qos}",
                qos=qos,
            )
            assert isinstance(count, int)

    def test_subscription_not_connected(self, broker: MQTTBroker) -> None:
        """Test subscribing with unconnected client fails."""

        def handler(topic: str, payload: str, qos: int) -> None:
            pass

        with pytest.raises(MQTTError):
            broker.subscribe(
                client_id="unknown_client",
                topic="test/topic",
                handler=handler,
            )

    def test_message_history_with_filter(self, broker: MQTTBroker) -> None:
        """Test filtering message history."""
        broker.publish(topic="devices/sensor1/telemetry", payload="data1")
        broker.publish(topic="devices/sensor1/status", payload="online")
        broker.publish(topic="devices/sensor2/telemetry", payload="data2")

        history = broker.get_message_history(
            topic_filter="devices/sensor1/+",
            limit=10,
        )

        assert len(history) == 2
