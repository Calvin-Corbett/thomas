"""Monitoring and metrics for webhook delivery."""

from collections import defaultdict
from datetime import datetime, timedelta

from thomas.marketplace.webhooks._types import Delivery, DeliveryAttempt, DeliveryStatus


class DeliveryMetrics:
    """Tracks delivery metrics for webhooks.

    Metrics include:
    - Success/failure rates
    - Latency percentiles (p50, p95, p99)
    - Error rates by endpoint
    - Volume tracking
    """

    def __init__(self, retention_seconds: int = 3600) -> None:
        """Initialize metrics tracker.

        Args:
            retention_seconds: How long to keep metric data.
        """
        self.retention_seconds = retention_seconds
        self._deliveries: list[tuple[datetime, Delivery, DeliveryAttempt]] = []
        self._endpoint_stats: dict[str, dict] = defaultdict(
            lambda: {
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "latencies": [],
            }
        )

    def record_delivery(
        self,
        delivery: Delivery,
        endpoint_id: str,
        attempt: DeliveryAttempt,
    ) -> None:
        """Record a delivery attempt.

        Args:
            delivery: The delivery record.
            endpoint_id: ID of the endpoint.
            attempt: The delivery attempt.
        """
        now = datetime.utcnow()
        self._deliveries.append((now, delivery, attempt))
        self._cleanup_old_data(now)

        stats = self._endpoint_stats[endpoint_id]
        stats["attempts"] += 1

        if attempt.status == DeliveryStatus.DELIVERED:
            stats["successes"] += 1
        else:
            stats["failures"] += 1

        if attempt.latency_ms is not None:
            stats["latencies"].append(attempt.latency_ms)

    def get_success_rate(self, endpoint_id: str | None = None) -> float:
        """Get success rate for endpoint or all endpoints.

        Args:
            endpoint_id: Optional endpoint ID to filter.

        Returns:
            Success rate as percentage (0-100).
        """
        if endpoint_id:
            stats = self._endpoint_stats.get(endpoint_id)
            if not stats or stats["attempts"] == 0:
                return 0.0
            return (stats["successes"] / stats["attempts"]) * 100

        total_attempts = sum(s["attempts"] for s in self._endpoint_stats.values())
        if total_attempts == 0:
            return 0.0

        total_successes = sum(s["successes"] for s in self._endpoint_stats.values())
        return (total_successes / total_attempts) * 100

    def get_failure_rate(self, endpoint_id: str | None = None) -> float:
        """Get failure rate for endpoint or all endpoints.

        Args:
            endpoint_id: Optional endpoint ID to filter.

        Returns:
            Failure rate as percentage (0-100).
        """
        return 100.0 - self.get_success_rate(endpoint_id)

    def get_latency_percentile(
        self,
        percentile: int,
        endpoint_id: str | None = None,
    ) -> float | None:
        """Get latency percentile.

        Args:
            percentile: Percentile (e.g., 95 for p95).
            endpoint_id: Optional endpoint ID to filter.

        Returns:
            Latency in milliseconds, or None if no data.
        """
        if endpoint_id:
            stats = self._endpoint_stats.get(endpoint_id)
            latencies = stats["latencies"] if stats else []
        else:
            latencies = []
            for stats in self._endpoint_stats.values():
                latencies.extend(stats["latencies"])

        if not latencies:
            return None

        sorted_latencies = sorted(latencies)
        index = int(len(sorted_latencies) * (percentile / 100.0))
        return float(sorted_latencies[min(index, len(sorted_latencies) - 1)])

    def get_endpoint_stats(self, endpoint_id: str) -> dict:
        """Get all stats for an endpoint.

        Args:
            endpoint_id: The endpoint ID.

        Returns:
            Dictionary of metrics.
        """
        stats = self._endpoint_stats.get(endpoint_id)
        if not stats:
            return {}

        latencies = stats["latencies"]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        return {
            "endpoint_id": endpoint_id,
            "total_attempts": stats["attempts"],
            "successes": stats["successes"],
            "failures": stats["failures"],
            "success_rate": ((stats["successes"] / stats["attempts"] * 100) if stats["attempts"] > 0 else 0),
            "avg_latency_ms": avg_latency,
            "p50_latency_ms": self.get_latency_percentile(50, endpoint_id),
            "p95_latency_ms": self.get_latency_percentile(95, endpoint_id),
            "p99_latency_ms": self.get_latency_percentile(99, endpoint_id),
        }

    def get_all_stats(self) -> list[dict]:
        """Get stats for all endpoints.

        Returns:
            List of endpoint stats dictionaries.
        """
        return [self.get_endpoint_stats(endpoint_id) for endpoint_id in self._endpoint_stats.keys()]

    def _cleanup_old_data(self, now: datetime) -> None:
        """Remove old metric data.

        Args:
            now: Current datetime.
        """
        cutoff = now - timedelta(seconds=self.retention_seconds)
        self._deliveries = [(dt, d, a) for dt, d, a in self._deliveries if dt > cutoff]


