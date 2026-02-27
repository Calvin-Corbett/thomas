"""Type definitions for HTTP/2 frames, settings, and stream state."""

from dataclasses import dataclass, field
from enum import IntEnum, auto


class FrameType(IntEnum):
    """HTTP/2 frame types per RFC 7540 Section 6."""

    DATA = 0x0
    HEADERS = 0x1
    PRIORITY = 0x2
    RST_STREAM = 0x3
    SETTINGS = 0x4
    PUSH_PROMISE = 0x5
    PING = 0x6
    GOAWAY = 0x7
    WINDOW_UPDATE = 0x8
    CONTINUATION = 0x9


class ErrorCode(IntEnum):
    """HTTP/2 error codes per RFC 7540 Section 7."""

    NO_ERROR = 0x0
    PROTOCOL_ERROR = 0x1
    INTERNAL_ERROR = 0x2
    FLOW_CONTROL_ERROR = 0x3
    SETTINGS_TIMEOUT = 0x4
    STREAM_CLOSED = 0x5
    FRAME_SIZE_ERROR = 0x6
    REFUSED_STREAM = 0x7
    CANCEL = 0x8
    COMPRESSION_ERROR = 0x9
    CONNECT_ERROR = 0xA
    ENHANCE_YOUR_CALM = 0xB
    INADEQUATE_SECURITY = 0xC
    HTTP_1_1_REQUIRED = 0xD


class SettingsParameter(IntEnum):
    """HTTP/2 SETTINGS parameters per RFC 7540 Section 6.5.2."""

    HEADER_TABLE_SIZE = 0x1
    ENABLE_PUSH = 0x2
    MAX_CONCURRENT_STREAMS = 0x3
    INITIAL_WINDOW_SIZE = 0x4
    MAX_FRAME_SIZE = 0x5
    MAX_HEADER_LIST_SIZE = 0x6


class StreamState(IntEnum):
    """HTTP/2 stream states per RFC 7540 Section 5.1."""

    IDLE = auto()
    RESERVED_LOCAL = auto()
    RESERVED_REMOTE = auto()
    OPEN = auto()
    HALF_CLOSED_LOCAL = auto()
    HALF_CLOSED_REMOTE = auto()
    CLOSED = auto()


@dataclass(frozen=True)
class Frame:
    """Represents an HTTP/2 frame."""

    type: FrameType
    flags: int
    stream_id: int
    payload: bytes = b""

    def __post_init__(self) -> None:
        """Validate frame fields."""
        if not (0 <= self.type <= 9):
            raise ValueError(f"Invalid frame type: {self.type}")
        if not (0 <= self.flags <= 0xFF):
            raise ValueError(f"Invalid flags: {self.flags}")
        if not (0 <= self.stream_id <= 0x7FFFFFFF):
            raise ValueError(f"Invalid stream_id: {self.stream_id}")
        if len(self.payload) > 16384:
            raise ValueError(f"Payload too large: {len(self.payload)} > 16384")

    def has_flag(self, flag: int) -> bool:
        """Check if a flag is set."""
        return bool(self.flags & flag)

    def set_flag(self, flag: int) -> "Frame":
        """Return a new frame with flag set."""
        return Frame(
            type=self.type,
            flags=self.flags | flag,
            stream_id=self.stream_id,
            payload=self.payload,
        )


@dataclass
class Settings:
    """HTTP/2 settings."""

    header_table_size: int = 4096
    enable_push: bool = True
    max_concurrent_streams: int | None = None
    initial_window_size: int = 65535
    max_frame_size: int = 16384
    max_header_list_size: int | None = None

    def to_dict(self) -> dict[SettingsParameter, int]:
        """Convert settings to dictionary format."""
        result = {
            SettingsParameter.HEADER_TABLE_SIZE: self.header_table_size,
            SettingsParameter.ENABLE_PUSH: int(self.enable_push),
            SettingsParameter.INITIAL_WINDOW_SIZE: self.initial_window_size,
            SettingsParameter.MAX_FRAME_SIZE: self.max_frame_size,
        }
        if self.max_concurrent_streams is not None:
            result[SettingsParameter.MAX_CONCURRENT_STREAMS] = self.max_concurrent_streams
        if self.max_header_list_size is not None:
            result[SettingsParameter.MAX_HEADER_LIST_SIZE] = self.max_header_list_size
        return result

    @classmethod
    def from_dict(cls, settings: dict[SettingsParameter, int]) -> "Settings":
        """Create settings from dictionary."""
        return cls(
            header_table_size=settings.get(SettingsParameter.HEADER_TABLE_SIZE, 4096),
            enable_push=bool(settings.get(SettingsParameter.ENABLE_PUSH, True)),
            max_concurrent_streams=settings.get(SettingsParameter.MAX_CONCURRENT_STREAMS),
            initial_window_size=settings.get(SettingsParameter.INITIAL_WINDOW_SIZE, 65535),
            max_frame_size=settings.get(SettingsParameter.MAX_FRAME_SIZE, 16384),
            max_header_list_size=settings.get(SettingsParameter.MAX_HEADER_LIST_SIZE),
        )


@dataclass
class HTTP2Config:
    """HTTP/2 connection configuration."""

    # Connection settings
    client_settings: Settings = field(default_factory=Settings)
    server_settings: Settings = field(default_factory=Settings)

    # Flow control
    initial_window_size: int = 65535
    max_frame_size: int = 16384

    # Stream limits
    max_concurrent_streams: int = 100
    max_header_list_size: int | None = None

    # Header compression
    header_table_size: int = 4096

    # Timeouts and keepalive
    settings_timeout: float = 10.0
    ping_interval: float | None = None
    ping_timeout: float = 5.0

    # Server push
    enable_server_push: bool = True

    def validate(self) -> None:
        """Validate configuration."""
        if self.initial_window_size < 1 or self.initial_window_size > 2147483647:
            raise ValueError(f"Invalid initial_window_size: {self.initial_window_size}")
        if self.max_frame_size < 16384 or self.max_frame_size > 16777215:
            raise ValueError(f"Invalid max_frame_size: {self.max_frame_size}")
        if self.header_table_size < 0:
            raise ValueError(f"Invalid header_table_size: {self.header_table_size}")
        if self.max_concurrent_streams < 1:
            raise ValueError(f"Invalid max_concurrent_streams: {self.max_concurrent_streams}")
