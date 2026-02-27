"""Input system for keyboard, mouse, and gamepad handling."""

from enum import Enum, auto

from thomas.gaming_platform._exceptions import InputError


class KeyCode(Enum):
    """Keyboard key codes."""

    A = auto()
    B = auto()
    C = auto()
    D = auto()
    E = auto()
    F = auto()
    G = auto()
    H = auto()
    I = auto()
    J = auto()
    K = auto()
    L = auto()
    M = auto()
    N = auto()
    O = auto()
    P = auto()
    Q = auto()
    R = auto()
    S = auto()
    T = auto()
    U = auto()
    V = auto()
    W = auto()
    X = auto()
    Y = auto()
    Z = auto()
    SPACE = auto()
    ENTER = auto()
    ESCAPE = auto()
    BACKSPACE = auto()
    TAB = auto()
    SHIFT = auto()
    CTRL = auto()
    ALT = auto()
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    F1 = auto()
    F2 = auto()
    F3 = auto()
    F4 = auto()
    F5 = auto()
    F6 = auto()
    F7 = auto()
    F8 = auto()
    F9 = auto()
    F10 = auto()
    F11 = auto()
    F12 = auto()


class MouseButton(Enum):
    """Mouse button codes."""

    LEFT = auto()
    RIGHT = auto()
    MIDDLE = auto()


class GamepadAxis(Enum):
    """Gamepad analog stick and trigger axes."""

    LEFT_STICK_X = auto()
    LEFT_STICK_Y = auto()
    RIGHT_STICK_X = auto()
    RIGHT_STICK_Y = auto()
    LEFT_TRIGGER = auto()
    RIGHT_TRIGGER = auto()


class GamepadButton(Enum):
    """Gamepad button codes."""

    A = auto()
    B = auto()
    X = auto()
    Y = auto()
    LB = auto()
    RB = auto()
    BACK = auto()
    START = auto()
    LEFT_STICK_PRESS = auto()
    RIGHT_STICK_PRESS = auto()
    DPAD_UP = auto()
    DPAD_DOWN = auto()
    DPAD_LEFT = auto()
    DPAD_RIGHT = auto()


class InputBuffer:
    """
    Input buffer for storing recent inputs (fighting game style).

    Allows querying input history for combo detection.
    """

    def __init__(self, buffer_size: int = 60) -> None:
        """
        Initialize input buffer.

        Args:
            buffer_size: Number of frames to buffer.
        """
        self.buffer_size = buffer_size
        self.buffer: list[set[str]] = [set() for _ in range(buffer_size)]
        self.current_index = 0

    def add_input(self, action: str) -> None:
        """Add action to current frame."""
        self.buffer[0].add(action)

    def advance(self) -> None:
        """Move to next frame."""
        # Keep buffer[0] as the current frame for easier querying/debugging.
        self.buffer.pop()
        self.buffer.insert(0, set())
        self.current_index = 0

    def has_sequence(self, sequence: list[str], max_frames: int = 10) -> bool:
        """
        Check if input buffer contains action sequence.

        Args:
            sequence: List of actions in order.
            max_frames: Maximum frames between actions.

        Returns:
            True if sequence found.
        """
        if not sequence:
            return False

        current_seq_index = 0
        frames_checked = 0

        for frame_inputs in self.buffer:
            if sequence[current_seq_index] in frame_inputs:
                current_seq_index += 1
                frames_checked = 0

                if current_seq_index >= len(sequence):
                    return True
            else:
                frames_checked += 1
                if frames_checked > max_frames:
                    current_seq_index = 0
                    frames_checked = 0

        return False


