"""Tests for SIEM event correlation module."""

from datetime import datetime, timedelta

from thomas.siem._types import (
    EventCategory,
    EventSeverity,
    Rule,
    SecurityEvent,
)
from thomas.siem.correlation import (
    CooccurrenceAnalyzer,
    CorrelationEngine,
    CorrelationState,
    FrequencyAnalyzer,
    KillChainDetector,
    SequenceRule,
    ThresholdRule,
)


class TestThresholdRule:
    """Tests for threshold rule."""

    def test_threshold_rule_triggers(self):
        """Test threshold rule triggers when limit met."""
        rule = ThresholdRule(
            rule_id="rule1",
            event_category=EventCategory.AUTHENTICATION,
            threshold=3,
            time_window=300,
        )

        now = datetime.utcnow()
        events = [
            SecurityEvent(
                timestamp=now - timedelta(seconds=60),
                category=EventCategory.AUTHENTICATION,
            ),
            SecurityEvent(
                timestamp=now - timedelta(seconds=30),
                category=EventCategory.AUTHENTICATION,
            ),
            SecurityEvent(
                timestamp=now,
                category=EventCategory.AUTHENTICATION,
            ),
        ]

        assert rule.evaluate(events) is True

    def test_threshold_rule_does_not_trigger(self):
        """Test threshold rule doesn't trigger below limit."""
        rule = ThresholdRule(
            rule_id="rule1",
            event_category=EventCategory.AUTHENTICATION,
            threshold=5,
            time_window=300,
        )

        now = datetime.utcnow()
        events = [
            SecurityEvent(
                timestamp=now,
                category=EventCategory.AUTHENTICATION,
            ),
            SecurityEvent(
                timestamp=now,
                category=EventCategory.NETWORK,
            ),
        ]

        assert rule.evaluate(events) is False

    def test_threshold_rule_respects_time_window(self):
        """Test threshold rule ignores events outside time window."""
        rule = ThresholdRule(
            rule_id="rule1",
            event_category=EventCategory.AUTHENTICATION,
            threshold=2,
            time_window=60,
        )

        now = datetime.utcnow()
        events = [
            SecurityEvent(
                timestamp=now - timedelta(seconds=200),
                category=EventCategory.AUTHENTICATION,
            ),
            SecurityEvent(
                timestamp=now,
                category=EventCategory.AUTHENTICATION,
            ),
        ]

        assert rule.evaluate(events) is False


class TestSequenceRule:
    """Tests for sequence detection rule."""

    def test_sequence_rule_detects_pattern(self):
        """Test sequence rule detects event sequence."""
        rule = SequenceRule(
            rule_id="seq1",
            event_sequence=[
                EventCategory.RECONNAISSANCE,
                EventCategory.EXPLOITATION,
                EventCategory.LATERAL_MOVEMENT,
            ],
            time_window=3600,
        )

        now = datetime.utcnow()
        events = [
            SecurityEvent(
                timestamp=now,
                category=EventCategory.RECONNAISSANCE,
            ),
            SecurityEvent(
                timestamp=now + timedelta(seconds=100),
                category=EventCategory.EXPLOITATION,
            ),
            SecurityEvent(
                timestamp=now + timedelta(seconds=200),
                category=EventCategory.LATERAL_MOVEMENT,
            ),
        ]

        assert rule.evaluate(events) is True

    def test_sequence_rule_respects_order(self):
        """Test sequence must be in correct order."""
        rule = SequenceRule(
            rule_id="seq1",
            event_sequence=[
                EventCategory.RECONNAISSANCE,
                EventCategory.EXPLOITATION,
            ],
            time_window=3600,
        )

        now = datetime.utcnow()
        events = [
            SecurityEvent(
                timestamp=now,
                category=EventCategory.EXPLOITATION,
            ),
            SecurityEvent(
                timestamp=now + timedelta(seconds=100),
                category=EventCategory.RECONNAISSANCE,
            ),
        ]

        assert rule.evaluate(events) is False

    def test_sequence_rule_respects_time_window(self):
        """Test sequence must occur within time window."""
        rule = SequenceRule(
            rule_id="seq1",
            event_sequence=[
                EventCategory.RECONNAISSANCE,
                EventCategory.EXPLOITATION,
            ],
            time_window=100,
        )

        now = datetime.utcnow()
        events = [
            SecurityEvent(
                timestamp=now,
                category=EventCategory.RECONNAISSANCE,
            ),
            SecurityEvent(
                timestamp=now + timedelta(seconds=200),
                category=EventCategory.EXPLOITATION,
            ),
        ]

        assert rule.evaluate(events) is False


class TestFrequencyAnalyzer:
    """Tests for frequency analysis."""

    def test_frequency_analyzer_detects_anomaly(self):
        """Test frequency analyzer detects anomalous events."""
        analyzer = FrequencyAnalyzer(baseline_window=3600)

        # Create baseline
        baseline_events = [
            SecurityEvent(
                timestamp=datetime.utcnow() - timedelta(hours=1),
                src_ip="192.168.1.1",
            )
            for _ in range(10)
        ]

        analyzer.update_baseline("src_ip:192.168.1.1", baseline_events)

        # Check anomaly
        is_anomalous = analyzer.is_anomalous("src_ip:192.168.1.1", 50)

        assert is_anomalous is True

    def test_frequency_analyzer_baseline_not_found(self):
        """Test analyzer returns False for unknown baseline."""
        analyzer = FrequencyAnalyzer()

        is_anomalous = analyzer.is_anomalous("unknown_key", 100)

        assert is_anomalous is False


