"""
Pipeline monitoring and metrics framework.

Implements metrics collection, alerting, health checks, performance profiling,
SLA tracking, and dashboard data generation.
"""

import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class MetricPoint:
    """Single metric measurement."""

    timestamp: datetime
    value: float
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertRule:
    """Alert rule definition."""

    alert_id: str
    metric_name: str
    condition: str  # "gt", "lt", "gte", "lte", "eq", "ne"
    threshold: float
    duration: timedelta = field(default_factory=lambda: timedelta(minutes=5))
    severity: str = "warning"  # "info", "warning", "critical"
    description: str = ""
    enabled: bool = True


@dataclass
class HealthCheckResult:
    """Result of health check."""

    check_name: str
    status: str  # "healthy", "degraded", "unhealthy"
    message: str = ""
    last_checked: datetime = field(default_factory=datetime.utcnow)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceProfile:
    """Performance profile for a stage."""

    stage_name: str
    run_count: int = 0
    avg_duration: float = 0.0
    min_duration: float = 0.0
    max_duration: float = 0.0
    p95_duration: float = 0.0
    p99_duration: float = 0.0
    avg_records_per_sec: float = 0.0
    bottleneck_stage: str | None = None


class MetricsCollector:
    """
    Collects and stores pipeline metrics.

    Maintains time-series data for monitoring and analysis.
    """

    def __init__(self, retention_period: timedelta = None) -> None:
        """
        Initialize metrics collector.

        Args:
            retention_period: How long to keep metrics
        """
        self.retention_period = retention_period or timedelta(days=30)
        self._metrics: dict[str, list[MetricPoint]] = defaultdict(list)
        self._metric_metadata: dict[str, dict[str, Any]] = {}

    def record(
        self,
        metric_name: str,
        value: float,
        tags: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Record a metric value.

        Args:
            metric_name: Name of metric
            value: Metric value
            tags: Optional tags for filtering
            metadata: Optional additional metadata
        """
        point = MetricPoint(
            timestamp=datetime.utcnow(),
            value=value,
            tags=tags or {},
            metadata=metadata or {},
        )

        self._metrics[metric_name].append(point)
        self._cleanup_old_metrics()

    def get_metric(
        self,
        metric_name: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        tags_filter: dict[str, str] | None = None,
    ) -> list[MetricPoint]:
        """
        Get metric values.

        Args:
            metric_name: Name of metric
            start_time: Optional start time
            end_time: Optional end time
            tags_filter: Optional tag filter

        Returns:
            List of metric points
        """
        if metric_name not in self._metrics:
            return []

        points = self._metrics[metric_name]

        # Filter by time
        if start_time:
            points = [p for p in points if p.timestamp >= start_time]
        if end_time:
            points = [p for p in points if p.timestamp <= end_time]

        # Filter by tags
        if tags_filter:
            points = [p for p in points if all(p.tags.get(k) == v for k, v in tags_filter.items())]

        return points

    def aggregate(
        self,
        metric_name: str,
        aggregation: str = "avg",  # "avg", "sum", "min", "max", "count"
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> float | None:
        """
        Aggregate metric values.

        Args:
            metric_name: Name of metric
            aggregation: Aggregation function
            start_time: Optional start time
            end_time: Optional end time

        Returns:
            Aggregated value
        """
        points = self.get_metric(metric_name, start_time, end_time)
        if not points:
            return None

        values = [p.value for p in points]

        if aggregation == "avg":
            return statistics.mean(values)
        elif aggregation == "sum":
            return sum(values)
        elif aggregation == "min":
            return min(values)
        elif aggregation == "max":
            return max(values)
        elif aggregation == "count":
            return float(len(values))
        else:
            return statistics.mean(values)

    def _cleanup_old_metrics(self) -> None:
        """Remove expired metrics."""
        cutoff_time = datetime.utcnow() - self.retention_period

        for metric_name in self._metrics:
            self._metrics[metric_name] = [p for p in self._metrics[metric_name] if p.timestamp > cutoff_time]

    def get_all_metrics(self) -> dict[str, list[MetricPoint]]:
        """Get all collected metrics."""
        return dict(self._metrics)


class AlertingEngine:
    """
    Evaluates alert rules against metrics.

    Detects anomalies and triggers alerts.
    """

    def __init__(self, metrics_collector: MetricsCollector) -> None:
        """
        Initialize alerting engine.

        Args:
            metrics_collector: Metrics collector instance
        """
        self.metrics_collector = metrics_collector
        self._alert_rules: dict[str, AlertRule] = {}
        self._active_alerts: dict[str, datetime] = {}
        self._alert_history: list[tuple[AlertRule, bool, str]] = []

    def add_rule(self, rule: AlertRule) -> None:
        """Add alert rule."""
        self._alert_rules[rule.alert_id] = rule

    def evaluate_rules(self) -> list[tuple[AlertRule, bool, str]]:
        """
        Evaluate all alert rules.

        Returns:
            List of (rule, triggered, message) tuples
        """
        results = []

        for rule in self._alert_rules.values():
            if not rule.enabled:
                continue

            triggered, message = self._evaluate_rule(rule)
            results.append((rule, triggered, message))

            self._alert_history.append((rule, triggered, message))

        return results

    def _evaluate_rule(self, rule: AlertRule) -> tuple[bool, str]:
        """Evaluate single rule."""
        start_time = datetime.utcnow() - rule.duration
        points = self.metrics_collector.get_metric(rule.metric_name, start_time)

        if not points:
            return False, "No data"

        values = [p.value for p in points]
        latest_value = values[-1]

        triggered = False
        message = ""

        if rule.condition == "gt":
            triggered = latest_value > rule.threshold
            message = f"{rule.metric_name}={latest_value:.2f} > {rule.threshold}"
        elif rule.condition == "lt":
            triggered = latest_value < rule.threshold
            message = f"{rule.metric_name}={latest_value:.2f} < {rule.threshold}"
        elif rule.condition == "gte":
            triggered = latest_value >= rule.threshold
            message = f"{rule.metric_name}={latest_value:.2f} >= {rule.threshold}"
        elif rule.condition == "lte":
            triggered = latest_value <= rule.threshold
            message = f"{rule.metric_name}={latest_value:.2f} <= {rule.threshold}"

        return triggered, message

    def get_active_alerts(self) -> list[AlertRule]:
        """Get currently active alerts."""
        active = []
        for rule in self._alert_rules.values():
            triggered, _ = self._evaluate_rule(rule)
            if triggered:
                active.append(rule)
        return active


class HealthChecker:
    """
    Performs health checks on pipeline components.

    Monitors system health and reports degradation.
    """

    def __init__(self) -> None:
        """Initialize health checker."""
        self._health_checks: dict[str, Callable[[], HealthCheckResult]] = {}
        self._last_results: dict[str, HealthCheckResult] = {}

    def register_check(
        self,
        check_name: str,
        check_func: Callable[[], HealthCheckResult],
    ) -> None:
        """
        Register health check.

        Args:
            check_name: Name of check
            check_func: Function that performs check
        """
        self._health_checks[check_name] = check_func

    def run_checks(self) -> dict[str, HealthCheckResult]:
        """
        Run all health checks.

        Returns:
            Dictionary of check results
        """
        results = {}

        for check_name, check_func in self._health_checks.items():
            try:
                result = check_func()
                results[check_name] = result
                self._last_results[check_name] = result
            except Exception as e:
                results[check_name] = HealthCheckResult(
                    check_name=check_name,
                    status="unhealthy",
                    message=f"Check failed: {e}",
                )

        return results

    def get_overall_health(self) -> str:
        """Get overall health status."""
        if not self._last_results:
            return "unknown"

        statuses = [r.status for r in self._last_results.values()]

        if "unhealthy" in statuses:
            return "unhealthy"
        elif "degraded" in statuses:
            return "degraded"
        else:
            return "healthy"


class PerformanceProfiler:
    """
    Profiles performance of pipeline stages.

    Identifies bottlenecks and performance trends.
    """

    def __init__(self) -> None:
        """Initialize performance profiler."""
        self._stage_durations: dict[str, list[float]] = defaultdict(list)
        self._stage_record_counts: dict[str, list[int]] = defaultdict(list)
        self._profiles: dict[str, PerformanceProfile] = {}

    def record_stage_execution(
        self,
        stage_name: str,
        duration_seconds: float,
        record_count: int,
    ) -> None:
        """
        Record stage execution.

        Args:
            stage_name: Name of stage
            duration_seconds: Execution duration
            record_count: Records processed
        """
        self._stage_durations[stage_name].append(duration_seconds)
        self._stage_record_counts[stage_name].append(record_count)

    def generate_profiles(self) -> dict[str, PerformanceProfile]:
        """Generate performance profiles."""
        profiles = {}

        for stage_name, durations in self._stage_durations.items():
            if not durations:
                continue

            record_counts = self._stage_record_counts.get(stage_name, [record_count for record_count in [1]])

            # Calculate percentiles
            sorted_durations = sorted(durations)
            p95_idx = int(len(sorted_durations) * 0.95)
            p99_idx = int(len(sorted_durations) * 0.99)

            avg_records_per_sec = sum(record_counts) / sum(durations) if sum(durations) > 0 else 0

            profile = PerformanceProfile(
                stage_name=stage_name,
                run_count=len(durations),
                avg_duration=statistics.mean(durations),
                min_duration=min(durations),
                max_duration=max(durations),
                p95_duration=sorted_durations[p95_idx] if p95_idx < len(sorted_durations) else sorted_durations[-1],
                p99_duration=sorted_durations[p99_idx] if p99_idx < len(sorted_durations) else sorted_durations[-1],
                avg_records_per_sec=avg_records_per_sec,
            )

            profiles[stage_name] = profile

        return profiles

    def identify_bottleneck(self) -> str | None:
        """Identify bottleneck stage."""
        profiles = self.generate_profiles()

        if not profiles:
            return None

        return max(profiles.keys(), key=lambda s: profiles[s].avg_duration)


class DashboardGenerator:
    """
    Generates dashboard data for visualization.

    Provides aggregated metrics and statistics for monitoring.
    """

    def __init__(
        self,
        metrics_collector: MetricsCollector,
        alerting_engine: AlertingEngine,
        health_checker: HealthChecker,
        profiler: PerformanceProfiler,
    ) -> None:
        """
        Initialize dashboard generator.

        Args:
            metrics_collector: Metrics collector
            alerting_engine: Alerting engine
            health_checker: Health checker
            profiler: Performance profiler
        """
        self.metrics_collector = metrics_collector
        self.alerting_engine = alerting_engine
        self.health_checker = health_checker
        self.profiler = profiler

    def generate_dashboard(self) -> dict[str, Any]:
        """
        Generate complete dashboard data.

        Returns:
            Dashboard data structure
        """
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "health": {
                "overall": self.health_checker.get_overall_health(),
                "checks": [
                    {
                        "name": name,
                        "status": result.status,
                        "message": result.message,
                    }
                    for name, result in self.health_checker._last_results.items()
                ],
            },
            "alerts": {
                "active": len(self.alerting_engine.get_active_alerts()),
                "total_rules": len(self.alerting_engine._alert_rules),
                "rules": [
                    {
                        "id": rule.alert_id,
                        "metric": rule.metric_name,
                        "condition": rule.condition,
                        "threshold": rule.threshold,
                        "severity": rule.severity,
                    }
                    for rule in self.alerting_engine.get_active_alerts()
                ],
            },
            "performance": {
                "profiles": [
                    {
                        "stage": name,
                        "avg_duration": profile.avg_duration,
                        "records_per_sec": profile.avg_records_per_sec,
                    }
                    for name, profile in self.profiler.generate_profiles().items()
                ],
                "bottleneck": self.profiler.identify_bottleneck(),
            },
            "metrics": {
                "total_metrics": len(self.metrics_collector._metrics),
                "recent": self._get_recent_metrics(),
            },
        }

    def _get_recent_metrics(self, limit: int = 10) -> dict[str, float]:
        """Get recent metric values."""
        metrics = {}
        start_time = datetime.utcnow() - timedelta(minutes=5)

        for metric_name, points in self.metrics_collector._metrics.items():
            recent = [p for p in points if p.timestamp >= start_time]
            if recent:
                metrics[metric_name] = recent[-1].value

        return dict(list(metrics.items())[:limit])

    def generate_report(self, pipeline_name: str) -> dict[str, Any]:
        """
        Generate detailed report for pipeline.

        Args:
            pipeline_name: Pipeline name

        Returns:
            Report data
        """
        return {
            "pipeline": pipeline_name,
            "generated_at": datetime.utcnow().isoformat(),
            "dashboard": self.generate_dashboard(),
        }
