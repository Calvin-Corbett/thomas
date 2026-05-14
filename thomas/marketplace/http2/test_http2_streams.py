"""Tests for HTTP/2 stream management."""

import pytest

from thomas.marketplace.http2._exceptions import StreamError
from thomas.marketplace.http2._types import ErrorCode, StreamState
from thomas.marketplace.http2.streams import Stream, StreamManager


class TestStream:
    """Tests for Stream class."""

    def test_create_stream(self) -> None:
        """Test creating a stream."""
        stream = Stream(1)
        assert stream.stream_id == 1
        assert stream.state == StreamState.IDLE

    def test_open_stream(self) -> None:
        """Test opening a stream."""
        stream = Stream(1)
        stream.open()
        assert stream.state == StreamState.OPEN

    def test_cannot_open_non_idle_stream(self) -> None:
        """Test that non-idle streams cannot be opened."""
        stream = Stream(1)
        stream.open()

        with pytest.raises(StreamError):
            stream.open()

    def test_send_headers_transitions_to_open(self) -> None:
        """Test that sending headers transitions stream to OPEN."""
        stream = Stream(1)
        stream.send_headers()
        assert stream.state == StreamState.OPEN
        assert stream.headers_sent is True

    def test_cannot_send_headers_twice(self) -> None:
        """Test that headers cannot be sent twice."""
        stream = Stream(1)
        stream.send_headers()

        with pytest.raises(StreamError):
            stream.send_headers()

    def test_receive_headers_transitions_to_open(self) -> None:
        """Test that receiving headers transitions stream to OPEN."""
        stream = Stream(1)
        stream.receive_headers()
        assert stream.state == StreamState.OPEN
        assert stream.headers_received is True

    def test_send_data_transitions_to_half_closed(self) -> None:
        """Test sending data with END_STREAM flag."""
        stream = Stream(1)
        stream.send_headers()
        stream.send_data(end_stream=True)

        assert stream.state == StreamState.HALF_CLOSED_LOCAL
        assert stream.data_sent is True

    def test_receive_data_transitions_to_half_closed(self) -> None:
        """Test receiving data with END_STREAM flag."""
        stream = Stream(1)
        stream.receive_headers()
        stream.receive_data(end_stream=True)

        assert stream.state == StreamState.HALF_CLOSED_REMOTE

    def test_bidirectional_close(self) -> None:
        """Test stream closing after both sides send END_STREAM."""
        stream = Stream(1)

        # Client sends headers and data
        stream.send_headers()
        stream.send_data(end_stream=True)
        assert stream.state == StreamState.HALF_CLOSED_LOCAL

        # Server sends response headers and data
        stream.receive_headers()
        stream.receive_data(end_stream=True)
        assert stream.state == StreamState.CLOSED

    def test_reset_stream(self) -> None:
        """Test resetting a stream."""
        stream = Stream(1)
        stream.open()
        stream.reset_stream(ErrorCode.PROTOCOL_ERROR)

        assert stream.state == StreamState.CLOSED
        assert stream.error_code == ErrorCode.PROTOCOL_ERROR

    def test_is_open(self) -> None:
        """Test is_open() predicate."""
        stream = Stream(1)
        assert not stream.is_open()

        stream.open()
        assert stream.is_open()

        stream.state = StreamState.HALF_CLOSED_LOCAL
        assert stream.is_open()

        stream.state = StreamState.CLOSED
        assert not stream.is_open()

    def test_can_send(self) -> None:
        """Test can_send() predicate."""
        stream = Stream(1)
        stream.send_headers()

        assert stream.can_send()

        stream.send_data(end_stream=True)
        assert not stream.can_send()

    def test_can_receive(self) -> None:
        """Test can_receive() predicate."""
        stream = Stream(1)
        stream.receive_headers()

        assert stream.can_receive()

        stream.receive_data(end_stream=True)
        assert not stream.can_receive()

    def test_window_size_tracking(self) -> None:
        """Test window size tracking."""
        stream = Stream(1, initial_window_size=100)
        assert stream.window_size == 100
        assert stream.remote_window_size == 100

    def test_priority_fields(self) -> None:
        """Test priority fields."""
        stream = Stream(1)
        stream.priority_depends_on = 0
        stream.priority_weight = 20

        assert stream.priority_depends_on == 0
        assert stream.priority_weight == 20


