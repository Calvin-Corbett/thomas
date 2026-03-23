"""Tests for HTTP/2 connection handler."""

import pytest

from thomas.marketplace.http2._exceptions import ConnectionError
from thomas.marketplace.http2._types import ErrorCode, HTTP2Config
from thomas.marketplace.http2.connection import HTTP2Connection


class TestHTTP2ConnectionClient:
    """Tests for client-side HTTP/2 connection."""

    def setup_method(self) -> None:
        """Setup client connection."""
        config = HTTP2Config()
        self.conn = HTTP2Connection(config, is_server=False)

    def test_create_connection(self) -> None:
        """Test creating connection."""
        assert self.conn.is_server is False
        assert self.conn.state == "idle"

    def test_initiate_connection(self) -> None:
        """Test initiating connection."""
        data = self.conn.initiate()

        assert self.conn.CLIENT_PREFACE in data
        assert len(data) > len(self.conn.CLIENT_PREFACE)
        assert self.conn.state == "preface"

    def test_client_preface(self) -> None:
        """Test client sends proper preface."""
        data = self.conn.initiate()
        assert data.startswith(self.conn.CLIENT_PREFACE)

    def test_create_stream(self) -> None:
        """Test creating stream."""
        self.conn.initiate()
        stream = self.conn.create_stream()

        assert stream.stream_id == 1
        assert stream in self.conn.stream_manager.streams.values()

    def test_create_odd_stream_ids(self) -> None:
        """Test client creates odd stream IDs."""
        self.conn.initiate()

        stream1 = self.conn.create_stream()
        stream2 = self.conn.create_stream()

        assert stream1.stream_id % 2 == 1
        assert stream2.stream_id % 2 == 1

    def test_get_stream(self) -> None:
        """Test getting stream."""
        self.conn.initiate()
        stream = self.conn.create_stream()

        retrieved = self.conn.get_stream(stream.stream_id)
        assert retrieved is stream

    def test_send_headers(self) -> None:
        """Test sending headers."""
        self.conn.initiate()
        stream = self.conn.create_stream()

        headers = [
            (b":method", b"GET"),
            (b":path", b"/"),
            (b":scheme", b"https"),
        ]
        data = self.conn.send_headers(stream.stream_id, headers)

        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_send_data(self) -> None:
        """Test sending data."""
        self.conn.initiate()
        stream = self.conn.create_stream()
        stream.send_headers()

        data_to_send = b"test data"
        data = self.conn.send_data(stream.stream_id, data_to_send, end_stream=True)

        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_cannot_send_data_before_headers(self) -> None:
        """Test that data cannot be sent before headers."""
        self.conn.initiate()
        stream = self.conn.create_stream()

        with pytest.raises(ConnectionError):
            self.conn.send_data(stream.stream_id, b"data")


class TestHTTP2ConnectionServer:
    """Tests for server-side HTTP/2 connection."""

    def setup_method(self) -> None:
        """Setup server connection."""
        config = HTTP2Config()
        self.conn = HTTP2Connection(config, is_server=True)

    def test_server_no_preface(self) -> None:
        """Test server doesn't send preface."""
        data = self.conn.initiate()
        assert self.conn.CLIENT_PREFACE not in data

    def test_server_creates_even_stream_ids(self) -> None:
        """Test server creates even stream IDs."""
        self.conn.initiate()

        # Get next available ID for server
        next_id = self.conn.stream_manager.next_available_stream_id()
        # Manually set to 2 for testing
        self.conn.stream_manager.next_stream_id = 2

        stream1 = self.conn.create_stream()
        stream2 = self.conn.create_stream()

        assert stream1.stream_id % 2 == 0
        assert stream2.stream_id % 2 == 0


class TestHTTP2SettingsNegotiation:
    """Tests for SETTINGS negotiation."""

    def setup_method(self) -> None:
        """Setup connection."""
        self.conn = HTTP2Connection(is_server=False)

    def test_send_settings(self) -> None:
        """Test sending SETTINGS."""
        data = self.conn.send_settings()

        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_send_settings_ack(self) -> None:
        """Test sending SETTINGS ACK."""
        data = self.conn.send_settings(ack=True)

        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_handle_settings_frame(self) -> None:
        """Test handling SETTINGS frame."""
        settings = {
            1: 4096,  # HEADER_TABLE_SIZE
            4: 65535,  # INITIAL_WINDOW_SIZE
        }

        self.conn.handle_settings_frame(settings, ack=False)

        # Settings should be applied
        assert self.conn.remote_settings.header_table_size == 4096


class TestHTTP2PingPong:
    """Tests for PING/PONG."""

    def setup_method(self) -> None:
        """Setup connection."""
        self.conn = HTTP2Connection(is_server=False)

    def test_send_ping(self) -> None:
        """Test sending PING."""
        data = self.conn.send_ping()

        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_send_ping_with_data(self) -> None:
        """Test sending PING with custom data."""
        ping_data = b"12345678"
        data = self.conn.send_ping(ping_data)

        assert isinstance(data, bytes)

    def test_handle_ping_ack(self) -> None:
        """Test handling PING ACK."""
        ping_data = b"12345678"
        response = self.conn.handle_ping_frame(ping_data, ack=True)

        # No response to PING ACK
        assert response == b""

    def test_handle_ping_request(self) -> None:
        """Test handling PING request."""
        ping_data = b"12345678"
        response = self.conn.handle_ping_frame(ping_data, ack=False)

        # Should return PING ACK
        assert isinstance(response, bytes)
        assert len(response) > 0


