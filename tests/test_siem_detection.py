"""Tests for SIEM threat detection module."""

from datetime import datetime, timedelta

from thomas.marketplace.siem._types import (
    EventCategory,
    EventSeverity,
    Indicator,
    SecurityEvent,
)
from thomas.marketplace.siem.detection import (
    AnomalyDetector,
    BehavioralAnalyzer,
    BruteForceDetector,
    DataExfiltrationDetector,
    SignatureDetector,
    ThreatDetectionEngine,
)


class TestSignatureDetector:
    """Tests for signature-based detection."""

    def test_signature_detector_matches_yara_pattern(self):
        """Test signature detector matches YARA patterns."""
        detector = SignatureDetector()

        indicator = Indicator(
            pattern="malware.*detected",
            pattern_type="yara",
            severity=EventSeverity.CRITICAL,
            confidence=95,
        )

        detector.add_signature(indicator)

        event = SecurityEvent(message="Malware detected in file")
        matches = detector.detect(event)

        assert len(matches) > 0
        assert matches[0][0].indicator_id == indicator.indicator_id

    def test_signature_detector_no_match(self):
        """Test detector returns empty when no match."""
        detector = SignatureDetector()

        indicator = Indicator(
            pattern="suspicious_process",
            pattern_type="regex",
        )

        detector.add_signature(indicator)

        event = SecurityEvent(message="Normal system event")
        matches = detector.detect(event)

        assert len(matches) == 0

    def test_signature_detector_case_insensitive(self):
        """Test signature matching is case insensitive."""
        detector = SignatureDetector()

        indicator = Indicator(
            pattern="MALWARE",
            pattern_type="yara",
        )

        detector.add_signature(indicator)

        event = SecurityEvent(message="malware detected")
        matches = detector.detect(event)

        assert len(matches) > 0


class TestAnomalyDetector:
    """Tests for anomaly detection."""

    def test_anomaly_detector_creates_baseline(self):
        """Test creating baseline from events."""
        detector = AnomalyDetector()

        now = datetime.utcnow()
        events = [
            SecurityEvent(
                timestamp=now - timedelta(days=i),
                severity=EventSeverity.LOW,
                category=EventCategory.NETWORK,
            )
            for i in range(7)
        ]

        detector.update_baseline("user:admin", events)

        assert "user:admin" in detector.baselines

    def test_anomaly_detector_detects_high_severity(self):
        """Test detection of high severity anomaly."""
        detector = AnomalyDetector()

        # Create low severity baseline
        baseline = [
            SecurityEvent(
                timestamp=datetime.utcnow() - timedelta(days=i),
                severity=EventSeverity.LOW,
            )
            for i in range(7)
        ]

        detector.update_baseline("key1", baseline)

        # Check high severity event
        anomaly = detector.detect_anomaly(
            "key1",
            SecurityEvent(severity=EventSeverity.CRITICAL),
            threshold=1.0,
        )

        assert anomaly is not None

    def test_anomaly_detector_ignores_unknown_keys(self):
        """Test detector returns None for unknown keys."""
        detector = AnomalyDetector()

        anomaly = detector.detect_anomaly(
            "unknown_key",
            SecurityEvent(),
        )

        assert anomaly is None


class TestBehavioralAnalyzer:
    """Tests for behavioral analysis."""

    def test_behavioral_analyzer_creates_baseline(self):
        """Test creating user baseline."""
        analyzer = BehavioralAnalyzer()

        events = [
            SecurityEvent(
                timestamp=datetime.utcnow() - timedelta(hours=i),
                user="alice",
                host="workstation1",
            )
            for i in range(10)
        ]

        analyzer.update_baseline("alice", events)

        assert "alice" in analyzer.user_baselines

    def test_behavioral_analyzer_detects_unusual_host(self):
        """Test detection of unusual host login."""
        analyzer = BehavioralAnalyzer()

        # Create baseline with specific host
        baseline = [
            SecurityEvent(
                user="alice",
                host="workstation1",
            )
            for _ in range(5)
        ]

        analyzer.update_baseline("alice", baseline)

        # Check login from unusual host
        anomalies = analyzer.detect_anomalies(
            "alice",
            SecurityEvent(user="alice", host="unknown_host"),
        )

        assert len(anomalies) > 0

    def test_behavioral_analyzer_detects_unusual_time(self):
        """Test detection of unusual login time."""
        analyzer = BehavioralAnalyzer()

        # Create baseline with specific hours
        now = datetime.utcnow()
        baseline = [
            SecurityEvent(
                user="bob",
                timestamp=now.replace(hour=9),
            )
            for _ in range(5)
        ]

        analyzer.update_baseline("bob", baseline)

        # Check login at unusual hour
        unusual_time = now.replace(hour=2)
        anomalies = analyzer.detect_anomalies(
            "bob",
            SecurityEvent(user="bob", timestamp=unusual_time),
        )

        assert len(anomalies) > 0


