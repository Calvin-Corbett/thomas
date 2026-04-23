"""HTTP/2 frame parsing and stream management.

This module provides a complete implementation of HTTP/2 (RFC 7540) including:
- Frame parsing and serialization
- HPACK header compression (RFC 7541)
- Stream state management
- Flow control
- Connection lifecycle management
- Server push support
- Priority/dependency tree management
"""

from thomas.marketplace.http2._exceptions import (
    CompressionError,
    ConnectionError,
    FlowControlError,
    HTTP2Error,
    ProtocolError,
    StreamError,
)
from thomas.marketplace.http2._types import (
    ErrorCode,
    Frame,
    FrameType,
    HTTP2Config,
    Settings,
    SettingsParameter,
    StreamState,
)
from thomas.marketplace.http2.connection import HTTP2Connection
from thomas.marketplace.http2.flow_control import FlowControlEngine
from thomas.marketplace.http2.frames import FrameCodec
from thomas.marketplace.http2.hpack import HeaderDecoder, HeaderEncoder
from thomas.marketplace.http2.priority import PriorityTree
from thomas.marketplace.http2.server_push import ServerPushManager
from thomas.marketplace.http2.streams import StreamManager

__all__ = [
    "HTTP2Connection",
    "HTTP2Config",
    "HTTP2Error",
    "ProtocolError",
    "StreamError",
    "FlowControlError",
    "CompressionError",
    "ConnectionError",
    "Frame",
    "FrameType",
    "ErrorCode",
    "SettingsParameter",
    "StreamState",
    "Settings",
    "FrameCodec",
    "HeaderEncoder",
    "HeaderDecoder",
    "StreamManager",
    "FlowControlEngine",
    "PriorityTree",
    "ServerPushManager",
]

__version__ = "0.1.0"
