"""
Metric collection engine.

Handles both pull-based scraping and push-based ingestion of metrics,
with support for service discovery, relabeling rules, and target management.
"""

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from thomas.marketplace.monitoring._types import ScrapeTarget


@dataclass
class RelabelRule:
    """A relabeling rule for metrics during collection."""

    action: str  # keep, drop, replace, hashmod, labeldrop, labelkeep
    source_labels: list[str] = field(default_factory=list)
    target_label: str = ""
    regex: str = ".*"
    replacement: str = "$1"
    modulus: int = 0


@dataclass
class ScrapeJob:
    """A metric scraping job."""

    job_name: str
    targets: list[ScrapeTarget] = field(default_factory=list)
    scrape_interval: timedelta = field(default_factory=lambda: timedelta(seconds=15))
    scrape_timeout: timedelta = field(default_factory=lambda: timedelta(seconds=10))
    scheme: str = "http"
    relabel_rules: list[RelabelRule] = field(default_factory=list)
    metric_relabel_rules: list[RelabelRule] = field(default_factory=list)
    enabled: bool = True
    last_scrape: datetime | None = None
    last_error: str | None = None


@dataclass
class ScrapedMetric:
    """A metric scraped from a target."""

    name: str
    labels: dict[str, str]
    value: float
    timestamp: float
    target_labels: dict[str, str] = field(default_factory=dict)


@dataclass
class TargetStatus:
    """Status of a scrape target."""

    target: ScrapeTarget
    up: bool = True
    last_scrape_at: datetime | None = None
    last_error: str | None = None
    scrape_duration_ms: float = 0.0
    samples_scraped: int = 0
    consecutive_failures: int = 0


