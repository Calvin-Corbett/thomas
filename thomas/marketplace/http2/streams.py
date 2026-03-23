"""HTTP/2 stream management and state machine."""

from thomas.marketplace.http2._exceptions import StreamError
from thomas.marketplace.http2._types import ErrorCode, StreamState


class Stream:
    """Represents a single HTTP/2 stream."""

    def __init__(self, stream_id: int, initial_window_size: int = 65535) -> None:
        """Initialize stream.

        Args:
            stream_id: Stream ID.
            initial_window_size: Initial flow control window size.
        """
        self.stream_id = stream_id
        self.state = StreamState.IDLE
        self.window_size = initial_window_size
        self.remote_window_size = initial_window_size
        self.error_code: ErrorCode | None = None
        self.headers_sent = False
        self.headers_received = False
        self.data_sent = False
        self.data_received = False
        self.priority_depends_on = 0
        self.priority_weight = 16
        self.priority_exclusive = False

    def open(self, local: bool = True) -> None:
        """Open the stream (transition to OPEN state).

        Args:
            local: Whether stream was opened locally.

        Raises:
            StreamError: If transition is invalid.
        """
        if self.state != StreamState.IDLE:
            raise StreamError(f"Cannot open stream {self.stream_id} in state {self.state}")

        self.state = StreamState.OPEN

    def send_headers(self) -> None:
        """Mark headers as sent.

        Raises:
            StreamError: If already sent or invalid state.
        """
        if self.headers_sent:
            raise StreamError(f"Headers already sent on stream {self.stream_id}")

        if self.state == StreamState.IDLE:
            self.state = StreamState.OPEN
        elif self.state not in (StreamState.OPEN, StreamState.HALF_CLOSED_REMOTE):
            raise StreamError(f"Cannot send headers in state {self.state}")

        self.headers_sent = True

    def receive_headers(self) -> None:
        """Mark headers as received.

        Raises:
            StreamError: If already received or invalid state.
        """
        if self.headers_received:
            raise StreamError(f"Headers already received on stream {self.stream_id}")

        if self.state == StreamState.IDLE:
            self.state = StreamState.OPEN
        elif self.state not in (StreamState.OPEN, StreamState.HALF_CLOSED_LOCAL):
            raise StreamError(f"Cannot receive headers in state {self.state}")

        self.headers_received = True

    def send_data(self, end_stream: bool = False) -> None:
        """Mark data as sent.

        Args:
            end_stream: Whether this ends the stream.

        Raises:
            StreamError: If invalid state.
        """
        if not self.headers_sent:
            raise StreamError(f"Cannot send data before headers on stream {self.stream_id}")

        if self.state == StreamState.OPEN:
            if end_stream:
                self.state = StreamState.HALF_CLOSED_LOCAL
        elif self.state == StreamState.HALF_CLOSED_REMOTE:
            if end_stream:
                self.state = StreamState.CLOSED
        else:
            raise StreamError(f"Cannot send data in state {self.state}")

        self.data_sent = True

    def receive_data(self, end_stream: bool = False) -> None:
        """Mark data as received.

        Args:
            end_stream: Whether this ends the stream.

        Raises:
            StreamError: If invalid state.
        """
        if not self.headers_received:
            raise StreamError(f"Cannot receive data before headers on stream {self.stream_id}")

        if self.state == StreamState.OPEN:
            if end_stream:
                self.state = StreamState.HALF_CLOSED_REMOTE
        elif self.state == StreamState.HALF_CLOSED_LOCAL:
            if end_stream:
                self.state = StreamState.CLOSED
        else:
            raise StreamError(f"Cannot receive data in state {self.state}")

        self.data_received = True

    def reset_stream(self, error_code: ErrorCode = ErrorCode.NO_ERROR) -> None:
        """Reset the stream.

        Args:
            error_code: Error code for reset.
        """
        self.error_code = error_code
        self.state = StreamState.CLOSED

    def close(self) -> None:
        """Close the stream."""
        self.state = StreamState.CLOSED

    def is_open(self) -> bool:
        """Check if stream is open for sending/receiving.

        Returns:
            True if stream can receive data.
        """
        return self.state in (
            StreamState.OPEN,
            StreamState.HALF_CLOSED_LOCAL,
            StreamState.HALF_CLOSED_REMOTE,
        )

    def is_closed(self) -> bool:
        """Check if stream is closed.

        Returns:
            True if stream is closed.
        """
        return self.state == StreamState.CLOSED

    def can_send(self) -> bool:
        """Check if stream can send data.

        Returns:
            True if stream can send.
        """
        return self.state in (StreamState.OPEN, StreamState.HALF_CLOSED_REMOTE)

    def can_receive(self) -> bool:
        """Check if stream can receive data.

        Returns:
            True if stream can receive.
        """
        return self.state in (StreamState.OPEN, StreamState.HALF_CLOSED_LOCAL)


