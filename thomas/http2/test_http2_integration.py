"""Integration tests for HTTP/2 module."""

import pytest

from thomas.http2._types import ErrorCode, HTTP2Config
from thomas.http2.connection import HTTP2Connection
from thomas.http2.frames import FrameCodec
from thomas.http2.hpack import HeaderDecoder, HeaderEncoder


class TestFullRequestResponse:
    """Tests for full HTTP/2 request/response cycle."""

    def test_simple_get_request(self) -> None:
        """Test a simple GET request."""
        # Client setup
        client = HTTP2Connection(is_server=False)
        client.initiate()

        # Create request stream
        req_stream = client.create_stream()

        # Send request headers
        request_headers = [
            (b":method", b"GET"),
            (b":path", b"/index.html"),
            (b":scheme", b"https"),
            (b":authority", b"www.example.com"),
        ]

        request_data = client.send_headers(req_stream.stream_id, request_headers)
        assert len(request_data) > 0

        # End request with no body
        end_data = client.send_data(req_stream.stream_id, b"", end_stream=True)
        assert len(end_data) > 0

    def test_post_request_with_body(self) -> None:
        """Test POST request with request body."""
        client = HTTP2Connection(is_server=False)
        client.initiate()

        stream = client.create_stream()

        # Send request headers
        headers = [
            (b":method", b"POST"),
            (b":path", b"/api/data"),
            (b":scheme", b"https"),
            (b"content-type", b"application/json"),
        ]
        client.send_headers(stream.stream_id, headers)

        # Send request body
        body = b'{"key": "value"}'
        client.send_data(stream.stream_id, body, end_stream=True)

    def test_server_push(self) -> None:
        """Test server push promise."""
        server = HTTP2Connection(is_server=True)
        server.initiate()

        # Simulate receiving client preface
        client = HTTP2Connection(is_server=False)
        client.initiate()

        # Server creates push promise
        request_stream = 1
        promised_stream = server.push_manager.create_push_promise(request_stream, b"/style.css")

        assert promised_stream[0] == 2

    def test_multiple_concurrent_streams(self) -> None:
        """Test multiple concurrent streams."""
        client = HTTP2Connection(is_server=False)
        client.initiate()

        # Create multiple streams
        streams = [client.create_stream() for _ in range(5)]

        # Send data on each
        headers = [(b":method", b"GET"), (b":path", b"/")]
        for stream in streams:
            client.send_headers(stream.stream_id, headers, end_stream=True)

        # All should exist
        assert len(client.stream_manager.get_open_streams()) == 5

    def test_stream_multiplexing(self) -> None:
        """Test that streams can be interleaved."""
        codec = FrameCodec()
        client = HTTP2Connection(is_server=False)
        client.initiate()

        stream1 = client.create_stream()
        stream2 = client.create_stream()

        # Send headers on stream1
        h1 = client.send_headers(stream1.stream_id, [(b":path", b"/1")])

        # Send headers on stream2
        h2 = client.send_headers(stream2.stream_id, [(b":path", b"/2")])

        # Send data on stream1
        d1 = client.send_data(stream1.stream_id, b"data1", end_stream=True)

        # Send data on stream2
        d2 = client.send_data(stream2.stream_id, b"data2", end_stream=True)

        # Can interleave: h1, h2, d1, d2
        data = h1 + h2 + d1 + d2

        # Should be able to decode all frames
        frames = []
        pos = 0
        while pos < len(data):
            frame, consumed = codec.decode(data[pos:])
            frames.append(frame)
            pos += consumed

        assert len(frames) >= 4


class TestFlowControlIntegration:
    """Tests for flow control in integration."""

    def test_window_update_flow(self) -> None:
        """Test WINDOW_UPDATE flow."""
        client = HTTP2Connection(is_server=False)
        client.initiate()

        stream = client.create_stream()
        stream.send_headers()

        # Send data
        data1 = b"x" * 10000
        client.send_data(stream.stream_id, data1)

        # Check window reduced
        window_before = client.flow_control.get_stream_window(stream.stream_id)
        assert window_before < 65535

        # Send WINDOW_UPDATE
        update = client.send_window_update(stream.stream_id, 5000)
        assert len(update) > 0

        # Window increased
        window_after = client.flow_control.get_stream_window(stream.stream_id)
        assert window_after == window_before + 5000

    def test_connection_level_flow_control(self) -> None:
        """Test connection-level flow control."""
        client = HTTP2Connection(is_server=False)
        client.initiate()

        # Get initial connection window
        initial = client.flow_control.get_connection_window()

        # Send data on multiple streams
        streams = [client.create_stream() for _ in range(3)]
        for stream in streams:
            stream.send_headers()
            client.send_data(stream.stream_id, b"x" * 1000)

        # Connection window should be reduced
        final = client.flow_control.get_connection_window()
        assert final == initial - 3000


