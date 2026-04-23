"""Tests for retention policy management.

Tests policy enforcement, cleanup, and inheritance.
"""

import time

import pytest

from . import (
    RetentionManager,
    RetentionPolicy,
    TSDBConfig,
)


class TestRetentionPolicy:
    """Tests for retention policy creation and validation."""

    def test_create_basic_policy(self):
        """Test creating a basic retention policy."""
        policy = RetentionPolicy(
            name="30days",
            duration_days=30,
        )

        assert policy.name == "30days"
        assert policy.duration_days == 30

    def test_create_policy_with_size_limit(self):
        """Test creating policy with size limit."""
        policy = RetentionPolicy(
            name="limited",
            max_size_bytes=1024 * 1024 * 1024,  # 1GB
        )

        assert policy.max_size_bytes == 1024 * 1024 * 1024

    def test_create_policy_with_patterns(self):
        """Test creating policy with metric patterns."""
        policy = RetentionPolicy(
            name="logs",
            duration_days=7,
            metric_patterns=["logs.*", "errors.*"],
        )

        assert "logs.*" in policy.metric_patterns

    def test_policy_applies_to_metric(self):
        """Test checking if policy applies to metric."""
        policy = RetentionPolicy(
            name="logs",
            duration_days=7,
            metric_patterns=["logs.*", "errors.*"],
        )

        assert policy.applies_to("logs.app")
        assert policy.applies_to("errors.critical")
        assert not policy.applies_to("metrics.cpu")

    def test_policy_applies_to_all_if_no_patterns(self):
        """Test policy applies to all metrics if no patterns."""
        policy = RetentionPolicy(
            name="default",
            duration_days=30,
        )

        assert policy.applies_to("any.metric")
        assert policy.applies_to("logs.app")

    def test_is_expired(self):
        """Test checking if data is expired."""
        policy = RetentionPolicy(
            name="30days",
            duration_days=30,
        )

        now_ms = int(time.time() * 1000)
        old_timestamp = now_ms - (31 * 24 * 60 * 60 * 1000)  # 31 days ago

        assert policy.is_expired(old_timestamp, now_ms)

    def test_is_not_expired(self):
        """Test that recent data is not expired."""
        policy = RetentionPolicy(
            name="30days",
            duration_days=30,
        )

        now_ms = int(time.time() * 1000)
        recent_timestamp = now_ms - (15 * 24 * 60 * 60 * 1000)  # 15 days ago

        assert not policy.is_expired(recent_timestamp, now_ms)

    def test_infinite_retention(self):
        """Test policy with infinite retention."""
        policy = RetentionPolicy(
            name="infinite",
            duration_days=None,
        )

        now_ms = int(time.time() * 1000)
        very_old_timestamp = 1000  # Very old

        assert not policy.is_expired(very_old_timestamp, now_ms)

    def test_invalid_duration_raises_error(self):
        """Test that invalid duration raises error."""
        with pytest.raises(ValueError):
            RetentionPolicy(
                name="invalid",
                duration_days=0,
            )

        with pytest.raises(ValueError):
            RetentionPolicy(
                name="invalid",
                duration_days=-1,
            )

    def test_invalid_size_raises_error(self):
        """Test that invalid size raises error."""
        with pytest.raises(ValueError):
            RetentionPolicy(
                name="invalid",
                max_size_bytes=0,
            )


class TestRetentionManager:
    """Tests for retention manager."""

    @pytest.fixture
    def manager(self):
        """Provide retention manager."""
        config = TSDBConfig(storage_path="/tmp/tsdb")
        return RetentionManager(config)

    def test_add_policy(self, manager):
        """Test adding a retention policy."""
        policy = RetentionPolicy(
            name="30days",
            duration_days=30,
        )
        manager.add_policy(policy)

        assert manager.get_policy_for_metric("any.metric") == policy

    def test_get_policy_for_metric(self, manager):
        """Test retrieving policy for metric."""
        policy = RetentionPolicy(
            name="logs",
            duration_days=7,
            metric_patterns=["logs.*"],
        )
        manager.add_policy(policy)

        retrieved = manager.get_policy_for_metric("logs.app")
        assert retrieved == policy

    def test_metric_specific_policy_overrides(self, manager):
        """Test that metric-specific policy overrides default."""
        default_policy = RetentionPolicy(
            name="default",
            duration_days=30,
        )
        specific_policy = RetentionPolicy(
            name="specific",
            duration_days=7,
        )

        manager.add_policy(default_policy)
        manager.set_metric_policy("logs.app", specific_policy)

        retrieved = manager.get_policy_for_metric("logs.app")
        assert retrieved == specific_policy

    def test_set_metric_policy(self, manager):
        """Test setting policy for specific metric."""
        policy = RetentionPolicy(
            name="short",
            duration_days=3,
        )

        manager.set_metric_policy("important.metric", policy)
        retrieved = manager.get_policy_for_metric("important.metric")

        assert retrieved == policy

    def test_should_delete_point(self, manager):
        """Test checking if point should be deleted."""
        policy = RetentionPolicy(
            name="30days",
            duration_days=30,
        )
        manager.add_policy(policy)

        now_ms = int(time.time() * 1000)
        old_timestamp = now_ms - (31 * 24 * 60 * 60 * 1000)  # 31 days ago
        recent_timestamp = now_ms - (15 * 24 * 60 * 60 * 1000)  # 15 days ago

        assert manager.should_delete_point(old_timestamp, "any.metric")
        assert not manager.should_delete_point(recent_timestamp, "any.metric")

    def test_list_policies(self, manager):
        """Test listing all policies."""
        policy1 = RetentionPolicy(name="policy1", duration_days=30)
        policy2 = RetentionPolicy(name="policy2", duration_days=7)

        manager.add_policy(policy1)
        manager.add_policy(policy2)

        policies = manager.list_policies()
        assert "policy1" in policies
        assert "policy2" in policies

    def test_describe_policy(self, manager):
        """Test describing a policy."""
        policy = RetentionPolicy(
            name="test",
            duration_days=30,
            max_size_bytes=1024 * 1024,
            metric_patterns=["test.*"],
        )
        manager.add_policy(policy)

        description = manager.describe_policy("test")
        assert description is not None
        assert description["name"] == "test"
        assert description["duration_days"] == 30
        assert description["max_size_bytes"] == 1024 * 1024

    def test_describe_nonexistent_policy(self, manager):
        """Test describing non-existent policy returns None."""
        description = manager.describe_policy("nonexistent")
        assert description is None


