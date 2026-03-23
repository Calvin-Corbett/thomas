"""Threat detection engine.

Implements signature-based detection, anomaly detection, behavioral analysis,
brute force detection, and data exfiltration detection.
"""

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from thomas.marketplace.siem._exceptions import (
    AnomalyDetectionException,
    BruteForceDetectionException,
    SignatureMatchException,
)
from thomas.marketplace.siem._types import (
    Alert,
    EventCategory,
    EventSeverity,
    Indicator,
    SecurityEvent,
)


class SignatureDetector:
    """Signature-based detection engine.

    Matches events against patterns (YARA-like rules with string patterns
    and logical conditions).
    """

    def __init__(self):
        """Initialize signature detector."""
        self.signatures: dict[str, Indicator] = {}

    def add_signature(self, indicator: Indicator) -> None:
        """Add detection signature.

        Args:
            indicator: Indicator/signature to add.
        """
        self.signatures[str(indicator.indicator_id)] = indicator

    def detect(self, event: SecurityEvent) -> list[tuple[Indicator, float]]:
        """Detect if event matches any signatures.

        Args:
            event: Event to check.

        Returns:
            List of (Indicator, confidence) tuples for matches.

        Raises:
            SignatureMatchException: If detection fails.
        """
        matches = []

        try:
            for indicator in self.signatures.values():
                if self._match_signature(indicator, event):
                    matches.append((indicator, indicator.confidence / 100.0))
        except Exception as e:
            raise SignatureMatchException(f"Signature matching failed: {e}")

        return matches

    def _match_signature(self, indicator: Indicator, event: SecurityEvent) -> bool:
        """Check if event matches signature pattern.

        Args:
            indicator: Signature to match.
            event: Event to check.

        Returns:
            True if event matches.
        """
        pattern = indicator.pattern

        # Simple pattern matching
        if indicator.pattern_type == "yara":
            # Check message
            if re.search(pattern, event.message, re.IGNORECASE):
                return True
            if re.search(pattern, event.raw_data, re.IGNORECASE):
                return True

            # Check metadata values
            for value in event.metadata.values():
                if isinstance(value, str) and re.search(pattern, value, re.IGNORECASE):
                    return True

        elif indicator.pattern_type == "regex":
            if re.search(pattern, event.message):
                return True
            if re.search(pattern, event.raw_data):
                return True

        return False


class AnomalyDetector:
    """Anomaly detection using statistical baselines."""

    def __init__(self, baseline_days: int = 7):
        """Initialize anomaly detector.

        Args:
            baseline_days: Days of history to use for baseline.
        """
        self.baseline_days = baseline_days
        self.baselines: dict[str, dict[str, Any]] = {}
        self.event_history: dict[str, list[SecurityEvent]] = defaultdict(list)

    def update_baseline(self, key: str, events: list[SecurityEvent]) -> None:
        """Update baseline for a key from historical events.

        Args:
            key: Baseline key (e.g., 'user:admin').
            events: Historical events.
        """
        if not events:
            return

        cutoff = datetime.utcnow() - timedelta(days=self.baseline_days)
        relevant = [e for e in events if e.timestamp >= cutoff]

        if not relevant:
            return

        # Calculate baseline statistics
        baseline = {
            "event_count": len(relevant),
            "avg_severity": sum(e.severity.value for e in relevant) / len(relevant),
            "categories": list(set(e.category for e in relevant)),
            "hourly_distribution": self._calculate_hourly_dist(relevant),
        }

        self.baselines[key] = baseline
        self.event_history[key] = relevant

    def detect_anomaly(self, key: str, event: SecurityEvent, threshold: float = 2.0) -> dict[str, Any] | None:
        """Detect if event is anomalous for this key.

        Args:
            key: Baseline key.
            event: Event to check.
            threshold: Stddev threshold for anomaly.

        Returns:
            Anomaly details dict or None if normal.

        Raises:
            AnomalyDetectionException: If detection fails.
        """
        if key not in self.baselines:
            return None

        baseline = self.baselines[key]
        anomalies = []

        try:
            # Check severity
            severity_diff = abs(event.severity.value - baseline["avg_severity"])
            if severity_diff > threshold:
                anomalies.append({"type": "severity", "value": event.severity.name, "diff": severity_diff})

            # Check category
            if event.category not in baseline["categories"]:
                anomalies.append(
                    {
                        "type": "category",
                        "value": event.category.name,
                        "expected": [c.name for c in baseline["categories"]],
                    }
                )

            # Check time of day
            hour = event.timestamp.hour
            hourly_dist = baseline["hourly_distribution"]
            if hour in hourly_dist and hourly_dist[hour] == 0:
                anomalies.append({"type": "time_of_day", "hour": hour, "expected_hours": list(hourly_dist.keys())})

        except Exception as e:
            raise AnomalyDetectionException(f"Anomaly detection failed: {e}")

        return {"anomalies": anomalies, "severity": len(anomalies)} if anomalies else None

    def _calculate_hourly_dist(self, events: list[SecurityEvent]) -> dict[int, int]:
        """Calculate hourly distribution of events.

        Args:
            events: Events to analyze.

        Returns:
            Dictionary of hour -> count.
        """
        hourly = defaultdict(int)
        for event in events:
            hour = event.timestamp.hour
            hourly[hour] += 1
        return dict(hourly)


