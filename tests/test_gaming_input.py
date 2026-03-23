"""Tests for input system."""

from thomas.marketplace.gaming_platform.input import (
    GamepadAxis,
    GamepadButton,
    InputBuffer,
    InputManager,
    InputRecorder,
    KeyCode,
    MouseButton,
)


class TestInputBuffer:
    """Test input buffer for combos."""

    def test_buffer_creation(self) -> None:
        """Test input buffer initialization."""
        buffer = InputBuffer(buffer_size=60)
        assert buffer.buffer_size == 60

    def test_add_input(self) -> None:
        """Test adding input to buffer."""
        buffer = InputBuffer(buffer_size=10)
        buffer.add_input("jump")
        assert "jump" in buffer.buffer[0]

    def test_buffer_advance(self) -> None:
        """Test advancing buffer frame."""
        buffer = InputBuffer(buffer_size=10)
        buffer.add_input("jump")
        buffer.advance()

        assert "jump" not in buffer.buffer[0]

    def test_sequence_detection(self) -> None:
        """Test detecting input sequence."""
        buffer = InputBuffer(buffer_size=60)

        # Record sequence: jump, dash, jump
        buffer.add_input("jump")
        buffer.advance()
        buffer.add_input("dash")
        buffer.advance()
        buffer.add_input("jump")

        # Check sequence
        assert buffer.has_sequence(["jump", "dash", "jump"], max_frames=10)

    def test_sequence_not_found(self) -> None:
        """Test sequence not found."""
        buffer = InputBuffer(buffer_size=60)
        buffer.add_input("jump")

        assert not buffer.has_sequence(["dash", "jump"], max_frames=10)

    def test_buffer_wraparound(self) -> None:
        """Test buffer circular wraparound."""
        buffer = InputBuffer(buffer_size=5)

        for i in range(10):
            buffer.add_input(f"action_{i}")
            buffer.advance()

        # Should only remember last 5
        assert len([f for f in buffer.buffer if f]) <= 5


class TestInputRecorder:
    """Test input recording and playback."""

    def test_recorder_creation(self) -> None:
        """Test recorder initialization."""
        recorder = InputRecorder()
        assert not recorder.is_recording
        assert not recorder.is_playing

    def test_start_stop_recording(self) -> None:
        """Test recording control."""
        recorder = InputRecorder()
        recorder.start_recording()
        assert recorder.is_recording

        recorder.stop_recording()
        assert not recorder.is_recording

    def test_record_inputs(self) -> None:
        """Test recording input frames."""
        recorder = InputRecorder()
        recorder.start_recording()

        inputs = {"jump": True, "move_x": 0.5}
        recorder.record_frame(inputs)

        assert len(recorder.recording) == 1
        assert recorder.recording[0]["jump"] is True

    def test_playback(self) -> None:
        """Test input playback."""
        recorder = InputRecorder()
        recorder.start_recording()

        # Record sequence
        recorder.record_frame({"jump": True})
        recorder.record_frame({"move_x": 1.0})
        recorder.stop_recording()

        # Playback
        recorder.start_playback()
        inputs1 = recorder.get_playback_inputs()
        assert inputs1 is not None
        assert inputs1["jump"] is True

    def test_playback_completion(self) -> None:
        """Test playback finishing."""
        recorder = InputRecorder()
        recorder.start_recording()
        recorder.record_frame({"action": True})
        recorder.stop_recording()

        recorder.start_playback()
        recorder.get_playback_inputs()

        # Should stop after all frames
        result = recorder.get_playback_inputs()
        assert result is None


