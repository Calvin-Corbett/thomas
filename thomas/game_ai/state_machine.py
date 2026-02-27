"""
Finite state machine with hierarchical states and message handling.

Provides state-based AI with enter/execute/exit callbacks, state transitions,
global states, state stack, and message passing between states.
"""

import logging
from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from thomas.game_ai._types import Blackboard

logger = logging.getLogger(__name__)


@dataclass
class StateMessage:
    """Message sent to states."""

    message_type: str
    payload: Any = None


class State(ABC):
    """Abstract base class for FSM states."""

    def __init__(self, name: str) -> None:
        """Initialize state.

        Args:
            name: State identifier
        """
        self.name = name
        self.sub_states: list[State] = []
        self.current_sub_state: State | None = None

    def on_enter(self, blackboard: Blackboard) -> None:
        """Called when state becomes active.

        Args:
            blackboard: Shared state data
        """
        pass

    def on_execute(self, blackboard: Blackboard, delta_time: float) -> None:
        """Called every frame while state is active.

        Args:
            blackboard: Shared state data
            delta_time: Time since last frame
        """
        pass

    def on_exit(self, blackboard: Blackboard) -> None:
        """Called when state becomes inactive.

        Args:
            blackboard: Shared state data
        """
        pass

    def on_message(self, message: StateMessage, blackboard: Blackboard) -> bool:
        """Handle incoming message.

        Args:
            message: StateMessage to handle
            blackboard: Shared state data

        Returns:
            True if message was handled, False otherwise
        """
        return False

    def add_sub_state(self, state: "State") -> None:
        """Add a sub-state (for hierarchical states).

        Args:
            state: Sub-state to add
        """
        self.sub_states.append(state)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name})"


class SimpleState(State):
    """Basic state with custom callbacks."""

    def __init__(
        self,
        name: str,
        on_enter_func: Callable[[Blackboard], None] | None = None,
        on_execute_func: Callable[[Blackboard, float], None] | None = None,
        on_exit_func: Callable[[Blackboard], None] | None = None,
    ) -> None:
        """Initialize simple state with callbacks.

        Args:
            name: State name
            on_enter_func: Function called on enter
            on_execute_func: Function called on execute
            on_exit_func: Function called on exit
        """
        super().__init__(name)
        self._on_enter = on_enter_func
        self._on_execute = on_execute_func
        self._on_exit = on_exit_func

    def on_enter(self, blackboard: Blackboard) -> None:
        """Enter state."""
        if self._on_enter:
            self._on_enter(blackboard)

    def on_execute(self, blackboard: Blackboard, delta_time: float) -> None:
        """Execute state."""
        if self._on_execute:
            self._on_execute(blackboard, delta_time)

    def on_exit(self, blackboard: Blackboard) -> None:
        """Exit state."""
        if self._on_exit:
            self._on_exit(blackboard)


class Transition:
    """Represents a transition between states."""

    def __init__(
        self, from_state: State, to_state: State, condition: Callable[[Blackboard], bool] | None = None
    ) -> None:
        """Initialize transition.

        Args:
            from_state: Source state
            to_state: Destination state
            condition: Predicate that triggers transition
        """
        self.from_state = from_state
        self.to_state = to_state
        self.condition = condition or (lambda _: False)

    def should_transition(self, blackboard: Blackboard) -> bool:
        """Check if transition should occur.

        Args:
            blackboard: Shared state data

        Returns:
            True if condition is met
        """
        return self.condition(blackboard)