class BehavioralAnalyzer:
    """User entity behavior analytics (UEBA).

    Analyzes user login patterns, access patterns, and data access volumes.
    """

    def __init__(self):
        """Initialize behavioral analyzer."""
        self.user_baselines: dict[str, dict[str, Any]] = {}
        self.user_sessions: dict[str, list[SecurityEvent]] = defaultdict(list)

    def update_baseline(self, user: str, events: list[SecurityEvent]) -> None:
        """Update baseline for a user.

        Args:
            user: Username.
            events: Historical events for this user.
        """
        if not events:
            return

        baseline = {
            "login_count": len([e for e in events if "login" in e.message.lower()]),
            "typical_hosts": list(set(e.host for e in events if e.host)),
            "typical_hours": set(e.timestamp.hour for e in events),
            "data_volume_bytes": sum(e.metadata.get("bytes_transferred", 0) for e in events),
            "access_patterns": self._extract_access_patterns(events),
        }

        self.user_baselines[user] = baseline

    def detect_anomalies(self, user: str, event: SecurityEvent) -> list[str]:
        """Detect behavioral anomalies for user.

        Args:
            user: Username.
            event: Event to check.

        Returns:
            List of anomaly descriptions.
        """
        if user not in self.user_baselines:
            return []

        baseline = self.user_baselines[user]
        anomalies = []

        # Check host
        if event.host and event.host not in baseline["typical_hosts"]:
            anomalies.append(f"Unusual host: {event.host}")

        # Check time
        if event.timestamp.hour not in baseline["typical_hours"]:
            anomalies.append(f"Unusual login hour: {event.timestamp.hour}")

        # Check volume
        volume = event.metadata.get("bytes_transferred", 0)
        if volume > baseline["data_volume_bytes"] * 2:
            anomalies.append(f"High data volume: {volume} bytes")

        return anomalies

    def _extract_access_patterns(self, events: list[SecurityEvent]) -> dict[str, int]:
        """Extract access patterns from events.

        Args:
            events: Events to analyze.

        Returns:
            Dictionary of resource -> access count.
        """
        patterns = defaultdict(int)
        for event in events:
            resource = event.metadata.get("resource", "unknown")
            patterns[resource] += 1
        return dict(patterns)


class BruteForceDetector:
    """Detects brute force attacks on authentication systems."""

    def __init__(
        self,
        failed_auth_threshold: int = 5,
        time_window: int = 300,
        lockout_duration: int = 900,
    ):
        """Initialize brute force detector.

        Args:
            failed_auth_threshold: Failed attempts before lockout.
            time_window: Time window for counting attempts (seconds).
            lockout_duration: How long to lock account (seconds).
        """
        self.failed_auth_threshold = failed_auth_threshold
        self.time_window = time_window
        self.lockout_duration = lockout_duration
        self.failed_attempts: dict[str, list[datetime]] = defaultdict(list)
        self.locked_accounts: dict[str, datetime] = {}

    def check_failed_auth(self, user: str, event: SecurityEvent) -> tuple[bool, dict[str, Any] | None]:
        """Check for brute force on failed authentication.

        Args:
            user: Username with failed auth.
            event: Authentication failure event.

        Returns:
            (is_attack, details) tuple.

        Raises:
            BruteForceDetectionException: If check fails.
        """
        try:
            now = datetime.utcnow()

            # Check if account is locked
            if user in self.locked_accounts:
                if now < self.locked_accounts[user]:
                    return (True, {"status": "locked", "user": user})
                else:
                    del self.locked_accounts[user]

            # Add failure and clean old ones
            self.failed_attempts[user].append(now)
            cutoff = now - timedelta(seconds=self.time_window)
            self.failed_attempts[user] = [t for t in self.failed_attempts[user] if t >= cutoff]

            # Check threshold
            if len(self.failed_attempts[user]) >= self.failed_auth_threshold:
                self.locked_accounts[user] = now + timedelta(seconds=self.lockout_duration)
                return (
                    True,
                    {
                        "status": "attack_detected",
                        "user": user,
                        "attempts": len(self.failed_attempts[user]),
                        "locked_until": self.locked_accounts[user],
                    },
                )

            return (False, None)

        except Exception as e:
            raise BruteForceDetectionException(f"Brute force check failed: {e}")

    def reset_user(self, user: str) -> None:
        """Reset failed attempt counter for user.

        Args:
            user: Username to reset.
        """
        if user in self.failed_attempts:
            del self.failed_attempts[user]
        if user in self.locked_accounts:
            del self.locked_accounts[user]


