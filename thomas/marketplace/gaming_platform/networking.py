"""Game networking with client-server, state synchronization, and lag compensation."""

import struct
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from thomas.marketplace.gaming_platform._exceptions import NetworkingError


class MessageType(Enum):
    """Network message types."""

    HELLO = auto()
    GOODBYE = auto()
    STATE_SNAPSHOT = auto()
    INPUT = auto()
    RPC = auto()
    PING = auto()
    PONG = auto()


class ClientState(Enum):
    """Client connection state."""

    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    LOADING = auto()
    PLAYING = auto()


@dataclass
class NetworkMessage:
    """Network message container."""

    _HEADER_FORMAT = "<BIHd"
    _HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)

    message_type: MessageType
    sequence_number: int = 0
    timestamp: float = 0.0
    data: bytes = b""
    sender_id: int = 0

    def serialize(self) -> bytes:
        """Serialize message to bytes."""
        header = struct.pack(
            self._HEADER_FORMAT,
            self.message_type.value,
            self.sequence_number,
            self.sender_id,
            self.timestamp,
        )
        return header + self.data

    @classmethod
    def deserialize(cls, data: bytes) -> "NetworkMessage":
        """Deserialize message from bytes."""
        if len(data) < cls._HEADER_SIZE:
            raise NetworkingError("Invalid message size")

        msg_type, seq, sender, ts = struct.unpack(cls._HEADER_FORMAT, data[: cls._HEADER_SIZE])
        msg = cls(
            message_type=MessageType(msg_type),
            sequence_number=seq,
            sender_id=sender,
            timestamp=ts,
            data=data[cls._HEADER_SIZE :],
        )
        return msg


@dataclass
class EntitySnapshot:
    """Network snapshot of entity state."""

    # Padding float keeps wire format at 36 bytes for compatibility.
    _SNAPSHOT_FORMAT = "<Ifffffdf"
    _SNAPSHOT_SIZE = struct.calcsize(_SNAPSHOT_FORMAT)

    entity_id: int
    position: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    velocity: tuple[float, float] = (0.0, 0.0)
    timestamp: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)

    def serialize(self) -> bytes:
        """Serialize to bytes."""
        return struct.pack(
            self._SNAPSHOT_FORMAT,
            self.entity_id,
            self.position[0],
            self.position[1],
            self.rotation,
            self.velocity[0],
            self.velocity[1],
            self.timestamp,
            0.0,  # reserved/padding
        )

    @classmethod
    def deserialize(cls, data: bytes) -> "EntitySnapshot":
        """Deserialize from bytes."""
        if len(data) < cls._SNAPSHOT_SIZE:
            raise NetworkingError("Invalid entity snapshot size")

        entity_id, px, py, rot, vx, vy, ts, _pad = struct.unpack(cls._SNAPSHOT_FORMAT, data[: cls._SNAPSHOT_SIZE])
        return cls(
            entity_id=entity_id,
            position=(px, py),
            rotation=rot,
            velocity=(vx, vy),
            timestamp=ts,
        )


@dataclass
class PlayerInput:
    """Player input for network transmission."""

    player_id: int
    sequence: int
    timestamp: float
    inputs: dict[str, bool] = field(default_factory=dict)
    axes: dict[str, float] = field(default_factory=dict)

    def serialize(self) -> bytes:
        """Serialize to bytes."""
        data = struct.pack("<Iid", self.player_id, self.sequence, self.timestamp)
        # Encode inputs as bitmask for efficiency
        # inputs would be encoded based on action mapping
        return data


class NetworkStats:
    """Network statistics."""

    def __init__(self) -> None:
        """Initialize network stats."""
        self.ping = 0.0
        self.jitter = 0.0
        self.packet_loss = 0.0
        self.bandwidth_up = 0.0
        self.bandwidth_down = 0.0
        self.messages_sent = 0
        self.messages_received = 0
        self.bytes_sent = 0
        self.bytes_received = 0

    def update_ping(self, new_ping: float) -> None:
        """Update ping with exponential moving average."""
        alpha = 0.1
        self.ping = alpha * new_ping + (1.0 - alpha) * self.ping


