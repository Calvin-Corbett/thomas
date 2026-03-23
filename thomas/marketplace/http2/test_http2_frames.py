"""Tests for HTTP/2 frame codec."""

import pytest

from thomas.marketplace.http2._exceptions import ProtocolError
from thomas.marketplace.http2._types import ErrorCode, Frame, FrameType, SettingsParameter
from thomas.marketplace.http2.frames import FrameCodec


class TestFrameCodec:
    """Tests for FrameCodec."""

    def setup_method(self) -> None:
        """Setup codec for each test."""
        self.codec = FrameCodec()

    def test_encode_decode_data_frame(self) -> None:
        """Test DATA frame encoding/decoding."""
        data = b"Hello, World!"
        encoded = self.codec.encode_data_frame(1, data, end_stream=False)

        # Decode header
        length, ftype, flags, stream_id = self.codec.decode_header(encoded)
        assert ftype == FrameType.DATA
        assert stream_id == 1
        assert length == len(data)

        # Decode full frame
        frame, consumed = self.codec.decode(encoded)
        assert frame.type == FrameType.DATA
        assert frame.stream_id == 1
        decoded_data, end_stream, padding = self.codec.decode_data_frame(frame)
        assert decoded_data == data
        assert end_stream is False

    def test_data_frame_end_stream_flag(self) -> None:
        """Test DATA frame with END_STREAM flag."""
        data = b"Final data"
        encoded = self.codec.encode_data_frame(1, data, end_stream=True)

        frame, _ = self.codec.decode(encoded)
        decoded_data, end_stream, _ = self.codec.decode_data_frame(frame)

        assert end_stream is True
        assert decoded_data == data

    def test_data_frame_with_padding(self) -> None:
        """Test DATA frame with padding."""
        data = b"test"
        padding = b"\x00\x00\x00"
        encoded = self.codec.encode_data_frame(1, data, padding=padding)

        frame, _ = self.codec.decode(encoded)
        decoded_data, _, padding_len = self.codec.decode_data_frame(frame)

        assert decoded_data == data
        assert padding_len == len(padding)

    def test_encode_decode_headers_frame(self) -> None:
        """Test HEADERS frame encoding/decoding."""
        header_block = b"\x00\x01\x02\x03"
        encoded = self.codec.encode_headers_frame(1, header_block, end_stream=False, end_headers=True)

        frame, _ = self.codec.decode(encoded)
        decoded_block, end_stream, end_headers, priority, _ = self.codec.decode_headers_frame(frame)

        assert decoded_block == header_block
        assert end_stream is False
        assert end_headers is True

    def test_headers_with_priority(self) -> None:
        """Test HEADERS frame with priority."""
        header_block = b"\x00\x01"
        priority = (0, 16, False)
        encoded = self.codec.encode_headers_frame(3, header_block, priority=priority)

        frame, _ = self.codec.decode(encoded)
        _, _, _, decoded_priority, _ = self.codec.decode_headers_frame(frame)

        assert decoded_priority == priority

    def test_headers_exclusive_dependency(self) -> None:
        """Test HEADERS with exclusive dependency."""
        header_block = b"\x00\x01"
        priority = (1, 20, True)
        encoded = self.codec.encode_headers_frame(3, header_block, priority=priority)

        frame, _ = self.codec.decode(encoded)
        _, _, _, decoded_priority, _ = self.codec.decode_headers_frame(frame)

        assert decoded_priority == priority

    def test_encode_decode_priority_frame(self) -> None:
        """Test PRIORITY frame encoding/decoding."""
        encoded = self.codec.encode_priority_frame(3, 1, 20, exclusive=False)

        frame, _ = self.codec.decode(encoded)
        depends_on, weight, exclusive = self.codec.decode_priority_frame(frame)

        assert depends_on == 1
        assert weight == 20
        assert exclusive is False

    def test_priority_exclusive(self) -> None:
        """Test PRIORITY with exclusive flag."""
        encoded = self.codec.encode_priority_frame(5, 1, 30, exclusive=True)

        frame, _ = self.codec.decode(encoded)
        depends_on, weight, exclusive = self.codec.decode_priority_frame(frame)

        assert depends_on == 1
        assert weight == 30
        assert exclusive is True

    def test_encode_decode_rst_stream_frame(self) -> None:
        """Test RST_STREAM frame encoding/decoding."""
        error_code = ErrorCode.STREAM_CLOSED
        encoded = self.codec.encode_rst_stream_frame(1, error_code)

        frame, _ = self.codec.decode(encoded)
        decoded_error = self.codec.decode_rst_stream_frame(frame)

        assert decoded_error == error_code

    def test_encode_decode_settings_frame(self) -> None:
        """Test SETTINGS frame encoding/decoding."""
        settings = {
            SettingsParameter.HEADER_TABLE_SIZE: 4096,
            SettingsParameter.ENABLE_PUSH: 1,
            SettingsParameter.INITIAL_WINDOW_SIZE: 65535,
        }
        encoded = self.codec.encode_settings_frame(settings)

        frame, _ = self.codec.decode(encoded)
        decoded_settings, ack = self.codec.decode_settings_frame(frame)

        assert decoded_settings == settings
        assert ack is False

    def test_settings_ack_frame(self) -> None:
        """Test SETTINGS ACK frame."""
        encoded = self.codec.encode_settings_frame({}, ack=True)

        frame, _ = self.codec.decode(encoded)
        settings, ack = self.codec.decode_settings_frame(frame)

        assert ack is True
        assert len(settings) == 0

    def test_encode_decode_ping_frame(self) -> None:
        """Test PING frame encoding/decoding."""
        data = b"\x00\x01\x02\x03\x04\x05\x06\x07"
        encoded = self.codec.encode_ping_frame(data)

        frame, _ = self.codec.decode(encoded)
        decoded_data, ack = self.codec.decode_ping_frame(frame)

        assert decoded_data == data
        assert ack is False

    def test_ping_ack_frame(self) -> None:
        """Test PING ACK frame."""
        data = b"\x00\x01\x02\x03\x04\x05\x06\x07"
        encoded = self.codec.encode_ping_frame(data, ack=True)

        frame, _ = self.codec.decode(encoded)
        decoded_data, ack = self.codec.decode_ping_frame(frame)

        assert decoded_data == data
        assert ack is True

    def test_encode_decode_goaway_frame(self) -> None:
        """Test GOAWAY frame encoding/decoding."""
        error_code = ErrorCode.FLOW_CONTROL_ERROR
        debug_data = b"debug info"
        encoded = self.codec.encode_goaway_frame(42, error_code, debug_data)

        frame, _ = self.codec.decode(encoded)
        last_id, decoded_error, decoded_debug = self.codec.decode_goaway_frame(frame)

        assert last_id == 42
        assert decoded_error == error_code
        assert decoded_debug == debug_data

    def test_encode_decode_window_update_frame(self) -> None:
        """Test WINDOW_UPDATE frame encoding/decoding."""
        increment = 65535
        encoded = self.codec.encode_window_update_frame(1, increment)

        frame, _ = self.codec.decode(encoded)
        decoded_increment = self.codec.decode_window_update_frame(frame)

        assert decoded_increment == increment

    def test_encode_decode_push_promise_frame(self) -> None:
        """Test PUSH_PROMISE frame encoding/decoding."""
        promised_id = 2
        header_block = b"\x00\x01\x02"
        encoded = self.codec.encode_push_promise_frame(1, promised_id, header_block, end_headers=True)

        frame, _ = self.codec.decode(encoded)
        decoded_id, decoded_block, end_headers, _ = self.codec.decode_push_promise_frame(frame)

        assert decoded_id == promised_id
        assert decoded_block == header_block
        assert end_headers is True

    def test_encode_decode_continuation_frame(self) -> None:
        """Test CONTINUATION frame encoding/decoding."""
        header_block = b"\x00\x01\x02\x03"
        encoded = self.codec.encode_continuation_frame(1, header_block, end_headers=True)

        frame, _ = self.codec.decode(encoded)
        decoded_block, end_headers = self.codec.decode_continuation_frame(frame)

        assert decoded_block == header_block
        assert end_headers is True

    def test_frame_payload_too_large(self) -> None:
        """Test that oversized payload raises error."""
        large_payload = b"x" * (16384 + 1)
        frame = Frame(
            type=FrameType.DATA,
            flags=0,
            stream_id=1,
            payload=large_payload,
        )

        with pytest.raises(ValueError):
            self.codec.encode(frame)

    def test_decode_incomplete_header(self) -> None:
        """Test that incomplete frame header raises error."""
        data = b"\x00\x00\x00"  # Only 3 bytes instead of 9

        with pytest.raises(ProtocolError):
            self.codec.decode_header(data)

    def test_decode_incomplete_frame(self) -> None:
        """Test that incomplete frame raises error."""
        # Header says 10 bytes, but only 5 provided
        data = b"\x00\x00\x0a\x00\x00\x00\x00\x00\x01\xaa\xbb"

        with pytest.raises(ProtocolError):
            self.codec.decode(data)

    def test_invalid_frame_type(self) -> None:
        """Test that invalid frame type raises error."""
        data = b"\x00\x00\x00\x0f\x00\x00\x00\x00\x01"  # Frame type 15 (invalid)

        with pytest.raises(ProtocolError):
            self.codec.decode_header(data)

    def test_stream_id_extraction(self) -> None:
        """Test that stream ID is extracted correctly."""
        # Stream ID with reserved bit set (should be masked)
        data = b"\x00\x00\x00\x00\x00\x80\x00\x00\x01"
        length, ftype, flags, stream_id = self.codec.decode_header(data)
        assert stream_id == 1  # Reserved bit should be masked off

    def test_max_frame_size_validation(self) -> None:
        """Test max frame size validation."""
        codec = FrameCodec(max_frame_size=100)

        # Try to encode frame larger than limit
        large_data = b"x" * 101
        with pytest.raises(ValueError):
            codec.encode_data_frame(1, large_data)

    def test_multiple_frames_decode(self) -> None:
        """Test decoding multiple consecutive frames."""
        frame1 = self.codec.encode_data_frame(1, b"data1")
        frame2 = self.codec.encode_data_frame(2, b"data2")
        frame3 = self.codec.encode_ping_frame(b"12345678")

        data = frame1 + frame2 + frame3

        # Decode first frame
        f1, pos1 = self.codec.decode(data)
        assert f1.stream_id == 1
        assert f1.type == FrameType.DATA

        # Decode second frame
        f2, pos2 = self.codec.decode(data[pos1:])
        assert f2.stream_id == 2
        assert f2.type == FrameType.DATA

        # Decode third frame
        f3, pos3 = self.codec.decode(data[pos1 + pos2 :])
        assert f3.type == FrameType.PING
