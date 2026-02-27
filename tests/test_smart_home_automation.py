"""Tests for automation engine."""

from datetime import datetime

import pytest

from thomas.smart_home._exceptions import AutomationError
from thomas.smart_home._types import (
    Action,
    Automation,
    ComparisonOperator,
    Condition,
    Trigger,
    TriggerType,
)
from thomas.smart_home.automation import AutomationEngine


class TestAutomationEngine:
    """Test AutomationEngine functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = AutomationEngine()

    def test_register_automation(self):
        """Test automation registration."""
        auto = Automation(automation_id="", name="Test Automation")

        registered = self.engine.register_automation(auto)

        assert registered.automation_id is not None
        assert registered.name == "Test Automation"
        assert self.engine.get_automation(registered.automation_id) == registered

    def test_unregister_automation(self):
        """Test unregistering automation."""
        auto = Automation(automation_id="", name="Test")

        registered = self.engine.register_automation(auto)
        self.engine.unregister_automation(registered.automation_id)

        with pytest.raises(AutomationError):
            self.engine.get_automation(registered.automation_id)

    def test_simple_state_change_trigger(self):
        """Test state change trigger."""
        trigger = Trigger(
            trigger_id="trigger1", trigger_type=TriggerType.STATE_CHANGE, device_id="light1", capability="on_off"
        )

        action = Action(
            action_id="action1", action_type="set_device_attr", device_id="light2", capability="on_off", value=True
        )

        auto = Automation(automation_id="", name="Light Chain", triggers=[trigger], actions=[action])

        registered = self.engine.register_automation(auto)

        # Simulate state change
        self.engine.trigger_state_change("light1", "on_off", False, True)

        # Check history
        history = self.engine.get_execution_history()
        assert len(history) > 0

    def test_condition_evaluation_true(self):
        """Test condition evaluation when true."""
        condition = Condition(attribute="brightness", operator=ComparisonOperator.GT, value=100, device_id="light1")

        auto = Automation(automation_id="", name="Test", conditions=[condition], actions=[])

        registered = self.engine.register_automation(auto)

        # Set device state
        self.engine.update_device_state("light1", "brightness", 150)

        # Execute
        result = self.engine.execute_automation(registered.automation_id)

        assert result.success is True

    def test_condition_evaluation_false(self):
        """Test condition evaluation when false."""
        condition = Condition(attribute="brightness", operator=ComparisonOperator.GT, value=100, device_id="light1")

        auto = Automation(automation_id="", name="Test", conditions=[condition], actions=[])

        registered = self.engine.register_automation(auto)

        # Set device state below threshold
        self.engine.update_device_state("light1", "brightness", 50)

        # Execute
        result = self.engine.execute_automation(registered.automation_id)

        assert result.success is False

    def test_action_execution(self):
        """Test action execution."""
        action = Action(
            action_id="action1", action_type="set_device_attr", device_id="light1", capability="brightness", value=200
        )

        auto = Automation(automation_id="", name="Test", actions=[action])

        registered = self.engine.register_automation(auto)
        result = self.engine.execute_automation(registered.automation_id)

        assert result.actions_executed == 1
        assert result.success is True

    def test_multiple_actions(self):
        """Test executing multiple actions."""
        actions = [
            Action(
                action_id="action1", action_type="set_device_attr", device_id="light1", capability="on_off", value=True
            ),
            Action(
                action_id="action2", action_type="set_device_attr", device_id="light2", capability="on_off", value=True
            ),
            Action(
                action_id="action3", action_type="set_device_attr", device_id="light3", capability="on_off", value=True
            ),
        ]

        auto = Automation(automation_id="", name="Test", actions=actions)

        registered = self.engine.register_automation(auto)
        result = self.engine.execute_automation(registered.automation_id)

        assert result.actions_executed == 3

    def test_and_conditions(self):
        """Test AND logic for multiple conditions."""
        conditions = [
            Condition(attribute="brightness", operator=ComparisonOperator.GT, value=100, device_id="light1"),
            Condition(attribute="on_off", operator=ComparisonOperator.EQ, value=True, device_id="light1"),
        ]

        auto = Automation(automation_id="", name="Test", conditions=conditions, actions=[])

        registered = self.engine.register_automation(auto)

        # Both conditions met
        self.engine.update_device_state("light1", "brightness", 150)
        self.engine.update_device_state("light1", "on_off", True)

        result = self.engine.execute_automation(registered.automation_id)
        assert result.success is True

        # Only one condition met
        self.engine.update_device_state("light1", "brightness", 50)
        result = self.engine.execute_automation(registered.automation_id)
        assert result.success is False

    def test_comparison_operators(self):
        """Test various comparison operators."""
        ops = [
            (ComparisonOperator.EQ, 100, 100, True),
            (ComparisonOperator.NEQ, 100, 99, True),
            (ComparisonOperator.GT, 100, 101, True),
            (ComparisonOperator.GTE, 100, 100, True),
            (ComparisonOperator.LT, 100, 99, True),
            (ComparisonOperator.LTE, 100, 100, True),
            (ComparisonOperator.IN, [1, 2, 3], 2, True),
        ]

        for op, expected, actual, should_pass in ops:
            condition = Condition(attribute="test", operator=op, value=expected, device_id="device1")

            auto = Automation(automation_id="", name="Test", conditions=[condition], actions=[])

            registered = self.engine.register_automation(auto)
            self.engine.update_device_state("device1", "test", actual)
            result = self.engine.execute_automation(registered.automation_id)

            assert result.success == should_pass, f"Failed for {op}"

    def test_trigger_listener(self):
        """Test trigger listener callback."""
        trigger = Trigger(
            trigger_id="trigger1", trigger_type=TriggerType.STATE_CHANGE, device_id="light1", capability="on_off"
        )

        auto = Automation(automation_id="", name="Test", triggers=[trigger], actions=[])

        registered = self.engine.register_automation(auto)

        events = []

        def listener(event):
            events.append(event)

        self.engine.register_trigger_listener("trigger1", listener)

        # Fire trigger
        self.engine.fire_trigger("trigger1", registered.automation_id)

        assert len(events) == 1

    def test_automation_pause_resume(self):
        """Test pausing and resuming automation."""
        auto = Automation(automation_id="", name="Test", enabled=True)

        registered = self.engine.register_automation(auto)

        # Pause
        self.engine.pause_automation(registered.automation_id)
        assert not self.engine.get_automation(registered.automation_id).enabled

        # Resume
        self.engine.resume_automation(registered.automation_id)
        assert self.engine.get_automation(registered.automation_id).enabled

    def test_conflict_detection(self):
        """Test automation conflict detection."""
        auto1 = Automation(
            automation_id="",
            name="Auto1",
            actions=[
                Action(
                    action_id="action1",
                    action_type="set_device_attr",
                    device_id="light1",
                    capability="brightness",
                    value=100,
                )
            ],
        )

        auto2 = Automation(
            automation_id="",
            name="Auto2",
            actions=[
                Action(
                    action_id="action2",
                    action_type="set_device_attr",
                    device_id="light1",
                    capability="brightness",
                    value=200,
                )
            ],
        )

        reg1 = self.engine.register_automation(auto1)
        reg2 = self.engine.register_automation(auto2)

        conflicts = self.engine.detect_conflicts()

        assert len(conflicts) > 0
        assert (reg1.automation_id, reg2.automation_id) in conflicts or (
            reg2.automation_id,
            reg1.automation_id,
        ) in conflicts

    def test_conflict_resolution_by_priority(self):
        """Test conflict resolution using priority."""
        auto1 = Automation(automation_id="", name="Auto1", priority=50, actions=[])

        auto2 = Automation(automation_id="", name="Auto2", priority=80, actions=[])

        reg1 = self.engine.register_automation(auto1)
        reg2 = self.engine.register_automation(auto2)

        winner = self.engine.resolve_conflict(reg1.automation_id, reg2.automation_id)

        assert winner == reg2.automation_id

    def test_execution_history(self):
        """Test execution history tracking."""
        auto = Automation(automation_id="", name="Test", actions=[])

        registered = self.engine.register_automation(auto)

        for _ in range(5):
            self.engine.execute_automation(registered.automation_id)

        history = self.engine.get_execution_history(registered.automation_id)

        assert len(history) >= 5

    def test_last_execution_time(self):
        """Test tracking last execution time."""
        auto = Automation(automation_id="", name="Test")

        registered = self.engine.register_automation(auto)

        last = self.engine.get_last_execution(registered.automation_id)
        assert last is None

        self.engine.execute_automation(registered.automation_id)

        last = self.engine.get_last_execution(registered.automation_id)
        assert last is not None
        assert isinstance(last, datetime)

    def test_device_state_tracking(self):
        """Test device state tracking."""
        self.engine.update_device_state("light1", "brightness", 100)
        self.engine.update_device_state("light1", "on_off", True)

        state = self.engine.get_device_state("light1")

        assert state["brightness"] == 100
        assert state["on_off"] is True

    def test_get_all_automations(self):
        """Test getting all automations."""
        for i in range(3):
            auto = Automation(automation_id="", name=f"Auto {i}")
            self.engine.register_automation(auto)

        all_autos = self.engine.get_all_automations()

        assert len(all_autos) == 3

    def test_negated_condition(self):
        """Test negated condition."""
        condition = Condition(
            attribute="motion", operator=ComparisonOperator.EQ, value=False, device_id="sensor1", negate=True
        )

        auto = Automation(automation_id="", name="Test", conditions=[condition])

        registered = self.engine.register_automation(auto)

        # Motion is False, negated makes it True -> should fail
        self.engine.update_device_state("sensor1", "motion", False)
        result = self.engine.execute_automation(registered.automation_id)
        assert result.success is False

        # Motion is True, negated makes it False -> should pass
        self.engine.update_device_state("sensor1", "motion", True)
        result = self.engine.execute_automation(registered.automation_id)
        assert result.success is True