class DataExfiltrationDetector:
    """Detects data exfiltration based on volume anomalies."""

    def __init__(self, baseline_multiplier: float = 2.5):
        """Initialize exfiltration detector.

        Args:
            baseline_multiplier: Multiplier above baseline to trigger alert.
        """
        self.baseline_multiplier = baseline_multiplier
        self.user_baselines: dict[str, int] = {}

    def update_baseline(self, user: str, events: list[SecurityEvent]) -> None:
        """Update data volume baseline for user.

        Args:
            user: Username.
            events: Historical events.
        """
        total_bytes = sum(e.metadata.get("bytes_out", 0) for e in events)
        avg_bytes = total_bytes / max(1, len(events))
        self.user_baselines[user] = int(avg_bytes)

    def detect_exfiltration(self, user: str, event: SecurityEvent) -> dict[str, Any] | None:
        """Check if event indicates data exfiltration.

        Args:
            user: Username.
            event: Event to check.

        Returns:
            Exfiltration details or None.
        """
        if user not in self.user_baselines:
            return None

        baseline = self.user_baselines[user]
        bytes_out = event.metadata.get("bytes_out", 0)

        if bytes_out > baseline * self.baseline_multiplier:
            return {
                "user": user,
                "baseline": baseline,
                "current": bytes_out,
                "multiplier": bytes_out / max(1, baseline),
            }

        return None


class ThreatDetectionEngine:
    """Main threat detection engine.

    Coordinates signature detection, anomaly detection, behavioral analysis,
    and specialized detectors.
    """

    def __init__(self):
        """Initialize detection engine."""
        self.signature_detector = SignatureDetector()
        self.anomaly_detector = AnomalyDetector()
        self.behavioral_analyzer = BehavioralAnalyzer()
        self.brute_force_detector = BruteForceDetector()
        self.exfiltration_detector = DataExfiltrationDetector()
        self.detections: list[dict[str, Any]] = []

    def detect_threats(self, event: SecurityEvent, event_history: list[SecurityEvent] | None = None) -> list[Alert]:
        """Detect threats in an event.

        Args:
            event: Event to analyze.
            event_history: Optional historical events for context.

        Returns:
            List of generated alerts.
        """
        alerts = []

        # Signature detection
        matches = self.signature_detector.detect(event)
        for indicator, confidence in matches:
            alert = Alert(
                rule_id=indicator.indicator_id,
                severity=indicator.severity,
                title=f"Signature Match: {indicator.pattern_type}",
                description=f"Pattern matched with {confidence:.1%} confidence",
                events=[event],
            )
            alerts.append(alert)
            self.detections.append({"type": "signature", "indicator": str(indicator.indicator_id)})

        # Anomaly detection
        if event_history:
            for key_type in ["user", "host", "src_ip"]:
                key_value = getattr(event, key_type, None)
                if key_value:
                    key = f"{key_type}:{key_value}"
                    self.anomaly_detector.update_baseline(key, event_history)
                    anomaly = self.anomaly_detector.detect_anomaly(key, event)
                    if anomaly:
                        alert = Alert(
                            rule_id=uuid4(),
                            severity=EventSeverity.MEDIUM,
                            title=f"Anomaly Detected: {key_type}",
                            description=f"Anomalies: {anomaly['anomalies']}",
                            events=[event],
                        )
                        alerts.append(alert)

        # Behavioral analysis
        if event.user and event_history:
            self.behavioral_analyzer.update_baseline(event.user, event_history)
            anomalies = self.behavioral_analyzer.detect_anomalies(event.user, event)
            if anomalies:
                alert = Alert(
                    rule_id=uuid4(),
                    severity=EventSeverity.HIGH,
                    title="Behavioral Anomaly Detected",
                    description=f"User {event.user}: {'; '.join(anomalies)}",
                    events=[event],
                )
                alerts.append(alert)

        # Brute force detection
        if event.category == EventCategory.AUTHENTICATION and "fail" in event.message.lower():
            if event.user:
                is_attack, details = self.brute_force_detector.check_failed_auth(event.user, event)
                if is_attack and details:
                    alert = Alert(
                        rule_id=uuid4(),
                        severity=EventSeverity.HIGH,
                        title="Brute Force Attack Detected",
                        description=f"Account {event.user}: {details}",
                        events=[event],
                    )
                    alerts.append(alert)

        # Data exfiltration detection
        if event.user:
            exfil = self.exfiltration_detector.detect_exfiltration(event.user, event)
            if exfil:
                alert = Alert(
                    rule_id=uuid4(),
                    severity=EventSeverity.CRITICAL,
                    title="Data Exfiltration Suspected",
                    description=f"Abnormal data transfer: {exfil['current']} bytes (baseline: {exfil['baseline']})",
                    events=[event],
                )
                alerts.append(alert)

        return alerts

    def add_indicator(self, indicator: Indicator) -> None:
        """Add detection indicator.

        Args:
            indicator: Indicator to add.
        """
        self.signature_detector.add_signature(indicator)

    def get_detections(self) -> list[dict[str, Any]]:
        """Get all detections.

        Returns:
            List of detection records.
        """
        return self.detections.copy()

    def clear_detections(self) -> None:
        """Clear detection history."""
        self.detections.clear()