class MetricCollector:
    """Manages metric collection from targets."""

    def __init__(self, max_samples_per_scrape: int = 10000) -> None:
        self.max_samples_per_scrape = max_samples_per_scrape
        self._lock = threading.Lock()
        self._jobs: dict[str, ScrapeJob] = {}
        self._targets: dict[str, TargetStatus] = {}
        self._scraped_data: list[ScrapedMetric] = []
        self._scrape_callbacks: list[Callable[[list[ScrapedMetric]], None]] = []
        self._running = False
        self._scrape_thread: threading.Thread | None = None

    def add_job(self, job: ScrapeJob) -> None:
        """Add a scrape job."""
        with self._lock:
            self._jobs[job.job_name] = job
            for target in job.targets:
                target_key = f"{job.job_name}_{target.address}_{target.port}"
                self._targets[target_key] = TargetStatus(target=target)

    def remove_job(self, job_name: str) -> bool:
        """Remove a scrape job."""
        with self._lock:
            if job_name in self._jobs:
                del self._jobs[job_name]
                # Remove targets from this job
                keys_to_remove = [k for k in self._targets if k.startswith(f"{job_name}_")]
                for k in keys_to_remove:
                    del self._targets[k]
                return True
            return False

    def get_job(self, job_name: str) -> ScrapeJob | None:
        """Get a scrape job by name."""
        with self._lock:
            return self._jobs.get(job_name)

    def register_scrape_callback(self, callback: Callable[[list[ScrapedMetric]], None]) -> None:
        """Register a callback to be called with scraped metrics."""
        with self._lock:
            self._scrape_callbacks.append(callback)

    def start(self) -> None:
        """Start the metric collection process."""
        with self._lock:
            if self._running:
                return
            self._running = True

        self._scrape_thread = threading.Thread(target=self._scrape_loop, daemon=True)
        self._scrape_thread.start()

    def stop(self) -> None:
        """Stop the metric collection process."""
        with self._lock:
            self._running = False

        if self._scrape_thread:
            self._scrape_thread.join(timeout=5.0)

    def _scrape_loop(self) -> None:
        """Main scraping loop."""
        while True:
            with self._lock:
                if not self._running:
                    break

            try:
                self._run_scrapes()
            except Exception:
                pass

            time.sleep(1.0)

    def _run_scrapes(self) -> None:
        """Execute all due scrapes."""
        now = datetime.utcnow()

        with self._lock:
            jobs = list(self._jobs.values())

        for job in jobs:
            if not job.enabled:
                continue

            should_scrape = job.last_scrape is None or (now - job.last_scrape) >= job.scrape_interval

            if should_scrape:
                self._scrape_job(job, now)

    def _scrape_job(self, job: ScrapeJob, now: datetime) -> None:
        """Scrape a single job."""
        with self._lock:
            job.last_scrape = now

        for target in job.targets:
            if not target.enabled:
                continue

            target_key = f"{job.job_name}_{target.address}_{target.port}"
            metrics = self._scrape_target(job, target)

            with self._lock:
                if target_key in self._targets:
                    status = self._targets[target_key]
                    status.up = len(metrics) > 0
                    status.last_scrape_at = now
                    status.samples_scraped = len(metrics)
                    if len(metrics) > 0:
                        status.consecutive_failures = 0
                    else:
                        status.consecutive_failures += 1

            # Call registered callbacks
            if metrics:
                with self._lock:
                    callbacks = list(self._scrape_callbacks)

                for callback in callbacks:
                    try:
                        callback(metrics)
                    except (ValueError, TypeError):
                        pass

    def _scrape_target(self, job: ScrapeJob, target: ScrapeTarget) -> list[ScrapedMetric]:
        """Scrape a single target."""
        try:
            url = f"{target.scheme}://{target.address}:{target.port}{target.path}"
            metrics = self._fetch_metrics(url)
            return self._process_metrics(metrics, job, target)
        except (ValueError, TypeError):
            return []

    def _fetch_metrics(self, url: str) -> str:
        """Fetch metrics from a URL (simulation)."""
        # In real implementation, would use HTTP client
        return ""

    def _process_metrics(self, raw_metrics: str, job: ScrapeJob, target: ScrapeTarget) -> list[ScrapedMetric]:
        """Process raw metrics into structured format."""
        metrics = []
        timestamp = time.time()

        # Parse Prometheus text format
        for line in raw_metrics.split("\n"):
            if not line or line.startswith("#"):
                continue

            try:
                metric = self._parse_metric_line(line, timestamp, target)
                if metric:
                    metric = self._apply_relabel_rules(metric, job.metric_relabel_rules)
                    if metric:
                        metrics.append(metric)
            except Exception:  # REVIEWED: broad catch
                pass

            if len(metrics) >= self.max_samples_per_scrape:
                break

        return metrics

    def _parse_metric_line(self, line: str, timestamp: float, target: ScrapeTarget) -> ScrapedMetric | None:
        """Parse a single metric line from Prometheus text format."""
        # Simple parser for metric_name{labels} value timestamp
        parts = line.strip().split()
        if len(parts) < 2:
            return None

        metric_and_labels = parts[0]
        value = float(parts[1])

        # Parse metric name and labels
        if "{" in metric_and_labels:
            name_end = metric_and_labels.index("{")
            name = metric_and_labels[:name_end]
            labels_str = metric_and_labels[name_end + 1 : -1]
            labels = self._parse_labels(labels_str)
        else:
            name = metric_and_labels
            labels = {}

        return ScrapedMetric(
            name=name,
            labels=labels,
            value=value,
            timestamp=timestamp,
            target_labels=target.labels.copy(),
        )

    def _parse_labels(self, labels_str: str) -> dict[str, str]:
        """Parse label string."""
        labels = {}
        # Parse quoted label values
        pattern = r'(\w+)="([^"]*)"'
        for match in re.finditer(pattern, labels_str):
            labels[match.group(1)] = match.group(2)
        return labels

    def _apply_relabel_rules(self, metric: ScrapedMetric, rules: list[RelabelRule]) -> ScrapedMetric | None:
        """Apply relabeling rules to a metric."""
        for rule in rules:
            if rule.action == "keep":
                if not self._matches_regex(metric, rule):
                    return None

            elif rule.action == "drop":
                if self._matches_regex(metric, rule):
                    return None

            elif rule.action == "replace":
                metric = self._apply_replacement(metric, rule)

            elif rule.action == "labeldrop":
                pattern = re.compile(rule.regex)
                metric.labels = {k: v for k, v in metric.labels.items() if not pattern.match(k)}

            elif rule.action == "labelkeep":
                pattern = re.compile(rule.regex)
                metric.labels = {k: v for k, v in metric.labels.items() if pattern.match(k)}

        return metric

    def _matches_regex(self, metric: ScrapedMetric, rule: RelabelRule) -> bool:
        """Check if metric matches regex from rule."""
        values = []
        for label in rule.source_labels:
            if label == "__name__":
                values.append(metric.name)
            else:
                values.append(metric.labels.get(label, ""))

        combined = ";".join(values)
        pattern = re.compile(rule.regex)
        return bool(pattern.match(combined))

    def _apply_replacement(self, metric: ScrapedMetric, rule: RelabelRule) -> ScrapedMetric:
        """Apply replacement rule."""
        values = []
        for label in rule.source_labels:
            if label == "__name__":
                values.append(metric.name)
            else:
                values.append(metric.labels.get(label, ""))

        combined = ";".join(values)
        pattern = re.compile(rule.regex)
        match = pattern.match(combined)

        if match and rule.target_label:
            groups = match.groups()
            replacement = rule.replacement
            for i, group in enumerate(groups):
                replacement = replacement.replace(f"${i + 1}", group or "")
            metric.labels[rule.target_label] = replacement

        return metric

    def get_target_status(self, job_name: str | None = None) -> list[TargetStatus]:
        """Get status of scrape targets."""
        with self._lock:
            if job_name:
                return [status for key, status in self._targets.items() if key.startswith(f"{job_name}_")]
            return list(self._targets.values())

    def mark_down(self, target_key: str, error: str) -> None:
        """Mark a target as down."""
        with self._lock:
            if target_key in self._targets:
                self._targets[target_key].up = False
                self._targets[target_key].last_error = error
                self._targets[target_key].consecutive_failures += 1

    def mark_up(self, target_key: str) -> None:
        """Mark a target as up."""
        with self._lock:
            if target_key in self._targets:
                self._targets[target_key].up = True
                self._targets[target_key].consecutive_failures = 0
                self._targets[target_key].last_error = None
