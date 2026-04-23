"""
Tests for distributed scheduling, leader election, and job locking.
"""

import tempfile
from datetime import datetime, timedelta, timezone

from thomas.marketplace.scheduler_deep.distributed import DistributedScheduler, JobLock, NodeInfo


class TestNodeInfo:
    """Test node information and heartbeat."""

    def test_node_creation(self) -> None:
        """Test creating node info."""
        now = datetime.now(timezone.utc)
        node = NodeInfo(
            node_id="node1",
            hostname="localhost",
            last_heartbeat=now,
        )
        assert node.node_id == "node1"
        assert node.hostname == "localhost"

    def test_node_alive_recent_heartbeat(self) -> None:
        """Test node is alive with recent heartbeat."""
        now = datetime.now(timezone.utc)
        node = NodeInfo(
            node_id="node1",
            hostname="localhost",
            last_heartbeat=now,
        )
        assert node.is_alive(timeout_seconds=30) is True

    def test_node_dead_old_heartbeat(self) -> None:
        """Test node is dead with old heartbeat."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        node = NodeInfo(
            node_id="node1",
            hostname="localhost",
            last_heartbeat=old_time,
        )
        assert node.is_alive(timeout_seconds=30) is False


class TestJobLock:
    """Test job locking."""

    def test_lock_creation(self) -> None:
        """Test creating job lock."""
        now = datetime.now(timezone.utc)
        future = now + timedelta(minutes=5)
        lock = JobLock(
            job_id="job1",
            node_id="node1",
            acquired_at=now,
            expires_at=future,
        )
        assert lock.job_id == "job1"
        assert lock.node_id == "node1"

    def test_lock_valid(self) -> None:
        """Test lock is valid."""
        now = datetime.now(timezone.utc)
        future = now + timedelta(minutes=5)
        lock = JobLock(
            job_id="job1",
            node_id="node1",
            acquired_at=now,
            expires_at=future,
        )
        assert lock.is_valid() is True

    def test_lock_expired(self) -> None:
        """Test lock is expired."""
        now = datetime.now(timezone.utc)
        past = now - timedelta(minutes=5)
        lock = JobLock(
            job_id="job1",
            node_id="node1",
            acquired_at=past,
            expires_at=past,
        )
        assert lock.is_valid() is False


class TestDistributedScheduler:
    """Test distributed scheduler functionality."""

    def test_creation(self) -> None:
        """Test creating distributed scheduler."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(coordination_dir=tmpdir)
            assert scheduler.node_id is not None
            assert scheduler._running is False

    def test_custom_node_id(self) -> None:
        """Test creating scheduler with custom node ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(node_id="custom_node", coordination_dir=tmpdir)
            assert scheduler.node_id == "custom_node"

    def test_start_stop(self) -> None:
        """Test starting and stopping scheduler."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(coordination_dir=tmpdir)
            scheduler.start()
            assert scheduler._running is True

            scheduler.stop()
            assert scheduler._running is False

    def test_register_node(self) -> None:
        """Test node registration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)
            scheduler._register_node()

            nodes = scheduler.get_nodes()
            assert len(nodes) > 0
            assert any(n.node_id == "node1" for n in nodes)

    def test_deregister_node(self) -> None:
        """Test node deregistration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)
            scheduler._register_node()
            scheduler._deregister_node()

            nodes = scheduler.get_nodes()
            assert not any(n.node_id == "node1" for n in nodes)

    def test_try_acquire_lock(self) -> None:
        """Test acquiring job lock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)
            acquired = scheduler.try_acquire_lock("job1")
            assert acquired is True

    def test_lock_prevents_double_acquisition(self) -> None:
        """Test lock prevents double acquisition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler1 = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)
            scheduler2 = DistributedScheduler(node_id="node2", coordination_dir=tmpdir)

            acquired1 = scheduler1.try_acquire_lock("job1")
            assert acquired1 is True

            acquired2 = scheduler2.try_acquire_lock("job1")
            assert acquired2 is False

    def test_release_lock(self) -> None:
        """Test releasing job lock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)
            scheduler.try_acquire_lock("job1")
            scheduler.release_lock("job1")

            # Should be able to acquire again
            acquired = scheduler.try_acquire_lock("job1")
            assert acquired is True

    def test_lock_expiration(self) -> None:
        """Test lock expiration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler1 = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)
            scheduler2 = DistributedScheduler(node_id="node2", coordination_dir=tmpdir)

            # Acquire lock with short timeout
            scheduler1.try_acquire_lock("job1", lock_timeout_seconds=1)

            # Try to acquire immediately - should fail
            acquired = scheduler2.try_acquire_lock("job1")
            assert acquired is False

    def test_leader_election(self) -> None:
        """Test leader election."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler1 = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)
            scheduler2 = DistributedScheduler(node_id="node2", coordination_dir=tmpdir)

            scheduler1.start()
            scheduler2.start()

            # Give time for election
            import time

            time.sleep(1)

            # One should be leader
            leader_id = scheduler1.get_leader_id()
            assert leader_id in ["node1", "node2"]

            scheduler1.stop()
            scheduler2.stop()

    def test_get_alive_nodes(self) -> None:
        """Test getting alive nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)
            scheduler.start()

            alive = scheduler.get_alive_nodes()
            assert len(alive) > 0

            scheduler.stop()

    def test_heartbeat_updates(self) -> None:
        """Test heartbeat updates node status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)
            scheduler._register_node()

            node = scheduler._nodes["node1"]
            old_heartbeat = node.last_heartbeat

            import time

            time.sleep(0.1)

            scheduler._send_heartbeat()
            new_heartbeat = scheduler._nodes["node1"].last_heartbeat

            assert new_heartbeat > old_heartbeat

    def test_multiple_locks_different_jobs(self) -> None:
        """Test acquiring locks for different jobs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)

            acquired1 = scheduler.try_acquire_lock("job1")
            acquired2 = scheduler.try_acquire_lock("job2")

            assert acquired1 is True
            assert acquired2 is True

    def test_same_node_can_reacquire_lock(self) -> None:
        """Test same node can reacquire its own lock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = DistributedScheduler(node_id="node1", coordination_dir=tmpdir)

            acquired1 = scheduler.try_acquire_lock("job1")
            acquired2 = scheduler.try_acquire_lock("job1")

            # Same node should be able to reacquire
            assert acquired1 is True
            assert acquired2 is True
