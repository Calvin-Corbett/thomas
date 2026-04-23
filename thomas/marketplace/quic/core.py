"""QUIC protocol implementation with streams, connections, and congestion control.

Provides QUIC protocol handling, stream management, connection
lifecycle, and congestion control algorithms.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ConnectionState(Enum):
    """QUIC connection state."""

    IDLE = "idle"
    INITIAL = "initial"
    HANDSHAKE = "handshake"
    ESTABLISHED = "established"
    CLOSED = "closed"


class StreamState(Enum):
    """QUIC stream state."""

    IDLE = "idle"
    OPEN = "open"
    HALF_CLOSED_LOCAL = "half_closed_local"
    HALF_CLOSED_REMOTE = "half_closed_remote"
    CLOSED = "closed"


@dataclass
class StreamInfo:
    """QUIC stream information."""

    stream_id: int
    state: StreamState
    send_buffer: bytes = b""
    recv_buffer: bytes = b""
    created_at: datetime = field(default_factory=datetime.utcnow)
    bytes_sent: int = 0
    bytes_received: int = 0


@dataclass
class ConnectionInfo:
    """QUIC connection information."""

    connection_id: str
    state: ConnectionState
    local_addr: str
    remote_addr: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    streams: dict[int, StreamInfo] = field(default_factory=dict)
    bytes_sent: int = 0
    bytes_received: int = 0
    rtt_ms: float = 100.0


class StreamManager:
    """Manage QUIC streams."""

    def __init__(self):
        self.streams: dict[int, StreamInfo] = {}
        self.next_stream_id = 0

    def create_stream(self) -> StreamInfo:
        """Create new stream."""
        stream_id = self.next_stream_id
        self.next_stream_id += 4  # Bidirectional streams increment by 4
        stream = StreamInfo(stream_id=stream_id, state=StreamState.OPEN)
        self.streams[stream_id] = stream
        return stream

    def get_stream(self, stream_id: int) -> StreamInfo | None:
        """Get stream by ID."""
        return self.streams.get(stream_id)

    def close_stream(self, stream_id: int) -> bool:
        """Close stream."""
        stream = self.streams.get(stream_id)
        if stream:
            stream.state = StreamState.CLOSED
            return True
        return False

    def send_on_stream(self, stream_id: int, data: bytes) -> bool:
        """Send data on stream."""
        stream = self.streams.get(stream_id)
        if stream:
            stream.send_buffer += data
            stream.bytes_sent += len(data)
            return True
        return False

    def receive_on_stream(self, stream_id: int, data: bytes) -> bool:
        """Receive data on stream."""
        stream = self.streams.get(stream_id)
        if stream:
            stream.recv_buffer += data
            stream.bytes_received += len(data)
            return True
        return False

    def get_stream_stats(self) -> dict[str, Any]:
        """Get stream statistics."""
        return {
            "total_streams": len(self.streams),
            "open_streams": sum(1 for s in self.streams.values() if s.state == StreamState.OPEN),
            "closed_streams": sum(1 for s in self.streams.values() if s.state == StreamState.CLOSED),
        }


class CongestionController:
    """QUIC congestion control."""

    def __init__(self, initial_cwnd: int = 10):
        self.cwnd = initial_cwnd  # Congestion window
        self.ssthresh = 65535  # Slow start threshold
        self.rtt_min = float("inf")
        self.rtt_samples: list[float] = []
        self.in_slow_start = True

    def on_packet_ack(self, rtt: float) -> None:
        """Handle packet acknowledgment."""
        self.rtt_samples.append(rtt)
        if len(self.rtt_samples) > 100:
            self.rtt_samples.pop(0)

        self.rtt_min = min(self.rtt_min, rtt)

        if self.in_slow_start:
            self.cwnd += 1
            if self.cwnd >= self.ssthresh:
                self.in_slow_start = False
        else:
            # Congestion avoidance
            self.cwnd += 1 / self.cwnd

    def on_packet_loss(self) -> None:
        """Handle packet loss."""
        self.ssthresh = max(self.cwnd // 2, 2)
        self.cwnd = self.ssthresh
        self.in_slow_start = False

    def get_cwnd(self) -> int:
        """Get current congestion window."""
        return int(self.cwnd)

    def get_avg_rtt(self) -> float:
        """Get average RTT."""
        if not self.rtt_samples:
            return 100.0
        return sum(self.rtt_samples) / len(self.rtt_samples)


class QUICConnection:
    """QUIC connection."""

    def __init__(self, connection_id: str, local_addr: str, remote_addr: str):
        self.info = ConnectionInfo(
            connection_id=connection_id, state=ConnectionState.IDLE, local_addr=local_addr, remote_addr=remote_addr
        )
        self.stream_manager = StreamManager()
        self.congestion_controller = CongestionController()
        self.packet_handlers: dict[str, any] = {}

    async def establish(self) -> bool:
        """Establish connection."""
        self.info.state = ConnectionState.HANDSHAKE
        await asyncio.sleep(0.1)  # Simulate handshake
        self.info.state = ConnectionState.ESTABLISHED
        return True

    async def send_data(self, stream_id: int, data: bytes) -> bool:
        """Send data on stream."""
        if self.info.state != ConnectionState.ESTABLISHED:
            return False
        return self.stream_manager.send_on_stream(stream_id, data)

    async def receive_data(self, stream_id: int) -> bytes | None:
        """Receive data from stream."""
        stream = self.stream_manager.get_stream(stream_id)
        if stream and stream.recv_buffer:
            data = stream.recv_buffer
            stream.recv_buffer = b""
            return data
        return None

    async def close(self) -> bool:
        """Close connection."""
        self.info.state = ConnectionState.CLOSED
        return True

    def get_connection_info(self) -> dict[str, Any]:
        """Get connection information."""
        return {
            "connection_id": self.info.connection_id,
            "state": self.info.state.value,
            "rtt_ms": self.info.rtt_ms,
            "bytes_sent": self.info.bytes_sent,
            "bytes_received": self.info.bytes_received,
            "streams": self.stream_manager.get_stream_stats(),
        }


class QUICEndpoint:
    """QUIC endpoint managing multiple connections."""

    def __init__(self):
        self.connections: dict[str, QUICConnection] = {}
        self.local_addr = "0.0.0.0:0"

    async def create_connection(self, connection_id: str, remote_addr: str) -> QUICConnection:
        """Create new connection."""
        conn = QUICConnection(connection_id, self.local_addr, remote_addr)
        self.connections[connection_id] = conn
        return conn

    def get_connection(self, connection_id: str) -> QUICConnection | None:
        """Get connection by ID."""
        return self.connections.get(connection_id)

    async def close_connection(self, connection_id: str) -> bool:
        """Close connection."""
        conn = self.connections.get(connection_id)
        if conn:
            await conn.close()
            del self.connections[connection_id]
            return True
        return False

    def get_endpoint_stats(self) -> dict[str, Any]:
        """Get endpoint statistics."""
        return {
            "total_connections": len(self.connections),
            "established": sum(1 for c in self.connections.values() if c.info.state == ConnectionState.ESTABLISHED),
            "local_addr": self.local_addr,
        }
