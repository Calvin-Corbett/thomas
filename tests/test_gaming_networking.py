"""Tests for networking system."""

import pytest

from thomas.marketplace.gaming_platform._exceptions import NetworkingError
from thomas.marketplace.gaming_platform.networking import (
    ClientConnection,
    ClientState,
    EntitySnapshot,
    MessageType,
    NetworkManager,
    NetworkMessage,
    NetworkStats,
)


class TestNetworkMessage:
    """Test network message serialization."""

    def test_message_creation(self) -> None:
        """Test creating network message."""
        message = NetworkMessage(
            message_type=MessageType.HELLO,
            sequence_number=1,
            sender_id=100,
            timestamp=0.0,
        )

        assert message.message_type == MessageType.HELLO
        assert message.sequence_number == 1

    def test_message_serialization(self) -> None:
        """Test message serialization."""
        message = NetworkMessage(
            message_type=MessageType.PING,
            sequence_number=5,
            sender_id=42,
            timestamp=1.0,
            data=b"test",
        )

        serialized = message.serialize()
        assert len(serialized) >= 16

    def test_message_deserialization(self) -> None:
        """Test message deserialization."""
        original = NetworkMessage(
            message_type=MessageType.PONG,
            sequence_number=10,
            sender_id=50,
            timestamp=2.0,
            data=b"response",
        )

        serialized = original.serialize()
        deserialized = NetworkMessage.deserialize(serialized)

        assert deserialized.message_type == MessageType.PONG
        assert deserialized.sequence_number == 10
        assert deserialized.sender_id == 50

    def test_invalid_message_size(self) -> None:
        """Test deserializing invalid message."""
        with pytest.raises(NetworkingError):
            NetworkMessage.deserialize(b"short")


class TestEntitySnapshot:
    """Test entity snapshot serialization."""

    def test_snapshot_creation(self) -> None:
        """Test creating entity snapshot."""
        snapshot = EntitySnapshot(
            entity_id=1,
            position=(10.0, 20.0),
            rotation=45.0,
            velocity=(5.0, 0.0),
            timestamp=1.0,
        )

        assert snapshot.entity_id == 1
        assert snapshot.position == (10.0, 20.0)

    def test_snapshot_serialization(self) -> None:
        """Test snapshot serialization."""
        snapshot = EntitySnapshot(
            entity_id=5,
            position=(100.0, 200.0),
            rotation=90.0,
            velocity=(10.0, -5.0),
            timestamp=5.5,
        )

        data = snapshot.serialize()
        assert len(data) >= 36

    def test_snapshot_deserialization(self) -> None:
        """Test snapshot deserialization."""
        original = EntitySnapshot(
            entity_id=3,
            position=(50.0, 75.0),
            rotation=30.0,
            velocity=(2.0, 3.0),
            timestamp=2.5,
        )

        data = original.serialize()
        restored = EntitySnapshot.deserialize(data)

        assert restored.entity_id == 3
        assert restored.position[0] == pytest.approx(50.0)
        assert restored.position[1] == pytest.approx(75.0)