class TestStreamManager:
    """Tests for StreamManager class."""

    def setup_method(self) -> None:
        """Setup stream manager."""
        self.manager = StreamManager(max_concurrent_streams=10)

    def test_create_stream(self) -> None:
        """Test creating a stream."""
        stream = self.manager.create_stream(1)
        assert stream.stream_id == 1
        assert stream in self.manager.streams.values()

    def test_get_stream(self) -> None:
        """Test getting a stream."""
        stream = self.manager.create_stream(1)
        retrieved = self.manager.get_stream(1)

        assert retrieved is stream

    def test_get_nonexistent_stream(self) -> None:
        """Test getting nonexistent stream returns None."""
        retrieved = self.manager.get_stream(999)
        assert retrieved is None

    def test_create_duplicate_stream_fails(self) -> None:
        """Test that creating duplicate stream fails."""
        self.manager.create_stream(1)

        with pytest.raises(StreamError):
            self.manager.create_stream(1)

    def test_max_concurrent_streams_limit(self) -> None:
        """Test maximum concurrent streams limit."""
        # Create max streams
        for i in range(1, 11, 2):
            self.manager.create_stream(i)

        # Next stream creation should fail
        with pytest.raises(StreamError):
            self.manager.create_stream(21)

    def test_closed_streams_dont_count_toward_limit(self) -> None:
        """Test that closed streams don't count toward limit."""
        for i in range(1, 11, 2):
            stream = self.manager.create_stream(i)
            stream.close()

        # Should be able to create more
        stream = self.manager.create_stream(21)
        assert stream.stream_id == 21

    def test_close_stream(self) -> None:
        """Test closing a stream."""
        stream = self.manager.create_stream(1)
        self.manager.close_stream(1)

        assert stream.state == StreamState.CLOSED

    def test_remove_stream(self) -> None:
        """Test removing a stream."""
        self.manager.create_stream(1)
        self.manager.remove_stream(1)

        assert 1 not in self.manager.streams

    def test_get_all_streams(self) -> None:
        """Test getting all streams."""
        for i in range(1, 6, 2):
            self.manager.create_stream(i)

        streams = self.manager.get_all_streams()
        assert len(streams) == 3

    def test_get_open_streams(self) -> None:
        """Test getting only open streams."""
        s1 = self.manager.create_stream(1)
        s2 = self.manager.create_stream(3)
        s1.open()
        s2.open()
        s2.close()

        open_streams = self.manager.get_open_streams()
        assert len(open_streams) == 1
        assert 1 in open_streams

    def test_get_closed_streams(self) -> None:
        """Test getting only closed streams."""
        s1 = self.manager.create_stream(1)
        self.manager.create_stream(3)
        s1.close()

        closed = self.manager.get_closed_streams()
        assert len(closed) == 1
        assert 1 in closed

    def test_get_stream_count(self) -> None:
        """Test getting open stream count."""
        for i in range(1, 6, 2):
            self.manager.create_stream(i)

        count = self.manager.get_stream_count()
        assert count == 3

    def test_get_or_create_stream_existing(self) -> None:
        """Test get_or_create with existing stream."""
        stream1 = self.manager.create_stream(1)
        stream2 = self.manager.get_or_create_stream(1)

        assert stream1 is stream2

    def test_get_or_create_stream_new(self) -> None:
        """Test get_or_create creates new stream."""
        stream = self.manager.get_or_create_stream(1)
        assert stream.stream_id == 1

    def test_next_available_stream_id(self) -> None:
        """Test getting next available stream ID."""
        self.manager.create_stream(1)
        self.manager.create_stream(3)

        next_id = self.manager.next_available_stream_id()
        assert next_id not in self.manager.streams

    def test_validate_stream_id_client(self) -> None:
        """Test stream ID validation for client."""
        # Client should generate odd IDs
        assert self.manager.validate_stream_id(1, local_initiator=True)
        assert self.manager.validate_stream_id(3, local_initiator=True)
        assert not self.manager.validate_stream_id(2, local_initiator=True)
        assert not self.manager.validate_stream_id(0, local_initiator=True)

    def test_validate_stream_id_server(self) -> None:
        """Test stream ID validation for server."""
        # Server should generate even IDs
        assert self.manager.validate_stream_id(2, local_initiator=False)
        assert self.manager.validate_stream_id(4, local_initiator=False)
        assert not self.manager.validate_stream_id(1, local_initiator=False)
        assert not self.manager.validate_stream_id(0, local_initiator=False)

    def test_reset_stream(self) -> None:
        """Test resetting a stream."""
        self.manager.create_stream(1)
        self.manager.reset_stream(1, ErrorCode.FLOW_CONTROL_ERROR)

        stream = self.manager.get_stream(1)
        assert stream.state == StreamState.CLOSED
        assert stream.error_code == ErrorCode.FLOW_CONTROL_ERROR

    def test_has_stream(self) -> None:
        """Test checking if stream exists."""
        self.manager.create_stream(1)

        assert self.manager.has_stream(1)
        assert not self.manager.has_stream(999)

    def test_get_state_summary(self) -> None:
        """Test getting state summary."""
        for i in range(1, 6, 2):
            self.manager.create_stream(i)

        summary = self.manager.get_state_summary()
        assert summary["total_streams"] == 3
        assert summary["open_streams"] == 3

    def test_clear_closed_streams(self) -> None:
        """Test clearing closed streams."""
        for i in range(1, 100, 2):
            self.manager.closed_streams.add(i)

        self.manager.clear_closed_streams()
        assert len(self.manager.closed_streams) == 0