class HealthScore:
    """Calculates health score for endpoints.

    Weighted average of:
    - Recent success rate (60%)
    - Latency (30%)
    - Error trend (10%)
    """

    def __init__(self, lookback_minutes: int = 60) -> None:
        """Initialize health scorer.

        Args:
            lookback_minutes: Minutes of history to consider.
        """
        self.lookback_minutes = lookback_minutes
        self._metrics: dict[str, DeliveryMetrics] = {}

    def register_metrics(self, endpoint_id: str, metrics: DeliveryMetrics) -> None:
        """Register metrics source for an endpoint.

        Args:
            endpoint_id: The endpoint ID.
            metrics: The metrics tracker.
        """
        self._metrics[endpoint_id] = metrics

    def calculate_score(self, endpoint_id: str) -> float:
        """Calculate health score (0-100).

        Args:
            endpoint_id: The endpoint ID.

        Returns:
            Health score from 0 to 100.
        """
        metrics = self._metrics.get(endpoint_id)
        if not metrics:
            return 50.0

        success_rate = metrics.get_success_rate(endpoint_id)
        p95_latency = metrics.get_latency_percentile(95, endpoint_id) or 0
        max_acceptable_latency = 5000

        latency_score = max(0, 100 - (p95_latency / max_acceptable_latency * 100))

        health_score = success_rate * 0.6 + latency_score * 0.3 + 10

        return min(100.0, max(0.0, health_score))

    def get_health_status(self, endpoint_id: str) -> str:
        """Get health status description.

        Args:
            endpoint_id: The endpoint ID.

        Returns:
            Status string (healthy, degraded, critical).
        """
        score = self.calculate_score(endpoint_id)

        if score >= 85:
            return "healthy"
        elif score >= 70:
            return "degraded"
        else:
            return "critical"


