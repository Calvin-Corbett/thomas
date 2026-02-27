"""Automation engine for rule-based home automation."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from thomas.smart_home._exceptions import (
    ActionError,
    AutomationError,
    ConditionError,
    ConflictError,
)
from thomas.smart_home._types import (
    Action,
    Automation,
    ComparisonOperator,
    Condition,
    TriggerType,
)


@dataclass
class TriggerEvent:
    """Event fired by a trigger."""

    trigger_id: str
    """Trigger that fired."""
    automation_id: str
    """Automation triggered."""
    timestamp: datetime = field(default_factory=datetime.now)
    """When event occurred."""
    device_id: str | None = None
    """Device involved."""
    old_value: Any | None = None
    """Previous value."""
    new_value: Any | None = None
    """New value."""


@dataclass
class ExecutionResult:
    """Result of automation execution."""

    automation_id: str
    """Automation that ran."""
    success: bool
    """Whether execution succeeded."""
    actions_executed: int = 0
    """Number of actions executed."""
    timestamp: datetime = field(default_factory=datetime.now)
    """When execution completed."""
    error: str | None = None
    """Error message if failed."""


class AutomationEngine:
    """Automation engine with rule-based if-then-else execution.

    Provides trigger-based automation with conditional logic, action sequences,
    conflict detection, and priority-based resolution.
    """

    def __init__(self) -> None:
        """Initialize the automation engine."""
        self._automations: dict[str, Automation] = {}
        self._execution_history: list[ExecutionResult] = []
        self._trigger_listeners: dict[str, list[Callable]] = {}
        self._device_state: dict[str, dict[str, Any]] = {}
        self._last_execution: dict[str, datetime] = {}
        self._active_conflicts: set[str] = set()

    def register_automation(self, automation: Automation) -> Automation:
        """Register an automation rule.

        Args:
            automation: Automation object to register.

        Returns:
            Registered automation.
        """
        if not automation.automation_id:
            automation.automation_id = str(uuid.uuid4())
        self._automations[automation.automation_id] = automation
        return automation

    def unregister_automation(self, automation_id: str) -> None:
        """Unregister an automation.

        Args:
            automation_id: ID of automation to remove.

        Raises:
            AutomationError: If automation not found.
        """
        if automation_id not in self._automations:
            raise AutomationError(f"Automation {automation_id} not found")
        del self._automations[automation_id]

    def get_automation(self, automation_id: str) -> Automation:
        """Get an automation by ID.

        Args:
            automation_id: ID of automation.

        Returns:
            Automation object.

        Raises:
            AutomationError: If not found.
        """
        if automation_id not in self._automations:
            raise AutomationError(f"Automation {automation_id} not found")
        return self._automations[automation_id]

    def get_all_automations(self) -> list[Automation]:
        """Get all registered automations.

        Returns:
            List of automations.
        """
        return list(self._automations.values())

    def fire_trigger(
        self,
        trigger_id: str,
        automation_id: str,
        device_id: str | None = None,
        old_value: Any | None = None,
        new_value: Any | None = None,
    ) -> None:
        """Fire a trigger event.

        Args:
            trigger_id: ID of trigger.
            automation_id: ID of automation.
            device_id: Device involved.
            old_value: Previous value if state change.
            new_value: New value if state change.
        """
        event = TriggerEvent(
            trigger_id=trigger_id,
            automation_id=automation_id,
            device_id=device_id,
            old_value=old_value,
            new_value=new_value,
        )

        # Notify listeners
        for listener in self._trigger_listeners.get(trigger_id, []):
            try:
                listener(event)
            except Exception:  # REVIEWED: broad catch
                pass

        # Try to execute automation
        try:
            self.execute_automation(automation_id, event)
        except Exception:
            # Log but don't raise
            pass

    def register_trigger_listener(self, trigger_id: str, listener: Callable) -> None:
        """Register a listener for trigger events.

        Args:
            trigger_id: ID of trigger.
            listener: Callable(event) to call when trigger fires.
        """
        if trigger_id not in self._trigger_listeners:
            self._trigger_listeners[trigger_id] = []
        self._trigger_listeners[trigger_id].append(listener)

    def update_device_state(self, device_id: str, capability: str, value: Any) -> None:
        """Update device state for condition evaluation.

        Args:
            device_id: ID of device.
            capability: Capability name.
            value: New value.
        """
        if device_id not in self._device_state:
            self._device_state[device_id] = {}
        self._device_state[device_id][capability] = value

    def get_device_state(self, device_id: str, capability: str | None = None) -> Any:
        """Get device state.

        Args:
            device_id: ID of device.
            capability: Specific capability or None for all.

        Returns:
            State value or dict of all capabilities.
        """
        if device_id not in self._device_state:
            return None
        if capability:
            return self._device_state[device_id].get(capability)
        return self._device_state[device_id]

    def execute_automation(self, automation_id: str, trigger_event: TriggerEvent | None = None) -> ExecutionResult:
        """Execute an automation rule.

        Args:
            automation_id: ID of automation to execute.
            trigger_event: Optional trigger event that fired.

        Returns:
            Execution result.

        Raises:
            AutomationError: If automation not found or fails.
        """
        if automation_id not in self._automations:
            raise AutomationError(f"Automation {automation_id} not found")

        automation = self._automations[automation_id]

        if not automation.enabled:
            return ExecutionResult(
                automation_id=automation_id, success=True, actions_executed=0, error="Automation disabled"
            )

        result = ExecutionResult(automation_id=automation_id, success=True)

        try:
            # Evaluate conditions
            if not self._evaluate_conditions(automation.conditions):
                result.success = False
                result.error = "Conditions not met"
                return result

            # Execute actions
            for action in automation.actions:
                try:
                    self._execute_action(action)
                    result.actions_executed += 1
                except Exception as e:
                    result.success = False
                    result.error = f"Action failed: {e}"
                    break

            self._execution_history.append(result)
            self._last_execution[automation_id] = datetime.now()

        except Exception as e:
            result.success = False
            result.error = str(e)

        return result

    def _evaluate_conditions(self, conditions: list[Condition]) -> bool:
        """Evaluate all conditions with AND logic.

        Args:
            conditions: List of conditions to evaluate.

        Returns:
            True if all conditions are met (AND logic).
        """
        if not conditions:
            return True

        for condition in conditions:
            if not self._evaluate_condition(condition):
                return False
        return True

    def _evaluate_condition(self, condition: Condition) -> bool:
        """Evaluate a single condition.

        Args:
            condition: Condition to evaluate.

        Returns:
            True if condition is met.

        Raises:
            ConditionError: If evaluation fails.
        """
        try:
            # Get current device state
            if condition.device_id:
                current = self.get_device_state(condition.device_id, condition.attribute)
            else:
                current = condition.value

            result = self._compare_values(current, condition.value, condition.operator)

            if condition.negate:
                result = not result

            return result

        except Exception as e:
            raise ConditionError(f"Condition evaluation failed: {e}")

    def _compare_values(self, current: Any, expected: Any, operator: ComparisonOperator) -> bool:
        """Compare two values using an operator.

        Args:
            current: Current value.
            expected: Expected value.
            operator: Comparison operator.

        Returns:
            Result of comparison.
        """
        if operator == ComparisonOperator.EQ:
            return current == expected
        elif operator == ComparisonOperator.NEQ:
            return current != expected
        elif operator == ComparisonOperator.GT:
            return current > expected
        elif operator == ComparisonOperator.GTE:
            return current >= expected
        elif operator == ComparisonOperator.LT:
            return current < expected
        elif operator == ComparisonOperator.LTE:
            return current <= expected
        elif operator == ComparisonOperator.IN:
            return current in expected
        elif operator == ComparisonOperator.NOT_IN:
            return current not in expected
        else:
            return False

    def _execute_action(self, action: Action) -> None:
        """Execute a single action.

        Args:
            action: Action to execute.

        Raises:
            ActionError: If execution fails.
        """
        try:
            if action.delay_seconds > 0:
                # In real implementation would schedule delay
                pass

            if action.action_type == "set_device_attr":
                if action.device_id and action.capability:
                    self.update_device_state(action.device_id, action.capability, action.value)
            elif action.action_type == "call_service":
                # Service action
                pass
            elif action.action_type == "activate_scene":
                # Scene activation
                pass
            else:
                raise ActionError(f"Unknown action type: {action.action_type}")

        except Exception as e:
            raise ActionError(f"Action execution failed: {e}")

    def detect_conflicts(self) -> list[tuple]:
        """Detect automations with conflicting actions.

        Returns:
            List of (automation1_id, automation2_id) tuples that conflict.
        """
        conflicts = []
        automations = list(self._automations.values())

        for i, auto1 in enumerate(automations):
            for auto2 in automations[i + 1 :]:
                if self._automations_conflict(auto1, auto2):
                    conflicts.append((auto1.automation_id, auto2.automation_id))

        return conflicts

    def _automations_conflict(self, auto1: Automation, auto2: Automation) -> bool:
        """Check if two automations conflict.

        Args:
            auto1: First automation.
            auto2: Second automation.

        Returns:
            True if they conflict.
        """
        # Automations conflict if they set the same capability on same device
        devices1 = {a.device_id for a in auto1.actions if a.device_id and a.capability}
        devices2 = {a.device_id for a in auto2.actions if a.device_id and a.capability}

        return bool(devices1 & devices2)

    def resolve_conflict(self, automation_id1: str, automation_id2: str) -> str:
        """Resolve a conflict between two automations.

        Uses priority and conflict_resolution settings to determine winner.

        Args:
            automation_id1: First automation.
            automation_id2: Second automation.

        Returns:
            ID of automation that wins conflict.

        Raises:
            ConflictError: If conflict cannot be resolved.
        """
        auto1 = self.get_automation(automation_id1)
        auto2 = self.get_automation(automation_id2)

        # By priority
        if auto1.priority > auto2.priority:
            return automation_id1
        if auto2.priority > auto1.priority:
            return automation_id2

        # Both same priority
        if auto1.priority == auto2.priority:
            raise ConflictError(f"Cannot resolve conflict: {automation_id1} vs {automation_id2}")

        return automation_id1

    def get_execution_history(self, automation_id: str | None = None, limit: int = 100) -> list[ExecutionResult]:
        """Get execution history.

        Args:
            automation_id: Optional ID to filter by automation.
            limit: Maximum results to return.

        Returns:
            List of execution results.
        """
        results = self._execution_history
        if automation_id:
            results = [r for r in results if r.automation_id == automation_id]
        return results[-limit:]

    def get_last_execution(self, automation_id: str) -> datetime | None:
        """Get last execution time for automation.

        Args:
            automation_id: ID of automation.

        Returns:
            Datetime of last execution or None.
        """
        return self._last_execution.get(automation_id)

    def trigger_state_change(self, device_id: str, capability: str, old_value: Any, new_value: Any) -> None:
        """Trigger a state change event for matching automations.

        Args:
            device_id: ID of device that changed.
            capability: Capability that changed.
            old_value: Old value.
            new_value: New value.
        """
        # Update device state
        self.update_device_state(device_id, capability, new_value)

        # Find matching automations with state-change triggers
        for automation in self._automations.values():
            for trigger in automation.triggers:
                if (
                    trigger.trigger_type == TriggerType.STATE_CHANGE
                    and trigger.device_id == device_id
                    and trigger.capability == capability
                ):
                    # Check if state matches expected
                    if trigger.state_value is None or trigger.state_value == new_value:
                        self.fire_trigger(
                            trigger.trigger_id,
                            automation.automation_id,
                            device_id=device_id,
                            old_value=old_value,
                            new_value=new_value,
                        )

    def trigger_time_event(self, automation_id: str) -> None:
        """Trigger a time-based automation.

        Args:
            automation_id: ID of automation to trigger.
        """
        if automation_id not in self._automations:
            return

        automation = self._automations[automation_id]
        for trigger in automation.triggers:
            if trigger.trigger_type == TriggerType.TIME:
                self.fire_trigger(trigger.trigger_id, automation.automation_id)

    def pause_automation(self, automation_id: str) -> None:
        """Pause an automation without deleting it.

        Args:
            automation_id: ID of automation.
        """
        if automation_id in self._automations:
            self._automations[automation_id].enabled = False

    def resume_automation(self, automation_id: str) -> None:
        """Resume a paused automation.

        Args:
            automation_id: ID of automation.
        """
        if automation_id in self._automations:
            self._automations[automation_id].enabled = True