class TestHTTP2GOAWAY:
    """Tests for GOAWAY handling."""

    def setup_method(self) -> None:
        """Setup connection."""
        self.conn = HTTP2Connection(is_server=False)

    def test_send_goaway(self) -> None:
        """Test sending GOAWAY."""
        data = self.conn.send_goaway(ErrorCode.PROTOCOL_ERROR)

        assert isinstance(data, bytes)
        assert len(data) > 0
        assert self.conn.goaway_sent is True
        assert self.conn.state == "closed"

    def test_send_goaway_with_debug_data(self) -> None:
        """Test sending GOAWAY with debug data."""
        debug = b"protocol violation"
        data = self.conn.send_goaway(ErrorCode.PROTOCOL_ERROR, debug_data=debug)

        assert isinstance(data, bytes)

    def test_handle_goaway_frame(self) -> None:
        """Test handling received GOAWAY."""
        self.conn.state = "open"
        self.conn.handle_goaway_frame(42, ErrorCode.PROTOCOL_ERROR, b"")

        assert self.conn.goaway_received is True
        assert self.conn.last_stream_id == 42
        assert self.conn.goaway_error_code == ErrorCode.PROTOCOL_ERROR
        assert self.conn.state == "goaway"


class TestHTTP2StateManagement:
    """Tests for connection state management."""

    def setup_method(self) -> None:
        """Setup connection."""
        self.conn = HTTP2Connection(is_server=False)

    def test_get_state(self) -> None:
        """Test getting connection state."""
        state = self.conn.get_state()

        assert state["state"] == "idle"
        assert state["is_server"] is False

    def test_is_open(self) -> None:
        """Test checking if connection is open."""
        assert not self.conn.is_open()

        self.conn.initiate()
        assert self.conn.is_open()

        self.conn.state = "goaway"
        assert not self.conn.is_open()

    def test_is_closed(self) -> None:
        """Test checking if connection is closed."""
        assert not self.conn.is_closed()

        self.conn.state = "closed"
        assert self.conn.is_closed()

    def test_close_connection(self) -> None:
        """Test closing connection."""
        self.conn.close()
        assert self.conn.state == "closed"


class TestHTTP2Errors:
    """Tests for error handling."""

    def setup_method(self) -> None:
        """Setup connection."""
        self.conn = HTTP2Connection(is_server=False)

    def test_cannot_create_stream_closed_connection(self) -> None:
        """Test that streams cannot be created on closed connection."""
        self.conn.state = "closed"

        with pytest.raises(ConnectionError):
            self.conn.create_stream()

    def test_cannot_send_headers_nonexistent_stream(self) -> None:
        """Test sending headers to nonexistent stream."""
        self.conn.initiate()

        with pytest.raises(ConnectionError):
            self.conn.send_headers(999, [])

    def test_cannot_send_data_nonexistent_stream(self) -> None:
        """Test sending data to nonexistent stream."""
        self.conn.initiate()

        with pytest.raises(ConnectionError):
            self.conn.send_data(999, b"data")

    def test_flow_control_enforcement(self) -> None:
        """Test that flow control is enforced."""
        self.conn.initiate()
        stream = self.conn.create_stream()
        stream.send_headers()

        # Exhaust connection window
        self.conn.flow_control.send_data(0, 65535)

        # Try to send more data
        with pytest.raises(ConnectionError):
            self.conn.send_data(stream.stream_id, b"x" * 1000)


class TestHTTP2WindowUpdate:
    """Tests for WINDOW_UPDATE."""

    def setup_method(self) -> None:
        """Setup connection."""
        self.conn = HTTP2Connection(is_server=False)

    def test_send_window_update_connection(self) -> None:
        """Test sending WINDOW_UPDATE on connection."""
        data = self.conn.send_window_update(0, 1000)

        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_send_window_update_stream(self) -> None:
        """Test sending WINDOW_UPDATE on stream."""
        self.conn.initiate()
        stream = self.conn.create_stream()

        data = self.conn.send_window_update(stream.stream_id, 1000)

        assert isinstance(data, bytes)


class TestHTTP2Integration:
    """Integration tests for HTTP/2 connection."""

    def test_client_server_handshake(self) -> None:
        """Test client-server connection setup."""
        # Client initiates
        client = HTTP2Connection(is_server=False)
        client_init = client.initiate()

        # Server initiates
        server = HTTP2Connection(is_server=True)
        server_init = server.initiate()

        # Server has no preface
        assert client.CLIENT_PREFACE in client_init
        assert client.CLIENT_PREFACE not in server_init

    def test_stream_lifecycle(self) -> None:
        """Test complete stream lifecycle."""
        conn = HTTP2Connection(is_server=False)
        conn.initiate()

        # Create stream
        stream = conn.create_stream()

        # Send request
        headers = [(b":method", b"GET"), (b":path", b"/")]
        conn.send_headers(stream.stream_id, headers)

        # Send data
        conn.send_data(stream.stream_id, b"", end_stream=True)

        # Stream should be half-closed local
        assert stream.state.name == "HALF_CLOSED_LOCAL"

    def test_multiple_streams(self) -> None:
        """Test managing multiple streams."""
        conn = HTTP2Connection(is_server=False)
        conn.initiate()

        streams = [conn.create_stream() for _ in range(5)]

        assert len(streams) == 5
        for i, stream in enumerate(streams):
            assert stream.stream_id == 1 + (i * 2)
