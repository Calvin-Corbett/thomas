"""Event correlation engine.

Correlates security events using rules, statistical analysis, sequence detection,
and multi-stage attack detection across the cyber kill chain.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from thomas.marketplace.siem._exceptions import (
    RuleEngineException,
)
from thomas.marketplace.siem._types import (
    Alert,
    EventCategory,
    EventSeverity,
    KillChainPhase,
    Rule,
    SecurityEvent,
)


@dataclass
class CorrelationState:
    """State for tracking correlation operations.

    Attributes:
        state_id: Unique identifier.
        rule_id: Associated rule identifier.
        event_window: Time window for correlation (seconds).
        events: Events matching this correlation.
        created_at: When state was created.
        last_updated: Last event addition time.
    """

    state_id: str = field(default_factory=lambda: str(uuid4()))
    rule_id: str = ""
    event_window: int = 300  # seconds
    events: deque = field(default_factory=lambda: deque(maxlen=1000))
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def is_expired(self) -> bool:
        """Check if state has expired based on time window."""
        age = datetime.utcnow() - self.last_updated
        return age > timedelta(seconds=self.event_window)

    def add_event(self, event: SecurityEvent) -> None:
        """Add event to state."""
        self.events.append(event)
        self.last_updated = datetime.utcnow()


class ThresholdRule:
    """Threshold-based correlation rule.

    Triggers when N events of a specific type occur within T seconds.
    """

    def __init__(
        self,
        rule_id: str,
        event_category: EventCategory,
        threshold: int,
        time_window: int,
        min_severity: EventSeverity = EventSeverity.LOW,
    ):
        """Initialize threshold rule.

        Args:
            rule_id: Unique rule identifier.
            event_category: Category of events to count.
            threshold: Number of events to trigger.
            time_window: Time window in seconds.
            min_severity: Minimum severity to count.
        """
        self.rule_id = rule_id
        self.event_category = event_category
        self.threshold = threshold
        self.time_window = time_window
        self.min_severity = min_severity

    def evaluate(self, events: list[SecurityEvent]) -> bool:
        """Evaluate if threshold is met.

        Args:
            events: Events to evaluate.

        Returns:
            True if threshold is exceeded.
        """
        if not events:
            return False

        now = datetime.utcnow()
        window_start = now - timedelta(seconds=self.time_window)

        matching = [
            e
            for e in events
            if e.category == self.event_category and e.severity >= self.min_severity and e.timestamp >= window_start
        ]

        return len(matching) >= self.threshold


class SequenceRule:
    """Sequence detection rule.

    Triggers when events occur in a specific order within a time window.
    """

    def __init__(
        self,
        rule_id: str,
        event_sequence: list[EventCategory],
        time_window: int,
    ):
        """Initialize sequence rule.

        Args:
            rule_id: Unique rule identifier.
            event_sequence: Ordered list of event categories.
            time_window: Time window for entire sequence (seconds).
        """
        self.rule_id = rule_id
        self.event_sequence = event_sequence
        self.time_window = time_window

    def evaluate(self, events: list[SecurityEvent]) -> bool:
        """Evaluate if sequence is found.

        Args:
            events: Events to evaluate.

        Returns:
            True if sequence detected.
        """
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        for i in range(len(sorted_events) - len(self.event_sequence) + 1):
            window_events = sorted_events[i : i + len(self.event_sequence)]

            # Check time window
            time_span = window_events[-1].timestamp - window_events[0].timestamp
            if time_span > timedelta(seconds=self.time_window):
                continue

            # Check sequence match
            if all(we.category == es for we, es in zip(window_events, self.event_sequence)):
                return True

        return False


class FrequencyAnalyzer:
    """Analyzes event frequency and deviations from baseline."""

    def __init__(self, baseline_window: int = 3600):
        """Initialize frequency analyzer.

        Args:
            baseline_window: Seconds to consider for baseline (default: 1 hour).
        """
        self.baseline_window = baseline_window
        self.baselines: dict[str, tuple[float, float]] = {}  # key -> (mean, stddev)
        self.history: dict[str, list[tuple[datetime, int]]] = defaultdict(list)

    def update_baseline(self, key: str, events: list[SecurityEvent]) -> None:
        """Update baseline statistics for a key.

        Args:
            key: Baseline key (e.g., 'src_ip:192.168.1.1').
            events: Events to calculate baseline from.
        """
        if not events:
            return

        now = datetime.utcnow()
        window_start = now - timedelta(seconds=self.baseline_window)

        relevant = [e for e in events if e.timestamp >= window_start]
        if not relevant:
            return

        # Calculate hourly frequency
        hour_counts = defaultdict(int)
        for event in relevant:
            hour_key = event.timestamp.replace(minute=0, second=0, microsecond=0)
            hour_counts[hour_key] += 1

        counts = list(hour_counts.values())
        if counts:
            mean = sum(counts) / len(counts)
            variance = sum((x - mean) ** 2 for x in counts) / len(counts)
            stddev = variance**0.5
            self.baselines[key] = (mean, stddev)

    def is_anomalous(self, key: str, current_count: int, stddev_threshold: float = 2.0) -> bool:
        """Check if current count is anomalous.

        Args:
            key: Baseline key.
            current_count: Current count to check.
            stddev_threshold: Number of standard deviations for anomaly.

        Returns:
            True if count is anomalous (beyond threshold).
        """
        if key not in self.baselines:
            return False

        mean, stddev = self.baselines[key]
        if stddev == 0:
            return current_count > mean

        z_score = abs((current_count - mean) / stddev)
        return z_score > stddev_threshold


class CooccurrenceAnalyzer:
    """Analyzes co-occurrence of events for statistical correlation."""

    def __init__(self):
        """Initialize co-occurrence analyzer."""
        self.event_pairs: dict[tuple[str, str], int] = defaultdict(int)
        self.total_pairs = 0

    def add_pair(self, event1: SecurityEvent, event2: SecurityEvent) -> None:
        """Record a pair of events.

        Args:
            event1: First event.
            event2: Second event.
        """
        key1 = (event1.source, event1.category.name)
        key2 = (event2.source, event2.category.name)

        if key1 <= key2:
            pair = (key1, key2)
        else:
            pair = (key2, key1)

        self.event_pairs[pair] += 1
        self.total_pairs += 1

    def get_correlation_score(self, event1_key: tuple[str, str], event2_key: tuple[str, str]) -> float:
        """Get correlation score between two event types.

        Args:
            event1_key: (source, category) tuple for first event type.
            event2_key: (source, category) tuple for second event type.

        Returns:
            Correlation score (0-1).
        """
        if self.total_pairs == 0:
            return 0.0

        if event1_key <= event2_key:
            pair = (event1_key, event2_key)
        else:
            pair = (event2_key, event1_key)

        count = self.event_pairs.get(pair, 0)
        return min(1.0, count / max(1, self.total_pairs / 10))


class KillChainDetector:
    """Detects multi-stage attacks across kill chain phases."""

    PHASE_CATEGORIES = {
        KillChainPhase.RECONNAISSANCE: [EventCategory.NETWORK],
        KillChainPhase.WEAPONIZATION: [EventCategory.MALWARE],
        KillChainPhase.DELIVERY: [EventCategory.MALWARE, EventCategory.INTRUSION],
        KillChainPhase.EXPLOITATION: [EventCategory.VULNERABILITY],
        KillChainPhase.INSTALLATION: [EventCategory.SUSPICIOUS_PROCESS],
        KillChainPhase.COMMAND_AND_CONTROL: [EventCategory.C2_COMMUNICATION],
        KillChainPhase.ACTIONS_ON_OBJECTIVES: [
            EventCategory.DATA_EXFILTRATION,
            EventCategory.LATERAL_MOVEMENT,
        ],
    }

    def __init__(self, time_window: int = 86400):
        """Initialize kill chain detector.

        Args:
            time_window: Seconds to track for attack chains (default: 24 hours).
        """
        self.time_window = time_window
        self.attack_chains: list[dict[str, Any]] = []

    def detect(self, events: list[SecurityEvent]) -> list[dict[str, Any]]:
        """Detect multi-stage attacks across kill chain.

        Args:
            events: Events to analyze.

        Returns:
            List of detected attack chains.
        """
        detected_chains = []

        # Group events by source/destination
        connection_groups = defaultdict(list)
        for event in events:
            key = (event.src_ip, event.dst_ip) if event.src_ip and event.dst_ip else None
            if key:
                connection_groups[key].append(event)

        # Check each group for kill chain progression
        for (src, dst), group_events in connection_groups.items():
            phases_detected = set()

            for event in sorted(group_events, key=lambda e: e.timestamp):
                for phase, categories in self.PHASE_CATEGORIES.items():
                    if event.category in categories:
                        phases_detected.add(phase)

            # If we see 3+ phases, it's likely an attack chain
            if len(phases_detected) >= 3:
                detected_chains.append(
                    {
                        "src_ip": src,
                        "dst_ip": dst,
                        "phases": sorted(phases_detected, key=lambda p: p.value),
                        "events": group_events,
                        "confidence": len(phases_detected) / len(self.PHASE_CATEGORIES),
                    }
                )

        return detected_chains


class CorrelationEngine:
    """Main event correlation engine.

    Implements rule-based, statistical, and sequence-based correlation
    for detecting complex security incidents.
    """

    def __init__(self):
        """Initialize correlation engine."""
        self.rules: dict[str, Rule] = {}
        self.states: dict[str, CorrelationState] = {}
        self.frequency_analyzer = FrequencyAnalyzer()
        self.cooccurrence = CooccurrenceAnalyzer()
        self.kill_chain_detector = KillChainDetector()
        self.alerts: list[Alert] = []

    def add_rule(self, rule: Rule) -> None:
        """Add correlation rule.

        Args:
            rule: Rule to add.
        """
        self.rules[str(rule.rule_id)] = rule

    def correlate(self, events: list[SecurityEvent]) -> list[Alert]:
        """Correlate events against all rules.

        Args:
            events: Events to correlate.

        Returns:
            List of generated alerts.

        Raises:
            CorrelationException: If correlation fails.
        """
        generated_alerts = []

        # Apply threshold rules
        for rule in self.rules.values():
            if not rule.enabled or rule.rule_type != "threshold":
                continue

            try:
                threshold_rule = self._parse_threshold_rule(rule)
                if threshold_rule.evaluate(events):
                    alert = self._create_alert(rule, events)
                    generated_alerts.append(alert)
                    self.alerts.append(alert)
            except Exception as e:
                raise RuleEngineException(f"Threshold rule error: {e}")

        # Apply sequence rules
        for rule in self.rules.values():
            if not rule.enabled or rule.rule_type != "sequence":
                continue

            try:
                sequence_rule = self._parse_sequence_rule(rule)
                if sequence_rule.evaluate(events):
                    alert = self._create_alert(rule, events)
                    generated_alerts.append(alert)
                    self.alerts.append(alert)
            except Exception as e:
                raise RuleEngineException(f"Sequence rule error: {e}")

        # Detect multi-stage attacks
        chains = self.kill_chain_detector.detect(events)
        for chain in chains:
            alert = Alert(
                rule_id=uuid4(),
                severity=EventSeverity.CRITICAL,
                title=f"Multi-stage Attack Detected: {chain['src_ip']} -> {chain['dst_ip']}",
                description=f"Kill chain phases: {[p.name for p in chain['phases']]}",
                events=chain["events"],
            )
            generated_alerts.append(alert)
            self.alerts.append(alert)

        return generated_alerts

    def _parse_threshold_rule(self, rule: Rule) -> ThresholdRule:
        """Parse threshold rule configuration.

        Args:
            rule: Rule to parse.

        Returns:
            ThresholdRule instance.

        Raises:
            RuleEngineException: If parsing fails.
        """
        meta = rule.metadata
        try:
            return ThresholdRule(
                rule_id=str(rule.rule_id),
                event_category=EventCategory[meta.get("event_category", "NETWORK")],
                threshold=int(meta.get("threshold", 5)),
                time_window=int(meta.get("time_window", 300)),
                min_severity=EventSeverity[meta.get("min_severity", "LOW")],
            )
        except (KeyError, ValueError) as e:
            raise RuleEngineException(f"Invalid threshold rule: {e}")

    def _parse_sequence_rule(self, rule: Rule) -> SequenceRule:
        """Parse sequence rule configuration.

        Args:
            rule: Rule to parse.

        Returns:
            SequenceRule instance.

        Raises:
            RuleEngineException: If parsing fails.
        """
        meta = rule.metadata
        try:
            sequence = [EventCategory[cat] for cat in meta.get("event_sequence", [])]
            return SequenceRule(
                rule_id=str(rule.rule_id),
                event_sequence=sequence,
                time_window=int(meta.get("time_window", 3600)),
            )
        except (KeyError, ValueError) as e:
            raise RuleEngineException(f"Invalid sequence rule: {e}")

    def _create_alert(self, rule: Rule, triggering_events: list[SecurityEvent]) -> Alert:
        """Create alert from rule trigger.

        Args:
            rule: Triggered rule.
            triggering_events: Events that triggered the rule.

        Returns:
            Generated Alert.
        """
        return Alert(
            rule_id=rule.rule_id,
            severity=rule.severity,
            title=f"Alert: {rule.name}",
            description=rule.description,
            events=triggering_events,
        )

    def get_state(self, rule_id: str) -> CorrelationState | None:
        """Get correlation state for a rule.

        Args:
            rule_id: Rule identifier.

        Returns:
            CorrelationState or None if not found.
        """
        return self.states.get(rule_id)

    def create_state(self, rule_id: str, event_window: int = 300) -> CorrelationState:
        """Create new correlation state.

        Args:
            rule_id: Rule identifier.
            event_window: Time window for state (seconds).

        Returns:
            New CorrelationState.

        Raises:
            StateManagementException: If state creation fails.
        """
        state = CorrelationState(rule_id=rule_id, event_window=event_window)
        self.states[state.state_id] = state
        return state

    def cleanup_states(self) -> int:
        """Remove expired correlation states.

        Returns:
            Number of states removed.
        """
        expired = [sid for sid, state in self.states.items() if state.is_expired()]
        for sid in expired:
            del self.states[sid]
        return len(expired)

    def get_alerts(
        self,
        severity: EventSeverity | None = None,
        status: str | None = None,
    ) -> list[Alert]:
        """Get correlation alerts.

        Args:
            severity: Filter by severity or higher.
            status: Filter by alert status.

        Returns:
            List of alerts.
        """
        alerts = self.alerts

        if severity:
            alerts = [a for a in alerts if a.severity >= severity]

        if status:
            alerts = [a for a in alerts if a.status == status]

        return alerts

    def clear_alerts(self) -> None:
        """Clear all alerts."""
        self.alerts.clear()
