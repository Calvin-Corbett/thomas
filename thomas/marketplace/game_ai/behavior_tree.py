"""
Behavior Tree implementation for hierarchical AI decision-making.

Provides a complete behavior tree system with composite nodes (Sequence, Selector,
Parallel), decorator nodes (Inverter, Repeater, Cooldown, etc.), and leaf nodes
(Action, Condition). Includes blackboard for shared data and debug logging.
"""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from thomas.marketplace.game_ai._exceptions import BehaviorTreeError
from thomas.marketplace.game_ai._types import Blackboard, BTNodeStatus

logger = logging.getLogger(__name__)


class BehaviorNode(ABC):
    """Abstract base class for all behavior tree nodes.

    All nodes must implement tick() which executes the node's behavior
    and returns a BTNodeStatus.
    """

    def __init__(self, name: str) -> None:
        """Initialize behavior node.

        Args:
            name: Unique identifier for this node
        """
        self.name = name
        self.parent: BehaviorNode | None = None

    @abstractmethod
    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Execute node logic for one frame.

        Args:
            blackboard: Shared memory between nodes
            delta_time: Time elapsed since last tick in seconds

        Returns:
            BTNodeStatus indicating execution result
        """
        pass

    def on_enter(self) -> None:
        """Called when node transitions from not-running to running."""
        pass

    def on_exit(self) -> None:
        """Called when node transitions from running to not-running."""
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name})"


class Composite(BehaviorNode):
    """Base class for composite (parent) nodes.

    Composite nodes contain child nodes and determine execution order.
    """

    def __init__(self, name: str, children: list[BehaviorNode] | None = None) -> None:
        """Initialize composite node.

        Args:
            name: Node identifier
            children: List of child nodes
        """
        super().__init__(name)
        self.children = children or []
        for child in self.children:
            child.parent = self

    def add_child(self, child: BehaviorNode) -> "Composite":
        """Add a child node and return self for chaining.

        Args:
            child: Node to add as child

        Returns:
            Self for method chaining
        """
        child.parent = self
        self.children.append(child)
        return self


class Sequence(Composite):
    """Composite node that runs children in order until one fails (AND logic).

    Returns:
        SUCCESS: All children succeeded
        FAILURE: First child to fail
        RUNNING: Waiting for current child
    """

    def __init__(self, name: str = "Sequence", children: list[BehaviorNode] | None = None) -> None:
        """Initialize sequence node."""
        super().__init__(name, children)
        self._current_index = 0

    def on_enter(self) -> None:
        """Reset to first child when entering."""
        self._current_index = 0

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Execute children sequentially until one fails."""
        logger.debug(f"Sequence {self.name} tick")

        while self._current_index < len(self.children):
            child = self.children[self._current_index]
            status = child.tick(blackboard, delta_time)

            if status == BTNodeStatus.FAILURE:
                logger.debug(f"  Child {self._current_index} failed, sequence fails")
                return BTNodeStatus.FAILURE

            if status == BTNodeStatus.RUNNING:
                logger.debug(f"  Child {self._current_index} running, sequence running")
                return BTNodeStatus.RUNNING

            # SUCCESS - move to next child
            self._current_index += 1

        logger.debug("  All children succeeded")
        return BTNodeStatus.SUCCESS