class AlertingManager:
    """Manages alerts based on webhook metrics."""

    def __init__(self) -> None:
        """Initialize the alerting manager."""
        self._alerts: list[dict] = []
        self._alert_handlers: dict[str, callable] = {}

    def register_handler(self, alert_type: str, handler: callable) -> None:
        """Register a handler for an alert type.

        Args:
            alert_type: Type of alert (e.g., "endpoint_degradation").
            handler: Callable to handle the alert.
        """
        self._alert_handlers[alert_type] = handler

    def check_endpoint_degradation(
        self,
        endpoint_id: str,
        health_score: float,
        threshold: float = 70.0,
    ) -> bool:
        """Check if endpoint is degraded.

        Args:
            endpoint_id: The endpoint ID.
            health_score: Current health score.
            threshold: Degradation threshold.

        Returns:
            True if degraded, False otherwise.
        """
        if health_score < threshold:
            self._fire_alert(
                {
                    "type": "endpoint_degradation",
                    "endpoint_id": endpoint_id,
                    "health_score": health_score,
                    "threshold": threshold,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            return True

        return False

    def check_high_error_rate(
        self,
        endpoint_id: str,
        error_rate: float,
        threshold: float = 5.0,
    ) -> bool:
        """Check if error rate is high.

        Args:
            endpoint_id: The endpoint ID.
            error_rate: Current error rate (percentage).
            threshold: Error rate threshold.

        Returns:
            True if rate is high, False otherwise.
        """
        if error_rate > threshold:
            self._fire_alert(
                {
                    "type": "high_error_rate",
                    "endpoint_id": endpoint_id,
                    "error_rate": error_rate,
                    "threshold": threshold,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            return True

        return False

    def check_high_latency(
        self,
        endpoint_id: str,
        latency_ms: float,
        threshold_ms: float = 5000,
    ) -> bool:
        """Check if latency is high.

        Args:
            endpoint_id: The endpoint ID.
            latency_ms: Current latency in milliseconds.
            threshold_ms: Latency threshold.

        Returns:
            True if latency is high, False otherwise.
        """
        if latency_ms > threshold_ms:
            self._fire_alert(
                {
                    "type": "high_latency",
                    "endpoint_id": endpoint_id,
                    "latency_ms": latency_ms,
                    "threshold_ms": threshold_ms,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            return True

        return False

    def get_alerts(self, alert_type: str | None = None) -> list[dict]:
        """Get current alerts.

        Args:
            alert_type: Optional filter by alert type.

        Returns:
            List of alert dictionaries.
        """
        if alert_type:
            return [a for a in self._alerts if a["type"] == alert_type]

        return list(self._alerts)

    def clear_alerts(self, alert_type: str | None = None) -> None:
        """Clear alerts.

        Args:
            alert_type: Optional filter by alert type.
        """
        if alert_type:
            self._alerts = [a for a in self._alerts if a["type"] != alert_type]
        else:
            self._alerts.clear()

    def _fire_alert(self, alert: dict) -> None:
        """Fire an alert.

        Args:
            alert: The alert dictionary.
        """
        self._alerts.append(alert)

        handler = self._alert_handlers.get(alert["type"])
        if handler:
            handler(alert)


class EventVolumeMeter:
    """Tracks event volume over time."""

    def __init__(self, retention_minutes: int = 60) -> None:
        """Initialize volume meter.

        Args:
            retention_minutes: Minutes of history to keep.
        """
        self.retention_minutes = retention_minutes
        self._events: list[tuple[datetime, str]] = []

    def record_event(self, event_type: str) -> None:
        """Record an event.

        Args:
            event_type: Type of event.
        """
        self._events.append((datetime.utcnow(), event_type))
        self._cleanup_old_data()

    def get_volume(self, event_type: str | None = None) -> int:
        """Get event volume.

        Args:
            event_type: Optional filter by event type.

        Returns:
            Number of events.
        """
        if event_type:
            return sum(1 for _, et in self._events if et == event_type)

        return len(self._events)

    def get_volume_by_type(self) -> dict[str, int]:
        """Get volume grouped by event type.

        Returns:
            Dictionary of event_type -> count.
        """
        volumes = defaultdict(int)

        for _, event_type in self._events:
            volumes[event_type] += 1

        return dict(volumes)

    def _cleanup_old_data(self) -> None:
        """Remove old event data."""
        cutoff = datetime.utcnow() - timedelta(minutes=self.retention_minutes)
        self._events = [(dt, et) for dt, et in self._events if dt > cutoff]


class SLATracker:
    """Tracks SLA compliance for deliveries."""

    def __init__(self, sla_seconds: int = 60) -> None:
        """Initialize SLA tracker.

        Args:
            sla_seconds: SLA target in seconds.
        """
        self.sla_seconds = sla_seconds
        self._compliant: int = 0
        self._non_compliant: int = 0

    def record_delivery(self, delivery: Delivery) -> bool:
        """Record delivery and check SLA compliance.

        Args:
            delivery: The delivery record.

        Returns:
            True if delivery meets SLA, False otherwise.
        """
        if not delivery.attempts:
            return False

        first_attempt = delivery.attempts[0]
        delivery_time = first_attempt.timestamp - delivery.created_at
        delivery_seconds = delivery_time.total_seconds()

        compliant = delivery_seconds <= self.sla_seconds

        if compliant:
            self._compliant += 1
        else:
            self._non_compliant += 1

        return compliant

    def get_sla_compliance_rate(self) -> float:
        """Get SLA compliance rate.

        Returns:
            Compliance rate as percentage (0-100).
        """
        total = self._compliant + self._non_compliant
        if total == 0:
            return 100.0

        return (self._compliant / total) * 100

    def get_stats(self) -> dict:
        """Get SLA statistics.

        Returns:
            Dictionary with SLA stats.
        """
        total = self._compliant + self._non_compliant

        return {
            "sla_seconds": self.sla_seconds,
            "compliant": self._compliant,
            "non_compliant": self._non_compliant,
            "total": total,
            "compliance_rate": self.get_sla_compliance_rate(),
        }