class TestNetworkManager:
    """Test network manager."""

    def test_server_creation(self) -> None:
        """Test creating server instance."""
        manager = NetworkManager(is_server=True)
        assert manager.is_server is True
        assert not manager.connected

    def test_client_creation(self) -> None:
        """Test creating client instance."""
        manager = NetworkManager(is_server=False)
        assert manager.is_server is False
        assert not manager.connected

    def test_client_connect(self) -> None:
        """Test client connection."""
        client = NetworkManager(is_server=False)
        client.connect("localhost:5000")

        assert client.connected
        assert client.server_address == "localhost:5000"

    def test_client_cannot_connect_twice(self) -> None:
        """Test client cannot connect twice."""
        client = NetworkManager(is_server=False)
        client.connect("localhost:5000")

        with pytest.raises(NetworkingError):
            client.connect("localhost:5001")

    def test_server_cannot_connect(self) -> None:
        """Test server cannot call connect."""
        server = NetworkManager(is_server=True)

        with pytest.raises(NetworkingError):
            server.connect("localhost:5000")

    def test_client_disconnect(self) -> None:
        """Test client disconnection."""
        client = NetworkManager(is_server=False)
        client.connect("localhost:5000")
        client.disconnect()

        assert not client.connected

    def test_accept_client(self) -> None:
        """Test server accepting client."""
        server = NetworkManager(is_server=True)
        client_id = server.accept_client("192.168.1.100:12345")

        assert client_id > 0
        assert client_id in server.clients

    def test_multiple_clients(self) -> None:
        """Test server with multiple clients."""
        server = NetworkManager(is_server=True)

        ids = []
        for i in range(5):
            client_id = server.accept_client(f"192.168.1.{100 + i}:12345")
            ids.append(client_id)

        assert len(ids) == 5
        assert len(set(ids)) == 5  # All unique

    def test_send_message(self) -> None:
        """Test sending message."""
        manager = NetworkManager()
        message = NetworkMessage(message_type=MessageType.PING)

        manager.send_message(message)
        assert manager.stats.messages_sent == 1

    def test_receive_message(self) -> None:
        """Test receiving message."""
        manager = NetworkManager()
        original = NetworkMessage(
            message_type=MessageType.STATE_SNAPSHOT,
            sequence_number=1,
        )

        data = original.serialize()
        received = manager.receive_message(data)

        assert received is not None
        assert received.message_type == MessageType.STATE_SNAPSHOT
        assert manager.stats.messages_received == 1

    def test_send_player_input(self) -> None:
        """Test sending player input."""
        client = NetworkManager(is_server=False)
        client.connected = True

        inputs = {"jump": True, "move_x": 0.5}
        client.send_input(1, inputs)

        assert len(client.input_buffer) == 1

    def test_entity_update(self) -> None:
        """Test sending entity updates."""
        server = NetworkManager(is_server=True)

        snapshot = EntitySnapshot(
            entity_id=1,
            position=(100.0, 200.0),
            velocity=(5.0, 0.0),
        )

        server.send_entity_update(1, snapshot)
        assert len(server.snapshot_buffer) == 1

    def test_interpolation(self) -> None:
        """Test snapshot interpolation."""
        import time

        manager = NetworkManager()

        # Add two snapshots
        t0 = time.time()
        snapshot1 = EntitySnapshot(
            entity_id=1,
            position=(0.0, 0.0),
            timestamp=t0,
        )

        snapshot2 = EntitySnapshot(
            entity_id=1,
            position=(100.0, 0.0),
            timestamp=t0 + 1.0,
        )

        manager.snapshot_buffer = [snapshot1, snapshot2]

        # Interpolate at midpoint
        # This is a simplified test
        position = manager.get_interpolated_position(1)
        assert position is not None

    def test_client_prediction(self) -> None:
        """Test client-side prediction."""
        client = NetworkManager()

        client.apply_client_prediction(1, velocity=(10.0, 0.0), dt=0.016)
        predicted = client.predicted_state.get(1)

        assert predicted is not None
        assert predicted[0] > 0.0

    def test_state_reconciliation(self) -> None:
        """Test client prediction reconciliation."""
        client = NetworkManager()

        client.predicted_state[1] = (50.0, 50.0)
        server_position = (48.0, 50.0)

        client.reconcile_state(1, server_position)
        assert client.predicted_state[1] == server_position

    def test_lobby_creation(self) -> None:
        """Test creating lobby."""
        server = NetworkManager(is_server=True)
        lobby_id = server.create_lobby("game_session", max_players=4)

        assert lobby_id > 0

    def test_lobby_join(self) -> None:
        """Test joining lobby."""
        server = NetworkManager(is_server=True)
        lobby_id = server.create_lobby("session", max_players=4)

        result = server.join_lobby(lobby_id, player_id=1)
        assert result is True

    def test_network_stats(self) -> None:
        """Test network statistics."""
        manager = NetworkManager()

        stats = manager.get_network_stats()
        assert "ping" in stats
        assert "messages_sent" in stats
        assert "messages_received" in stats


class TestNetworkStats:
    """Test network statistics."""

    def test_stats_creation(self) -> None:
        """Test creating stats."""
        stats = NetworkStats()
        assert stats.ping == 0.0
        assert stats.messages_sent == 0

    def test_ping_averaging(self) -> None:
        """Test ping exponential moving average."""
        stats = NetworkStats()

        stats.update_ping(100.0)
        first_ping = stats.ping

        stats.update_ping(80.0)
        second_ping = stats.ping

        assert first_ping != second_ping


class TestClientConnection:
    """Test client connection."""

    def test_connection_creation(self) -> None:
        """Test creating client connection."""
        conn = ClientConnection(client_id=1, address="192.168.1.100:12345")

        assert conn.client_id == 1
        assert conn.address == "192.168.1.100:12345"
        assert conn.state == ClientState.CONNECTING

    def test_connection_stats(self) -> None:
        """Test client connection stats."""
        conn = ClientConnection(1, "127.0.0.1:5000")

        conn.stats.update_ping(50.0)
        assert conn.stats.ping > 0.0