class TestStreamStateTransitions:
    """Tests for valid stream state transitions."""

    def test_client_initiated_request(self) -> None:
        """Test client-initiated request stream transitions."""
        stream = Stream(1)

        # Client sends request
        stream.send_headers()
        assert stream.state == StreamState.OPEN

        stream.send_data(end_stream=True)
        assert stream.state == StreamState.HALF_CLOSED_LOCAL

        # Server sends response
        stream.receive_headers()
        assert stream.state == StreamState.HALF_CLOSED_LOCAL

        stream.receive_data(end_stream=True)
        assert stream.state == StreamState.CLOSED

    def test_server_initiated_push(self) -> None:
        """Test server-initiated push stream transitions."""
        stream = Stream(2)

        # Server sends push promise (implicit headers)
        stream.send_headers()
        assert stream.state == StreamState.OPEN

        stream.send_data(end_stream=True)
        assert stream.state == StreamState.HALF_CLOSED_LOCAL

        # Client receives push (no client response)
        stream.receive_headers()
        assert stream.state == StreamState.HALF_CLOSED_LOCAL

        stream.receive_data(end_stream=True)
        assert stream.state == StreamState.CLOSED

    def test_invalid_transitions(self) -> None:
        """Test that invalid transitions raise errors."""
        stream = Stream(1)

        # Cannot send data before headers
        with pytest.raises(StreamError):
            stream.send_data()

        # Cannot receive data before headers
        with pytest.raises(StreamError):
            stream.receive_data()

        # Now send headers
        stream.send_headers()

        # Can send data
        stream.send_data(end_stream=True)
        assert stream.state == StreamState.HALF_CLOSED_LOCAL

        # Cannot send more data
        with pytest.raises(StreamError):
            stream.send_data()
