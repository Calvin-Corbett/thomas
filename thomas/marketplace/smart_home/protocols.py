"""Protocol abstraction and bridging for multiple IoT protocols."""

import json
import struct
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from thomas.marketplace.smart_home._exceptions import (
    BridgeError,
    MessageRoutingError,
    ProtocolError,
    SerializationError,
)
from thomas.marketplace.smart_home._types import Protocol


@dataclass
class ProtocolMessage:
    """A protocol-level message."""

    protocol: Protocol
    """Target protocol."""
    source_device: str
    """Source device ID."""
    dest_device: str
    """Destination device ID."""
    command: str
    """Command name."""
    payload: dict[str, Any] = field(default_factory=dict)
    """Command payload."""
    message_id: str | None = None
    """Unique message ID."""
    timestamp: datetime = field(default_factory=datetime.now)
    """When message was created."""
    requires_ack: bool = False
    """Whether message requires acknowledgment."""


@dataclass
class ProtocolAcknowledgment:
    """Acknowledgment of received message."""

    message_id: str
    """ID of message being acknowledged."""
    status: str
    """Status: 'ok', 'error', 'timeout'."""
    timestamp: datetime = field(default_factory=datetime.now)
    """When ACK was sent."""
    error_detail: str | None = None
    """Error detail if status is error."""


@dataclass
class ZigbeeRoute:
    """A route in Zigbee mesh network."""

    dest_id: str
    """Destination device."""
    next_hop: str | None = None
    """Next hop device."""
    hop_count: int = 0
    """Number of hops."""
    link_quality: int = 100
    """Link quality 0-100."""


@dataclass
class NetworkNode:
    """A node in a protocol network."""

    node_id: str
    """Device ID."""
    protocol: Protocol
    """Protocol it uses."""
    parent_node: str | None = None
    """Parent in mesh/hierarchy."""
    children: list[str] = field(default_factory=list)
    """Child nodes."""
    last_seen: datetime = field(default_factory=datetime.now)
    """Last communication time."""


