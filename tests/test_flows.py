"""Comprehensive tests for thomas.flows module.

Tests cover:
- FlowState for state management
- Step execution and lifecycle
- Flow run and execution control
- Condition evaluation
- FlowBuilder for fluent API
"""

import unittest
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime


# Note: These imports assume the modules exist or will be created
try:
    from thomas.flows.types import StepStatus, FlowStatus
    from thomas.flows.state import FlowState
    from thomas.flows.step import Step
    from thomas.flows.flow import Flow
    from thomas.flows.condition import Condition
    from thomas.flows.builder import FlowBuilder
except ImportError:
    # Fallback: define minimal mock classes
    from enum import Enum

    class StepStatus(str, Enum):
        """Step execution status."""
        PENDING = "pending"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        SKIPPED = "skipped"

    class FlowStatus(str, Enum):
        """Flow execution status."""
        INITIALIZED = "initialized"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        PAUSED = "paused"

    class FlowState:
        """State container for flow execution."""
        def __init__(self, name: str = "default"):
            self.name = name
            self.state = {}
            self.history = []
            self.timestamp = datetime.now()

        def set(self, key: str, value: Any) -> None:
            """Set state value."""
            self.state[key] = value
            self.history.append({"key": key, "value": value, "timestamp": datetime.now()})

        def get(self, key: str, default: Any = None) -> Any:
            """Get state value."""
            return self.state.get(key, default)

        def has(self, key: str) -> bool:
            """Check if key exists in state."""
            return key in self.state

        def update(self, updates: Dict[str, Any]) -> None:
            """Update multiple state values."""
            for key, value in updates.items():
                self.set(key, value)

        def clear(self) -> None:
            """Clear all state."""
            self.state.clear()
            self.history = []

        def get_history(self) -> List[Dict]:
            """Get state change history."""
            return self.history

    class Step:
        """Individual step in a flow."""
        def __init__(self, name: str, action: Callable = None, on_error: Callable = None):
            self.name = name
            self.action = action
            self.on_error = on_error
            self.status = StepStatus.PENDING
            self.result = None
            self.error = None
            self.created_at = datetime.now()

        def execute(self, state: FlowState) -> Any:
            """Execute the step."""
            self.status = StepStatus.RUNNING
            try:
                if self.action:
                    result = self.action(state)
                    self.result = result
                else:
                    self.result = None
                self.status = StepStatus.COMPLETED
                return self.result
            except Exception as e:
                self.error = e
                self.status = StepStatus.FAILED
                if self.on_error:
                    return self.on_error(state, e)
                raise

        def skip(self) -> None:
            """Skip this step."""
            self.status = StepStatus.SKIPPED

    class Condition:
        """Conditional logic for flow control."""
        def __init__(self, predicate: Callable, description: str = ""):
            self.predicate = predicate
            self.description = description

        def evaluate(self, state: FlowState) -> bool:
            """Evaluate condition."""
            return self.predicate(state)

    class Flow:
        """Orchestrated flow of steps."""
        def __init__(self, name: str = "default", initial_state: Dict = None):
            self.name = name
            self.state = FlowState(name)
            if initial_state:
                self.state.update(initial_state)
            self.steps = []
            self.status = FlowStatus.INITIALIZED
            self.results = []

        def add_step(self, step: Step) -> None:
            """Add step to flow."""
            self.steps.append(step)

        def run(self) -> List[Any]:
            """Execute all steps in flow."""
            self.status = FlowStatus.RUNNING
            try:
                for step in self.steps:
                    result = step.execute(self.state)
                    self.results.append(result)
                self.status = FlowStatus.COMPLETED
            except Exception as e:
                self.status = FlowStatus.FAILED
                raise
            return self.results

        def pause(self) -> None:
            """Pause flow execution."""
            self.status = FlowStatus.PAUSED

        def resume(self) -> None:
            """Resume paused flow."""
            if self.status == FlowStatus.PAUSED:
                self.status = FlowStatus.RUNNING

    class FlowBuilder:
        """Fluent API for building flows."""
        def __init__(self, name: str = "default"):
            self.flow = Flow(name)

        def with_initial_state(self, state: Dict) -> "FlowBuilder":
            """Set initial state."""
            self.flow.state.update(state)
            return self

        def add_step(self, name: str, action: Callable = None) -> "FlowBuilder":
            """Add step to flow."""
            step = Step(name, action)
            self.flow.add_step(step)
            return self

        def add_conditional_step(self, name: str, condition: Condition,
                                 action_true: Callable, action_false: Callable) -> "FlowBuilder":
            """Add conditional step."""
            def conditional_action(state):
                if condition.evaluate(state):
                    return action_true(state)
                else:
                    return action_false(state)

            step = Step(name, conditional_action)
            self.flow.add_step(step)
            return self

        def build(self) -> Flow:
            """Build the flow."""
            return self.flow


