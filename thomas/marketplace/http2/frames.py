"""HTTP/2 frame codec for parsing and serializing frames."""

import struct

from thomas.marketplace.http2._exceptions import ProtocolError
from thomas.marketplace.http2._types import ErrorCode, Frame, FrameType, SettingsParameter


class FrameCodec:
    """Codec for encoding and decoding HTTP/2 frames."""

    FRAME_HEADER_SIZE = 9
    DEFAULT_MAX_FRAME_SIZE = 16384
    MAX_FRAME_SIZE = 16777215  # 2^24 - 1

    def __init__(self, max_frame_size: int = DEFAULT_MAX_FRAME_SIZE) -> None:
        """Initialize frame codec.

        Args:
            max_frame_size: Maximum allowed frame payload size (default 16384).
                           Must be between 16384 and 16777215 inclusive.

        Raises:
            ValueError: If max_frame_size is out of range.
        """
        if max_frame_size < 16384 or max_frame_size > self.MAX_FRAME_SIZE:
            raise ValueError(f"max_frame_size must be between 16384 and {self.MAX_FRAME_SIZE}, got {max_frame_size}")
        self.max_frame_size = max_frame_size

    def encode(self, frame: Frame) -> bytes:
        """Encode a frame to bytes.

        Args:
            frame: Frame to encode.

        Returns:
            Encoded frame as bytes.

        Raises:
            ValueError: If payload exceeds max_frame_size.
        """
        if len(frame.payload) > self.max_frame_size:
            raise ValueError(f"Frame payload too large: {len(frame.payload)} > {self.max_frame_size}")

        # Frame header: 3-byte length + 1-byte type + 1-byte flags + 4-byte stream ID
        length = len(frame.payload)
        header = struct.pack(
            "!3sBBi",
            length.to_bytes(3, "big"),
            frame.type,
            frame.flags,
            frame.stream_id & 0x7FFFFFFF,
        )
        return header + frame.payload

    def decode_header(self, data: bytes) -> tuple[int, FrameType, int, int]:
        """Decode frame header (9 bytes).

        Args:
            data: At least 9 bytes of frame data.

        Returns:
            Tuple of (length, type, flags, stream_id).

        Raises:
            ProtocolError: If header is invalid.
        """
        if len(data) < self.FRAME_HEADER_SIZE:
            raise ProtocolError(f"Frame header too short: {len(data)} < {self.FRAME_HEADER_SIZE}")

        length_bytes = data[0:3]
        length = int.from_bytes(length_bytes, "big")

        frame_type = data[3]
        flags = data[4]
        stream_id = struct.unpack("!i", data[5:9])[0] & 0x7FFFFFFF

        if length > self.max_frame_size:
            raise ProtocolError(f"Frame payload exceeds max_frame_size: {length} > {self.max_frame_size}")

        try:
            frame_type = FrameType(frame_type)
        except ValueError:
            raise ProtocolError(f"Invalid frame type: {frame_type}")

        return length, frame_type, flags, stream_id

    def decode(self, data: bytes) -> tuple[Frame, int]:
        """Decode a complete frame from bytes.

        Args:
            data: Frame data (header + payload).

        Returns:
            Tuple of (Frame, bytes_consumed).

        Raises:
            ProtocolError: If frame is invalid.
        """
        length, frame_type, flags, stream_id = self.decode_header(data)

        required_length = self.FRAME_HEADER_SIZE + length
        if len(data) < required_length:
            raise ProtocolError(f"Incomplete frame: {len(data)} < {required_length}")

        payload = data[self.FRAME_HEADER_SIZE : required_length]

        # Validate payload for specific frame types
        if frame_type == FrameType.DATA:
            self._validate_data_frame(flags, payload)
        elif frame_type == FrameType.HEADERS:
            self._validate_headers_frame(flags, payload)
        elif frame_type == FrameType.PRIORITY:
            self._validate_priority_frame(payload)
        elif frame_type == FrameType.RST_STREAM:
            self._validate_rst_stream_frame(payload)
        elif frame_type == FrameType.SETTINGS:
            self._validate_settings_frame(payload)
        elif frame_type == FrameType.PUSH_PROMISE:
            self._validate_push_promise_frame(flags, payload)
        elif frame_type == FrameType.PING:
            self._validate_ping_frame(payload)
        elif frame_type == FrameType.GOAWAY:
            self._validate_goaway_frame(payload)
        elif frame_type == FrameType.WINDOW_UPDATE:
            self._validate_window_update_frame(payload)
        elif frame_type == FrameType.CONTINUATION:
            self._validate_continuation_frame(payload)

        return Frame(
            type=frame_type,
            flags=flags,
            stream_id=stream_id,
            payload=payload,
        ), required_length

    def _validate_data_frame(self, flags: int, payload: bytes) -> None:
        """Validate DATA frame payload."""
        if flags & 0x08:  # PADDED flag
            if len(payload) < 1:
                raise ProtocolError("DATA frame with PADDED flag has no padding length")
            padding_length = payload[0]
            if padding_length >= len(payload):
                raise ProtocolError(f"Padding length too large: {padding_length} >= {len(payload)}")

    def _validate_headers_frame(self, flags: int, payload: bytes) -> None:
        """Validate HEADERS frame payload."""
        offset = 0
        if flags & 0x20:  # PRIORITY flag
            if len(payload) < 5:
                raise ProtocolError("HEADERS frame with PRIORITY flag requires at least 5 bytes")
            offset = 5
        if flags & 0x08:  # PADDED flag
            if len(payload) < offset + 1:
                raise ProtocolError("HEADERS frame with PADDED flag has no padding length")
            padding_length = payload[offset]
            if padding_length >= len(payload) - offset:
                raise ProtocolError(f"Padding length too large: {padding_length} >= {len(payload) - offset}")

    def _validate_priority_frame(self, payload: bytes) -> None:
        """Validate PRIORITY frame payload."""
        if len(payload) != 5:
            raise ProtocolError(f"PRIORITY frame must be exactly 5 bytes, got {len(payload)}")

    def _validate_rst_stream_frame(self, payload: bytes) -> None:
        """Validate RST_STREAM frame payload."""
        if len(payload) != 4:
            raise ProtocolError(f"RST_STREAM frame must be exactly 4 bytes, got {len(payload)}")

    def _validate_settings_frame(self, payload: bytes) -> None:
        """Validate SETTINGS frame payload."""
        if len(payload) % 6 != 0:
            raise ProtocolError(f"SETTINGS frame payload must be multiple of 6 bytes, got {len(payload)}")

    def _validate_push_promise_frame(self, flags: int, payload: bytes) -> None:
        """Validate PUSH_PROMISE frame payload."""
        if len(payload) < 4:
            raise ProtocolError(f"PUSH_PROMISE frame must be at least 4 bytes, got {len(payload)}")
        if flags & 0x08:  # PADDED flag
            if len(payload) < 5:
                raise ProtocolError("PUSH_PROMISE frame with PADDED flag has no padding length")
            padding_length = payload[4]
            if padding_length >= len(payload) - 4:
                raise ProtocolError(f"Padding length too large: {padding_length} >= {len(payload) - 4}")

    def _validate_ping_frame(self, payload: bytes) -> None:
        """Validate PING frame payload."""
        if len(payload) != 8:
            raise ProtocolError(f"PING frame must be exactly 8 bytes, got {len(payload)}")

    def _validate_goaway_frame(self, payload: bytes) -> None:
        """Validate GOAWAY frame payload."""
        if len(payload) < 8:
            raise ProtocolError(f"GOAWAY frame must be at least 8 bytes, got {len(payload)}")

    def _validate_window_update_frame(self, payload: bytes) -> None:
        """Validate WINDOW_UPDATE frame payload."""
        if len(payload) != 4:
            raise ProtocolError(f"WINDOW_UPDATE frame must be exactly 4 bytes, got {len(payload)}")

    def _validate_continuation_frame(self, payload: bytes) -> None:
        """Validate CONTINUATION frame payload."""
        pass  # CONTINUATION can have any length

    def encode_data_frame(
        self,
        stream_id: int,
        data: bytes,
        end_stream: bool = False,
        padding: bytes | None = None,
    ) -> bytes:
        """Encode a DATA frame.

        Args:
            stream_id: Stream ID.
            data: Frame data.
            end_stream: Whether this is the last DATA frame.
            padding: Optional padding bytes.

        Returns:
            Encoded frame bytes.
        """
        flags = 0
        payload = data

        if padding is not None:
            flags |= 0x08  # PADDED
            payload = bytes([len(padding)]) + payload + padding
        if end_stream:
            flags |= 0x01  # END_STREAM

        frame = Frame(
            type=FrameType.DATA,
            flags=flags,
            stream_id=stream_id,
            payload=payload,
        )
        return self.encode(frame)

    def decode_data_frame(self, frame: Frame) -> tuple[bytes, bool, int | None]:
        """Decode a DATA frame.

        Args:
            frame: Frame to decode.

        Returns:
            Tuple of (data, end_stream, padding_length).
        """
        if frame.type != FrameType.DATA:
            raise ProtocolError(f"Expected DATA frame, got {frame.type}")

        payload = frame.payload
        end_stream = bool(frame.flags & 0x01)
        padding_length: int | None = None

        if frame.flags & 0x08:  # PADDED
            padding_length = payload[0]
            payload = payload[1 : len(payload) - padding_length]
        else:
            payload = payload

        return payload, end_stream, padding_length

    def encode_headers_frame(
        self,
        stream_id: int,
        header_block: bytes,
        end_stream: bool = False,
        end_headers: bool = True,
        priority: tuple[int, int, bool] | None = None,
        padding: bytes | None = None,
    ) -> bytes:
        """Encode a HEADERS frame.

        Args:
            stream_id: Stream ID.
            header_block: Encoded header block fragment.
            end_stream: Whether this is the last frame for the stream.
            end_headers: Whether this is the last header frame.
            priority: Tuple of (depends_on, weight, exclusive).
            padding: Optional padding bytes.

        Returns:
            Encoded frame bytes.
        """
        flags = 0
        payload = b""

        if priority is not None:
            flags |= 0x20  # PRIORITY
            depends_on, weight, exclusive = priority
            if exclusive:
                depends_on |= 0x80000000
            payload += struct.pack("!I", depends_on)
            payload += bytes([weight - 1])

        if end_stream:
            flags |= 0x01  # END_STREAM
        if end_headers:
            flags |= 0x04  # END_HEADERS

        payload += header_block

        if padding is not None:
            flags |= 0x08  # PADDED
            payload = bytes([len(padding)]) + payload + padding

        frame = Frame(
            type=FrameType.HEADERS,
            flags=flags,
            stream_id=stream_id,
            payload=payload,
        )
        return self.encode(frame)

    def decode_headers_frame(self, frame: Frame) -> tuple[bytes, bool, bool, tuple[int, int, bool] | None, int | None]:
        """Decode a HEADERS frame.

        Args:
            frame: Frame to decode.

        Returns:
            Tuple of (header_block, end_stream, end_headers,
                     priority (depends_on, weight, exclusive), padding_length).
        """
        if frame.type != FrameType.HEADERS:
            raise ProtocolError(f"Expected HEADERS frame, got {frame.type}")

        payload = frame.payload
        offset = 0
        end_stream = bool(frame.flags & 0x01)
        end_headers = bool(frame.flags & 0x04)
        priority: tuple[int, int, bool] | None = None
        padding_length: int | None = None

        if frame.flags & 0x08:  # PADDED
            padding_length = payload[0]
            offset = 1

        if frame.flags & 0x20:  # PRIORITY
            depends_on = struct.unpack("!I", payload[offset : offset + 4])[0]
            exclusive = bool(depends_on & 0x80000000)
            depends_on &= 0x7FFFFFFF
            weight = payload[offset + 4] + 1
            priority = (depends_on, weight, exclusive)
            offset += 5

        header_block = payload[offset:]
        if padding_length is not None:
            header_block = header_block[:-padding_length]

        return header_block, end_stream, end_headers, priority, padding_length

    def encode_settings_frame(self, settings: dict[SettingsParameter, int], ack: bool = False) -> bytes:
        """Encode a SETTINGS frame.

        Args:
            settings: Dictionary of parameter ID to value.
            ack: Whether this is a SETTINGS ACK frame.

        Returns:
            Encoded frame bytes.
        """
        flags = 0x01 if ack else 0x00
        payload = b""

        for param, value in settings.items():
            payload += struct.pack("!HI", param, value)

        frame = Frame(
            type=FrameType.SETTINGS,
            flags=flags,
            stream_id=0,
            payload=payload,
        )
        return self.encode(frame)

    def decode_settings_frame(self, frame: Frame) -> tuple[dict[SettingsParameter, int], bool]:
        """Decode a SETTINGS frame.

        Args:
            frame: Frame to decode.

        Returns:
            Tuple of (settings_dict, is_ack).
        """
        if frame.type != FrameType.SETTINGS:
            raise ProtocolError(f"Expected SETTINGS frame, got {frame.type}")

        is_ack = bool(frame.flags & 0x01)
        settings: dict[SettingsParameter, int] = {}

        for i in range(0, len(frame.payload), 6):
            param, value = struct.unpack("!HI", frame.payload[i : i + 6])
            try:
                param_enum = SettingsParameter(param)
            except ValueError:
                param_enum = param  # Allow unknown parameters
            settings[param_enum] = value

        return settings, is_ack

    def encode_rst_stream_frame(self, stream_id: int, error_code: ErrorCode) -> bytes:
        """Encode a RST_STREAM frame.

        Args:
            stream_id: Stream ID.
            error_code: Error code.

        Returns:
            Encoded frame bytes.
        """
        payload = struct.pack("!I", error_code)
        frame = Frame(
            type=FrameType.RST_STREAM,
            flags=0,
            stream_id=stream_id,
            payload=payload,
        )
        return self.encode(frame)

    def decode_rst_stream_frame(self, frame: Frame) -> ErrorCode:
        """Decode a RST_STREAM frame.

        Args:
            frame: Frame to decode.

        Returns:
            Error code.
        """
        if frame.type != FrameType.RST_STREAM:
            raise ProtocolError(f"Expected RST_STREAM frame, got {frame.type}")

        error_code = struct.unpack("!I", frame.payload)[0]
        try:
            return ErrorCode(error_code)
        except ValueError:
            return error_code  # Allow unknown error codes

    def encode_goaway_frame(
        self,
        last_stream_id: int,
        error_code: ErrorCode,
        debug_data: bytes | None = None,
    ) -> bytes:
        """Encode a GOAWAY frame.

        Args:
            last_stream_id: Last stream ID.
            error_code: Error code.
            debug_data: Optional debug data.

        Returns:
            Encoded frame bytes.
        """
        payload = struct.pack("!II", last_stream_id, error_code)
        if debug_data is not None:
            payload += debug_data

        frame = Frame(
            type=FrameType.GOAWAY,
            flags=0,
            stream_id=0,
            payload=payload,
        )
        return self.encode(frame)

    def decode_goaway_frame(self, frame: Frame) -> tuple[int, ErrorCode, bytes]:
        """Decode a GOAWAY frame.

        Args:
            frame: Frame to decode.

        Returns:
            Tuple of (last_stream_id, error_code, debug_data).
        """
        if frame.type != FrameType.GOAWAY:
            raise ProtocolError(f"Expected GOAWAY frame, got {frame.type}")

        last_stream_id, error_code = struct.unpack("!II", frame.payload[:8])
        debug_data = frame.payload[8:]

        try:
            error_code = ErrorCode(error_code)
        except ValueError:
            pass  # Allow unknown error codes

        return last_stream_id, error_code, debug_data

    def encode_ping_frame(self, opaque_data: bytes, ack: bool = False) -> bytes:
        """Encode a PING frame.

        Args:
            opaque_data: 8 bytes of opaque data.
            ack: Whether this is a PING ACK.

        Returns:
            Encoded frame bytes.
        """
        if len(opaque_data) != 8:
            raise ValueError(f"PING data must be 8 bytes, got {len(opaque_data)}")

        flags = 0x01 if ack else 0x00
        frame = Frame(
            type=FrameType.PING,
            flags=flags,
            stream_id=0,
            payload=opaque_data,
        )
        return self.encode(frame)

    def decode_ping_frame(self, frame: Frame) -> tuple[bytes, bool]:
        """Decode a PING frame.

        Args:
            frame: Frame to decode.

        Returns:
            Tuple of (opaque_data, is_ack).
        """
        if frame.type != FrameType.PING:
            raise ProtocolError(f"Expected PING frame, got {frame.type}")

        is_ack = bool(frame.flags & 0x01)
        return frame.payload, is_ack

    def encode_window_update_frame(self, stream_id: int, window_increment: int) -> bytes:
        """Encode a WINDOW_UPDATE frame.

        Args:
            stream_id: Stream ID (0 for connection).
            window_increment: Window size increment (1-2147483647).

        Returns:
            Encoded frame bytes.
        """
        if window_increment < 1 or window_increment > 0x7FFFFFFF:
            raise ValueError(f"Window increment must be 1-2147483647, got {window_increment}")

        payload = struct.pack("!I", window_increment)
        frame = Frame(
            type=FrameType.WINDOW_UPDATE,
            flags=0,
            stream_id=stream_id,
            payload=payload,
        )
        return self.encode(frame)

    def decode_window_update_frame(self, frame: Frame) -> int:
        """Decode a WINDOW_UPDATE frame.

        Args:
            frame: Frame to decode.

        Returns:
            Window increment value.
        """
        if frame.type != FrameType.WINDOW_UPDATE:
            raise ProtocolError(f"Expected WINDOW_UPDATE frame, got {frame.type}")

        return struct.unpack("!I", frame.payload)[0] & 0x7FFFFFFF

    def encode_priority_frame(
        self,
        stream_id: int,
        depends_on: int,
        weight: int,
        exclusive: bool = False,
    ) -> bytes:
        """Encode a PRIORITY frame.

        Args:
            stream_id: Stream ID.
            depends_on: Parent stream ID.
            weight: Stream weight (1-256).
            exclusive: Whether dependency is exclusive.

        Returns:
            Encoded frame bytes.
        """
        if weight < 1 or weight > 256:
            raise ValueError(f"Weight must be 1-256, got {weight}")

        if exclusive:
            depends_on |= 0x80000000

        payload = struct.pack("!I", depends_on)
        payload += bytes([weight - 1])

        frame = Frame(
            type=FrameType.PRIORITY,
            flags=0,
            stream_id=stream_id,
            payload=payload,
        )
        return self.encode(frame)

    def decode_priority_frame(self, frame: Frame) -> tuple[int, int, bool]:
        """Decode a PRIORITY frame.

        Args:
            frame: Frame to decode.

        Returns:
            Tuple of (depends_on, weight, exclusive).
        """
        if frame.type != FrameType.PRIORITY:
            raise ProtocolError(f"Expected PRIORITY frame, got {frame.type}")

        depends_on = struct.unpack("!I", frame.payload[:4])[0]
        exclusive = bool(depends_on & 0x80000000)
        depends_on &= 0x7FFFFFFF
        weight = frame.payload[4] + 1

        return depends_on, weight, exclusive

    def encode_push_promise_frame(
        self,
        stream_id: int,
        promised_stream_id: int,
        header_block: bytes,
        end_headers: bool = True,
        padding: bytes | None = None,
    ) -> bytes:
        """Encode a PUSH_PROMISE frame.

        Args:
            stream_id: Stream ID.
            promised_stream_id: Promised stream ID.
            header_block: Encoded header block.
            end_headers: Whether this is the last header frame.
            padding: Optional padding.

        Returns:
            Encoded frame bytes.
        """
        flags = 0x04 if end_headers else 0x00
        payload = struct.pack("!I", promised_stream_id)

        if padding is not None:
            flags |= 0x08
            payload = bytes([len(padding)]) + payload + header_block + padding
        else:
            payload = payload + header_block

        frame = Frame(
            type=FrameType.PUSH_PROMISE,
            flags=flags,
            stream_id=stream_id,
            payload=payload,
        )
        return self.encode(frame)

    def decode_push_promise_frame(self, frame: Frame) -> tuple[int, bytes, bool, int | None]:
        """Decode a PUSH_PROMISE frame.

        Args:
            frame: Frame to decode.

        Returns:
            Tuple of (promised_stream_id, header_block, end_headers, padding_length).
        """
        if frame.type != FrameType.PUSH_PROMISE:
            raise ProtocolError(f"Expected PUSH_PROMISE frame, got {frame.type}")

        payload = frame.payload
        offset = 0
        padding_length: int | None = None

        if frame.flags & 0x08:
            padding_length = payload[0]
            offset = 1

        promised_stream_id = struct.unpack("!I", payload[offset : offset + 4])[0]
        offset += 4

        header_block = payload[offset:]
        if padding_length is not None:
            header_block = header_block[:-padding_length]

        end_headers = bool(frame.flags & 0x04)
        return promised_stream_id, header_block, end_headers, padding_length

    def encode_continuation_frame(self, stream_id: int, header_block: bytes, end_headers: bool = True) -> bytes:
        """Encode a CONTINUATION frame.

        Args:
            stream_id: Stream ID.
            header_block: Header block fragment.
            end_headers: Whether this is the last header frame.

        Returns:
            Encoded frame bytes.
        """
        flags = 0x04 if end_headers else 0x00
        frame = Frame(
            type=FrameType.CONTINUATION,
            flags=flags,
            stream_id=stream_id,
            payload=header_block,
        )
        return self.encode(frame)

    def decode_continuation_frame(self, frame: Frame) -> tuple[bytes, bool]:
        """Decode a CONTINUATION frame.

        Args:
            frame: Frame to decode.

        Returns:
            Tuple of (header_block, end_headers).
        """
        if frame.type != FrameType.CONTINUATION:
            raise ProtocolError(f"Expected CONTINUATION frame, got {frame.type}")

        end_headers = bool(frame.flags & 0x04)
        return frame.payload, end_headers