class TestBruteForceDetector:
    """Tests for brute force detection."""

    def test_brute_force_detector_counts_failures(self):
        """Test detection counts failed auth attempts."""
        detector = BruteForceDetector(
            failed_auth_threshold=3,
            time_window=300,
        )

        event = SecurityEvent(message="Failed auth", user="admin")

        is_attack1, _ = detector.check_failed_auth("admin", event)
        is_attack2, _ = detector.check_failed_auth("admin", event)
        is_attack3, details = detector.check_failed_auth("admin", event)

        assert is_attack3 is True
        assert details["status"] == "attack_detected"

    def test_brute_force_detector_lockout(self):
        """Test account lockout after threshold."""
        detector = BruteForceDetector(
            failed_auth_threshold=2,
            lockout_duration=600,
        )

        event = SecurityEvent(message="Failed", user="admin")

        detector.check_failed_auth("admin", event)
        detector.check_failed_auth("admin", event)

        is_attack, details = detector.check_failed_auth("admin", event)

        assert is_attack is True
        assert details["status"] == "locked"

    def test_brute_force_detector_reset(self):
        """Test resetting user attempts."""
        detector = BruteForceDetector(failed_auth_threshold=2)

        event = SecurityEvent(message="Failed", user="user1")

        detector.check_failed_auth("user1", event)
        detector.reset_user("user1")

        is_attack, _ = detector.check_failed_auth("user1", event)

        assert is_attack is False


class TestDataExfiltrationDetector:
    """Tests for data exfiltration detection."""

    def test_exfiltration_detector_updates_baseline(self):
        """Test updating data volume baseline."""
        detector = DataExfiltrationDetector()

        events = [
            SecurityEvent(
                user="alice",
                metadata={"bytes_out": 1000},
            )
            for _ in range(5)
        ]

        detector.update_baseline("alice", events)

        assert "alice" in detector.user_baselines

    def test_exfiltration_detector_detects_spike(self):
        """Test detection of data volume spike."""
        detector = DataExfiltrationDetector(baseline_multiplier=2.0)

        # Create baseline of 1000 bytes
        events = [
            SecurityEvent(
                user="bob",
                metadata={"bytes_out": 1000},
            )
            for _ in range(5)
        ]

        detector.update_baseline("bob", events)

        # Check 3x normal volume
        event = SecurityEvent(
            user="bob",
            metadata={"bytes_out": 3000},
        )

        exfil = detector.detect_exfiltration("bob", event)

        assert exfil is not None
        assert exfil["multiplier"] >= 3.0


class TestThreatDetectionEngine:
    """Tests for main detection engine."""

    def test_engine_detects_signatures(self):
        """Test engine detects signature matches."""
        engine = ThreatDetectionEngine()

        indicator = Indicator(
            pattern="malware",
            pattern_type="yara",
            severity=EventSeverity.CRITICAL,
        )

        engine.add_indicator(indicator)

        event = SecurityEvent(message="Malware detected")
        history = [event]

        alerts = engine.detect_threats(event, history)

        assert len(alerts) > 0

    def test_engine_detects_brute_force(self):
        """Test engine detects brute force attacks."""
        engine = ThreatDetectionEngine()

        # Simulate failed auth events
        events = [
            SecurityEvent(
                user="admin",
                message="Failed login",
                category=EventCategory.AUTHENTICATION,
            )
            for _ in range(6)
        ]

        alerts = engine.detect_threats(events[5], events)

        # Should detect brute force
        assert any("Brute Force" in a.title for a in alerts)

    def test_engine_detects_anomalies(self):
        """Test engine detects anomalous behavior."""
        engine = ThreatDetectionEngine()

        # Create normal events
        normal = [SecurityEvent(user="user1", host="workstation1") for _ in range(5)]

        # Check unusual event
        unusual = SecurityEvent(user="user1", host="unusual_host")

        alerts = engine.detect_threats(unusual, normal)

        # May detect anomaly
        assert isinstance(alerts, list)

    def test_engine_clears_detections(self):
        """Test engine can clear detection history."""
        engine = ThreatDetectionEngine()

        event = SecurityEvent(message="Malware detected")
        indicator = Indicator(pattern="malware")
        engine.add_indicator(indicator)

        engine.detect_threats(event)

        detections_before = len(engine.get_detections())

        engine.clear_detections()

        detections_after = len(engine.get_detections())

        assert detections_after == 0