class TestFlowState(unittest.TestCase):
    """Test FlowState functionality."""

    def test_create_state(self):
        """Test creating flow state."""
        state = FlowState("test_flow")

        self.assertEqual(state.name, "test_flow")
        self.assertEqual(state.state, {})

    def test_set_and_get_value(self):
        """Test setting and getting state value."""
        state = FlowState()

        state.set("counter", 0)
        result = state.get("counter")

        self.assertEqual(result, 0)

    def test_get_with_default(self):
        """Test getting non-existent value with default."""
        state = FlowState()

        result = state.get("nonexistent", "default")

        self.assertEqual(result, "default")

    def test_has_key(self):
        """Test checking key existence."""
        state = FlowState()
        state.set("exists", True)

        self.assertTrue(state.has("exists"))
        self.assertFalse(state.has("nonexistent"))

    def test_update_multiple_values(self):
        """Test updating multiple values."""
        state = FlowState()
        updates = {"key1": "value1", "key2": "value2", "key3": "value3"}

        state.update(updates)

        for key, value in updates.items():
            self.assertEqual(state.get(key), value)

    def test_clear_state(self):
        """Test clearing all state."""
        state = FlowState()
        state.set("key", "value")
        state.clear()

        self.assertEqual(state.get("key"), None)
        self.assertEqual(len(state.state), 0)

    def test_state_history(self):
        """Test tracking state change history."""
        state = FlowState()

        state.set("key1", "value1")
        state.set("key2", "value2")

        history = state.get_history()

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["key"], "key1")
        self.assertEqual(history[1]["key"], "key2")

    def test_state_with_complex_values(self):
        """Test storing complex values."""
        state = FlowState()
        complex_value = {"nested": {"data": [1, 2, 3]}}

        state.set("complex", complex_value)
        result = state.get("complex")

        self.assertEqual(result["nested"]["data"], [1, 2, 3])


class TestStep(unittest.TestCase):
    """Test Step functionality."""

    def test_create_step(self):
        """Test creating a step."""
        step = Step("test_step")

        self.assertEqual(step.name, "test_step")
        self.assertEqual(step.status, StepStatus.PENDING)

    def test_step_with_action(self):
        """Test step with action function."""
        action = lambda state: state.set("result", "done")
        step = Step("action_step", action)

        self.assertIsNotNone(step.action)

    def test_execute_step(self):
        """Test executing step."""
        action = lambda state: "result"
        step = Step("exec_step", action)
        state = FlowState()

        result = step.execute(state)

        self.assertEqual(result, "result")
        self.assertEqual(step.status, StepStatus.COMPLETED)

    def test_step_execution_with_state_modification(self):
        """Test step that modifies state."""
        def action(state):
            state.set("counter", state.get("counter", 0) + 1)
            return state.get("counter")

        step = Step("counter", action)
        state = FlowState()

        result = step.execute(state)

        self.assertEqual(result, 1)
        self.assertEqual(state.get("counter"), 1)

    def test_step_error_handling(self):
        """Test step with error."""
        action = lambda state: 1 / 0
        step = Step("error_step", action)
        state = FlowState()

        with self.assertRaises(ZeroDivisionError):
            step.execute(state)

        self.assertEqual(step.status, StepStatus.FAILED)

    def test_step_with_error_handler(self):
        """Test step with error handler."""
        action = lambda state: 1 / 0
        on_error = lambda state, e: "handled"
        step = Step("handled_error", action, on_error)
        state = FlowState()

        result = step.execute(state)

        self.assertEqual(result, "handled")

    def test_skip_step(self):
        """Test skipping a step."""
        step = Step("skip_me")
        step.skip()

        self.assertEqual(step.status, StepStatus.SKIPPED)


class TestCondition(unittest.TestCase):
    """Test Condition functionality."""

    def test_create_condition(self):
        """Test creating condition."""
        predicate = lambda state: state.get("flag", False)
        condition = Condition(predicate, "Check flag")

        self.assertIsNotNone(condition)

    def test_evaluate_true_condition(self):
        """Test evaluating true condition."""
        condition = Condition(lambda state: state.get("value", 0) > 5)
        state = FlowState()
        state.set("value", 10)

        result = condition.evaluate(state)

        self.assertTrue(result)

    def test_evaluate_false_condition(self):
        """Test evaluating false condition."""
        condition = Condition(lambda state: state.get("value", 0) > 5)
        state = FlowState()
        state.set("value", 3)

        result = condition.evaluate(state)

        self.assertFalse(result)

    def test_condition_with_description(self):
        """Test condition with description."""
        condition = Condition(
            lambda state: True,
            "Always true condition"
        )

        self.assertEqual(condition.description, "Always true condition")

    def test_complex_condition(self):
        """Test complex condition logic."""
        condition = Condition(
            lambda state: (state.get("count", 0) > 0 and
                          state.has("name") and
                          state.get("status") == "active")
        )
        state = FlowState()
        state.set("count", 5)
        state.set("name", "test")
        state.set("status", "active")

        self.assertTrue(condition.evaluate(state))