class InputRecorder:
    """Record and replay input for deterministic playback."""

    def __init__(self) -> None:
        """Initialize input recorder."""
        self.recording: list[dict[str, bool]] = []
        self.playback_index = 0
        self.is_recording = False
        self.is_playing = False

    def start_recording(self) -> None:
        """Start recording inputs."""
        self.recording.clear()
        self.is_recording = True

    def stop_recording(self) -> None:
        """Stop recording inputs."""
        self.is_recording = False

    def record_frame(self, inputs: dict[str, bool]) -> None:
        """Record inputs for current frame."""
        if self.is_recording:
            self.recording.append(inputs.copy())

    def start_playback(self) -> None:
        """Start playing back recorded inputs."""
        self.playback_index = 0
        self.is_playing = True

    def stop_playback(self) -> None:
        """Stop playing back inputs."""
        self.is_playing = False

    def get_playback_inputs(self) -> dict[str, bool] | None:
        """Get inputs for current playback frame."""
        if not self.is_playing or self.playback_index >= len(self.recording):
            return None

        inputs = self.recording[self.playback_index].copy()
        self.playback_index += 1

        if self.playback_index >= len(self.recording):
            self.is_playing = False

        return inputs

    def save_recording(self, filename: str) -> None:
        """Save recording to file."""
        import json

        data = {"frames": self.recording}
        with open(filename, "w") as f:
            json.dump(data, f)

    def load_recording(self, filename: str) -> None:
        """Load recording from file."""
        import json

        with open(filename) as f:
            data = json.load(f)
            self.recording = data["frames"]