class Selector(Composite):
    """Composite node that runs children until one succeeds (OR logic).

    Returns:
        SUCCESS: First child to succeed
        FAILURE: All children failed
        RUNNING: Waiting for current child
    """

    def __init__(self, name: str = "Selector", children: list[BehaviorNode] | None = None) -> None:
        """Initialize selector node."""
        super().__init__(name, children)
        self._current_index = 0

    def on_enter(self) -> None:
        """Reset to first child when entering."""
        self._current_index = 0

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Execute children until one succeeds."""
        logger.debug(f"Selector {self.name} tick")

        while self._current_index < len(self.children):
            child = self.children[self._current_index]
            status = child.tick(blackboard, delta_time)

            if status == BTNodeStatus.SUCCESS:
                logger.debug(f"  Child {self._current_index} succeeded, selector succeeds")
                return BTNodeStatus.SUCCESS

            if status == BTNodeStatus.RUNNING:
                logger.debug(f"  Child {self._current_index} running, selector running")
                return BTNodeStatus.RUNNING

            # FAILURE - move to next child
            self._current_index += 1

        logger.debug("  All children failed")
        return BTNodeStatus.FAILURE


class Parallel(Composite):
    """Composite node that runs all children simultaneously.

    Returns:
        SUCCESS: At least N children succeeded (based on mode)
        FAILURE: More than (children - N) children failed
        RUNNING: Otherwise
    """

    def __init__(
        self, name: str = "Parallel", children: list[BehaviorNode] | None = None, success_threshold: int = 1
    ) -> None:
        """Initialize parallel node.

        Args:
            name: Node identifier
            children: Child nodes to run in parallel
            success_threshold: Number of successful children needed for SUCCESS
        """
        super().__init__(name, children)
        self.success_threshold = success_threshold

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Execute all children and check success threshold."""
        logger.debug(f"Parallel {self.name} tick (threshold={self.success_threshold})")

        successes = 0
        failures = 0
        running = 0

        for child in self.children:
            status = child.tick(blackboard, delta_time)

            if status == BTNodeStatus.SUCCESS:
                successes += 1
            elif status == BTNodeStatus.FAILURE:
                failures += 1
            else:
                running += 1

        # Check failure threshold
        if failures > len(self.children) - self.success_threshold:
            logger.debug(f"  Too many failures ({failures}), parallel fails")
            return BTNodeStatus.FAILURE

        # Check success threshold
        if successes >= self.success_threshold:
            logger.debug(f"  Success threshold reached ({successes}), parallel succeeds")
            return BTNodeStatus.SUCCESS

        logger.debug(f"  Running (S:{successes} F:{failures} R:{running})")
        return BTNodeStatus.RUNNING


class Decorator(BehaviorNode):
    """Base class for decorator nodes that modify child behavior."""

    def __init__(self, name: str, child: BehaviorNode) -> None:
        """Initialize decorator.

        Args:
            name: Node identifier
            child: Child node to decorate
        """
        super().__init__(name)
        self.child = child
        child.parent = self

    @abstractmethod
    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Execute decorator logic."""
        pass


class Inverter(Decorator):
    """Decorator that inverts child result (SUCCESS <-> FAILURE, RUNNING stays RUNNING)."""

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Invert child status."""
        logger.debug(f"Inverter {self.name} tick")
        status = self.child.tick(blackboard, delta_time)

        if status == BTNodeStatus.RUNNING:
            return BTNodeStatus.RUNNING

        return BTNodeStatus.SUCCESS if status == BTNodeStatus.FAILURE else BTNodeStatus.FAILURE


class Repeater(Decorator):
    """Decorator that repeats child execution N times."""

    def __init__(self, name: str, child: BehaviorNode, count: int = -1) -> None:
        """Initialize repeater.

        Args:
            name: Node identifier
            child: Child node to repeat
            count: Number of repetitions (-1 for infinite)
        """
        super().__init__(name, child)
        self.count = count
        self._iterations = 0

    def on_enter(self) -> None:
        """Reset iteration counter."""
        self._iterations = 0

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Repeat child until count reached or child fails."""
        logger.debug(f"Repeater {self.name} tick (iteration {self._iterations})")

        while self.count == -1 or self._iterations < self.count:
            status = self.child.tick(blackboard, delta_time)

            if status == BTNodeStatus.FAILURE:
                return BTNodeStatus.FAILURE

            if status == BTNodeStatus.RUNNING:
                return BTNodeStatus.RUNNING

            self._iterations += 1

        logger.debug(f"  Repeater completed {self._iterations} iterations")
        return BTNodeStatus.SUCCESS


class Succeeder(Decorator):
    """Decorator that always returns SUCCESS regardless of child result."""

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Execute child and always succeed."""
        logger.debug(f"Succeeder {self.name} tick")
        self.child.tick(blackboard, delta_time)
        return BTNodeStatus.SUCCESS