class TestCleanupExpiredPoints:
    """Tests for expired point cleanup."""

    @pytest.fixture
    def manager(self):
        """Provide retention manager."""
        config = TSDBConfig(storage_path="/tmp/tsdb")
        return RetentionManager(config)

    def test_cleanup_expired_points(self, manager):
        """Test cleaning up expired points."""
        policy = RetentionPolicy(
            name="30days",
            duration_days=30,
        )
        manager.add_policy(policy)

        chunks = [
            {
                "chunk_id": 1,
                "start_time": int(time.time() * 1000) - (31 * 24 * 60 * 60 * 1000),
                "end_time": int(time.time() * 1000) - (30 * 24 * 60 * 60 * 1000),
                "point_count": 100,
                "size_bytes": 10000,
            }
        ]

        # Mock deleter to track deletions
        deleted_chunks = []

        def mock_deleter(chunk_id):
            deleted_chunks.append(chunk_id)

        manager.chunk_deleter = mock_deleter

        stats = manager.cleanup_expired_points("metric", chunks)

        assert stats.chunks_deleted > 0

    def test_cleanup_recent_points_not_deleted(self, manager):
        """Test that recent points are not deleted."""
        policy = RetentionPolicy(
            name="30days",
            duration_days=30,
        )
        manager.add_policy(policy)

        now_ms = int(time.time() * 1000)
        chunks = [
            {
                "chunk_id": 1,
                "start_time": now_ms - (15 * 24 * 60 * 60 * 1000),
                "end_time": now_ms,
                "point_count": 100,
                "size_bytes": 10000,
            }
        ]

        deleted_chunks = []

        def mock_deleter(chunk_id):
            deleted_chunks.append(chunk_id)

        manager.chunk_deleter = mock_deleter

        stats = manager.cleanup_expired_points("metric", chunks)

        assert stats.chunks_deleted == 0


class TestSizeLimitEnforcement:
    """Tests for size-based retention limits."""

    @pytest.fixture
    def manager(self):
        """Provide retention manager."""
        config = TSDBConfig(storage_path="/tmp/tsdb")
        return RetentionManager(config)

    def test_enforce_size_limit(self, manager):
        """Test enforcing size-based limits."""
        policy = RetentionPolicy(
            name="limited",
            max_size_bytes=5000,
        )
        manager.add_policy(policy)

        chunks = [
            {"chunk_id": 1, "size_bytes": 1000, "point_count": 100},
            {"chunk_id": 2, "size_bytes": 2000, "point_count": 200},
            {"chunk_id": 3, "size_bytes": 3000, "point_count": 300},
            {"chunk_id": 4, "size_bytes": 2000, "point_count": 200},
        ]

        deleted_chunks = []

        def mock_deleter(chunk_id):
            deleted_chunks.append(chunk_id)

        manager.chunk_deleter = mock_deleter

        manager.enforce_size_limit("metric", 8000, chunks)

        # Should delete oldest chunks until under limit
        assert len(deleted_chunks) > 0

    def test_no_size_limit(self, manager):
        """Test that unlimited size policy doesn't trigger deletion."""
        policy = RetentionPolicy(
            name="unlimited",
            max_size_bytes=None,
        )
        manager.add_policy(policy)

        chunks = [
            {"chunk_id": 1, "size_bytes": 1000000},
            {"chunk_id": 2, "size_bytes": 1000000},
        ]

        deleted_chunks = []

        def mock_deleter(chunk_id):
            deleted_chunks.append(chunk_id)

        manager.chunk_deleter = mock_deleter

        manager.enforce_size_limit("metric", 2000000, chunks)

        assert len(deleted_chunks) == 0


class TestRetentionStats:
    """Tests for retention statistics."""

    @pytest.fixture
    def manager(self):
        """Provide retention manager."""
        config = TSDBConfig(storage_path="/tmp/tsdb")
        return RetentionManager(config)

    def test_get_stats(self, manager):
        """Test getting retention statistics."""
        stats = manager.get_stats()

        assert "chunks_deleted" in stats
        assert "points_deleted" in stats
        assert "bytes_freed" in stats
        assert "policies_enforced" in stats
        assert stats["chunks_deleted"] == 0
