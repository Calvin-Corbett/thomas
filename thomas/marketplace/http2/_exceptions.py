"""HTTP/2 exception classes."""


class HTTP2Error(Exception):
    """Base exception for HTTP/2 errors."""

    pass


class ProtocolError(HTTP2Error):
    """Protocol-level error (e.g., invalid frame format)."""

    pass


class StreamError(HTTP2Error):
    """Stream-level error."""

    pass


class FlowControlError(HTTP2Error):
    """Flow control error (e.g., window exhaustion)."""

    pass


class CompressionError(HTTP2Error):
    """Header compression/decompression error."""

    pass


class ConnectionError(HTTP2Error):
    """Connection-level error."""

    pass
