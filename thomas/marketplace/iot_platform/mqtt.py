"""
MQTT protocol implementation for IoT messaging.

Provides topic structure, message parsing, QoS levels, retained
messages, subscriptions, and message routing.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from thomas.marketplace.iot_platform._exceptions import MQTTError
from thomas.marketplace.iot_platform._types import MQTTConfig


class MQTTBroker:
    """
    MQTT message broker simulator for IoT platform.

    Implements topic subscriptions, message routing, QoS levels,
    retained messages, and topic wildcards.
    """

    def __init__(self, config: MQTTConfig) -> None:
        """
        Initialize MQTT broker.

        Args:
            config: MQTT configuration.
        """
        self._config = config
        self._subscriptions: dict[str, list[Callable[[str, str, int], None]]] = {}
        self._retained_messages: dict[str, tuple[str, int, datetime]] = {}
        self._message_history: list[dict[str, Any]] = []
        self._connected_clients: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def connect(self, client_id: str) -> bool:
        """
        Connect a client to the broker.

        Args:
            client_id: MQTT client identifier.

        Returns:
            True if connection successful.
        """
        with self._lock:
            if client_id in self._connected_clients:
                return False

            self._connected_clients[client_id] = {
                "connected_at": datetime.utcnow(),
                "last_activity": datetime.utcnow(),
                "subscriptions": set(),
            }

            return True

    def disconnect(self, client_id: str) -> bool:
        """
        Disconnect a client from the broker.

        Args:
            client_id: MQTT client identifier.

        Returns:
            True if disconnection successful.
        """
        with self._lock:
            if client_id not in self._connected_clients:
                return False

            # Remove all client subscriptions
            client_subs = self._connected_clients[client_id]["subscriptions"]
            for topic in list(client_subs):
                self._unsubscribe(client_id, topic)

            del self._connected_clients[client_id]
            return True

    def subscribe(
        self,
        client_id: str,
        topic: str,
        handler: Callable[[str, str, int], None],
        qos: int = 1,
    ) -> bool:
        """
        Subscribe to a topic.

        Args:
            client_id: MQTT client ID.
            topic: Topic to subscribe to (supports +, # wildcards).
            handler: Callback function for messages.
            qos: Quality of Service level (0, 1, or 2).

        Returns:
            True if subscription successful.

        Raises:
            MQTTError: If QoS invalid or client not connected.
        """
        if qos not in (0, 1, 2):
            raise MQTTError(f"Invalid QoS: {qos}")

        with self._lock:
            if client_id not in self._connected_clients:
                raise MQTTError(f"Client {client_id} not connected")

            if topic not in self._subscriptions:
                self._subscriptions[topic] = []

            self._subscriptions[topic].append(handler)
            self._connected_clients[client_id]["subscriptions"].add(topic)

            return True

    def _unsubscribe(self, client_id: str, topic: str) -> None:
        """Internal unsubscribe (assumes lock held)."""
        if topic in self._subscriptions:
            self._subscriptions[topic] = [
                h for h in self._subscriptions[topic] if not self._is_same_handler(h, client_id)
            ]

            if not self._subscriptions[topic]:
                del self._subscriptions[topic]

    def _is_same_handler(self, handler: Callable, client_id: str) -> bool:
        """Check if handler belongs to client (heuristic)."""
        return hasattr(handler, "__self__") and (getattr(handler.__self__, "client_id", None) == client_id)

    def publish(
        self,
        topic: str,
        payload: str | bytes,
        qos: int = 1,
        retain: bool = False,
    ) -> int:
        """
        Publish message to topic.

        Args:
            topic: Topic to publish to.
            payload: Message payload.
            qos: Quality of Service level.
            retain: Whether to retain message.

        Returns:
            Number of subscribers that received message.

        Raises:
            MQTTError: If topic or QoS invalid.
        """
        if not topic or len(topic.strip()) == 0:
            raise MQTTError("Topic cannot be empty")

        if qos not in (0, 1, 2):
            raise MQTTError(f"Invalid QoS: {qos}")

        if isinstance(payload, bytes):
            payload_str = payload.decode("utf-8")
        else:
            payload_str = payload

        with self._lock:
            # Store retained message
            if retain:
                self._retained_messages[topic] = (payload_str, qos, datetime.utcnow())

            # Record in history
            self._message_history.append(
                {
                    "topic": topic,
                    "payload": payload_str,
                    "qos": qos,
                    "timestamp": datetime.utcnow(),
                }
            )

            # Route message to subscribers
            subscribers_count = self._route_message(topic, payload_str, qos)

            return subscribers_count

    def _route_message(self, topic: str, payload: str, qos: int) -> int:
        """Route message to matching subscriptions (assumes lock held)."""
        count = 0

        for sub_topic, handlers in self._subscriptions.items():
            if self._topic_matches(sub_topic, topic):
                for handler in handlers:
                    try:
                        handler(topic, payload, qos)
                        count += 1
                    except Exception:  # REVIEWED: broad catch
                        pass

        return count

    def _topic_matches(self, subscription: str, published: str) -> bool:
        """Check if published topic matches subscription pattern."""
        # Convert MQTT topic wildcards to regex
        if subscription == published:
            return True

        if "#" in subscription:
            # Multi-level wildcard
            parts = subscription.split("/#")
            if len(parts) == 2:
                prefix = parts[0]
                return published.startswith(prefix)

        # Single-level wildcard
        pattern = re.escape(subscription).replace(r"\+", "[^/]+")
        pattern = f"^{pattern}$"
        return bool(re.match(pattern, published))

    def publish_device_telemetry(
        self,
        device_id: UUID,
        metric: str,
        value: float | str | int,
        timestamp: datetime,
        qos: int = 1,
    ) -> int:
        """
        Publish device telemetry message.

        Args:
            device_id: Source device ID.
            metric: Metric name.
            value: Metric value.
            timestamp: Measurement timestamp.
            qos: QoS level.

        Returns:
            Number of subscribers.
        """
        topic = f"devices/{device_id}/telemetry"
        payload = json.dumps(
            {
                "metric": metric,
                "value": value,
                "timestamp": timestamp.isoformat(),
            }
        )

        return self.publish(topic, payload, qos)

    def publish_device_status(
        self,
        device_id: UUID,
        status: str,
        qos: int = 1,
    ) -> int:
        """
        Publish device status message.

        Args:
            device_id: Device ID.
            status: Device status.
            qos: QoS level.

        Returns:
            Number of subscribers.
        """
        topic = f"devices/{device_id}/status"
        payload = json.dumps(
            {
                "status": status,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        return self.publish(topic, payload, qos, retain=True)

    def publish_command(
        self,
        device_id: UUID,
        command_id: UUID,
        action: str,
        parameters: dict[str, Any],
        qos: int = 1,
    ) -> int:
        """
        Publish command to device.

        Args:
            device_id: Target device ID.
            command_id: Command ID.
            action: Command action.
            parameters: Command parameters.
            qos: QoS level.

        Returns:
            Number of subscribers.
        """
        topic = f"devices/{device_id}/commands"
        payload = json.dumps(
            {
                "command_id": str(command_id),
                "action": action,
                "parameters": parameters,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        return self.publish(topic, payload, qos)

    def get_retained_message(self, topic: str) -> tuple[str, int] | None:
        """
        Get retained message for topic.

        Args:
            topic: Topic to retrieve.

        Returns:
            Tuple of (payload, qos) or None if no retained message.
        """
        with self._lock:
            if topic in self._retained_messages:
                payload, qos, _ = self._retained_messages[topic]
                return (payload, qos)
            return None

    def clear_retained_message(self, topic: str) -> bool:
        """
        Clear retained message for topic.

        Args:
            topic: Topic to clear.

        Returns:
            True if message was cleared.
        """
        with self._lock:
            if topic in self._retained_messages:
                del self._retained_messages[topic]
                return True
            return False

    def get_message_history(
        self,
        topic_filter: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get message history.

        Args:
            topic_filter: Optional topic filter.
            limit: Maximum results.

        Returns:
            List of message history entries.
        """
        with self._lock:
            history = self._message_history

            if topic_filter:
                history = [m for m in history if self._topic_matches(topic_filter, m["topic"])]

            return history[-limit:]

    def get_subscription_count(self) -> int:
        """Get total number of subscriptions."""
        with self._lock:
            return sum(len(handlers) for handlers in self._subscriptions.values())

    def get_connected_clients(self) -> list[str]:
        """Get list of connected client IDs."""
        with self._lock:
            return list(self._connected_clients.keys())

    def get_client_subscriptions(self, client_id: str) -> list[str]:
        """
        Get subscriptions for a client.

        Args:
            client_id: Client ID.

        Returns:
            List of subscribed topics.
        """
        with self._lock:
            if client_id not in self._connected_clients:
                return []
            return list(self._connected_clients[client_id]["subscriptions"])

    def set_last_will(
        self,
        client_id: str,
        topic: str,
        message: str,
        qos: int = 1,
    ) -> bool:
        """
        Set Last Will and Testament for client.

        Args:
            client_id: Client ID.
            topic: Topic to publish to on disconnect.
            message: Message to publish.
            qos: QoS level.

        Returns:
            True if LWT set successfully.
        """
        with self._lock:
            if client_id not in self._connected_clients:
                return False

            self._connected_clients[client_id]["last_will"] = {
                "topic": topic,
                "message": message,
                "qos": qos,
            }

            return True

    def parse_device_message(self, payload: str) -> dict[str, Any]:
        """
        Parse device message payload.

        Args:
            payload: MQTT message payload.

        Returns:
            Parsed message dictionary.

        Raises:
            MQTTError: If payload invalid.
        """
        try:
            return json.loads(payload)
        except json.JSONDecodeError as e:
            raise MQTTError(f"Invalid message payload: {e}")