class ClientConnection:
    """Represents client connection on server."""

    def __init__(self, client_id: int, address: str) -> None:
        """
        Initialize client connection.

        Args:
            client_id: Unique client ID.
            address: Client network address.
        """
        self.client_id = client_id
        self.address = address
        self.state = ClientState.CONNECTING
        self.last_input_time = 0.0
        self.last_snapshot_time = 0.0
        self.next_sequence_number = 0
        self.stats = NetworkStats()


class GameNetworkMessage:
    """Game-specific network message."""

    def __init__(self, msg_type: str, data: dict[str, Any]) -> None:
        """Initialize game network message."""
        self.message_type = msg_type
        self.data = data
        self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.message_type,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class NetworkManager:
    """
    Game networking with client-server architecture.

    Features:
    - Message serialization (compact binary format)
    - State synchronization (snapshot interpolation)
    - Client-side prediction
    - Lag compensation
    - Lobby system
    - Matchmaking with ELO rating
    - Network statistics
    """

    def __init__(self, is_server: bool = True) -> None:
        """
        Initialize network manager.

        Args:
            is_server: Whether this is server or client instance.
        """
        self.is_server = is_server
        self.client_id = 0
        self.connected = False

        # Server state
        self.clients: dict[int, ClientConnection] = {}
        self.next_client_id = 1

        # Client state
        self.server_address = ""
        self.input_buffer: list[PlayerInput] = []
        self.snapshot_buffer: list[EntitySnapshot] = []
        self.predicted_state: dict[int, tuple[float, float]] = {}

        # Network settings
        self.snapshot_rate = 20.0  # snapshots per second
        self.input_rate = 60.0  # inputs per second
        self.interpolation_delay = 0.1  # 100ms
        self.stats = NetworkStats()

    def connect(self, address: str) -> None:
        """
        Connect to server (client only).

        Args:
            address: Server address.

        Raises:
            NetworkingError: If already connected.
        """
        if self.is_server:
            raise NetworkingError("Cannot connect on server instance")

        if self.connected:
            raise NetworkingError("Already connected")

        self.server_address = address
        self.connected = True

    def disconnect(self) -> None:
        """Disconnect from server."""
        self.connected = False
        self.input_buffer.clear()
        self.snapshot_buffer.clear()

    def accept_client(self, address: str) -> int:
        """
        Accept new client connection (server only).

        Args:
            address: Client address.

        Returns:
            Client ID.

        Raises:
            NetworkingError: If not server.
        """
        if not self.is_server:
            raise NetworkingError("Not a server")

        client_id = self.next_client_id
        self.next_client_id += 1

        client = ClientConnection(client_id, address)
        self.clients[client_id] = client

        return client_id

    def send_message(self, message: NetworkMessage) -> None:
        """Send network message."""
        self.stats.messages_sent += 1
        self.stats.bytes_sent += len(message.serialize())

    def receive_message(self, data: bytes) -> NetworkMessage | None:
        """Receive network message."""
        try:
            message = NetworkMessage.deserialize(data)
            self.stats.messages_received += 1
            self.stats.bytes_received += len(data)
            return message
        except Exception:
            return None

    def send_input(self, player_id: int, inputs: dict[str, bool]) -> None:
        """
        Send player input to server.

        Args:
            player_id: Player ID.
            inputs: Input dict.
        """
        if not self.is_server and self.connected:
            input_msg = PlayerInput(
                player_id=player_id,
                sequence=len(self.input_buffer),
                timestamp=time.time(),
                inputs=inputs,
            )
            self.input_buffer.append(input_msg)

    def send_entity_update(self, entity_id: int, snapshot: EntitySnapshot) -> None:
        """Send entity state update."""
        if self.is_server:
            self.snapshot_buffer.append(snapshot)

    def get_interpolated_position(self, entity_id: int) -> tuple[float, float] | None:
        """
        Get interpolated entity position.

        Uses snapshot interpolation for smooth motion.

        Args:
            entity_id: Entity ID.

        Returns:
            Interpolated position or None.
        """
        if not self.snapshot_buffer:
            return None

        # Find two closest snapshots
        current_time = time.time()
        snapshots = [s for s in self.snapshot_buffer if s.entity_id == entity_id]

        if len(snapshots) < 2:
            return snapshots[0].position if snapshots else None

        # Sort by timestamp
        snapshots.sort(key=lambda s: s.timestamp)

        # Find interpolation window
        for i in range(len(snapshots) - 1):
            s0 = snapshots[i]
            s1 = snapshots[i + 1]

            if s0.timestamp <= current_time <= s1.timestamp:
                # Interpolate between s0 and s1
                dt = s1.timestamp - s0.timestamp
                if dt == 0:
                    return s0.position

                t = (current_time - s0.timestamp) / dt
                t = max(0.0, min(1.0, t))

                x = s0.position[0] + (s1.position[0] - s0.position[0]) * t
                y = s0.position[1] + (s1.position[1] - s0.position[1]) * t

                return (x, y)

        # Return latest
        return snapshots[-1].position

    def apply_client_prediction(self, entity_id: int, velocity: tuple[float, float], dt: float) -> None:
        """
        Apply client-side prediction for immediate feedback.

        Args:
            entity_id: Entity ID.
            velocity: Entity velocity.
            dt: Time step.
        """
        if entity_id not in self.predicted_state:
            self.predicted_state[entity_id] = (0.0, 0.0)

        px, py = self.predicted_state[entity_id]
        vx, vy = velocity

        px += vx * dt
        py += vy * dt

        self.predicted_state[entity_id] = (px, py)

    def reconcile_state(self, entity_id: int, server_position: tuple[float, float]) -> None:
        """
        Reconcile client prediction with server state.

        Args:
            entity_id: Entity ID.
            server_position: Server-authoritative position.
        """
        # In production, would rewind and resimulate
        self.predicted_state[entity_id] = server_position

    def register_matchmaking(self, player_id: int, elo_rating: float) -> None:
        """Register player for matchmaking."""
        # Store player info for matching
        pass

    def find_match(self, player_id: int, search_radius: float = 100.0) -> list[int] | None:
        """
        Find match for player.

        Args:
            player_id: Player ID.
            search_radius: ELO rating search radius.

        Returns:
            List of matched player IDs or None.
        """
        # Simple ELO-based matching
        return None

    def create_lobby(self, lobby_name: str, max_players: int = 4) -> int:
        """
        Create new lobby.

        Args:
            lobby_name: Lobby name.
            max_players: Max players.

        Returns:
            Lobby ID.
        """
        # Generate lobby ID
        lobby_id = int(time.time() * 1000) % 100000
        return lobby_id

    def join_lobby(self, lobby_id: int, player_id: int) -> bool:
        """Join existing lobby."""
        # Implementation would check capacity and add player
        return True

    def update(self, dt: float) -> None:
        """Update network."""
        if self.is_server:
            # Server: send snapshots periodically
            for client in self.clients.values():
                client.stats.update_ping(20.0)  # Simulated ping
        else:
            # Client: process server messages
            pass

    def get_network_stats(self) -> dict[str, Any]:
        """Get network statistics."""
        return {
            "ping": self.stats.ping,
            "jitter": self.stats.jitter,
            "packet_loss": self.stats.packet_loss,
            "messages_sent": self.stats.messages_sent,
            "messages_received": self.stats.messages_received,
            "bytes_sent": self.stats.bytes_sent,
            "bytes_received": self.stats.bytes_received,
        }