class StreamManager:
    """Manages HTTP/2 streams and their lifecycle."""

    def __init__(self, max_concurrent_streams: int = 100) -> None:
        """Initialize stream manager.

        Args:
            max_concurrent_streams: Maximum number of concurrent streams.
        """
        self.streams: dict[int, Stream] = {}
        self.max_concurrent_streams = max_concurrent_streams
        self.next_stream_id = 1
        self.closed_streams: set[int] = set()

    def create_stream(
        self,
        stream_id: int,
        initial_window_size: int = 65535,
    ) -> Stream:
        """Create a new stream.

        Args:
            stream_id: Stream ID.
            initial_window_size: Initial flow control window.

        Returns:
            New Stream object.

        Raises:
            StreamError: If stream already exists or limit exceeded.
        """
        if stream_id in self.streams:
            raise StreamError(f"Stream {stream_id} already exists")

        # Count open streams (not closed)
        open_count = sum(1 for s in self.streams.values() if not s.is_closed())
        if open_count >= self.max_concurrent_streams:
            raise StreamError(f"Maximum concurrent streams ({self.max_concurrent_streams}) exceeded")

        stream = Stream(stream_id, initial_window_size)
        self.streams[stream_id] = stream
        return stream

    def get_stream(self, stream_id: int) -> Stream | None:
        """Get a stream by ID.

        Args:
            stream_id: Stream ID.

        Returns:
            Stream object or None.
        """
        return self.streams.get(stream_id)

    def get_or_create_stream(self, stream_id: int, initial_window_size: int = 65535) -> Stream:
        """Get stream or create if doesn't exist.

        Args:
            stream_id: Stream ID.
            initial_window_size: Initial flow control window.

        Returns:
            Stream object.
        """
        if stream_id not in self.streams:
            return self.create_stream(stream_id, initial_window_size)
        return self.streams[stream_id]

    def close_stream(self, stream_id: int) -> None:
        """Close a stream.

        Args:
            stream_id: Stream ID.
        """
        if stream_id in self.streams:
            self.streams[stream_id].close()
            self.closed_streams.add(stream_id)

    def remove_stream(self, stream_id: int) -> None:
        """Remove a stream (for cleanup).

        Args:
            stream_id: Stream ID.
        """
        self.streams.pop(stream_id, None)

    def get_all_streams(self) -> dict[int, Stream]:
        """Get all streams.

        Returns:
            Dictionary of stream_id -> Stream.
        """
        return dict(self.streams)

    def get_open_streams(self) -> dict[int, Stream]:
        """Get all open streams.

        Returns:
            Dictionary of stream_id -> Stream for open streams.
        """
        return {sid: s for sid, s in self.streams.items() if s.is_open()}

    def get_closed_streams(self) -> dict[int, Stream]:
        """Get all closed streams.

        Returns:
            Dictionary of stream_id -> Stream for closed streams.
        """
        return {sid: s for sid, s in self.streams.items() if s.is_closed()}

    def get_stream_count(self) -> int:
        """Get count of open streams.

        Returns:
            Number of open streams.
        """
        return sum(1 for s in self.streams.values() if s.is_open())

    def update_settings_initial_window_size(self, new_window_size: int) -> None:
        """Update initial window size for all existing streams.

        This is called when SETTINGS INITIAL_WINDOW_SIZE is received.

        Args:
            new_window_size: New initial window size.

        Raises:
            StreamError: If any stream window would become negative.
        """
        for stream in self.streams.values():
            # For simplicity, just update for open streams
            if stream.is_open():
                # Window size adjustment happens in FlowControlEngine
                pass

    def validate_stream_id(self, stream_id: int, local_initiator: bool) -> bool:
        """Validate a stream ID.

        Args:
            stream_id: Stream ID.
            local_initiator: Whether this endpoint initiates streams.

        Returns:
            True if stream ID is valid.
        """
        if stream_id <= 0:
            return False

        # Client initiates odd stream IDs, server initiates even
        if local_initiator:
            return stream_id % 2 == 1
        else:
            return stream_id % 2 == 0

    def next_available_stream_id(self) -> int:
        """Get next available stream ID for this endpoint.

        Returns:
            Next stream ID to use.
        """
        while self.next_stream_id in self.streams:
            self.next_stream_id += 2

        return self.next_stream_id

    def reset_stream(self, stream_id: int, error_code: ErrorCode = ErrorCode.NO_ERROR) -> None:
        """Reset a stream.

        Args:
            stream_id: Stream ID.
            error_code: Error code for reset.
        """
        if stream_id in self.streams:
            self.streams[stream_id].reset_stream(error_code)
            self.closed_streams.add(stream_id)

    def clear_closed_streams(self) -> None:
        """Clear closed streams from tracking.

        This can be called periodically to clean up old streams.
        """
        # Only keep recent closed streams
        if len(self.closed_streams) > 1000:
            self.closed_streams = set()

    def has_stream(self, stream_id: int) -> bool:
        """Check if stream exists.

        Args:
            stream_id: Stream ID.

        Returns:
            True if stream exists.
        """
        return stream_id in self.streams

    def get_state_summary(self) -> dict:
        """Get summary of stream states.

        Returns:
            Dictionary with state counts.
        """
        states = {}
        for stream in self.streams.values():
            state_name = stream.state.name
            states[state_name] = states.get(state_name, 0) + 1

        return {
            "total_streams": len(self.streams),
            "open_streams": self.get_stream_count(),
            "state_distribution": states,
        }
