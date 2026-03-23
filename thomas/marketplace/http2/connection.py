"""HTTP/2 connection handler."""

import time

from thomas.marketplace.http2._exceptions import (
    ConnectionError,
    ProtocolError,
)
from thomas.marketplace.http2._types import ErrorCode, Frame, HTTP2Config, Settings
from thomas.marketplace.http2.flow_control import FlowControlEngine
from thomas.marketplace.http2.frames import FrameCodec
from thomas.marketplace.http2.hpack import HeaderDecoder, HeaderEncoder
from thomas.marketplace.http2.priority import PriorityTree
from thomas.marketplace.http2.server_push import ServerPushManager
from thomas.marketplace.http2.streams import Stream, StreamManager


class HTTP2Connection:
    """Manages an HTTP/2 connection."""

    # HTTP/2 connection preface
    CLIENT_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

    def __init__(self, config: HTTP2Config | None = None, is_server: bool = False) -> None:
        """Initialize HTTP/2 connection.

        Args:
            config: Connection configuration.
            is_server: Whether this is a server endpoint.
        """
        self.config = config or HTTP2Config()
        self.config.validate()

        self.is_server = is_server
        self.state = "idle"  # idle, preface, settings, open, goaway, closed

        # Frame codec
        self.frame_codec = FrameCodec(self.config.max_frame_size)

        # Header compression
        self.header_encoder = HeaderEncoder(self.config.header_table_size)
        self.header_decoder = HeaderDecoder(self.config.header_table_size)

        # Stream management
        self.stream_manager = StreamManager(self.config.max_concurrent_streams)

        # Flow control
        self.flow_control = FlowControlEngine(self.config.initial_window_size)

        # Priority tree
        self.priority_tree = PriorityTree()

        # Server push
        self.push_manager = ServerPushManager(self.stream_manager)

        # Settings negotiation
        self.local_settings = self.config.client_settings
        self.remote_settings = Settings()
        self.settings_acked = False
        self.remote_settings_acked = False

        # Connection state
        self.last_stream_id = 0
        self.goaway_sent = False
        self.goaway_received = False
        self.goaway_error_code = ErrorCode.NO_ERROR
        self.last_ping_time: float | None = None
        self.pending_window_updates: list[tuple[int, int]] = []

    def initiate(self) -> bytes:
        """Initiate connection (send preface and SETTINGS).

        Returns:
            Bytes to send to peer.
        """
        if self.state != "idle":
            raise ConnectionError("Connection already initiated")

        self.state = "preface"
        data = b""

        # Client sends connection preface
        if not self.is_server:
            data += self.CLIENT_PREFACE

        # Send SETTINGS frame
        settings_dict = self.local_settings.to_dict()
        data += self.frame_codec.encode_settings_frame(settings_dict)

        return data

    def receive_data(self, data: bytes) -> list[Frame]:
        """Process received data.

        Args:
            data: Received bytes.

        Returns:
            List of decoded frames.

        Raises:
            ProtocolError: If data is invalid.
            ConnectionError: If connection is closed.
        """
        if self.state == "closed":
            raise ConnectionError("Connection is closed")

        frames = []
        pos = 0

        while pos < len(data):
            try:
                frame, consumed = self.frame_codec.decode(data[pos:])
                frames.append(frame)
                pos += consumed
            except ProtocolError as e:
                # Send GOAWAY on protocol error
                self.send_goaway(ErrorCode.PROTOCOL_ERROR)
                raise ConnectionError(f"Protocol error: {e}")

        return frames

    def handle_settings_frame(self, settings: dict, ack: bool) -> None:
        """Handle received SETTINGS frame.

        Args:
            settings: Settings dictionary.
            ack: Whether this is an ACK.

        Raises:
            ConnectionError: If settings invalid.
        """
        if ack:
            self.remote_settings_acked = True
            return

        # Apply settings
        try:
            self.remote_settings = Settings.from_dict(settings)
        except Exception as e:
            raise ConnectionError(f"Invalid settings: {e}")

        # Transition to open state if both sides have sent SETTINGS
        if self.state == "preface" or self.state == "settings":
            if self.settings_acked and self.remote_settings_acked:
                self.state = "open"
            else:
                self.state = "settings"

    def handle_ping_frame(self, data: bytes, ack: bool) -> bytes:
        """Handle received PING frame.

        Args:
            data: PING data.
            ack: Whether this is PING ACK.

        Returns:
            PING ACK response to send.
        """
        if ack:
            # PING ACK received
            self.last_ping_time = time.time()
            return b""

        # Send PING ACK
        return self.frame_codec.encode_ping_frame(data, ack=True)

    def handle_goaway_frame(self, last_stream_id: int, error_code: ErrorCode, debug_data: bytes) -> None:
        """Handle received GOAWAY frame.

        Args:
            last_stream_id: Last stream ID processed.
            error_code: Error code.
            debug_data: Debug data.
        """
        self.goaway_received = True
        self.last_stream_id = last_stream_id
        self.goaway_error_code = error_code

        # Stop accepting new streams
        if self.state == "open":
            self.state = "goaway"

    def send_goaway(
        self,
        error_code: ErrorCode = ErrorCode.NO_ERROR,
        debug_data: bytes | None = None,
    ) -> bytes:
        """Send GOAWAY frame.

        Args:
            error_code: Error code.
            debug_data: Optional debug data.

        Returns:
            Encoded GOAWAY frame.
        """
        self.goaway_sent = True
        self.state = "closed"

        return self.frame_codec.encode_goaway_frame(self.last_stream_id, error_code, debug_data or b"")

    def send_ping(self, data: bytes | None = None) -> bytes:
        """Send PING frame.

        Args:
            data: 8 bytes of opaque data (random if not provided).

        Returns:
            Encoded PING frame.
        """
        if data is None:
            import os

            data = os.urandom(8)

        self.last_ping_time = time.time()
        return self.frame_codec.encode_ping_frame(data)

    def create_stream(self, stream_id: int | None = None, depends_on: int = 0, weight: int = 16) -> Stream:
        """Create a new stream.

        Args:
            stream_id: Stream ID (auto-assigned if not provided).
            depends_on: Parent stream ID for priority.
            weight: Stream weight.

        Returns:
            New Stream object.

        Raises:
            ConnectionError: If stream creation fails.
        """
        if self.state not in ("settings", "open"):
            raise ConnectionError(f"Cannot create stream in state {self.state}")

        if stream_id is None:
            stream_id = self.stream_manager.next_available_stream_id()

        try:
            stream = self.stream_manager.create_stream(stream_id)
            self.priority_tree.create_stream(stream_id, depends_on, weight)
            return stream
        except Exception as e:
            raise ConnectionError(f"Failed to create stream: {e}")

    def get_stream(self, stream_id: int) -> Stream | None:
        """Get a stream by ID.

        Args:
            stream_id: Stream ID.

        Returns:
            Stream or None.
        """
        return self.stream_manager.get_stream(stream_id)

    def send_headers(
        self,
        stream_id: int,
        headers: list[tuple[bytes, bytes]],
        end_stream: bool = False,
        end_headers: bool = True,
    ) -> bytes:
        """Send HEADERS frame.

        Args:
            stream_id: Stream ID.
            headers: Header list.
            end_stream: Whether to end stream.
            end_headers: Whether to end header block.

        Returns:
            Encoded frame(s).

        Raises:
            ConnectionError: If stream invalid or closed.
        """
        stream = self.get_stream(stream_id)
        if not stream:
            raise ConnectionError(f"Stream {stream_id} doesn't exist")

        if not stream.can_send():
            raise ConnectionError(f"Stream {stream_id} cannot send in state {stream.state}")

        # Encode headers
        header_block = self.header_encoder.encode_headers(headers)

        # Send HEADERS frame
        return self.frame_codec.encode_headers_frame(stream_id, header_block, end_stream, end_headers)

    def send_data(self, stream_id: int, data: bytes, end_stream: bool = False) -> bytes:
        """Send DATA frame.

        Args:
            stream_id: Stream ID.
            data: Data to send.
            end_stream: Whether to end stream.

        Returns:
            Encoded frame.

        Raises:
            ConnectionError: If stream invalid.
        """
        stream = self.get_stream(stream_id)
        if not stream:
            raise ConnectionError(f"Stream {stream_id} doesn't exist")

        if not stream.can_send():
            raise ConnectionError(f"Stream {stream_id} cannot send in state {stream.state}")

        # Check flow control
        try:
            self.flow_control.send_data(stream_id, len(data))
        except Exception as e:
            raise ConnectionError(f"Flow control error: {e}")

        return self.frame_codec.encode_data_frame(stream_id, data, end_stream)

    def send_window_update(self, stream_id: int, increment: int) -> bytes:
        """Send WINDOW_UPDATE frame.

        Args:
            stream_id: Stream ID (0 for connection).
            increment: Window increment.

        Returns:
            Encoded frame.
        """
        return self.frame_codec.encode_window_update_frame(stream_id, increment)

    def send_settings(self, ack: bool = False) -> bytes:
        """Send SETTINGS frame.

        Args:
            ack: Whether this is SETTINGS ACK.

        Returns:
            Encoded frame.
        """
        if ack:
            return self.frame_codec.encode_settings_frame({}, ack=True)

        settings_dict = self.local_settings.to_dict()
        self.settings_acked = True
        return self.frame_codec.encode_settings_frame(settings_dict)

    def close(self) -> None:
        """Close the connection."""
        self.state = "closed"

    def is_open(self) -> bool:
        """Check if connection is open for sending.

        Returns:
            True if connection is open.
        """
        return self.state in ("settings", "open")

    def is_closed(self) -> bool:
        """Check if connection is closed.

        Returns:
            True if connection is closed.
        """
        return self.state in ("closed", "goaway")

    def get_state(self) -> dict:
        """Get connection state.

        Returns:
            Dictionary with connection state.
        """
        return {
            "state": self.state,
            "is_server": self.is_server,
            "settings_acked": self.settings_acked,
            "remote_settings_acked": self.remote_settings_acked,
            "goaway_sent": self.goaway_sent,
            "goaway_received": self.goaway_received,
            "last_stream_id": self.last_stream_id,
            "stream_count": self.stream_manager.get_stream_count(),
            "connection_window": self.flow_control.get_connection_window(),
        }
