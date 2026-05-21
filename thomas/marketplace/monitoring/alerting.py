"""
Alerting engine for monitoring.

Alert rule evaluation with state management, grouping, inhibition,
silencing, and notification routing.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from thomas.marketplace.monitoring._types import Alert, AlertRule, AlertState

log = logging.getLogger(__name__)


@dataclass
class AlertGroupKey:
    """Key for grouping alerts."""

    labels: dict[str, str]

    def __hash__(self) -> int:
        items = tuple(sorted(self.labels.items()))
        return hash(items)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AlertGroupKey):
            return NotImplemented
        return self.labels == other.labels


@dataclass
class AlertGroup:
    """A group of alerts."""

    key: AlertGroupKey
    alerts: list[Alert] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_alert(self, alert: Alert) -> None:
        """Add an alert to the group."""
        self.alerts.append(alert)
        self.updated_at = datetime.utcnow()

    def remove_alert(self, alert: Alert) -> None:
        """Remove an alert from the group."""
        self.alerts = [a for a in self.alerts if a.fingerprint != alert.fingerprint]
        self.updated_at = datetime.utcnow()


@dataclass
class InhibitionRule:
    """A rule to inhibit alerts when other alerts fire."""

    source_matchers: dict[str, str]  # labels to match in source alert
    target_matchers: dict[str, str]  # labels to match in target alert
    equal_labels: list[str] = field(default_factory=list)


@dataclass
class SilenceRule:
    """A rule to silence alerts for a time period."""

    matchers: dict[str, str]
    starts_at: datetime = field(default_factory=datetime.utcnow)
    ends_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(hours=1))
    comment: str = ""
    created_by: str = ""


@dataclass
class NotificationRoute:
    """A route for notifications."""

    matchers: dict[str, str]
    receivers: list[str] = field(default_factory=list)
    continue_routing: bool = False


class AlertManager:
    """Manages alert evaluation and routing."""

    def __init__(self, query_engine: any) -> None:
        self.query_engine = query_engine
        self._lock = threading.Lock()
        self._rules: dict[str, AlertRule] = {}
        self._alerts: dict[str, Alert] = {}
        self._alert_groups: dict[AlertGroupKey, AlertGroup] = {}
        self._alert_history: list[tuple[Alert, datetime]] = []
        self._inhibition_rules: list[InhibitionRule] = []
        self._silence_rules: list[SilenceRule] = []
        self._notification_routes: list[NotificationRoute] = []
        self._notification_callbacks: list[Callable[[Alert], None]] = []
        self._eval_thread: threading.Thread | None = None
        self._running = False

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule."""
        with self._lock:
            self._rules[rule.name] = rule

    def remove_rule(self, rule_name: str) -> bool:
        """Remove an alert rule."""
        with self._lock:
            if rule_name in self._rules:
                del self._rules[rule_name]
                return True
            return False

    def get_rule(self, rule_name: str) -> AlertRule | None:
        """Get an alert rule."""
        with self._lock:
            return self._rules.get(rule_name)

    def add_inhibition_rule(self, rule: InhibitionRule) -> None:
        """Add an inhibition rule."""
        with self._lock:
            self._inhibition_rules.append(rule)

    def add_silence_rule(self, rule: SilenceRule) -> None:
        """Add a silence rule."""
        with self._lock:
            self._silence_rules.append(rule)

    def add_notification_route(self, route: NotificationRoute) -> None:
        """Add a notification route."""
        with self._lock:
            self._notification_routes.append(route)

    def register_notification_callback(self, callback: Callable[[Alert], None]) -> None:
        """Register a callback for alert notifications."""
        with self._lock:
            self._notification_callbacks.append(callback)

    def start(self) -> None:
        """Start alert evaluation loop."""
        with self._lock:
            if self._running:
                return
            self._running = True

        self._eval_thread = threading.Thread(target=self._evaluation_loop, daemon=True)
        self._eval_thread.start()

    def stop(self) -> None:
        """Stop alert evaluation."""
        with self._lock:
            self._running = False

        if self._eval_thread:
            self._eval_thread.join(timeout=5.0)

    def _evaluation_loop(self) -> None:
        """Main evaluation loop."""
        while True:
            with self._lock:
                if not self._running:
                    break

            try:
                self._evaluate_rules()
                self._update_alert_states()
            except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError) as e:
                log.warning("Alert evaluation failed: %s", e)

            time.sleep(15.0)

    def _evaluate_rules(self) -> None:
        """Evaluate all alert rules."""
        with self._lock:
            rules = list(self._rules.values())

        now = datetime.utcnow()

        for rule in rules:
            if not rule.enabled:
                continue

            try:
                # Query the metric
                result = self.query_engine.instant_query(rule.expr)

                # Create alerts for each series
                for series_key, value in result.series.items():
                    fingerprint = self._make_fingerprint(rule, series_key)

                    with self._lock:
                        if fingerprint in self._alerts:
                            alert = self._alerts[fingerprint]
                            alert.value = value
                        else:
                            alert = Alert(
                                rule=rule,
                                state=AlertState.PENDING,
                                value=value,
                                pending_since=now,
                                fingerprint=fingerprint,
                                labels=rule.labels.copy(),
                                annotations=rule.annotations.copy(),
                            )
                            self._alerts[fingerprint] = alert

                        # Check if should fire
                        if alert.state == AlertState.PENDING:
                            if alert.pending_since and (now - alert.pending_since) >= rule.duration:
                                alert.state = AlertState.FIRING
                                alert.firing_at = now

            except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError) as e:
                log.warning("Rule evaluation failed for rule %s: %s", rule.name, e)

    def _update_alert_states(self) -> None:
        """Update alert states based on inhibition and silencing."""
        with self._lock:
            alerts_to_remove = []

            for fingerprint, alert in self._alerts.items():
                if self._is_silenced(alert) or self._is_inhibited(alert):
                    alert.state = AlertState.INHIBITED
                elif alert.state == AlertState.FIRING and not any(
                    historical_alert.fingerprint == alert.fingerprint for historical_alert, _ in self._alert_history
                ):
                    # First time firing - call callbacks
                    callbacks = list(self._notification_callbacks)
                    for cb in callbacks:
                        try:
                            cb(alert)
                        except (ValueError, TypeError):
                            pass

                # Check if alert has resolved
                if alert.state == AlertState.FIRING:
                    # Check if metric still exists
                    try:
                        result = self.query_engine.instant_query(alert.rule.expr)
                        if not result.series:
                            alert.state = AlertState.RESOLVED
                            alert.resolved_at = datetime.utcnow()
                            alerts_to_remove.append(fingerprint)
                    except (ValueError, TypeError):
                        pass

            # Remove resolved alerts after keeping history
            for fingerprint in alerts_to_remove:
                if fingerprint in self._alerts:
                    alert = self._alerts[fingerprint]
                    self._alert_history.append((alert, datetime.utcnow()))
                    del self._alerts[fingerprint]

    def _is_silenced(self, alert: Alert) -> bool:
        """Check if alert is silenced."""
        with self._lock:
            now = datetime.utcnow()

            for rule in self._silence_rules:
                if rule.starts_at <= now <= rule.ends_at:
                    if self._matches_labels(alert.labels, rule.matchers):
                        return True

        return False

    def _is_inhibited(self, alert: Alert) -> bool:
        """Check if alert is inhibited by another firing alert."""
        with self._lock:
            for inhibition_rule in self._inhibition_rules:
                # Check if this alert matches target matchers
                if not self._matches_labels(alert.labels, inhibition_rule.target_matchers):
                    continue

                # Find source alerts
                for other in self._alerts.values():
                    if other.fingerprint == alert.fingerprint:
                        continue
                    if other.state != AlertState.FIRING:
                        continue

                    # Check if source matches
                    if not self._matches_labels(other.labels, inhibition_rule.source_matchers):
                        continue

                    # Check equal labels
                    equal = True
                    for label in inhibition_rule.equal_labels:
                        if alert.labels.get(label) != other.labels.get(label):
                            equal = False
                            break

                    if equal:
                        return True

        return False

    def _matches_labels(self, alert_labels: dict[str, str], matchers: dict[str, str]) -> bool:
        """Check if alert labels match matchers."""
        for key, value in matchers.items():
            if alert_labels.get(key) != value:
                return False
        return True

    def _make_fingerprint(self, rule: AlertRule, series_key: str) -> str:
        """Create fingerprint for alert."""
        content = f"{rule.name}_{series_key}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get_alerts(self, state: AlertState | None = None) -> list[Alert]:
        """Get alerts, optionally filtered by state."""
        with self._lock:
            alerts = list(self._alerts.values())
            if state:
                alerts = [a for a in alerts if a.state == state]
            return alerts

    def get_alert_groups(self) -> list[AlertGroup]:
        """Get grouped alerts."""
        with self._lock:
            # Group alerts by labels
            grouping: dict[AlertGroupKey, AlertGroup] = defaultdict(lambda: AlertGroup(key=AlertGroupKey({})))

            for alert in self._alerts.values():
                key = AlertGroupKey(alert.labels.copy())
                if key not in grouping:
                    grouping[key] = AlertGroup(key=key)
                grouping[key].add_alert(alert)

            return list(grouping.values())

    def get_alert_history(self, limit: int = 100) -> list[tuple[Alert, datetime]]:
        """Get alert history."""
        with self._lock:
            return self._alert_history[-limit:]

    def resolve_alert(self, fingerprint: str) -> bool:
        """Manually resolve an alert."""
        with self._lock:
            if fingerprint in self._alerts:
                alert = self._alerts[fingerprint]
                alert.state = AlertState.RESOLVED
                alert.resolved_at = datetime.utcnow()
                return True
            return False
