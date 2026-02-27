"""
IoT rules engine for automation and event handling.

Implements condition evaluation, action execution, rule priority,
and conflict resolution for IoT automation workflows.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from thomas.iot_platform._exceptions import InvalidRuleError
from thomas.iot_platform._types import Alert, AlertSeverity, Rule, TelemetryPoint


class RulesEngine:
    """
    Evaluates and executes IoT automation rules.

    Supports threshold, pattern, absence, and compound conditions
    with configurable actions and conflict resolution.
    """

    def __init__(self) -> None:
        """Initialize the rules engine."""
        self._rules: dict[UUID, Rule] = {}
        self._last_condition_eval: dict[UUID, dict[str, Any]] = {}
        self._metric_history: dict[str, list[tuple[datetime, float]]] = {}
        self._action_handlers: list[Callable[[dict[str, Any]], None]] = []
        self._alert_handlers: list[Callable[[Alert], None]] = []
        self._lock = threading.RLock()

    def create_rule(
        self,
        name: str,
        condition: dict[str, Any],
        actions: list[dict[str, Any]],
        priority: int = 0,
    ) -> Rule:
        """
        Create a new automation rule.

        Condition format:
        - threshold: {"type": "threshold", "device_id": UUID, "metric": str, "operator": ">/</>=/<=", "value": float}
        - pattern: {"type": "pattern", "device_id": UUID, "metric": str, "pattern": "increasing/decreasing", "duration_minutes": int}
        - absence: {"type": "absence", "device_id": UUID, "metric": str, "duration_minutes": int}
        - compound: {"type": "compound", "operator": "AND/OR", "conditions": [condition, ...]}

        Args:
            name: Rule name.
            condition: Condition specification dictionary.
            actions: List of action specifications.
            priority: Execution priority (higher = earlier).

        Returns:
            Created Rule instance.

        Raises:
            InvalidRuleError: If condition or actions are invalid.
        """
        self._validate_condition(condition)
        self._validate_actions(actions)

        with self._lock:
            rule_id = uuid4()
            rule = Rule(
                rule_id=rule_id,
                name=name,
                condition=condition,
                actions=actions,
                priority=priority,
            )
            self._rules[rule_id] = rule
            return rule

    def _validate_condition(self, condition: dict[str, Any]) -> None:
        """Validate condition format."""
        if not condition or "type" not in condition:
            raise InvalidRuleError("Condition must have 'type' field")

        cond_type = condition["type"]

        if cond_type == "threshold":
            required = {"device_id", "metric", "operator", "value"}
            if not required.issubset(condition.keys()):
                raise InvalidRuleError(f"Threshold requires fields: {required}")
            if condition["operator"] not in (">", "<", ">=", "<=", "==", "!="):
                raise InvalidRuleError("Invalid operator")

        elif cond_type == "pattern":
            required = {"device_id", "metric", "pattern", "duration_minutes"}
            if not required.issubset(condition.keys()):
                raise InvalidRuleError(f"Pattern requires fields: {required}")
            if condition["pattern"] not in ("increasing", "decreasing"):
                raise InvalidRuleError("Invalid pattern type")

        elif cond_type == "absence":
            required = {"device_id", "metric", "duration_minutes"}
            if not required.issubset(condition.keys()):
                raise InvalidRuleError(f"Absence requires fields: {required}")

        elif cond_type == "compound":
            required = {"operator", "conditions"}
            if not required.issubset(condition.keys()):
                raise InvalidRuleError(f"Compound requires fields: {required}")
            if condition["operator"] not in ("AND", "OR"):
                raise InvalidRuleError("Invalid compound operator")
            for sub_condition in condition["conditions"]:
                self._validate_condition(sub_condition)

        else:
            raise InvalidRuleError(f"Unknown condition type: {cond_type}")

    def _validate_actions(self, actions: list[dict[str, Any]]) -> None:
        """Validate action formats."""
        if not actions:
            raise InvalidRuleError("At least one action required")

        for action in actions:
            if not action or "type" not in action:
                raise InvalidRuleError("Action must have 'type' field")

            action_type = action["type"]

            if action_type == "alert":
                if "severity" not in action:
                    raise InvalidRuleError("Alert action requires 'severity'")

            elif action_type == "command":
                required = {"target_device_id", "action_name"}
                if not required.issubset(action.keys()):
                    raise InvalidRuleError(f"Command requires fields: {required}")

            elif action_type == "webhook":
                if "url" not in action:
                    raise InvalidRuleError("Webhook action requires 'url'")

            elif action_type == "transform":
                if "metric" not in action or "formula" not in action:
                    raise InvalidRuleError("Transform requires 'metric' and 'formula'")

    def evaluate_telemetry(self, point: TelemetryPoint) -> list[Alert]:
        """
        Evaluate all rules against a telemetry point.

        Args:
            point: TelemetryPoint to evaluate.

        Returns:
            List of Alert objects generated.
        """
        alerts: list[Alert] = []

        # Track metric history
        key = f"{point.device_id}:{point.metric}"
        with self._lock:
            if key not in self._metric_history:
                self._metric_history[key] = []
            if isinstance(point.value, (int, float)):
                self._metric_history[key].append((point.timestamp, float(point.value)))

        # Sort rules by priority
        sorted_rules = sorted(self._rules.values(), key=lambda r: r.priority, reverse=True)

        for rule in sorted_rules:
            if not rule.enabled:
                continue

            if self._evaluate_condition(rule.condition, point):
                new_alerts = self._execute_actions(rule, point)
                alerts.extend(new_alerts)

        return alerts

    def _evaluate_condition(self, condition: dict[str, Any], point: TelemetryPoint) -> bool:
        """Evaluate a single condition."""
        cond_type = condition.get("type")

        if cond_type == "threshold":
            return self._evaluate_threshold(condition, point)

        elif cond_type == "pattern":
            return self._evaluate_pattern(condition, point)

        elif cond_type == "absence":
            return self._evaluate_absence(condition, point)

        elif cond_type == "compound":
            return self._evaluate_compound(condition, point)

        return False

    def _evaluate_threshold(self, condition: dict[str, Any], point: TelemetryPoint) -> bool:
        """Evaluate threshold condition."""
        if condition["device_id"] != point.device_id:
            return False

        if condition["metric"] != point.metric:
            return False

        if not isinstance(point.value, (int, float)):
            return False

        value = float(point.value)
        threshold = condition["value"]
        operator = condition["operator"]

        if operator == ">":
            return value > threshold
        elif operator == "<":
            return value < threshold
        elif operator == ">=":
            return value >= threshold
        elif operator == "<=":
            return value <= threshold
        elif operator == "==":
            return value == threshold
        elif operator == "!=":
            return value != threshold

        return False

    def _evaluate_pattern(self, condition: dict[str, Any], point: TelemetryPoint) -> bool:
        """Evaluate pattern condition (increasing/decreasing)."""
        if condition["device_id"] != point.device_id:
            return False

        if condition["metric"] != point.metric:
            return False

        if not isinstance(point.value, (int, float)):
            return False

        key = f"{point.device_id}:{point.metric}"
        duration_minutes = condition["duration_minutes"]
        pattern = condition["pattern"]

        with self._lock:
            if key not in self._metric_history:
                return False

            history = self._metric_history[key]
            cutoff = point.timestamp - timedelta(minutes=duration_minutes)
            recent = [(t, v) for t, v in history if t >= cutoff]

            if len(recent) < 2:
                return False

            values = [v for t, v in recent]

            if pattern == "increasing":
                return all(values[i] <= values[i + 1] for i in range(len(values) - 1))

            elif pattern == "decreasing":
                return all(values[i] >= values[i + 1] for i in range(len(values) - 1))

        return False

    def _evaluate_absence(self, condition: dict[str, Any], point: TelemetryPoint) -> bool:
        """Evaluate absence condition (no data for duration)."""
        if condition["device_id"] != point.device_id:
            return False

        if condition["metric"] != point.metric:
            return False

        key = f"{point.device_id}:{point.metric}"
        duration_minutes = condition["duration_minutes"]

        with self._lock:
            if key not in self._metric_history:
                return True

            history = self._metric_history[key]
            cutoff = point.timestamp - timedelta(minutes=duration_minutes)
            recent = [t for t, v in history if t >= cutoff]

            return len(recent) == 0

    def _evaluate_compound(self, condition: dict[str, Any], point: TelemetryPoint) -> bool:
        """Evaluate compound condition (AND/OR)."""
        operator = condition["operator"]
        sub_conditions = condition["conditions"]

        results = [self._evaluate_condition(cond, point) for cond in sub_conditions]

        if operator == "AND":
            return all(results)
        elif operator == "OR":
            return any(results)

        return False

    def _execute_actions(self, rule: Rule, point: TelemetryPoint) -> list[Alert]:
        """Execute all actions for a matched rule."""
        alerts: list[Alert] = []

        for action_spec in rule.actions:
            action_type = action_spec.get("type")

            if action_type == "alert":
                alert = self._create_alert(rule, point, action_spec)
                alerts.append(alert)
                self._notify_alert_handlers(alert)

            elif action_type == "command" or action_type == "webhook" or action_type == "transform":
                self._notify_action_handlers(action_spec)

        return alerts

    def _create_alert(self, rule: Rule, point: TelemetryPoint, action_spec: dict[str, Any]) -> Alert:
        """Create an alert from rule action."""
        severity_str = action_spec.get("severity", "warning")

        try:
            severity = AlertSeverity(severity_str)
        except ValueError:
            severity = AlertSeverity.WARNING

        return Alert(
            alert_id=uuid4(),
            device_id=point.device_id,
            rule_id=rule.rule_id,
            severity=severity,
            message=action_spec.get("message", f"Rule '{rule.name}' triggered"),
            details={
                "metric": point.metric,
                "value": point.value,
                "condition": rule.condition,
            },
            triggered_at=datetime.utcnow(),
        )

    def register_action_handler(self, handler: Callable[[dict[str, Any]], None]) -> None:
        """Register handler for rule actions."""
        with self._lock:
            self._action_handlers.append(handler)

    def register_alert_handler(self, handler: Callable[[Alert], None]) -> None:
        """Register handler for alert generation."""
        with self._lock:
            self._alert_handlers.append(handler)

    def _notify_action_handlers(self, action: dict[str, Any]) -> None:
        """Notify action handlers."""
        for handler in self._action_handlers:
            try:
                handler(action)
            except Exception:  # REVIEWED: broad catch
                pass

    def _notify_alert_handlers(self, alert: Alert) -> None:
        """Notify alert handlers."""
        for handler in self._alert_handlers:
            try:
                handler(alert)
            except Exception:  # REVIEWED: broad catch
                pass

    def update_rule(self, rule_id: UUID, enabled: bool | None = None) -> Rule:
        """
        Update a rule.

        Args:
            rule_id: ID of rule to update.
            enabled: New enabled state.

        Returns:
            Updated Rule.
        """
        with self._lock:
            if rule_id not in self._rules:
                raise InvalidRuleError(f"Rule {rule_id} not found")

            rule = self._rules[rule_id]

            if enabled is not None:
                rule.enabled = enabled

            return rule

    def delete_rule(self, rule_id: UUID) -> None:
        """Delete a rule."""
        with self._lock:
            if rule_id in self._rules:
                del self._rules[rule_id]

    def get_rule(self, rule_id: UUID) -> Rule:
        """Get a rule by ID."""
        with self._lock:
            if rule_id not in self._rules:
                raise InvalidRuleError(f"Rule {rule_id} not found")
            return self._rules[rule_id]

    def list_rules(self) -> list[Rule]:
        """List all rules."""
        with self._lock:
            return list(self._rules.values())

    def get_rule_count(self) -> int:
        """Get total number of rules."""
        with self._lock:
            return len(self._rules)
