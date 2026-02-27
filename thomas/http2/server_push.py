"""HTTP/2 server push implementation."""

from enum import Enum

from thomas.http2._exceptions import ProtocolError, StreamError
from thomas.http2.streams import StreamManager


class PushPromiseState(Enum):
    """States for a push promise."""

    RESERVED = "reserved"
    SENT = "sent"
    HEADERS_SENT = "headers_sent"
    CANCELLED = "cancelled"


class PushPromise:
    """Represents a server push promise."""

    def __init__(
        self,
        stream_id: int,
        promised_stream_id: int,
        request_headers: list[tuple[bytes, bytes]],
    ) -> None:
        """Initialize push promise.

        Args:
            stream_id: Request stream ID.
            promised_stream_id: Promised stream ID.
            request_headers: Request headers (path, method, etc).
        """
        self.stream_id = stream_id
        self.promised_stream_id = promised_stream_id
        self.request_headers = request_headers
        self.state = PushPromiseState.RESERVED
        self.response_headers: list[tuple[bytes, bytes]] | None = None
        self.response_data: bytearray = bytearray()

    def send_headers(self, headers: list[tuple[bytes, bytes]]) -> None:
        """Send response headers for push promise.

        Args:
            headers: Response headers.

        Raises:
            StreamError: If already sent or cancelled.
        """
        if self.state == PushPromiseState.CANCELLED:
            raise StreamError(f"Push promise {self.promised_stream_id} was cancelled")

        if self.state in (PushPromiseState.HEADERS_SENT,):
            raise StreamError(f"Headers already sent for push {self.promised_stream_id}")

        self.response_headers = headers
        self.state = PushPromiseState.HEADERS_SENT

    def add_data(self, data: bytes) -> None:
        """Add response data.

        Args:
            data: Response data chunk.
        """
        self.response_data.extend(data)

    def cancel(self) -> None:
        """Cancel the push promise."""
        self.state = PushPromiseState.CANCELLED

    def is_complete(self) -> bool:
        """Check if push is complete.

        Returns:
            True if headers and data sent.
        """
        return self.state == PushPromiseState.HEADERS_SENT