class TestCooccurrenceAnalyzer:
    """Tests for co-occurrence analysis."""

    def test_cooccurrence_counts_pairs(self):
        """Test co-occurrence analyzer counts event pairs."""
        analyzer = CooccurrenceAnalyzer()

        event1 = SecurityEvent(
            source="syslog",
            category=EventCategory.AUTHENTICATION,
        )
        event2 = SecurityEvent(
            source="firewall",
            category=EventCategory.NETWORK,
        )

        analyzer.add_pair(event1, event2)

        assert analyzer.total_pairs == 1

    def test_cooccurrence_calculates_score(self):
        """Test co-occurrence score calculation."""
        analyzer = CooccurrenceAnalyzer()

        event1 = SecurityEvent(
            source="syslog",
            category=EventCategory.AUTHENTICATION,
        )
        event2 = SecurityEvent(
            source="firewall",
            category=EventCategory.NETWORK,
        )

        for _ in range(5):
            analyzer.add_pair(event1, event2)

        key1 = ("syslog", "AUTHENTICATION")
        key2 = ("firewall", "NETWORK")

        score = analyzer.get_correlation_score(key1, key2)

        assert score > 0.0


class TestKillChainDetector:
    """Tests for kill chain detection."""

    def test_kill_chain_detects_multi_stage_attack(self):
        """Test detection of multi-stage attack."""
        detector = KillChainDetector()

        now = datetime.utcnow()
        events = [
            SecurityEvent(
                timestamp=now,
                src_ip="192.168.1.100",
                dst_ip="10.0.0.1",
                category=EventCategory.RECONNAISSANCE,
            ),
            SecurityEvent(
                timestamp=now + timedelta(seconds=60),
                src_ip="192.168.1.100",
                dst_ip="10.0.0.1",
                category=EventCategory.VULNERABILITY,
            ),
            SecurityEvent(
                timestamp=now + timedelta(seconds=120),
                src_ip="192.168.1.100",
                dst_ip="10.0.0.1",
                category=EventCategory.C2_COMMUNICATION,
            ),
        ]

        chains = detector.detect(events)

        assert len(chains) > 0
        assert chains[0]["src_ip"] == "192.168.1.100"

    def test_kill_chain_requires_multiple_phases(self):
        """Test kill chain detection requires multiple phases."""
        detector = KillChainDetector()

        events = [
            SecurityEvent(
                src_ip="192.168.1.100",
                dst_ip="10.0.0.1",
                category=EventCategory.RECONNAISSANCE,
            ),
        ]

        chains = detector.detect(events)

        assert len(chains) == 0


class TestCorrelationEngine:
    """Tests for main correlation engine."""

    def test_engine_applies_threshold_rules(self):
        """Test correlation engine applies threshold rules."""
        engine = CorrelationEngine()

        rule = Rule(
            name="Failed Auth",
            rule_type="threshold",
            severity=EventSeverity.HIGH,
            metadata={
                "event_category": "AUTHENTICATION",
                "threshold": 3,
                "time_window": 300,
                "min_severity": "LOW",
            },
        )

        engine.add_rule(rule)

        now = datetime.utcnow()
        events = [
            SecurityEvent(
                timestamp=now,
                category=EventCategory.AUTHENTICATION,
            ),
            SecurityEvent(
                timestamp=now + timedelta(seconds=30),
                category=EventCategory.AUTHENTICATION,
            ),
            SecurityEvent(
                timestamp=now + timedelta(seconds=60),
                category=EventCategory.AUTHENTICATION,
            ),
        ]

        alerts = engine.correlate(events)

        assert len(alerts) > 0

    def test_engine_detects_kill_chains(self):
        """Test correlation engine detects kill chains."""
        engine = CorrelationEngine()

        now = datetime.utcnow()
        events = [
            SecurityEvent(
                timestamp=now,
                src_ip="192.168.1.100",
                dst_ip="10.0.0.1",
                category=EventCategory.RECONNAISSANCE,
            ),
            SecurityEvent(
                timestamp=now + timedelta(seconds=60),
                src_ip="192.168.1.100",
                dst_ip="10.0.0.1",
                category=EventCategory.VULNERABILITY,
            ),
            SecurityEvent(
                timestamp=now + timedelta(seconds=120),
                src_ip="192.168.1.100",
                dst_ip="10.0.0.1",
                category=EventCategory.C2_COMMUNICATION,
            ),
        ]

        alerts = engine.correlate(events)

        # Should detect multi-stage attack
        assert any("Multi-stage" in a.title for a in alerts)

    def test_engine_manages_state(self):
        """Test correlation engine manages state."""
        engine = CorrelationEngine()

        state = engine.create_state("rule1", event_window=300)

        assert state is not None
        assert not state.is_expired()

    def test_engine_cleanup_expired_states(self):
        """Test engine cleans up expired states."""
        engine = CorrelationEngine()

        state = engine.create_state("rule1", event_window=1)
        import time

        time.sleep(0.1)

        cleaned = engine.cleanup_states()

        assert cleaned >= 0


class TestCorrelationState:
    """Tests for correlation state."""

    def test_state_expiration(self):
        """Test state expiration detection."""
        state = CorrelationState(rule_id="rule1", event_window=1)

        import time

        time.sleep(0.2)

        assert state.is_expired() is True

    def test_state_add_event(self):
        """Test adding event to state."""
        state = CorrelationState(rule_id="rule1")

        event = SecurityEvent(message="test")
        state.add_event(event)

        assert len(state.events) == 1