class UntilFail(Decorator):
    """Decorator that repeats child until it fails."""

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Keep ticking child until it fails."""
        logger.debug(f"UntilFail {self.name} tick")

        while True:
            status = self.child.tick(blackboard, delta_time)

            if status == BTNodeStatus.FAILURE:
                return BTNodeStatus.SUCCESS

            if status == BTNodeStatus.RUNNING:
                return BTNodeStatus.RUNNING


class Cooldown(Decorator):
    """Decorator that prevents child execution until cooldown expires."""

    def __init__(self, name: str, child: BehaviorNode, duration: float) -> None:
        """Initialize cooldown.

        Args:
            name: Node identifier
            child: Child node
            duration: Cooldown duration in seconds
        """
        super().__init__(name, child)
        self.duration = duration
        self._last_success_time = -duration

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Check cooldown before executing child."""
        logger.debug(f"Cooldown {self.name} tick")
        current_time = time.time()

        if current_time - self._last_success_time < self.duration:
            logger.debug("  Cooldown active")
            return BTNodeStatus.FAILURE

        status = self.child.tick(blackboard, delta_time)

        if status == BTNodeStatus.SUCCESS:
            self._last_success_time = current_time

        return status


class Limiter(Decorator):
    """Decorator that limits child execution to N times within a time window."""

    def __init__(self, name: str, child: BehaviorNode, max_runs: int, window: float) -> None:
        """Initialize limiter.

        Args:
            name: Node identifier
            child: Child node
            max_runs: Maximum executions within window
            window: Time window in seconds
        """
        super().__init__(name, child)
        self.max_runs = max_runs
        self.window = window
        self._execution_times: list[float] = []

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Check limit before executing child."""
        logger.debug(f"Limiter {self.name} tick")
        current_time = time.time()

        # Remove old executions outside window
        self._execution_times = [t for t in self._execution_times if current_time - t < self.window]

        if len(self._execution_times) >= self.max_runs:
            logger.debug("  Rate limit exceeded")
            return BTNodeStatus.FAILURE

        status = self.child.tick(blackboard, delta_time)

        if status != BTNodeStatus.RUNNING:
            self._execution_times.append(current_time)

        return status


class Action(BehaviorNode):
    """Leaf node that executes a function.

    The function receives blackboard and delta_time and returns BTNodeStatus.
    """

    def __init__(self, name: str, func: Callable[[Blackboard, float], BTNodeStatus]) -> None:
        """Initialize action node.

        Args:
            name: Node identifier
            func: Callable that executes action
        """
        super().__init__(name)
        self.func = func

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Execute action function."""
        logger.debug(f"Action {self.name} tick")
        return self.func(blackboard, delta_time)


class Condition(BehaviorNode):
    """Leaf node that checks a predicate.

    Returns SUCCESS if predicate is True, FAILURE if False.
    """

    def __init__(self, name: str, predicate: Callable[[Blackboard], bool]) -> None:
        """Initialize condition node.

        Args:
            name: Node identifier
            predicate: Callable that checks condition
        """
        super().__init__(name)
        self.predicate = predicate

    def tick(self, blackboard: Blackboard, delta_time: float) -> BTNodeStatus:
        """Check condition."""
        logger.debug(f"Condition {self.name} tick")
        result = self.predicate(blackboard)
        return BTNodeStatus.SUCCESS if result else BTNodeStatus.FAILURE


