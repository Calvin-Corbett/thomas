"""QUIC protocol implementation.

Provides QUIC connections, stream management, congestion control,
and endpoint management.
"""

from .core import (
    CongestionController,
    ConnectionInfo,
    ConnectionState,
    QUICConnection,
    QUICEndpoint,
    StreamInfo,
    StreamManager,
    StreamState,
)

__all__ = [
    "ConnectionState",
    "StreamState",
    "StreamInfo",
    "ConnectionInfo",
    "StreamManager",
    "CongestionController",
    "QUICConnection",
    "QUICEndpoint",
]

__version__ = "1.0.0"