class InputManager:
    """
    Input system handling keyboard, mouse, and gamepad input.

    Features:
    - Current and previous frame state tracking
    - Input mapping (action → keys)
    - Input buffering for combos
    - Input recording/replay
    - Dead zone handling
    """

    def __init__(self) -> None:
        """Initialize input manager."""
        # Keyboard state
        self.keys_pressed: set[KeyCode] = set()
        self.keys_previous: set[KeyCode] = set()

        # Mouse state
        self.mouse_position: tuple[float, float] = (0.0, 0.0)
        self.mouse_buttons: set[MouseButton] = set()
        self.mouse_buttons_previous: set[MouseButton] = set()
        self.mouse_scroll: tuple[float, float] = (0.0, 0.0)

        # Gamepad state (supports 4 gamepads)
        self.gamepad_axes: dict[int, dict[GamepadAxis, float]] = {
            i: {axis: 0.0 for axis in GamepadAxis} for i in range(4)
        }
        self.gamepad_buttons: dict[int, set[GamepadButton]] = {i: set() for i in range(4)}
        self.gamepad_buttons_previous: dict[int, set[GamepadButton]] = {i: set() for i in range(4)}

        # Input mapping
        self.action_mappings: dict[str, list[KeyCode]] = {}
        self.gamepad_action_mappings: dict[str, list[GamepadButton]] = {}

        # Buffering and recording
        self.input_buffer = InputBuffer(buffer_size=60)
        self.input_recorder = InputRecorder()

        # Dead zones
        self.stick_dead_zone = 0.15
        self.trigger_dead_zone = 0.1

    def update(self) -> None:
        """Update input state (call once per frame)."""
        # Shift current state to previous
        self.keys_previous = self.keys_pressed.copy()
        self.mouse_buttons_previous = self.mouse_buttons.copy()

        for i in range(4):
            self.gamepad_buttons_previous[i] = self.gamepad_buttons[i].copy()

        # Clear scroll
        self.mouse_scroll = (0.0, 0.0)

        # Advance input buffer
        self.input_buffer.advance()

    def set_key_pressed(self, key: KeyCode, pressed: bool) -> None:
        """
        Set key pressed state.

        Args:
            key: Key code.
            pressed: Whether key is pressed.
        """
        if pressed:
            self.keys_pressed.add(key)
            self.input_buffer.add_input(f"key_{key.name.lower()}")
        else:
            self.keys_pressed.discard(key)

    def set_mouse_position(self, x: float, y: float) -> None:
        """
        Set mouse position.

        Args:
            x: Mouse X coordinate.
            y: Mouse Y coordinate.
        """
        self.mouse_position = (x, y)

    def set_mouse_button(self, button: MouseButton, pressed: bool) -> None:
        """
        Set mouse button state.

        Args:
            button: Mouse button.
            pressed: Whether button is pressed.
        """
        if pressed:
            self.mouse_buttons.add(button)
        else:
            self.mouse_buttons.discard(button)

    def set_mouse_scroll(self, dx: float, dy: float) -> None:
        """
        Set mouse scroll delta.

        Args:
            dx: Horizontal scroll.
            dy: Vertical scroll.
        """
        self.mouse_scroll = (dx, dy)

    def set_gamepad_axis(self, gamepad: int, axis: GamepadAxis, value: float) -> None:
        """
        Set gamepad axis value.

        Args:
            gamepad: Gamepad index (0-3).
            axis: Axis identifier.
            value: Axis value (-1 to 1).
        """
        if gamepad < 0 or gamepad >= 4:
            raise InputError(f"Invalid gamepad index: {gamepad}")

        # Apply dead zone
        if axis in (
            GamepadAxis.LEFT_STICK_X,
            GamepadAxis.LEFT_STICK_Y,
            GamepadAxis.RIGHT_STICK_X,
            GamepadAxis.RIGHT_STICK_Y,
        ):
            if abs(value) < self.stick_dead_zone:
                value = 0.0

        elif axis in (GamepadAxis.LEFT_TRIGGER, GamepadAxis.RIGHT_TRIGGER):
            if abs(value) < self.trigger_dead_zone:
                value = 0.0

        self.gamepad_axes[gamepad][axis] = value

    def set_gamepad_button(self, gamepad: int, button: GamepadButton, pressed: bool) -> None:
        """
        Set gamepad button state.

        Args:
            gamepad: Gamepad index (0-3).
            button: Button identifier.
            pressed: Whether button is pressed.
        """
        if gamepad < 0 or gamepad >= 4:
            raise InputError(f"Invalid gamepad index: {gamepad}")

        if pressed:
            self.gamepad_buttons[gamepad].add(button)
            self.input_buffer.add_input(f"gamepad_{button.name.lower()}")
        else:
            self.gamepad_buttons[gamepad].discard(button)

    def is_key_pressed(self, key: KeyCode) -> bool:
        """Check if key is currently pressed."""
        return key in self.keys_pressed

    def is_key_just_pressed(self, key: KeyCode) -> bool:
        """Check if key was just pressed this frame."""
        return key in self.keys_pressed and key not in self.keys_previous

    def is_key_just_released(self, key: KeyCode) -> bool:
        """Check if key was just released this frame."""
        return key not in self.keys_pressed and key in self.keys_previous

    def is_mouse_button_pressed(self, button: MouseButton) -> bool:
        """Check if mouse button is currently pressed."""
        return button in self.mouse_buttons

    def is_mouse_button_just_pressed(self, button: MouseButton) -> bool:
        """Check if mouse button was just pressed this frame."""
        return button in self.mouse_buttons and button not in self.mouse_buttons_previous

    def is_mouse_button_just_released(self, button: MouseButton) -> bool:
        """Check if mouse button was just released this frame."""
        return button not in self.mouse_buttons and button in self.mouse_buttons_previous

    def is_gamepad_button_pressed(self, gamepad: int, button: GamepadButton) -> bool:
        """Check if gamepad button is currently pressed."""
        if gamepad < 0 or gamepad >= 4:
            return False
        return button in self.gamepad_buttons[gamepad]

    def is_gamepad_button_just_pressed(self, gamepad: int, button: GamepadButton) -> bool:
        """Check if gamepad button was just pressed this frame."""
        if gamepad < 0 or gamepad >= 4:
            return False
        return button in self.gamepad_buttons[gamepad] and button not in self.gamepad_buttons_previous[gamepad]

    def is_gamepad_button_just_released(self, gamepad: int, button: GamepadButton) -> bool:
        """Check if gamepad button was just released this frame."""
        if gamepad < 0 or gamepad >= 4:
            return False
        return button not in self.gamepad_buttons[gamepad] and button in self.gamepad_buttons_previous[gamepad]

    def get_gamepad_axis(self, gamepad: int, axis: GamepadAxis) -> float:
        """Get gamepad axis value."""
        if gamepad < 0 or gamepad >= 4:
            return 0.0
        return self.gamepad_axes[gamepad].get(axis, 0.0)

    def add_action_mapping(self, action: str, key: KeyCode) -> None:
        """
        Map action name to keyboard key.

        Args:
            action: Action name.
            key: Keyboard key.
        """
        if action not in self.action_mappings:
            self.action_mappings[action] = []
        if key not in self.action_mappings[action]:
            self.action_mappings[action].append(key)

    def add_gamepad_action_mapping(self, action: str, button: GamepadButton) -> None:
        """
        Map action name to gamepad button.

        Args:
            action: Action name.
            button: Gamepad button.
        """
        if action not in self.gamepad_action_mappings:
            self.gamepad_action_mappings[action] = []
        if button not in self.gamepad_action_mappings[action]:
            self.gamepad_action_mappings[action].append(button)

    def is_action_pressed(self, action: str) -> bool:
        """Check if action is pressed."""
        if action in self.action_mappings:
            for key in self.action_mappings[action]:
                if self.is_key_pressed(key):
                    return True

        if action in self.gamepad_action_mappings:
            for button in self.gamepad_action_mappings[action]:
                if self.is_gamepad_button_pressed(0, button):
                    return True

        return False

    def is_action_just_pressed(self, action: str) -> bool:
        """Check if action was just pressed."""
        if action in self.action_mappings:
            for key in self.action_mappings[action]:
                if self.is_key_just_pressed(key):
                    return True

        if action in self.gamepad_action_mappings:
            for button in self.gamepad_action_mappings[action]:
                if self.is_gamepad_button_just_pressed(0, button):
                    return True

        return False

    def is_action_just_released(self, action: str) -> bool:
        """Check if action was just released."""
        if action in self.action_mappings:
            for key in self.action_mappings[action]:
                if self.is_key_just_released(key):
                    return True

        if action in self.gamepad_action_mappings:
            for button in self.gamepad_action_mappings[action]:
                if self.is_gamepad_button_just_released(0, button):
                    return True

        return False

    def _action_buffer_tokens(self, action: str) -> set[str]:
        """Resolve action name to possible input-buffer token strings."""
        tokens: set[str] = {action}

        for mapped in self.action_mappings.get(action, []):
            if isinstance(mapped, KeyCode):
                tokens.add(f"key_{mapped.name.lower()}")
            elif isinstance(mapped, GamepadButton):
                # Support mixed mappings added through add_action_mapping.
                tokens.add(f"gamepad_{mapped.name.lower()}")

        for button in self.gamepad_action_mappings.get(action, []):
            tokens.add(f"gamepad_{button.name.lower()}")

        return tokens

    def check_combo(self, combo: list[str], max_frames: int = 10) -> bool:
        """
        Check if input buffer contains combo sequence.

        Args:
            combo: List of action names.
            max_frames: Maximum frames between actions.

        Returns:
            True if combo detected.
        """
        if not combo:
            return False

        expected_actions = list(reversed(combo))
        current_seq_index = 0
        frames_checked = 0

        for frame_inputs in self.input_buffer.buffer:
            expected = self._action_buffer_tokens(expected_actions[current_seq_index])

            if any(token in frame_inputs for token in expected):
                current_seq_index += 1
                frames_checked = 0

                if current_seq_index >= len(combo):
                    return True
            else:
                frames_checked += 1
                if frames_checked > max_frames:
                    current_seq_index = 0
                    frames_checked = 0

        return False

    def get_direction(self) -> tuple[float, float]:
        """
        Get movement direction from WASD/arrow keys or gamepad.

        Returns:
            (x, y) direction vector.
        """
        x = 0.0
        y = 0.0

        # Keyboard
        if self.is_key_pressed(KeyCode.D):
            x += 1.0
        if self.is_key_pressed(KeyCode.A):
            x -= 1.0
        if self.is_key_pressed(KeyCode.W):
            y += 1.0
        if self.is_key_pressed(KeyCode.S):
            y -= 1.0

        # Gamepad left stick
        gp_x = self.get_gamepad_axis(0, GamepadAxis.LEFT_STICK_X)
        gp_y = self.get_gamepad_axis(0, GamepadAxis.LEFT_STICK_Y)

        x += gp_x
        y += gp_y

        # Normalize
        length = (x * x + y * y) ** 0.5
        if length > 1.0:
            x /= length
            y /= length

        return (x, y)
