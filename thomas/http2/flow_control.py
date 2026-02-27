"""HTTP/2 flow control engine."""

from thomas.http2._exceptions import FlowControlError


class FlowControlEngine:
    """Manages flow control for HTTP/2 connections and streams."""

    DEFAULT_WINDOW_SIZE = 65535
    MAX_WINDOW_SIZE = 2147483647  # 2^31 - 1

    def __init__(self, initial_window_size: int = DEFAULT_WINDOW_SIZE) -> None:
        """Initialize flow control engine.

        Args:
            initial_window_size: Initial window size for connection and streams.

        Raises:
            ValueError: If window size is invalid.
        """
        if initial_window_size < 1 or initial_window_size > self.MAX_WINDOW_SIZE:
            raise ValueError(f"Window size must be 1-{self.MAX_WINDOW_SIZE}, " f"got {initial_window_size}")

        self.connection_window = initial_window_size
        self.stream_windows: dict[int, int] = {}
        self.initial_window_size = initial_window_size

    def get_connection_window(self) -> int:
        """Get current connection window size.

        Returns:
            Available bytes for sending.
        """
        return self.connection_window

    def get_stream_window(self, stream_id: int) -> int:
        """Get current stream window size.

        Args:
            stream_id: Stream ID.

        Returns:
            Available bytes for sending, or initial window size if stream not found.
        """
        return self.stream_windows.get(stream_id, self.initial_window_size)

    def create_stream(self, stream_id: int, window_size: int | None = None) -> None:
        """Create a new stream's flow control window.

        Args:
            stream_id: Stream ID.
            window_size: Initial window size (default: connection's initial size).
        """
        if stream_id in self.stream_windows:
            raise FlowControlError(f"Stream {stream_id} already exists")

        self.stream_windows[stream_id] = window_size or self.initial_window_size

    def remove_stream(self, stream_id: int) -> None:
        """Remove a stream's flow control window.

        Args:
            stream_id: Stream ID.
        """
        self.stream_windows.pop(stream_id, None)

    def send_data(self, stream_id: int, length: int) -> tuple[int, int]:
        """Check and deduct from flow control windows for sending data.

        Args:
            stream_id: Stream ID (0 for connection).
            length: Number of bytes to send.

        Returns:
            Tuple of (connection_window_used, stream_window_used).

        Raises:
            FlowControlError: If window is exhausted.
        """
        if length < 0:
            raise ValueError(f"Length must be non-negative, got {length}")

        conn_use = min(length, self.connection_window)
        self.connection_window -= conn_use

        if stream_id == 0:
            return conn_use, 0

        stream_window = self.stream_windows.get(stream_id, self.initial_window_size)
        stream_use = min(length, stream_window)

        if stream_use < length:
            # Restore connection window
            self.connection_window += conn_use
            raise FlowControlError(f"Stream {stream_id} window exhausted: " f"need {length}, have {stream_window}")

        self.stream_windows[stream_id] = stream_window - stream_use
        return conn_use, stream_use

    def receive_data(self, stream_id: int, length: int) -> int:
        """Track received data and update flow control windows.

        Args:
            stream_id: Stream ID (0 for connection).
            length: Number of bytes received.

        Returns:
            Number of bytes credited to window.

        Raises:
            FlowControlError: If window would overflow.
        """
        if length < 0:
            raise ValueError(f"Length must be non-negative, got {length}")

        if stream_id == 0:
            # Connection-level
            if self.connection_window + length > self.MAX_WINDOW_SIZE:
                raise FlowControlError("Connection window overflow")
            self.connection_window += length
            return length

        # Stream-level
        stream_window = self.stream_windows.get(stream_id, self.initial_window_size)
        if stream_window + length > self.MAX_WINDOW_SIZE:
            raise FlowControlError(f"Stream {stream_id} window overflow")

        self.stream_windows[stream_id] = stream_window + length
        return length

    def consume_data(self, stream_id: int, length: int) -> tuple[int, int]:
        """Consume received data (reverse of receive_data for tracking consumption).

        Args:
            stream_id: Stream ID (0 for connection).
            length: Number of bytes consumed.

        Returns:
            Tuple of (connection_window_before, stream_window_before).

        Raises:
            FlowControlError: If window is insufficient.
        """
        if length < 0:
            raise ValueError(f"Length must be non-negative, got {length}")

        if stream_id == 0:
            conn_before = self.connection_window
            if self.connection_window < length:
                raise FlowControlError(f"Connection window exhausted: need {length}, have {self.connection_window}")
            self.connection_window -= length
            return conn_before, 0

        stream_window = self.stream_windows.get(stream_id, self.initial_window_size)
        stream_before = stream_window

        if stream_window < length:
            raise FlowControlError(f"Stream {stream_id} window exhausted: " f"need {length}, have {stream_window}")

        self.stream_windows[stream_id] = stream_window - length
        return self.connection_window, stream_before

    def increment_window(self, stream_id: int, increment: int) -> None:
        """Increment flow control window (receiver-initiated).

        Args:
            stream_id: Stream ID (0 for connection).
            increment: Window increment (1 to 2147483647).

        Raises:
            ValueError: If increment is invalid.
            FlowControlError: If window would overflow.
        """
        if increment < 1 or increment > self.MAX_WINDOW_SIZE:
            raise ValueError(f"Window increment must be 1-{self.MAX_WINDOW_SIZE}, " f"got {increment}")

        if stream_id == 0:
            # Connection-level
            if self.connection_window + increment > self.MAX_WINDOW_SIZE:
                raise FlowControlError("Connection window overflow")
            self.connection_window += increment
        else:
            # Stream-level
            stream_window = self.stream_windows.get(stream_id)
            if stream_window is None:
                return  # Stream may have closed

            if stream_window + increment > self.MAX_WINDOW_SIZE:
                raise FlowControlError(f"Stream {stream_id} window overflow")

            self.stream_windows[stream_id] = stream_window + increment

    def set_initial_window_size(self, new_size: int) -> None:
        """Update initial window size (usually from SETTINGS).

        This adjusts all existing stream windows proportionally.

        Args:
            new_size: New initial window size.

        Raises:
            ValueError: If size is invalid.
        """
        if new_size < 1 or new_size > self.MAX_WINDOW_SIZE:
            raise ValueError(f"Window size must be 1-{self.MAX_WINDOW_SIZE}, got {new_size}")

        size_delta = new_size - self.initial_window_size

        # Adjust all stream windows
        for stream_id in list(self.stream_windows.keys()):
            new_window = self.stream_windows[stream_id] + size_delta
            if new_window < 0:
                raise FlowControlError(f"Stream {stream_id} window would go negative with new initial size")
            self.stream_windows[stream_id] = new_window

        self.initial_window_size = new_size

    def should_send_window_update(self, stream_id: int, threshold: float = 0.5) -> bool:
        """Check if a WINDOW_UPDATE should be sent.

        Args:
            stream_id: Stream ID (0 for connection).
            threshold: Send update when window drops below this fraction of initial.

        Returns:
            True if window update should be sent.
        """
        if stream_id == 0:
            current = self.connection_window
            initial = self.initial_window_size
        else:
            current = self.stream_windows.get(stream_id, self.initial_window_size)
            initial = self.initial_window_size

        return current < (initial * threshold)

    def get_window_update_size(self, stream_id: int) -> int:
        """Calculate WINDOW_UPDATE size to restore to initial.

        Args:
            stream_id: Stream ID (0 for connection).

        Returns:
            Window increment needed.
        """
        if stream_id == 0:
            current = self.connection_window
            initial = self.initial_window_size
        else:
            current = self.stream_windows.get(stream_id, self.initial_window_size)
            initial = self.initial_window_size

        return max(0, initial - current)

    def is_window_exhausted(self, stream_id: int) -> bool:
        """Check if flow control window is exhausted.

        Args:
            stream_id: Stream ID (0 for connection).

        Returns:
            True if window is 0.
        """
        if stream_id == 0:
            return self.connection_window <= 0

        return self.stream_windows.get(stream_id, self.initial_window_size) <= 0

    def get_state(self) -> dict:
        """Get current flow control state.

        Returns:
            Dictionary with connection and stream windows.
        """
        return {
            "connection_window": self.connection_window,
            "stream_windows": dict(self.stream_windows),
            "initial_window_size": self.initial_window_size,
        }
