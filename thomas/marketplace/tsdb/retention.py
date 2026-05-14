"""Retention policy management for the Thomas TSDB.

Handles automatic cleanup and enforcement of data retention policies.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ._types import RetentionPolicy, TSDBConfig


@dataclass
class RetentionStats:
    """Statistics about retention cleanup."""

    chunks_deleted: int = 0
    points_deleted: int = 0
    bytes_freed: int = 0
    policies_enforced: int = 0


class RetentionManager:
    """Manages retention policies and automated cleanup."""

    def __init__(
        self,
        config: TSDBConfig,
        chunk_loader: Callable[[int], object] | None = None,
        chunk_deleter: Callable[[int], None] | None = None,
    ) -> None:
        """Initialize retention manager.

        Args:
            config: TSDB configuration
            chunk_loader: Optional callback to load chunk metadata
            chunk_deleter: Optional callback to delete a chunk
        """
        self.config = config
        self.chunk_loader = chunk_loader
        self.chunk_deleter = chunk_deleter

        self.policies: dict[str, RetentionPolicy] = {}
        if config.default_retention:
            self.policies["default"] = config.default_retention

        self.metric_policies: dict[str, RetentionPolicy] = {}
        self.cleanup_thread: threading.Thread | None = None
        self.cleanup_running = False
        self.stats = RetentionStats()

    def add_policy(self, policy: RetentionPolicy) -> None:
        """Add or update a retention policy.

        Args:
            policy: RetentionPolicy to add
        """
        self.policies[policy.name] = policy

    def get_policy_for_metric(self, metric_name: str) -> RetentionPolicy | None:
        """Get the applicable retention policy for a metric.

        Args:
            metric_name: Name of the metric

        Returns:
            Applicable RetentionPolicy or None
        """
        # Check metric-specific policy first
        if metric_name in self.metric_policies:
            return self.metric_policies[metric_name]

        # Check pattern-based policies
        for policy in self.policies.values():
            if policy.applies_to(metric_name):
                return policy

        # Fall back to default
        return self.policies.get("default")

    def set_metric_policy(self, metric_name: str, policy: RetentionPolicy) -> None:
        """Set a specific policy for a metric.

        Args:
            metric_name: Name of the metric
            policy: RetentionPolicy to apply
        """
        self.metric_policies[metric_name] = policy

    def should_delete_point(self, timestamp: int, metric_name: str) -> bool:
        """Check if a point is expired based on retention policy.

        Args:
            timestamp: Timestamp of the point in milliseconds
            metric_name: Name of the metric

        Returns:
            True if point is expired and should be deleted
        """
        policy = self.get_policy_for_metric(metric_name)
        if not policy:
            return False

        now = int(time.time() * 1000)
        return policy.is_expired(timestamp, now)

    def cleanup_expired_points(self, metric_name: str, chunks: list[dict], now_ms: int | None = None) -> RetentionStats:
        """Clean up expired points for a metric.

        Args:
            metric_name: Name of the metric
            chunks: List of chunk information dicts
            now_ms: Current time in milliseconds (for testing)

        Returns:
            RetentionStats about cleanup
        """
        stats = RetentionStats()
        policy = self.get_policy_for_metric(metric_name)

        if not policy:
            return stats

        if now_ms is None:
            now_ms = int(time.time() * 1000)

        for chunk_info in chunks:
            chunk_info.get("start_time", 0)
            chunk_end = chunk_info.get("end_time", now_ms)

            # Check if entire chunk is expired
            if policy.is_expired(chunk_end, now_ms):
                if self.chunk_deleter:
                    chunk_id = chunk_info.get("chunk_id")
                    self.chunk_deleter(chunk_id)
                    stats.chunks_deleted += 1
                    stats.points_deleted += chunk_info.get("point_count", 0)
                    stats.bytes_freed += chunk_info.get("size_bytes", 0)

        stats.policies_enforced += 1
        self.stats.chunks_deleted += stats.chunks_deleted
        self.stats.points_deleted += stats.points_deleted
        self.stats.bytes_freed += stats.bytes_freed
        self.stats.policies_enforced += 1

        return stats

    def enforce_size_limit(
        self,
        metric_name: str,
        current_size_bytes: int,
        chunks: list[dict],
    ) -> RetentionStats:
        """Enforce size-based retention limit.

        Deletes oldest chunks if size exceeds limit.

        Args:
            metric_name: Name of the metric
            current_size_bytes: Current total size in bytes
            chunks: List of chunk information dicts sorted by time

        Returns:
            RetentionStats about cleanup
        """
        stats = RetentionStats()
        policy = self.get_policy_for_metric(metric_name)

        if not policy or not policy.max_size_bytes:
            return stats

        # Delete oldest chunks until size is under limit
        remaining_size = current_size_bytes
        for chunk_info in chunks:
            if remaining_size <= policy.max_size_bytes:
                break

            if self.chunk_deleter:
                chunk_id = chunk_info.get("chunk_id")
                self.chunk_deleter(chunk_id)
                chunk_size = chunk_info.get("size_bytes", 0)
                remaining_size -= chunk_size
                stats.chunks_deleted += 1
                stats.points_deleted += chunk_info.get("point_count", 0)
                stats.bytes_freed += chunk_size

        self.stats.chunks_deleted += stats.chunks_deleted
        self.stats.points_deleted += stats.points_deleted
        self.stats.bytes_freed += stats.bytes_freed

        return stats

    def start_cleanup_scheduler(self, interval_seconds: int = 3600) -> None:
        """Start background cleanup scheduler.

        Args:
            interval_seconds: How often to run cleanup (default 1 hour)
        """
        if self.cleanup_running:
            return

        self.cleanup_running = True

        def cleanup_loop():
            while self.cleanup_running:
                time.sleep(interval_seconds)
                if self.cleanup_running:
                    # Cleanup would be called here with actual data
                    pass

        self.cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self.cleanup_thread.start()

    def stop_cleanup_scheduler(self) -> None:
        """Stop the background cleanup scheduler."""
        self.cleanup_running = False
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)

    def get_stats(self) -> dict:
        """Get retention statistics.

        Returns:
            Dictionary of statistics
        """
        return {
            "chunks_deleted": self.stats.chunks_deleted,
            "points_deleted": self.stats.points_deleted,
            "bytes_freed": self.stats.bytes_freed,
            "policies_enforced": self.stats.policies_enforced,
        }

    def list_policies(self) -> list[str]:
        """List all policy names.

        Returns:
            List of policy names
        """
        return list(self.policies.keys())

    def describe_policy(self, policy_name: str) -> dict | None:
        """Get description of a policy.

        Args:
            policy_name: Name of policy

        Returns:
            Dictionary with policy details or None
        """
        policy = self.policies.get(policy_name)
        if not policy:
            return None

        return {
            "name": policy.name,
            "duration_days": policy.duration_days,
            "max_size_bytes": policy.max_size_bytes,
            "metric_patterns": policy.metric_patterns,
        }
