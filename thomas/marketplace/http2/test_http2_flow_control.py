"""Tests for HTTP/2 flow control."""

import pytest

from thomas.marketplace.http2._exceptions import FlowControlError
from thomas.marketplace.http2.flow_control import FlowControlEngine


class TestFlowControlEngine:
    """Tests for FlowControlEngine."""

    def setup_method(self) -> None:
        """Setup flow control engine."""
        self.engine = FlowControlEngine(initial_window_size=65535)

    def test_initialization(self) -> None:
        """Test initialization."""
        assert self.engine.get_connection_window() == 65535
        assert self.engine.initial_window_size == 65535

    def test_create_stream_window(self) -> None:
        """Test creating stream window."""
        self.engine.create_stream(1)
        assert self.engine.get_stream_window(1) == 65535

    def test_create_stream_custom_window(self) -> None:
        """Test creating stream with custom window size."""
        self.engine.create_stream(1, window_size=32768)
        assert self.engine.get_stream_window(1) == 32768

    def test_send_data_connection(self) -> None:
        """Test sending data on connection."""
        conn_use, stream_use = self.engine.send_data(0, 100)

        assert conn_use == 100
        assert stream_use == 0
        assert self.engine.get_connection_window() == 65535 - 100

    def test_send_data_stream(self) -> None:
        """Test sending data on stream."""
        self.engine.create_stream(1)
        conn_use, stream_use = self.engine.send_data(1, 1000)

        assert conn_use == 1000
        assert stream_use == 1000
        assert self.engine.get_connection_window() == 65535 - 1000
        assert self.engine.get_stream_window(1) == 65535 - 1000

    def test_send_data_window_exhaustion(self) -> None:
        """Test window exhaustion on send."""
        self.engine.create_stream(1)

        with pytest.raises(FlowControlError):
            self.engine.send_data(1, 100000)

        # Window should be unchanged
        assert self.engine.get_stream_window(1) == 65535

    def test_send_data_partial_use(self) -> None:
        """Test partial window use on send."""
        self.engine.create_stream(1)
        # Exhaust connection window
        self.engine.send_data(0, 65535)

        # Try to send on stream
        with pytest.raises(FlowControlError):
            self.engine.send_data(1, 1000)

    def test_receive_data_connection(self) -> None:
        """Test receiving data on connection."""
        # First consume some window
        self.engine.send_data(0, 100)
        assert self.engine.get_connection_window() == 65435

        # Receive data (simulating receiver-side update)
        received = self.engine.receive_data(0, 50)
        assert received == 50
        assert self.engine.get_connection_window() == 65485

    def test_receive_data_stream(self) -> None:
        """Test receiving data on stream."""
        self.engine.create_stream(1)
        self.engine.send_data(1, 100)

        received = self.engine.receive_data(1, 50)
        assert received == 50
        assert self.engine.get_stream_window(1) == 65535 - 100 + 50

    def test_consume_data_connection(self) -> None:
        """Test consuming received data on connection."""
        self.engine.receive_data(0, 100)

        before, _ = self.engine.consume_data(0, 50)
        assert before == 65535 + 100
        assert self.engine.get_connection_window() == 65535 + 100 - 50

    def test_consume_data_stream(self) -> None:
        """Test consuming received data on stream."""
        self.engine.create_stream(1)
        self.engine.receive_data(1, 100)

        before, stream_before = self.engine.consume_data(1, 50)
        assert stream_before == 65535 + 100
        assert self.engine.get_stream_window(1) == 65535 + 100 - 50

    def test_consume_data_exhaustion(self) -> None:
        """Test consuming more data than available."""
        self.engine.create_stream(1)

        with pytest.raises(FlowControlError):
            self.engine.consume_data(1, 100000)

    def test_increment_window(self) -> None:
        """Test window increment (WINDOW_UPDATE)."""
        self.engine.create_stream(1)
        self.engine.send_data(1, 100)

        self.engine.increment_window(1, 50)
        assert self.engine.get_stream_window(1) == 65535 - 100 + 50

    def test_increment_window_connection(self) -> None:
        """Test connection window increment."""
        self.engine.send_data(0, 1000)

        self.engine.increment_window(0, 500)
        assert self.engine.get_connection_window() == 65535 - 1000 + 500

    def test_increment_window_overflow(self) -> None:
        """Test window overflow on increment."""
        self.engine.create_stream(1)

        # Try to increment beyond max
        with pytest.raises(FlowControlError):
            self.engine.increment_window(1, 2147483648)

    def test_increment_window_closed_stream(self) -> None:
        """Test incrementing window on removed stream."""
        self.engine.create_stream(1)
        self.engine.remove_stream(1)

        # Should not raise, just be ignored
        self.engine.increment_window(1, 100)

    def test_set_initial_window_size(self) -> None:
        """Test updating initial window size."""
        self.engine.create_stream(1)
        self.engine.send_data(1, 100)

        # Increase initial window size
        self.engine.set_initial_window_size(100000)

        # Stream window should be adjusted
        assert self.engine.get_stream_window(1) == 100000 - 100

    def test_set_initial_window_size_decrease(self) -> None:
        """Test decreasing initial window size."""
        self.engine.create_stream(1)

        # Decrease initial window size
        self.engine.set_initial_window_size(10000)

        # Stream window should be adjusted
        assert self.engine.get_stream_window(1) == 10000

    def test_set_initial_window_size_invalid(self) -> None:
        """Test invalid initial window size."""
        with pytest.raises(ValueError):
            self.engine.set_initial_window_size(0)

        with pytest.raises(ValueError):
            self.engine.set_initial_window_size(2147483648)

    def test_should_send_window_update(self) -> None:
        """Test window update decision."""
        self.engine.create_stream(1)

        # No update needed initially
        assert not self.engine.should_send_window_update(1, threshold=0.5)

        # Consume half the window
        self.engine.send_data(1, 32768)

        # Now should send update
        assert self.engine.should_send_window_update(1, threshold=0.5)

    def test_get_window_update_size(self) -> None:
        """Test calculating window update size."""
        self.engine.create_stream(1)
        self.engine.send_data(1, 10000)

        update_size = self.engine.get_window_update_size(1)
        assert update_size == 10000

    def test_is_window_exhausted(self) -> None:
        """Test checking window exhaustion."""
        self.engine.create_stream(1)

        assert not self.engine.is_window_exhausted(1)

        self.engine.send_data(1, 65535)
        assert self.engine.is_window_exhausted(1)

    def test_is_window_exhausted_connection(self) -> None:
        """Test connection window exhaustion."""
        assert not self.engine.is_window_exhausted(0)

        self.engine.send_data(0, 65535)
        assert self.engine.is_window_exhausted(0)

    def test_get_state(self) -> None:
        """Test getting flow control state."""
        self.engine.create_stream(1)
        self.engine.send_data(1, 100)

        state = self.engine.get_state()
        assert state["connection_window"] == 65535 - 100
        assert state["stream_windows"][1] == 65535 - 100
        assert state["initial_window_size"] == 65535

    def test_remove_stream(self) -> None:
        """Test removing stream."""
        self.engine.create_stream(1)
        assert 1 in self.engine.stream_windows

        self.engine.remove_stream(1)
        assert 1 not in self.engine.stream_windows

    def test_multiple_streams_independent_windows(self) -> None:
        """Test that stream windows are independent."""
        self.engine.create_stream(1)
        self.engine.create_stream(3)

        self.engine.send_data(1, 1000)
        self.engine.send_data(3, 2000)

        assert self.engine.get_stream_window(1) == 65535 - 1000
        assert self.engine.get_stream_window(3) == 65535 - 2000

    def test_connection_window_shared(self) -> None:
        """Test that connection window is shared."""
        self.engine.create_stream(1)
        self.engine.create_stream(3)

        self.engine.send_data(1, 1000)
        self.engine.send_data(3, 2000)

        # Both use same connection window
        assert self.engine.get_connection_window() == 65535 - 3000

    def test_max_window_size(self) -> None:
        """Test maximum window size enforcement."""
        with pytest.raises(ValueError):
            FlowControlEngine(initial_window_size=2147483648)

    def test_min_window_size(self) -> None:
        """Test minimum window size enforcement."""
        with pytest.raises(ValueError):
            FlowControlEngine(initial_window_size=0)

    def test_negative_length(self) -> None:
        """Test that negative length raises error."""
        with pytest.raises(ValueError):
            self.engine.send_data(0, -100)

        with pytest.raises(ValueError):
            self.engine.receive_data(0, -100)

        with pytest.raises(ValueError):
            self.engine.consume_data(0, -100)

    def test_invalid_increment(self) -> None:
        """Test invalid window increment."""
        with pytest.raises(ValueError):
            self.engine.increment_window(0, 0)

        with pytest.raises(ValueError):
            self.engine.increment_window(0, -100)

        with pytest.raises(ValueError):
            self.engine.increment_window(0, 2147483648)
