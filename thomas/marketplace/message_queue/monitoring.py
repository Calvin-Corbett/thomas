"""
Queue monitoring and health checks.

Monitors consumer lag, throughput, message age, topic size,
and provides health checks with configurable alert thresholds.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    is_healthy: bool
    checks: dict[str, bool] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AlertThreshold:
    """Configuration for an alert threshold."""

    name: str
    metric: str
    threshold: float
    comparison: str  # 'greater', 'less'
    enabled: bool = True


class QueueMonitor:
    """
    Monitors queue health and performance metrics.

    Tracks consumer lag, throughput, message age, and topic size,
    with configurable alert thresholds.
    """

    def __init__(self) -> None:
        """Initialize queue monitor."""
        self.broker: Any | None = None

        # Metrics tracking
        self.message_counts: dict[str, int] = {}
        self.consumer_lags: dict[str, int] = {}
        self.throughput_samples: dict[str, list[float]] = {}
        self.topic_sizes: dict[str, int] = {}

        # Alert thresholds
        self.thresholds: list[AlertThreshold] = [
            AlertThreshold(
                name="High Consumer Lag",
                metric="consumer_lag",
                threshold=10000,
                comparison="greater",
            ),
            AlertThreshold(
                name="Low Throughput",
                metric="throughput",
                threshold=100,
                comparison="less",
            ),
            AlertThreshold(
                name="Large Topic",
                metric="topic_size",
                threshold=1073741824,  # 1GB
                comparison="greater",
            ),
        ]

        # Tracking
        self.lock = asyncio.Lock()
        self._monitoring_task: asyncio.Task | None = None
        self._running = False

    async def start(self, broker: Any) -> None:
        """
        Start monitoring.

        Args:
            broker: Message broker to monitor
        """
        self.broker = broker
        self._running = True
        self._monitoring_task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._monitoring_task:
            try:
                self._monitoring_task.cancel()
                await asyncio.wait_for(self._monitoring_task, timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    async def _monitor_loop(self) -> None:
        """Periodically collect monitoring metrics."""
        while self._running:
            try:
                await asyncio.sleep(60)  # 1 minute

                if self._running and self.broker:
                    await self._collect_metrics()

            except asyncio.CancelledError:
                break
            except (ConnectionError, TimeoutError):
                pass

    async def _collect_metrics(self) -> None:
        """Collect current metrics."""
        if not self.broker:
            return

        try:
            # Get broker stats
            stats = await self.broker.get_broker_stats()

            async with self.lock:
                # Update message counts
                self.message_counts["total"] = stats.get("total_messages", 0)
                self.message_counts["total_bytes"] = stats.get("total_bytes", 0)

                # Collect topic sizes
                for topic in await self.broker.list_topics():
                    try:
                        topic_stats = await self.broker.get_topic_stats(topic)
                        self.topic_sizes[topic] = topic_stats.get("total_bytes", 0)
                    except Exception:  # REVIEWED: async context
                        pass

        except Exception:  # REVIEWED: async context
            pass

    async def record_consumer_lag(self, consumer_id: str, lag: int) -> None:
        """
        Record consumer lag metric.

        Args:
            consumer_id: Consumer identifier
            lag: Number of unprocessed messages
        """
        async with self.lock:
            self.consumer_lags[consumer_id] = lag

    async def record_throughput(self, consumer_id: str, msgs_per_sec: float) -> None:
        """
        Record throughput metric.

        Args:
            consumer_id: Consumer identifier
            msgs_per_sec: Messages per second
        """
        async with self.lock:
            if consumer_id not in self.throughput_samples:
                self.throughput_samples[consumer_id] = []

            samples = self.throughput_samples[consumer_id]
            samples.append(msgs_per_sec)

            # Keep last 10 samples
            if len(samples) > 10:
                samples.pop(0)

    async def get_consumer_lag(self, consumer_id: str) -> int:
        """
        Get consumer lag.

        Args:
            consumer_id: Consumer identifier

        Returns:
            Lag in number of messages
        """
        async with self.lock:
            return self.consumer_lags.get(consumer_id, 0)

    async def get_avg_consumer_lag(self) -> float:
        """
        Get average consumer lag across all consumers.

        Returns:
            Average lag
        """
        async with self.lock:
            if not self.consumer_lags:
                return 0.0
            return sum(self.consumer_lags.values()) / len(self.consumer_lags)

    async def get_avg_throughput(self, consumer_id: str) -> float:
        """
        Get average throughput for a consumer.

        Args:
            consumer_id: Consumer identifier

        Returns:
            Average messages per second
        """
        async with self.lock:
            samples = self.throughput_samples.get(consumer_id, [])
            if not samples:
                return 0.0
            return sum(samples) / len(samples)

    async def get_topic_size(self, topic: str) -> int:
        """
        Get topic size in bytes.

        Args:
            topic: Topic name

        Returns:
            Size in bytes
        """
        async with self.lock:
            return self.topic_sizes.get(topic, 0)

    async def perform_health_check(self) -> HealthCheckResult:
        """
        Perform a health check.

        Returns:
            Health check result with status and alerts
        """
        result = HealthCheckResult(is_healthy=True)

        if not self.broker:
            result.is_healthy = False
            result.alerts.append("Broker not configured")
            return result

        try:
            stats = await self.broker.get_broker_stats()

            # Check topic count
            if stats.get("topics", 0) > 0:
                result.checks["topics_available"] = True
            else:
                result.checks["topics_available"] = False

            # Check consumer groups
            if stats.get("consumer_groups", 0) > 0:
                result.checks["consumer_groups_available"] = True

            # Check message throughput
            avg_lag = await self.get_avg_consumer_lag()

            # Evaluate thresholds
            for threshold in self.thresholds:
                if not threshold.enabled:
                    continue

                triggered = False
                if threshold.metric == "consumer_lag":
                    if threshold.comparison == "greater":
                        triggered = avg_lag > threshold.threshold
                    else:
                        triggered = avg_lag < threshold.threshold

                if triggered:
                    result.is_healthy = False
                    result.alerts.append(
                        f"{threshold.name}: {avg_lag:.0f} "
                        f"{'>' if threshold.comparison == 'greater' else '<'} "
                        f"{threshold.threshold}"
                    )

        except Exception as e:
            result.is_healthy = False
            result.alerts.append(f"Health check error: {str(e)}")

        return result

    def add_threshold(self, threshold: AlertThreshold) -> None:
        """
        Add an alert threshold.

        Args:
            threshold: Threshold to add
        """
        self.thresholds.append(threshold)

    def remove_threshold(self, name: str) -> None:
        """
        Remove a threshold by name.

        Args:
            name: Threshold name
        """
        self.thresholds = [t for t in self.thresholds if t.name != name]

    async def get_metrics(self) -> dict[str, any]:
        """
        Get current metrics.

        Returns:
            Dictionary of all tracked metrics
        """
        if self.broker:
            await self._collect_metrics()

        async with self.lock:
            avg_lag = sum(self.consumer_lags.values()) / len(self.consumer_lags) if self.consumer_lags else 0.0

            throughputs = {
                consumer_id: (sum(samples) / len(samples) if samples else 0.0)
                for consumer_id, samples in self.throughput_samples.items()
            }

            return {
                "total_messages": self.message_counts.get("total", 0),
                "total_bytes": self.message_counts.get("total_bytes", 0),
                "consumer_count": len(self.consumer_lags),
                "average_consumer_lag": avg_lag,
                "max_consumer_lag": (max(self.consumer_lags.values()) if self.consumer_lags else 0),
                "average_throughput": (sum(throughputs.values()) / len(throughputs) if throughputs else 0),
                "topics": {topic: self.topic_sizes.get(topic, 0) for topic in self.topic_sizes},
            }

    async def get_alerts(self) -> list[str]:
        """
        Get current active alerts.

        Returns:
            List of alert messages
        """
        result = await self.perform_health_check()
        return result.alerts