class ServerPushManager:
    """Manages HTTP/2 server push promises."""

    def __init__(self, stream_manager: StreamManager) -> None:
        """Initialize push manager.

        Args:
            stream_manager: Stream manager instance.
        """
        self.stream_manager = stream_manager
        self.pushes: dict[int, PushPromise] = {}  # promised_stream_id -> PushPromise
        self.request_pushes: dict[int, set[int]] = {}  # request_stream_id -> push_ids
        self.next_promised_id = 2  # Server-initiated (even)

    def create_push_promise(
        self,
        request_stream_id: int,
        request_path: bytes,
        request_method: bytes = b"GET",
    ) -> tuple[int, PushPromise]:
        """Create a new push promise.

        Args:
            request_stream_id: Stream ID of request being responded to.
            request_path: Path being pushed.
            request_method: HTTP method (default GET).

        Returns:
            Tuple of (promised_stream_id, PushPromise).

        Raises:
            ProtocolError: If stream doesn't exist.
        """
        if request_stream_id not in self.stream_manager.streams:
            raise ProtocolError(f"Request stream {request_stream_id} doesn't exist")

        promised_id = self._get_next_promised_id()

        # Build request headers for the promised stream
        request_headers = [
            (b":method", request_method),
            (b":path", request_path),
            (b":scheme", b"https"),
            (b":authority", b""),
        ]

        push = PushPromise(request_stream_id, promised_id, request_headers)

        # Create the promised stream
        try:
            self.stream_manager.create_stream(promised_id)
        except StreamError:
            raise ProtocolError(f"Failed to create promised stream {promised_id}")

        self.pushes[promised_id] = push

        if request_stream_id not in self.request_pushes:
            self.request_pushes[request_stream_id] = set()
        self.request_pushes[request_stream_id].add(promised_id)

        return promised_id, push

    def get_push_promise(self, promised_stream_id: int) -> PushPromise | None:
        """Get a push promise.

        Args:
            promised_stream_id: Promised stream ID.

        Returns:
            PushPromise or None.
        """
        return self.pushes.get(promised_stream_id)

    def get_request_pushes(self, request_stream_id: int) -> set[int]:
        """Get all push IDs for a request stream.

        Args:
            request_stream_id: Request stream ID.

        Returns:
            Set of promised stream IDs.
        """
        return self.request_pushes.get(request_stream_id, set())

    def send_push_response(
        self,
        promised_stream_id: int,
        response_headers: list[tuple[bytes, bytes]],
        response_data: bytes | None = None,
    ) -> None:
        """Send response for a pushed resource.

        Args:
            promised_stream_id: Promised stream ID.
            response_headers: Response headers.
            response_data: Optional response data.

        Raises:
            ProtocolError: If push doesn't exist or already sent.
        """
        if promised_stream_id not in self.pushes:
            raise ProtocolError(f"Push promise {promised_stream_id} doesn't exist")

        push = self.pushes[promised_stream_id]
        push.send_headers(response_headers)

        if response_data:
            push.add_data(response_data)

    def cancel_push(self, promised_stream_id: int) -> None:
        """Cancel a push promise.

        Args:
            promised_stream_id: Promised stream ID.

        Raises:
            ProtocolError: If push doesn't exist.
        """
        if promised_stream_id not in self.pushes:
            raise ProtocolError(f"Push promise {promised_stream_id} doesn't exist")

        push = self.pushes[promised_stream_id]
        push.cancel()

        # Reset the promised stream
        self.stream_manager.reset_stream(promised_stream_id)

    def handle_push_cancelled(self, promised_stream_id: int) -> None:
        """Handle cancellation of push promise by client.

        Args:
            promised_stream_id: Promised stream ID.
        """
        if promised_stream_id in self.pushes:
            self.pushes[promised_stream_id].cancel()

    def validate_push_promise(
        self,
        request_stream_id: int,
        promised_stream_id: int,
        request_headers: list[tuple[bytes, bytes]],
    ) -> bool:
        """Validate a received push promise.

        Args:
            request_stream_id: Request stream ID.
            promised_stream_id: Promised stream ID.
            request_headers: Headers in PUSH_PROMISE.

        Returns:
            True if valid.

        Raises:
            ProtocolError: If validation fails.
        """
        if promised_stream_id % 2 == 1:
            raise ProtocolError(f"Push promise stream ID must be even, got {promised_stream_id}")

        if promised_stream_id in self.stream_manager.streams:
            raise ProtocolError(f"Stream {promised_stream_id} already exists")

        # Validate request headers
        has_method = any(h[0] == b":method" for h in request_headers)
        has_path = any(h[0] == b":path" for h in request_headers)

        if not (has_method and has_path):
            raise ProtocolError("Push promise must include :method and :path")

        return True

    def should_push(
        self,
        request_path: bytes,
        resource_path: bytes,
        cache_status: str = "unknown",
    ) -> bool:
        """Determine if a resource should be pushed.

        Args:
            request_path: Path of request being answered.
            resource_path: Path of resource to potentially push.
            cache_status: Cache status ("cached", "stale", "missing", "unknown").

        Returns:
            True if resource should be pushed.
        """
        # Don't push if resource is likely cached
        if cache_status == "cached":
            return False

        # Don't push unless it's a related resource
        if resource_path == request_path:
            return False

        # Don't push too many resources
        if len(self.pushes) > 10:
            return False

        return True

    def get_all_pushes(self) -> dict[int, PushPromise]:
        """Get all push promises.

        Returns:
            Dictionary of promised_stream_id -> PushPromise.
        """
        return dict(self.pushes)

    def cleanup_closed_pushes(self) -> None:
        """Remove completed or cancelled pushes from tracking."""
        completed = []
        for promised_id, push in self.pushes.items():
            if push.state in (PushPromiseState.CANCELLED,):
                completed.append(promised_id)

        for promised_id in completed:
            push = self.pushes.pop(promised_id)
            # Also remove from request mapping
            for stream_set in self.request_pushes.values():
                stream_set.discard(promised_id)

    def _get_next_promised_id(self) -> int:
        """Get next promised stream ID.

        Returns:
            Next available even stream ID.
        """
        while self.next_promised_id in self.stream_manager.streams:
            self.next_promised_id += 2

        return self.next_promised_id

    def get_stats(self) -> dict:
        """Get push manager statistics.

        Returns:
            Dictionary with stats.
        """
        states = {}
        for push in self.pushes.values():
            state = push.state.value
            states[state] = states.get(state, 0) + 1

        return {
            "total_pushes": len(self.pushes),
            "state_distribution": states,
            "requests_with_pushes": len(self.request_pushes),
        }