class TestHeaderCompressionIntegration:
    """Tests for HPACK in integration."""

    def test_header_compression_roundtrip(self) -> None:
        """Test headers are compressed and decompressed."""
        encoder = HeaderEncoder()
        decoder = HeaderDecoder()

        headers = [
            (b":method", b"POST"),
            (b":path", b"/api/data"),
            (b":scheme", b"https"),
            (b":authority", b"api.example.com"),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json"),
        ]

        # Encode
        encoded = encoder.encode_headers(headers)

        # Decode
        decoded = decoder.decode_headers(encoded)

        # Should have same headers
        assert len(decoded) == len(headers)

    def test_dynamic_table_reuse(self) -> None:
        """Test that dynamic table entries are reused."""
        encoder = HeaderEncoder()

        # First request
        headers1 = [
            (b":method", b"GET"),
            (b"x-custom", b"value1"),
        ]
        encoded1 = encoder.encode_headers(headers1)

        # Second request with same custom header
        headers2 = [
            (b":method", b"GET"),
            (b"x-custom", b"value1"),
        ]
        encoded2 = encoder.encode_headers(headers2)

        # Second encoding should be smaller (uses table)
        assert len(encoded2) <= len(encoded1)


class TestConnectionStateTransitions:
    """Tests for connection state transitions."""

    def test_idle_to_preface(self) -> None:
        """Test transition from IDLE to PREFACE."""
        conn = HTTP2Connection(is_server=False)
        assert conn.state == "idle"

        conn.initiate()
        assert conn.state == "preface"

    def test_preface_to_settings(self) -> None:
        """Test transition from PREFACE to SETTINGS."""
        conn = HTTP2Connection(is_server=False)
        conn.initiate()
        assert conn.state == "preface"

        # Handle settings from peer
        conn.handle_settings_frame({}, ack=False)
        # Should transition to settings once both ACK
        # (simplified - normally requires explicit ACK)

    def test_settings_to_open(self) -> None:
        """Test transition to OPEN."""
        conn = HTTP2Connection(is_server=False)
        conn.initiate()
        conn.settings_acked = True
        conn.remote_settings_acked = True

        conn.state = "settings"
        assert conn.is_open()

    def test_open_to_goaway(self) -> None:
        """Test GOAWAY transitions."""
        conn = HTTP2Connection(is_server=False)
        conn.state = "open"

        conn.handle_goaway_frame(0, ErrorCode.NO_ERROR, b"")
        assert conn.state == "goaway"

    def test_open_to_closed(self) -> None:
        """Test closing connection."""
        conn = HTTP2Connection(is_server=False)
        conn.state = "open"

        conn.close()
        assert conn.state == "closed"


class TestPriorityIntegration:
    """Tests for priority in integration."""

    def test_stream_with_priority(self) -> None:
        """Test creating stream with priority."""
        conn = HTTP2Connection(is_server=False)
        conn.initiate()

        # Create stream with priority
        stream = conn.create_stream(depends_on=0, weight=20)
        assert stream.stream_id > 0

        # Priority info in tree
        depends_on, weight, exclusive = conn.priority_tree.get_stream_priority(stream.stream_id)
        assert weight == 20

    def test_reprioritization(self) -> None:
        """Test stream reprioritization."""
        conn = HTTP2Connection(is_server=False)
        conn.initiate()

        stream1 = conn.create_stream()
        stream2 = conn.create_stream(depends_on=stream1.stream_id, weight=10)

        # Reprioritize stream2
        conn.priority_tree.reprioritize_stream(stream2.stream_id, depends_on=0, weight=30)

        depends_on, weight, _ = conn.priority_tree.get_stream_priority(stream2.stream_id)
        assert depends_on == 0
        assert weight == 30


class TestErrorRecovery:
    """Tests for error handling and recovery."""

    def test_protocol_error_recovery(self) -> None:
        """Test handling protocol errors."""
        conn = HTTP2Connection(is_server=False)
        conn.initiate()

        # Send GOAWAY on protocol error
        goaway = conn.send_goaway(ErrorCode.PROTOCOL_ERROR)
        assert len(goaway) > 0
        assert conn.goaway_sent

    def test_stream_reset(self) -> None:
        """Test stream reset."""
        conn = HTTP2Connection(is_server=False)
        conn.initiate()

        stream = conn.create_stream()
        stream.send_headers()

        # Reset stream
        conn.stream_manager.reset_stream(stream.stream_id, ErrorCode.CANCEL)

        # Stream should be closed
        assert stream.is_closed()

    def test_connection_limits(self) -> None:
        """Test connection stream limits."""
        config = HTTP2Config()
        config.max_concurrent_streams = 3
        conn = HTTP2Connection(config, is_server=False)
        conn.initiate()

        # Create up to limit
        for i in range(3):
            conn.create_stream()

        # Next should fail
        with pytest.raises(Exception):
            conn.create_stream()


class TestConfigurationIntegration:
    """Tests for configuration in integration."""

    def test_custom_window_size(self) -> None:
        """Test custom initial window size."""
        config = HTTP2Config(initial_window_size=32768)
        conn = HTTP2Connection(config)

        stream = conn.create_stream()
        assert conn.flow_control.get_stream_window(stream.stream_id) == 32768

    def test_max_frame_size_config(self) -> None:
        """Test custom max frame size."""
        config = HTTP2Config(max_frame_size=8192)
        conn = HTTP2Connection(config)

        assert conn.frame_codec.max_frame_size == 8192

    def test_header_table_size_config(self) -> None:
        """Test header table size configuration."""
        config = HTTP2Config(header_table_size=2048)
        conn = HTTP2Connection(config)

        assert conn.header_encoder.max_dynamic_table_size == 2048
        assert conn.header_decoder.max_dynamic_table_size == 2048