class TestInputManager:
    """Test input manager."""

    def test_manager_creation(self) -> None:
        """Test input manager initialization."""
        manager = InputManager()
        assert len(manager.keys_pressed) == 0
        assert manager.mouse_position == (0.0, 0.0)

    def test_key_pressed(self) -> None:
        """Test key press detection."""
        manager = InputManager()

        manager.set_key_pressed(KeyCode.W, True)
        assert manager.is_key_pressed(KeyCode.W)
        assert not manager.is_key_pressed(KeyCode.A)

    def test_key_just_pressed(self) -> None:
        """Test detecting key press on this frame."""
        manager = InputManager()

        manager.set_key_pressed(KeyCode.SPACE, True)
        assert manager.is_key_just_pressed(KeyCode.SPACE)

        manager.update()
        assert not manager.is_key_just_pressed(KeyCode.SPACE)
        assert manager.is_key_pressed(KeyCode.SPACE)

    def test_key_just_released(self) -> None:
        """Test detecting key release."""
        manager = InputManager()

        manager.set_key_pressed(KeyCode.SPACE, True)
        manager.update()

        manager.set_key_pressed(KeyCode.SPACE, False)
        assert manager.is_key_just_released(KeyCode.SPACE)

    def test_mouse_position(self) -> None:
        """Test mouse position tracking."""
        manager = InputManager()

        manager.set_mouse_position(100.0, 200.0)
        assert manager.mouse_position == (100.0, 200.0)

    def test_mouse_buttons(self) -> None:
        """Test mouse button states."""
        manager = InputManager()

        manager.set_mouse_button(MouseButton.LEFT, True)
        assert manager.is_mouse_button_pressed(MouseButton.LEFT)

        manager.update()
        manager.set_mouse_button(MouseButton.LEFT, False)
        assert manager.is_mouse_button_just_released(MouseButton.LEFT)

    def test_gamepad_axes(self) -> None:
        """Test gamepad analog stick input."""
        manager = InputManager()

        manager.set_gamepad_axis(0, GamepadAxis.LEFT_STICK_X, 0.5)
        value = manager.get_gamepad_axis(0, GamepadAxis.LEFT_STICK_X)
        assert value == 0.5

    def test_gamepad_dead_zone(self) -> None:
        """Test dead zone filtering."""
        manager = InputManager()
        manager.stick_dead_zone = 0.15

        # Below dead zone
        manager.set_gamepad_axis(0, GamepadAxis.LEFT_STICK_X, 0.1)
        assert manager.get_gamepad_axis(0, GamepadAxis.LEFT_STICK_X) == 0.0

        # Above dead zone
        manager.set_gamepad_axis(0, GamepadAxis.LEFT_STICK_X, 0.2)
        assert manager.get_gamepad_axis(0, GamepadAxis.LEFT_STICK_X) == 0.2

    def test_gamepad_buttons(self) -> None:
        """Test gamepad button input."""
        manager = InputManager()

        manager.set_gamepad_button(0, GamepadButton.A, True)
        assert manager.is_gamepad_button_pressed(0, GamepadButton.A)

    def test_action_mapping(self) -> None:
        """Test input action mapping."""
        manager = InputManager()

        manager.add_action_mapping("jump", KeyCode.SPACE)
        manager.add_action_mapping("jump", GamepadButton.A)

        manager.set_key_pressed(KeyCode.SPACE, True)
        assert manager.is_action_pressed("jump")

    def test_direction_input(self) -> None:
        """Test getting movement direction."""
        manager = InputManager()

        manager.set_key_pressed(KeyCode.W, True)
        manager.set_key_pressed(KeyCode.D, True)

        direction = manager.get_direction()
        assert direction[0] > 0.0  # X positive
        assert direction[1] > 0.0  # Y positive

    def test_combo_detection(self) -> None:
        """Test fighting game style combo detection."""
        manager = InputManager()

        manager.add_action_mapping("punch", KeyCode.Z)
        manager.add_action_mapping("kick", KeyCode.X)

        # Record combo: punch, kick
        manager.set_key_pressed(KeyCode.Z, True)
        manager.update()
        manager.set_key_pressed(KeyCode.Z, False)

        manager.set_key_pressed(KeyCode.X, True)
        manager.update()

        # Check combo
        assert manager.check_combo(["punch", "kick"], max_frames=20)

    def test_scroll_input(self) -> None:
        """Test mouse scroll."""
        manager = InputManager()

        manager.set_mouse_scroll(0.0, 5.0)
        assert manager.mouse_scroll == (0.0, 5.0)

        manager.update()
        assert manager.mouse_scroll == (0.0, 0.0)

    def test_invalid_gamepad(self) -> None:
        """Test invalid gamepad index."""
        manager = InputManager()

        # Should handle gracefully
        assert manager.get_gamepad_axis(10, GamepadAxis.LEFT_STICK_X) == 0.0
        assert not manager.is_gamepad_button_pressed(10, GamepadButton.A)
