"""
Tests for rules engine module.

Tests rule creation, condition evaluation, action execution,
priority, and conflict resolution.
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from thomas.marketplace.iot_platform._exceptions import InvalidRuleError
from thomas.marketplace.iot_platform._types import AlertSeverity, TelemetryPoint
from thomas.marketplace.iot_platform.rules_engine import RulesEngine


class TestRulesEngine:
    """Test rules engine functionality."""

    @pytest.fixture
    def engine(self) -> RulesEngine:
        """Create a rules engine instance."""
        return RulesEngine()

    @pytest.fixture
    def device_id(self) -> str:
        """Get a test device ID."""
        return uuid4()

    def test_create_threshold_rule(self, engine: RulesEngine, device_id) -> None:
        """Test creating a threshold rule."""
        condition = {
            "type": "threshold",
            "device_id": device_id,
            "metric": "temperature",
            "operator": ">",
            "value": 30.0,
        }

        actions = [
            {
                "type": "alert",
                "severity": "warning",
                "message": "Temperature high",
            }
        ]

        rule = engine.create_rule(
            name="High Temperature Alert",
            condition=condition,
            actions=actions,
        )

        assert rule.name == "High Temperature Alert"
        assert rule.enabled is True

    def test_create_rule_invalid_condition(self, engine: RulesEngine, device_id) -> None:
        """Test creating rule with invalid condition fails."""
        condition = {
            "type": "threshold",
            # Missing required fields
        }

        actions = [{"type": "alert", "severity": "warning"}]

        with pytest.raises(InvalidRuleError):
            engine.create_rule(
                name="Invalid Rule",
                condition=condition,
                actions=actions,
            )

    def test_create_rule_invalid_action(self, engine: RulesEngine, device_id) -> None:
        """Test creating rule with invalid action fails."""
        condition = {
            "type": "threshold",
            "device_id": device_id,
            "metric": "temperature",
            "operator": ">",
            "value": 30.0,
        }

        actions = [{"type": "alert"}]  # Missing severity

        with pytest.raises(InvalidRuleError):
            engine.create_rule(
                name="Invalid Rule",
                condition=condition,
                actions=actions,
            )

    def test_evaluate_threshold_condition(self, engine: RulesEngine, device_id) -> None:
        """Test threshold condition evaluation."""
        condition = {
            "type": "threshold",
            "device_id": device_id,
            "metric": "temperature",
            "operator": ">",
            "value": 30.0,
        }

        actions = [
            {
                "type": "alert",
                "severity": "warning",
                "message": "Temperature high",
            }
        ]

        engine.create_rule(
            name="High Temperature Alert",
            condition=condition,
            actions=actions,
        )

        # Test with value above threshold
        point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=35.0,
            timestamp=datetime.utcnow(),
        )

        alerts = engine.evaluate_telemetry(point)

        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING

    def test_evaluate_threshold_no_trigger(self, engine: RulesEngine, device_id) -> None:
        """Test threshold condition not triggered."""
        condition = {
            "type": "threshold",
            "device_id": device_id,
            "metric": "temperature",
            "operator": ">",
            "value": 30.0,
        }

        actions = [
            {
                "type": "alert",
                "severity": "warning",
                "message": "Temperature high",
            }
        ]

        engine.create_rule(
            name="High Temperature Alert",
            condition=condition,
            actions=actions,
        )

        # Test with value below threshold
        point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=25.0,
            timestamp=datetime.utcnow(),
        )

        alerts = engine.evaluate_telemetry(point)

        assert len(alerts) == 0

    def test_evaluate_pattern_increasing(self, engine: RulesEngine, device_id) -> None:
        """Test pattern condition for increasing values."""
        condition = {
            "type": "pattern",
            "device_id": device_id,
            "metric": "temperature",
            "pattern": "increasing",
            "duration_minutes": 10,
        }

        actions = [
            {
                "type": "alert",
                "severity": "info",
                "message": "Temperature increasing",
            }
        ]

        engine.create_rule(
            name="Temperature Increasing",
            condition=condition,
            actions=actions,
        )

        now = datetime.utcnow()

        # Ingest increasing values
        for i in range(5):
            point = TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=20.0 + i,
                timestamp=now - timedelta(minutes=5 - i),
            )
            engine.evaluate_telemetry(point)

        # Test final point
        final_point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=25.0,
            timestamp=now,
        )

        alerts = engine.evaluate_telemetry(final_point)

        assert len(alerts) == 1

    def test_evaluate_compound_and(self, engine: RulesEngine, device_id) -> None:
        """Test compound AND condition."""
        condition = {
            "type": "compound",
            "operator": "AND",
            "conditions": [
                {
                    "type": "threshold",
                    "device_id": device_id,
                    "metric": "temperature",
                    "operator": ">",
                    "value": 25.0,
                },
                {
                    "type": "threshold",
                    "device_id": device_id,
                    "metric": "temperature",
                    "operator": "<",
                    "value": 35.0,
                },
            ],
        }

        actions = [
            {
                "type": "alert",
                "severity": "info",
                "message": "Temperature in range",
            }
        ]

        engine.create_rule(
            name="Temperature Range",
            condition=condition,
            actions=actions,
        )

        # Test within range
        point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=30.0,
            timestamp=datetime.utcnow(),
        )

        alerts = engine.evaluate_telemetry(point)

        assert len(alerts) == 1

    def test_evaluate_compound_or(self, engine: RulesEngine, device_id) -> None:
        """Test compound OR condition."""
        condition = {
            "type": "compound",
            "operator": "OR",
            "conditions": [
                {
                    "type": "threshold",
                    "device_id": device_id,
                    "metric": "temperature",
                    "operator": "<",
                    "value": 10.0,
                },
                {
                    "type": "threshold",
                    "device_id": device_id,
                    "metric": "temperature",
                    "operator": ">",
                    "value": 40.0,
                },
            ],
        }

        actions = [
            {
                "type": "alert",
                "severity": "error",
                "message": "Extreme temperature",
            }
        ]

        engine.create_rule(
            name="Extreme Temperature",
            condition=condition,
            actions=actions,
        )

        # Test high extreme
        point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=45.0,
            timestamp=datetime.utcnow(),
        )

        alerts = engine.evaluate_telemetry(point)

        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ERROR

    def test_rule_priority(self, engine: RulesEngine, device_id) -> None:
        """Test rule priority affects execution order."""
        condition = {
            "type": "threshold",
            "device_id": device_id,
            "metric": "temperature",
            "operator": ">",
            "value": 25.0,
        }

        # Create two rules with different priorities
        rule1 = engine.create_rule(
            name="Rule 1",
            condition=condition,
            actions=[{"type": "alert", "severity": "warning"}],
            priority=1,
        )

        rule2 = engine.create_rule(
            name="Rule 2",
            condition=condition,
            actions=[{"type": "alert", "severity": "error"}],
            priority=10,
        )

        # Higher priority should execute first
        all_rules = engine.list_rules()
        sorted_rules = sorted(all_rules, key=lambda r: r.priority, reverse=True)

        assert sorted_rules[0].rule_id == rule2.rule_id

    def test_update_rule(self, engine: RulesEngine, device_id) -> None:
        """Test updating a rule."""
        condition = {
            "type": "threshold",
            "device_id": device_id,
            "metric": "temperature",
            "operator": ">",
            "value": 30.0,
        }

        actions = [
            {
                "type": "alert",
                "severity": "warning",
                "message": "Temperature high",
            }
        ]

        rule = engine.create_rule(
            name="High Temperature Alert",
            condition=condition,
            actions=actions,
        )

        updated = engine.update_rule(rule.rule_id, enabled=False)

        assert updated.enabled is False

    def test_delete_rule(self, engine: RulesEngine, device_id) -> None:
        """Test deleting a rule."""
        condition = {
            "type": "threshold",
            "device_id": device_id,
            "metric": "temperature",
            "operator": ">",
            "value": 30.0,
        }

        actions = [
            {
                "type": "alert",
                "severity": "warning",
                "message": "Temperature high",
            }
        ]

        rule = engine.create_rule(
            name="High Temperature Alert",
            condition=condition,
            actions=actions,
        )

        engine.delete_rule(rule.rule_id)

        with pytest.raises(Exception):
            engine.get_rule(rule.rule_id)

    def test_alert_handler(self, engine: RulesEngine, device_id) -> None:
        """Test alert handler callback."""
        handled_alerts = []

        def alert_handler(alert):
            handled_alerts.append(alert)

        engine.register_alert_handler(alert_handler)

        condition = {
            "type": "threshold",
            "device_id": device_id,
            "metric": "temperature",
            "operator": ">",
            "value": 30.0,
        }

        actions = [
            {
                "type": "alert",
                "severity": "warning",
                "message": "Temperature high",
            }
        ]

        engine.create_rule(
            name="High Temperature Alert",
            condition=condition,
            actions=actions,
        )

        point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=35.0,
            timestamp=datetime.utcnow(),
        )

        engine.evaluate_telemetry(point)

        assert len(handled_alerts) == 1

    def test_get_rule_count(self, engine: RulesEngine, device_id) -> None:
        """Test getting rule count."""
        condition = {
            "type": "threshold",
            "device_id": device_id,
            "metric": "temperature",
            "operator": ">",
            "value": 30.0,
        }

        actions = [
            {
                "type": "alert",
                "severity": "warning",
                "message": "Temperature high",
            }
        ]

        engine.create_rule(
            name="Rule 1",
            condition=condition,
            actions=actions,
        )

        engine.create_rule(
            name="Rule 2",
            condition=condition,
            actions=actions,
        )

        assert engine.get_rule_count() == 2