class ProtocolBridge:
    """Bridge between multiple IoT protocols.

    Provides protocol abstraction, message routing, serialization,
    and bridging between different protocols.
    """

    def __init__(self) -> None:
        """Initialize protocol bridge."""
        self._zigbee_routes: dict[str, list[ZigbeeRoute]] = {}
        self._zwave_network: dict[str, NetworkNode] = {}
        self._wifi_devices: set[str] = set()
        self._matter_devices: set[str] = set()
        self._pending_messages: dict[str, ProtocolMessage] = {}
        self._message_callbacks: dict[str, list] = {}
        self._route_callbacks: list = []

    def register_message_handler(self, protocol: Protocol, handler: Any) -> None:
        """Register handler for protocol messages.

        Args:
            protocol: Protocol to handle.
            handler: Handler callable.
        """
        key = f"handler_{protocol.value}"
        if key not in self._message_callbacks:
            self._message_callbacks[key] = []
        self._message_callbacks[key].append(handler)

    def send_message(self, message: ProtocolMessage) -> str:
        """Send a protocol message.

        Args:
            message: Message to send.

        Returns:
            Message ID.

        Raises:
            ProtocolError: If send fails.
        """
        if not message.message_id:
            message.message_id = self._generate_message_id()

        try:
            if message.protocol == Protocol.ZIGBEE:
                self._route_zigbee_message(message)
            elif message.protocol == Protocol.ZWAVE:
                self._send_zwave_message(message)
            elif message.protocol == Protocol.WIFI:
                self._send_wifi_message(message)
            elif message.protocol == Protocol.MATTER:
                self._send_matter_message(message)
            else:
                raise ProtocolError(f"Unknown protocol: {message.protocol}")

            if message.requires_ack:
                self._pending_messages[message.message_id] = message

            return message.message_id

        except Exception as e:
            raise ProtocolError(f"Message send failed: {e}")

    def _route_zigbee_message(self, message: ProtocolMessage) -> None:
        """Route a Zigbee message through mesh network.

        Args:
            message: Message to route.

        Raises:
            MessageRoutingError: If routing fails.
        """
        # Get route to destination
        route = self._get_zigbee_route(message.dest_device)
        if not route:
            raise MessageRoutingError(f"No route to {message.dest_device}")

        # Serialize with Zigbee framing
        frame = self._serialize_zigbee_frame(message)

        # Call handlers
        self._call_handlers(Protocol.ZIGBEE, message)

        # Notify route listeners
        for callback in self._route_callbacks:
            try:
                callback(message, route)
            except Exception:  # REVIEWED: broad catch
                pass

    def _get_zigbee_route(self, dest_id: str) -> ZigbeeRoute | None:
        """Find or create route to Zigbee device.

        Args:
            dest_id: Destination device ID.

        Returns:
            Route if found/created, None if unreachable.
        """
        if dest_id in self._zigbee_routes:
            routes = self._zigbee_routes[dest_id]
            if routes:
                return routes[0]  # Best route

        # Create direct route if device exists
        route = ZigbeeRoute(dest_id=dest_id, next_hop=dest_id)
        if dest_id not in self._zigbee_routes:
            self._zigbee_routes[dest_id] = []
        self._zigbee_routes[dest_id].append(route)
        return route

    def _serialize_zigbee_frame(self, message: ProtocolMessage) -> bytes:
        """Serialize message to Zigbee frame format.

        Args:
            message: Message to serialize.

        Returns:
            Serialized frame bytes.

        Raises:
            SerializationError: If serialization fails.
        """
        try:
            # Zigbee frame format:
            # [frame_type:1][msg_id:2][src:2][dst:2][cmd_id:1][payload:var]
            frame = bytearray()
            frame.append(0x01)  # Frame type

            # Message ID (2 bytes)
            msg_id = int(message.message_id or "0") & 0xFFFF
            frame.extend(struct.pack(">H", msg_id))

            # Source and dest (simplified)
            src_id = int(message.source_device[:8], 16) & 0xFFFF
            dst_id = int(message.dest_device[:8], 16) & 0xFFFF
            frame.extend(struct.pack(">HH", src_id, dst_id))

            # Command ID
            frame.append(ord(message.command[0]) if message.command else 0)

            # Payload
            payload_json = json.dumps(message.payload).encode()
            frame.extend(payload_json)

            return bytes(frame)

        except Exception as e:
            raise SerializationError(f"Zigbee serialization failed: {e}")

    def _send_zwave_message(self, message: ProtocolMessage) -> None:
        """Send a Z-Wave message.

        Args:
            message: Message to send.
        """
        # Ensure node exists in network
        if message.dest_device not in self._zwave_network:
            node = NetworkNode(node_id=message.dest_device, protocol=Protocol.ZWAVE)
            self._zwave_network[message.dest_device] = node

        self._call_handlers(Protocol.ZWAVE, message)

    def _send_wifi_message(self, message: ProtocolMessage) -> None:
        """Send a WiFi message (simulated HTTP).

        Args:
            message: Message to send.
        """
        self._wifi_devices.add(message.dest_device)
        self._call_handlers(Protocol.WIFI, message)

    def _send_matter_message(self, message: ProtocolMessage) -> None:
        """Send a Matter protocol message.

        Args:
            message: Message to send.
        """
        self._matter_devices.add(message.dest_device)
        self._call_handlers(Protocol.MATTER, message)

    def _call_handlers(self, protocol: Protocol, message: ProtocolMessage) -> None:
        """Call registered handlers for protocol.

        Args:
            protocol: Protocol of message.
            message: Message being handled.
        """
        key = f"handler_{protocol.value}"
        for handler in self._message_callbacks.get(key, []):
            try:
                handler(message)
            except Exception:  # REVIEWED: broad catch
                pass

    def receive_acknowledgment(self, ack: ProtocolAcknowledgment) -> None:
        """Receive an acknowledgment for a message.

        Args:
            ack: Acknowledgment to process.
        """
        if ack.message_id in self._pending_messages:
            del self._pending_messages[ack.message_id]

    def bridge_protocols(
        self, source_protocol: Protocol, dest_protocol: Protocol, message: ProtocolMessage
    ) -> ProtocolMessage:
        """Bridge a message from one protocol to another.

        Args:
            source_protocol: Source protocol.
            dest_protocol: Destination protocol.
            message: Message to bridge.

        Returns:
            Bridged message.

        Raises:
            BridgeError: If bridging fails.
        """
        try:
            # Convert message format
            new_message = ProtocolMessage(
                protocol=dest_protocol,
                source_device=message.source_device,
                dest_device=message.dest_device,
                command=message.command,
                payload=message.payload.copy(),
                requires_ack=message.requires_ack,
            )
            return new_message
        except Exception as e:
            raise BridgeError(f"Protocol bridge failed: {e}")

    def add_zigbee_route(self, dest_id: str, next_hop: str, hop_count: int, link_quality: int) -> None:
        """Add or update Zigbee route.

        Args:
            dest_id: Destination device.
            next_hop: Next hop device.
            hop_count: Number of hops.
            link_quality: Link quality 0-100.
        """
        route = ZigbeeRoute(dest_id=dest_id, next_hop=next_hop, hop_count=hop_count, link_quality=link_quality)
        if dest_id not in self._zigbee_routes:
            self._zigbee_routes[dest_id] = []
        self._zigbee_routes[dest_id].insert(0, route)
        # Keep best 3 routes
        self._zigbee_routes[dest_id] = self._zigbee_routes[dest_id][:3]

    def get_zigbee_routes(self, dest_id: str) -> list[ZigbeeRoute]:
        """Get all routes to a device.

        Args:
            dest_id: Destination device.

        Returns:
            List of routes.
        """
        return self._zigbee_routes.get(dest_id, [])

    def add_zwave_node(self, node: NetworkNode) -> None:
        """Add a node to Z-Wave network.

        Args:
            node: Node to add.
        """
        self._zwave_network[node.node_id] = node

    def get_zwave_network(self) -> dict[str, NetworkNode]:
        """Get Z-Wave network topology.

        Returns:
            Dictionary of nodes.
        """
        return self._zwave_network.copy()

    def discover_wifi_devices(self) -> list[str]:
        """Discover WiFi devices (simulated mDNS/SSDP).

        Returns:
            List of discovered device IDs.
        """
        return list(self._wifi_devices)

    def get_matter_devices(self) -> list[str]:
        """Get registered Matter devices.

        Returns:
            List of device IDs.
        """
        return list(self._matter_devices)

    def serialize_message(self, message: ProtocolMessage) -> bytes:
        """Serialize message for transmission.

        Args:
            message: Message to serialize.

        Returns:
            Serialized message.

        Raises:
            SerializationError: If serialization fails.
        """
        try:
            if message.protocol == Protocol.ZIGBEE:
                return self._serialize_zigbee_frame(message)
            elif message.protocol == Protocol.ZWAVE:
                return json.dumps(
                    {
                        "src": message.source_device,
                        "dst": message.dest_device,
                        "cmd": message.command,
                        "payload": message.payload,
                    }
                ).encode()
            elif message.protocol == Protocol.WIFI:
                return json.dumps({"command": message.command, "payload": message.payload}).encode()
            elif message.protocol == Protocol.MATTER:
                return json.dumps(message.payload).encode()
            else:
                raise SerializationError("Unknown protocol")
        except Exception as e:
            raise SerializationError(f"Serialization failed: {e}")

    def deserialize_message(self, protocol: Protocol, data: bytes) -> dict[str, Any]:
        """Deserialize incoming message.

        Args:
            protocol: Protocol of message.
            data: Serialized message data.

        Returns:
            Deserialized message dict.

        Raises:
            SerializationError: If deserialization fails.
        """
        try:
            if protocol in (Protocol.ZWAVE, Protocol.WIFI, Protocol.MATTER):
                return json.loads(data.decode())
            elif protocol == Protocol.ZIGBEE:
                # Parse Zigbee frame
                if len(data) < 6:
                    raise SerializationError("Frame too short")
                frame_type = data[0]
                msg_id = struct.unpack(">H", data[1:3])[0]
                src_id, dst_id = struct.unpack(">HH", data[3:7])
                cmd_id = data[7] if len(data) > 7 else 0
                payload = data[8:] if len(data) > 8 else b""
                return {
                    "frame_type": frame_type,
                    "message_id": msg_id,
                    "source": src_id,
                    "destination": dst_id,
                    "command": cmd_id,
                    "payload": payload,
                }
            else:
                raise SerializationError("Unknown protocol")
        except Exception as e:
            raise SerializationError(f"Deserialization failed: {e}")

    def _generate_message_id(self) -> str:
        """Generate a unique message ID.

        Returns:
            Message ID.
        """
        import uuid

        return str(uuid.uuid4())[:8]