class BehaviorTree:
    """Behavior tree manager that ticks the tree and manages blackboard."""

    def __init__(self, root: BehaviorNode, enable_logging: bool = False) -> None:
        """Initialize behavior tree.

        Args:
            root: Root node of the tree
            enable_logging: Enable debug logging of tree execution
        """
        if not root:
            raise BehaviorTreeError("Root node cannot be None")

        self.root = root
        self.blackboard: Blackboard = {}
        self._last_status = BTNodeStatus.FAILURE
        self._is_running = False

        if enable_logging:
            logger.setLevel(logging.DEBUG)
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            logger.addHandler(handler)

    def tick(self, delta_time: float = 0.016) -> BTNodeStatus:
        """Execute one tick of the behavior tree.

        Args:
            delta_time: Time elapsed since last tick in seconds

        Returns:
            BTNodeStatus of root node
        """
        status = self.root.tick(self.blackboard, delta_time)
        self._last_status = status
        self._is_running = status == BTNodeStatus.RUNNING
        return status

    def reset(self) -> None:
        """Reset tree state (call on_exit on all running nodes)."""
        self._reset_node(self.root)
        self._last_status = BTNodeStatus.FAILURE
        self._is_running = False

    def _reset_node(self, node: BehaviorNode) -> None:
        """Recursively reset node and children."""
        node.on_exit()
        if isinstance(node, (Composite, Decorator)):
            if isinstance(node, Composite):
                for child in node.children:
                    self._reset_node(child)
            elif isinstance(node, Decorator):
                self._reset_node(node.child)

    def get_blackboard(self) -> Blackboard:
        """Get the blackboard dictionary.

        Returns:
            Blackboard shared memory
        """
        return self.blackboard

    def set_blackboard_value(self, key: str, value: Any) -> None:
        """Set a value in the blackboard.

        Args:
            key: Key in blackboard
            value: Value to set
        """
        self.blackboard[key] = value

    def get_blackboard_value(self, key: str, default: Any = None) -> Any:
        """Get a value from blackboard.

        Args:
            key: Key in blackboard
            default: Default value if key not found

        Returns:
            Value from blackboard or default
        """
        return self.blackboard.get(key, default)

    @property
    def is_running(self) -> bool:
        """Check if tree is in RUNNING state."""
        return self._is_running

    @property
    def last_status(self) -> BTNodeStatus:
        """Get last tick status."""
        return self._last_status


class TreeBuilder:
    """Fluent builder for constructing behavior trees."""

    def __init__(self) -> None:
        """Initialize builder."""
        self._stack: list[BehaviorNode] = []

    def sequence(self, name: str = "Sequence") -> "TreeBuilder":
        """Create and push a sequence node."""
        node = Sequence(name)
        if self._stack:
            parent = self._stack[-1]
            if isinstance(parent, Composite):
                parent.add_child(node)
        self._stack.append(node)
        return self

    def selector(self, name: str = "Selector") -> "TreeBuilder":
        """Create and push a selector node."""
        node = Selector(name)
        if self._stack:
            parent = self._stack[-1]
            if isinstance(parent, Composite):
                parent.add_child(node)
        self._stack.append(node)
        return self

    def parallel(self, name: str = "Parallel", success_threshold: int = 1) -> "TreeBuilder":
        """Create and push a parallel node."""
        node = Parallel(name, success_threshold=success_threshold)
        if self._stack:
            parent = self._stack[-1]
            if isinstance(parent, Composite):
                parent.add_child(node)
        self._stack.append(node)
        return self

    def action(self, name: str, func: Callable[[Blackboard, float], BTNodeStatus]) -> "TreeBuilder":
        """Add an action node."""
        node = Action(name, func)
        if self._stack:
            parent = self._stack[-1]
            if isinstance(parent, Composite):
                parent.add_child(node)
        return self

    def condition(self, name: str, predicate: Callable[[Blackboard], bool]) -> "TreeBuilder":
        """Add a condition node."""
        node = Condition(name, predicate)
        if self._stack:
            parent = self._stack[-1]
            if isinstance(parent, Composite):
                parent.add_child(node)
        return self

    def inverter(self, name: str) -> "TreeBuilder":
        """Create and push an inverter decorator."""
        if not self._stack:
            raise BehaviorTreeError("Cannot add decorator without parent")

        parent = self._stack[-1]
        if isinstance(parent, Composite):
            raise BehaviorTreeError("Decorator must wrap a single node")

        node = Inverter(name, parent)
        self._stack[-1] = node
        return self

    def end(self) -> BehaviorNode:
        """Pop and return current node."""
        if not self._stack:
            raise BehaviorTreeError("Builder stack is empty")
        return self._stack.pop()

    def build(self) -> BehaviorTree:
        """Build and return behavior tree."""
        if not self._stack:
            raise BehaviorTreeError("Nothing to build")
        root = self._stack[0]
        self._stack.clear()
        return BehaviorTree(root)
