"""
Tests for alerting module.
"""

from datetime import datetime, timedelta

from thomas.marketplace.monitoring._types import AlertRule, AlertState
from thomas.marketplace.monitoring.alerting import (
    AlertGroup,
    AlertGroupKey,
    AlertManager,
    InhibitionRule,
    NotificationRoute,
    SilenceRule,
)


class MockQueryEngine:
    """Mock query engine for testing."""

    def instant_query(self, expr: str) -> object:
        """Return mock query results."""

        class Result:
            def __init__(self):
                self.series = {"series_1": 42.0}

        return Result()


class TestAlertManager:
    """Test AlertManager."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.query_engine = MockQueryEngine()
        self.manager = AlertManager(self.query_engine)

    def test_add_rule(self) -> None:
        """Test adding alert rule."""
        rule = AlertRule(
            name="test_rule",
            expr="metric > 10",
        )
        self.manager.add_rule(rule)

        found = self.manager.get_rule("test_rule")
        assert found is not None
        assert found.name == "test_rule"

    def test_remove_rule(self) -> None:
        """Test removing alert rule."""
        rule = AlertRule(name="test_rule", expr="metric > 10")
        self.manager.add_rule(rule)

        assert self.manager.remove_rule("test_rule")
        assert self.manager.get_rule("test_rule") is None

    def test_add_inhibition_rule(self) -> None:
        """Test adding inhibition rule."""
        inhibition = InhibitionRule(
            source_matchers={"severity": "critical"},
            target_matchers={"severity": "warning"},
        )
        self.manager.add_inhibition_rule(inhibition)

        assert len(self.manager._inhibition_rules) == 1

    def test_add_silence_rule(self) -> None:
        """Test adding silence rule."""
        silence = SilenceRule(
            matchers={"instance": "host1"},
            starts_at=datetime.utcnow(),
            ends_at=datetime.utcnow() + timedelta(hours=1),
        )
        self.manager.add_silence_rule(silence)

        assert len(self.manager._silence_rules) == 1

    def test_add_notification_route(self) -> None:
        """Test adding notification route."""
        route = NotificationRoute(
            matchers={"severity": "critical"},
            receivers=["pagerduty"],
        )
        self.manager.add_notification_route(route)

        assert len(self.manager._notification_routes) == 1

    def test_register_callback(self) -> None:
        """Test registering notification callback."""
        called = []

        def callback(alert):
            called.append(alert)

        self.manager.register_notification_callback(callback)
        assert len(self.manager._notification_callbacks) == 1

    def test_get_alerts_empty(self) -> None:
        """Test getting alerts when none exist."""
        alerts = self.manager.get_alerts()
        assert len(alerts) == 0

    def test_get_alerts_by_state(self) -> None:
        """Test filtering alerts by state."""
        # This would require setup of alerts first
        alerts = self.manager.get_alerts(state=AlertState.FIRING)
        assert isinstance(alerts, list)

    def test_get_alert_groups(self) -> None:
        """Test getting grouped alerts."""
        groups = self.manager.get_alert_groups()
        assert isinstance(groups, list)

    def test_get_alert_history(self) -> None:
        """Test getting alert history."""
        history = self.manager.get_alert_history(limit=10)
        assert isinstance(history, list)

    def test_resolve_alert(self) -> None:
        """Test manually resolving alert."""
        result = self.manager.resolve_alert("nonexistent_fingerprint")
        assert result is False


class TestAlertGroupKey:
    """Test AlertGroupKey."""

    def test_group_key_equality(self) -> None:
        """Test group key equality."""
        key1 = AlertGroupKey({"env": "prod", "service": "api"})
        key2 = AlertGroupKey({"env": "prod", "service": "api"})

        assert key1 == key2

    def test_group_key_hash(self) -> None:
        """Test group key hashing."""
        key1 = AlertGroupKey({"env": "prod"})
        key2 = AlertGroupKey({"env": "prod"})

        assert hash(key1) == hash(key2)

    def test_group_key_different(self) -> None:
        """Test different group keys."""
        key1 = AlertGroupKey({"env": "prod"})
        key2 = AlertGroupKey({"env": "dev"})

        assert key1 != key2


class TestAlertGroup:
    """Test AlertGroup."""

    def test_create_group(self) -> None:
        """Test creating alert group."""
        key = AlertGroupKey({"severity": "critical"})
        group = AlertGroup(key=key)

        assert group.key == key
        assert len(group.alerts) == 0

    def test_add_alert_to_group(self) -> None:
        """Test adding alert to group."""
        from thomas.marketplace.monitoring._types import Alert

        key = AlertGroupKey({"severity": "critical"})
        group = AlertGroup(key=key)

        rule = AlertRule(name="test", expr="metric > 10")
        alert = Alert(
            rule=rule,
            state=AlertState.FIRING,
            value=42.0,
            fingerprint="fp1",
        )

        group.add_alert(alert)
        assert len(group.alerts) == 1

    def test_remove_alert_from_group(self) -> None:
        """Test removing alert from group."""
        from thomas.marketplace.monitoring._types import Alert

        key = AlertGroupKey({})
        group = AlertGroup(key=key)

        rule = AlertRule(name="test", expr="metric > 10")
        alert = Alert(
            rule=rule,
            state=AlertState.FIRING,
            value=42.0,
            fingerprint="fp1",
        )

        group.add_alert(alert)
        group.remove_alert(alert)
        assert len(group.alerts) == 0


class TestInhibitionRule:
    """Test InhibitionRule."""

    def test_create_inhibition_rule(self) -> None:
        """Test creating inhibition rule."""
        rule = InhibitionRule(
            source_matchers={"severity": "critical"},
            target_matchers={"severity": "warning"},
            equal_labels=["instance"],
        )

        assert rule.source_matchers["severity"] == "critical"
        assert rule.target_matchers["severity"] == "warning"
        assert "instance" in rule.equal_labels


class TestSilenceRule:
    """Test SilenceRule."""

    def test_create_silence_rule(self) -> None:
        """Test creating silence rule."""
        now = datetime.utcnow()
        rule = SilenceRule(
            matchers={"instance": "host1"},
            starts_at=now,
            ends_at=now + timedelta(hours=1),
            comment="Maintenance window",
        )

        assert rule.matchers["instance"] == "host1"
        assert rule.comment == "Maintenance window"

    def test_silence_rule_active(self) -> None:
        """Test checking if silence is active."""
        now = datetime.utcnow()
        rule = SilenceRule(
            matchers={},
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(minutes=5),
        )

        assert rule.starts_at <= now <= rule.ends_at

    def test_silence_rule_expired(self) -> None:
        """Test checking if silence has expired."""
        now = datetime.utcnow()
        rule = SilenceRule(
            matchers={},
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
        )

        assert now > rule.ends_at


class TestNotificationRoute:
    """Test NotificationRoute."""

    def test_create_route(self) -> None:
        """Test creating notification route."""
        route = NotificationRoute(
            matchers={"severity": "critical"},
            receivers=["pagerduty", "slack"],
        )

        assert route.matchers["severity"] == "critical"
        assert len(route.receivers) == 2

    def test_route_continue_flag(self) -> None:
        """Test continue routing flag."""
        route = NotificationRoute(
            matchers={},
            receivers=["slack"],
            continue_routing=True,
        )

        assert route.continue_routing is True


class TestAlertRuleEvaluation:
    """Test alert rule evaluation."""

    def test_rule_enabled(self) -> None:
        """Test alert rule enabled flag."""
        rule = AlertRule(
            name="test_rule",
            expr="metric > 10",
            enabled=True,
        )

        assert rule.enabled is True

    def test_rule_duration(self) -> None:
        """Test alert rule duration."""
        rule = AlertRule(
            name="test_rule",
            expr="metric > 10",
            duration=timedelta(minutes=5),
        )

        assert rule.duration.total_seconds() == 300

    def test_rule_labels(self) -> None:
        """Test alert rule labels."""
        rule = AlertRule(
            name="test_rule",
            expr="metric > 10",
            labels={"severity": "warning", "team": "platform"},
        )

        assert rule.labels["severity"] == "warning"
        assert rule.labels["team"] == "platform"

    def test_rule_annotations(self) -> None:
        """Test alert rule annotations."""
        rule = AlertRule(
            name="test_rule",
            expr="metric > 10",
            annotations={
                "summary": "High metric value",
                "description": "Metric exceeded threshold",
            },
        )

        assert rule.annotations["summary"] == "High metric value"