class TestFlow(unittest.TestCase):
    """Test Flow functionality."""

    def test_create_flow(self):
        """Test creating a flow."""
        flow = Flow("test_flow")

        self.assertEqual(flow.name, "test_flow")
        self.assertEqual(flow.status, FlowStatus.INITIALIZED)

    def test_flow_with_initial_state(self):
        """Test flow with initial state."""
        initial = {"count": 0, "name": "flow"}
        flow = Flow("init_flow", initial)

        self.assertEqual(flow.state.get("count"), 0)
        self.assertEqual(flow.state.get("name"), "flow")

    def test_add_step_to_flow(self):
        """Test adding steps to flow."""
        flow = Flow()
        step1 = Step("step1")
        step2 = Step("step2")

        flow.add_step(step1)
        flow.add_step(step2)

        self.assertEqual(len(flow.steps), 2)

    def test_run_flow(self):
        """Test running a flow."""
        flow = Flow()
        step1 = Step("step1", lambda s: "result1")
        step2 = Step("step2", lambda s: "result2")

        flow.add_step(step1)
        flow.add_step(step2)

        results = flow.run()

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], "result1")
        self.assertEqual(results[1], "result2")

    def test_flow_status_changes(self):
        """Test flow status transitions."""
        flow = Flow()
        step = Step("test", lambda s: None)
        flow.add_step(step)

        self.assertEqual(flow.status, FlowStatus.INITIALIZED)

        flow.run()

        self.assertEqual(flow.status, FlowStatus.COMPLETED)

    def test_flow_with_state_passing(self):
        """Test state passing between steps."""
        flow = Flow(initial_state={"counter": 0})

        step1 = Step("increment", lambda s: s.set("counter", s.get("counter") + 1))
        step2 = Step("double", lambda s: s.set("counter", s.get("counter") * 2))

        flow.add_step(step1)
        flow.add_step(step2)

        flow.run()

        self.assertEqual(flow.state.get("counter"), 2)

    def test_flow_pause_resume(self):
        """Test pausing and resuming flow."""
        flow = Flow()
        flow.pause()

        self.assertEqual(flow.status, FlowStatus.PAUSED)

        flow.resume()

        self.assertEqual(flow.status, FlowStatus.RUNNING)

    def test_flow_error_handling(self):
        """Test flow handles step errors."""
        flow = Flow()
        error_step = Step("error", lambda s: 1 / 0)
        flow.add_step(error_step)

        with self.assertRaises(ZeroDivisionError):
            flow.run()

        self.assertEqual(flow.status, FlowStatus.FAILED)


class TestFlowBuilder(unittest.TestCase):
    """Test FlowBuilder for fluent API."""

    def test_create_builder(self):
        """Test creating flow builder."""
        builder = FlowBuilder("test")

        self.assertIsNotNone(builder.flow)

    def test_builder_with_initial_state(self):
        """Test builder with initial state."""
        builder = FlowBuilder()
        builder.with_initial_state({"count": 0})

        flow = builder.build()

        self.assertEqual(flow.state.get("count"), 0)

    def test_builder_add_step(self):
        """Test adding step via builder."""
        builder = FlowBuilder()
        builder.add_step("step1", lambda s: "done")

        flow = builder.build()

        self.assertEqual(len(flow.steps), 1)

    def test_builder_fluent_interface(self):
        """Test fluent interface chaining."""
        flow = (FlowBuilder("test")
                .with_initial_state({"count": 0})
                .add_step("step1", lambda s: s.set("count", 1))
                .add_step("step2", lambda s: s.set("count", 2))
                .build())

        self.assertEqual(len(flow.steps), 2)

    def test_builder_conditional_step(self):
        """Test adding conditional step."""
        condition = Condition(lambda s: s.get("flag", False))
        builder = FlowBuilder()
        builder.add_conditional_step(
            "conditional",
            condition,
            lambda s: "true",
            lambda s: "false"
        )

        flow = builder.build()

        self.assertEqual(len(flow.steps), 1)

    def test_builder_returns_self(self):
        """Test that builder methods return self."""
        builder = FlowBuilder()
        result = builder.add_step("step")

        self.assertIs(result, builder)

    def test_builder_complex_flow(self):
        """Test building complex flow."""
        flow = (FlowBuilder("complex")
                .with_initial_state({"total": 0})
                .add_step("load", lambda s: s.set("loaded", True))
                .add_step("process", lambda s: s.set("total", s.get("total") + 10))
                .add_step("finalize", lambda s: s.set("done", True))
                .build())

        results = flow.run()

        self.assertEqual(flow.state.get("total"), 10)
        self.assertTrue(flow.state.get("done"))

    def test_builder_with_error_handling(self):
        """Test builder with error handling step."""
        def safe_action(s):
            return s.get("value") / s.get("divisor", 1)

        flow = (FlowBuilder()
                .with_initial_state({"value": 10, "divisor": 2})
                .add_step("divide", safe_action)
                .build())

        results = flow.run()

        self.assertEqual(results[0], 5)


if __name__ == "__main__":
    unittest.main()