class StateMachine:
    """Finite state machine with transitions and message handling."""

    def __init__(self, initial_state: State, enable_logging: bool = False) -> None:
        """Initialize state machine.

        Args:
            initial_state: Starting state
            enable_logging: Enable debug logging
        """
        if not initial_state:
            raise ValueError("Initial state cannot be None")

        self.states: dict[str, State] = {}
        self.transitions: list[Transition] = []
        self.current_state = initial_state
        self.global_state: State | None = None
        self.state_stack: list[State] = []
        self.blackboard: Blackboard = {}
        self._history: list[str] = []
        self._enable_logging = enable_logging

        self.add_state(initial_state)

        if enable_logging:
            logger.setLevel(logging.DEBUG)
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            logger.addHandler(handler)

    def add_state(self, state: State) -> None:
        """Register a state.

        Args:
            state: State to add
        """
        self.states[state.name] = state
        logger.debug(f"Added state: {state.name}")

    def add_transition(
        self, from_state: State, to_state: State, condition: Callable[[Blackboard], bool] | None = None
    ) -> None:
        """Add a transition between states.

        Args:
            from_state: Source state
            to_state: Destination state
            condition: Condition that triggers transition
        """
        transition = Transition(from_state, to_state, condition)
        self.transitions.append(transition)
        logger.debug(f"Added transition: {from_state.name} -> {to_state.name}")

    def set_global_state(self, state: State | None) -> None:
        """Set global state (always executed before current state).

        Args:
            state: Global state or None
        """
        self.global_state = state
        if state:
            logger.debug(f"Global state set to: {state.name}")

    def change_state(self, new_state: State) -> None:
        """Change to a new state.

        Args:
            new_state: State to transition to
        """
        if new_state not in self.states.values():
            self.add_state(new_state)

        logger.debug(f"State change: {self.current_state.name} -> {new_state.name}")

        self.current_state.on_exit(self.blackboard)
        self._history.append(self.current_state.name)

        self.current_state = new_state
        self.current_state.on_enter(self.blackboard)

    def change_state_by_name(self, state_name: str) -> None:
        """Change to state by name.

        Args:
            state_name: Name of state to change to

        Raises:
            ValueError: If state not found
        """
        if state_name not in self.states:
            raise ValueError(f"State '{state_name}' not found")

        self.change_state(self.states[state_name])

    def push_state(self, new_state: State) -> None:
        """Push state onto stack (temporarily change to new state).

        Args:
            new_state: State to push
        """
        if new_state not in self.states.values():
            self.add_state(new_state)

        logger.debug(f"Push state: {new_state.name}")

        self.state_stack.append(self.current_state)
        self.current_state = new_state
        self.current_state.on_enter(self.blackboard)

    def pop_state(self) -> None:
        """Pop state from stack and return to previous state."""
        if not self.state_stack:
            logger.warning("Cannot pop from empty state stack")
            return

        logger.debug(f"Pop state: {self.current_state.name}")

        self.current_state.on_exit(self.blackboard)
        self.current_state = self.state_stack.pop()
        self.current_state.on_enter(self.blackboard)

    def execute(self, delta_time: float = 0.016) -> None:
        """Execute one frame of the state machine.

        Args:
            delta_time: Time elapsed since last frame
        """
        # Execute global state first
        if self.global_state:
            self.global_state.on_execute(self.blackboard, delta_time)

        # Check transitions
        for transition in self.transitions:
            if transition.from_state == self.current_state:
                if transition.should_transition(self.blackboard):
                    self.change_state(transition.to_state)
                    break

        # Execute current state
        self.current_state.on_execute(self.blackboard, delta_time)

    def send_message(self, message: StateMessage) -> bool:
        """Send message to current state.

        Args:
            message: StateMessage to send

        Returns:
            True if message was handled
        """
        logger.debug(f"Message to {self.current_state.name}: {message.message_type}")

        # Try current state
        if self.current_state.on_message(message, self.blackboard):
            return True

        # Try global state
        if self.global_state and self.global_state.on_message(message, self.blackboard):
            return True

        return False

    def set_blackboard_value(self, key: str, value: Any) -> None:
        """Set value in blackboard.

        Args:
            key: Key in blackboard
            value: Value to set
        """
        self.blackboard[key] = value

    def get_blackboard_value(self, key: str, default: Any = None) -> Any:
        """Get value from blackboard.

        Args:
            key: Key in blackboard
            default: Default value if key not found

        Returns:
            Value from blackboard or default
        """
        return self.blackboard.get(key, default)

    @property
    def current_state_name(self) -> str:
        """Get name of current state."""
        return self.current_state.name

    @property
    def is_in_state(self) -> Callable[[str], bool]:
        """Check if in specific state.

        Returns:
            Function that checks state by name
        """

        def check(state_name: str) -> bool:
            return self.current_state_name == state_name

        return check

    def get_history(self, count: int = 10) -> list[str]:
        """Get recent state history.

        Args:
            count: Number of recent states to return

        Returns:
            List of state names
        """
        return self._history[-count:]
