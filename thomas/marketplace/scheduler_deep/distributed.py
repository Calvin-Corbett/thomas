"""
Distributed scheduling with leader election and failover.

Enables multi-node scheduling with automatic failover and job locking.
"""

import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from thomas.marketplace.scheduler_deep._exceptions import DistributedSchedulingError


@dataclass
class NodeInfo:
    """Information about a scheduler node."""

    node_id: str
    hostname: str
    last_heartbeat: datetime
    is_leader: bool = False

    def is_alive(self, timeout_seconds: int = 30) -> bool:
        """Check if node is alive based on heartbeat.

        Args:
            timeout_seconds: Heartbeat timeout

        Returns:
            True if node is alive
        """
        elapsed = datetime.now(timezone.utc) - self.last_heartbeat
        return elapsed.total_seconds() < timeout_seconds


@dataclass
class JobLock:
    """Lock for distributed job execution."""

    job_id: str
    node_id: str
    acquired_at: datetime
    expires_at: datetime

    def is_valid(self) -> bool:
        """Check if lock is still valid.

        Returns:
            True if lock hasn't expired
        """
        return datetime.now(timezone.utc) < self.expires_at


class DistributedScheduler:
    """Distributed scheduler with leader election and job locking."""

    def __init__(
        self,
        node_id: str | None = None,
        coordination_dir: str | None = None,
        heartbeat_interval: int = 5,
        leader_election_interval: int = 10,
    ) -> None:
        """Initialize distributed scheduler.

        Args:
            node_id: Unique node identifier
            coordination_dir: Directory for coordination files
            heartbeat_interval: Heartbeat interval in seconds
            leader_election_interval: Leader election interval in seconds
        """
        self.node_id = node_id or str(uuid.uuid4())
        self.coordination_dir = Path(coordination_dir or "/tmp/scheduler_coordination")
        self.coordination_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat_interval = heartbeat_interval
        self.leader_election_interval = leader_election_interval

        self._is_leader = False
        self._nodes: dict[str, NodeInfo] = {}
        self._job_locks: dict[str, JobLock] = {}
        self._lock = threading.RLock()
        self._heartbeat_thread: threading.Thread | None = None
        self._election_thread: threading.Thread | None = None
        self._running = False

        self._init_files()

    def _init_files(self) -> None:
        """Initialize coordination files."""
        self._nodes_file = self.coordination_dir / "nodes.json"
        self._locks_file = self.coordination_dir / "locks.json"
        self._leader_file = self.coordination_dir / "leader"

    def start(self) -> None:
        """Start distributed scheduler."""
        with self._lock:
            if self._running:
                return

            self._running = True
            self._register_node()

            # Start heartbeat thread
            self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self._heartbeat_thread.start()

            # Start leader election thread
            self._election_thread = threading.Thread(target=self._leader_election_loop, daemon=True)
            self._election_thread.start()

    def stop(self) -> None:
        """Stop distributed scheduler."""
        with self._lock:
            self._running = False
            self._deregister_node()

    def _register_node(self) -> None:
        """Register this node."""
        with self._lock:
            node_info = NodeInfo(
                node_id=self.node_id,
                hostname="localhost",
                last_heartbeat=datetime.now(timezone.utc),
            )
            self._nodes[self.node_id] = node_info
            self._save_nodes()

    def _deregister_node(self) -> None:
        """Deregister this node."""
        with self._lock:
            self._nodes.pop(self.node_id, None)
            self._save_nodes()

            # Release all locks
            self._job_locks = {jid: lock for jid, lock in self._job_locks.items() if lock.node_id != self.node_id}
            self._save_locks()

    def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self._running:
            try:
                self._send_heartbeat()
                time.sleep(self.heartbeat_interval)
            except Exception as e:
                print(f"Heartbeat error: {e}")

    def _send_heartbeat(self) -> None:
        """Send heartbeat to update node status."""
        with self._lock:
            if self.node_id in self._nodes:
                self._nodes[self.node_id].last_heartbeat = datetime.now(timezone.utc)
                self._save_nodes()

    def _leader_election_loop(self) -> None:
        """Perform periodic leader election."""
        while self._running:
            try:
                self._perform_leader_election()
                time.sleep(self.leader_election_interval)
            except Exception as e:
                print(f"Leader election error: {e}")

    def _perform_leader_election(self) -> None:
        """Elect a leader from alive nodes."""
        with self._lock:
            self._load_nodes()

            # Filter alive nodes
            alive_nodes = [node for node in self._nodes.values() if node.is_alive()]

            if not alive_nodes:
                return

            # Select leader (node with smallest ID)
            leader = min(alive_nodes, key=lambda n: n.node_id)

            # Update leader status
            for node in self._nodes.values():
                node.is_leader = node.node_id == leader.node_id

            self._is_leader = leader.node_id == self.node_id
            self._save_nodes()

    def try_acquire_lock(
        self,
        job_id: str,
        lock_timeout_seconds: int = 300,
    ) -> bool:
        """Try to acquire lock for job execution.

        Args:
            job_id: Job to lock
            lock_timeout_seconds: Lock timeout in seconds

        Returns:
            True if lock acquired
        """
        with self._lock:
            self._load_locks()

            # Check if lock exists and is valid
            if job_id in self._job_locks:
                lock = self._job_locks[job_id]
                if lock.is_valid():
                    return lock.node_id == self.node_id

            # Acquire new lock
            now = datetime.now(timezone.utc)
            lock = JobLock(
                job_id=job_id,
                node_id=self.node_id,
                acquired_at=now,
                expires_at=now + timedelta(seconds=lock_timeout_seconds),
            )
            self._job_locks[job_id] = lock
            self._save_locks()
            return True

    def release_lock(self, job_id: str) -> None:
        """Release job lock.

        Args:
            job_id: Job to unlock
        """
        with self._lock:
            self._load_locks()
            if job_id in self._job_locks:
                lock = self._job_locks[job_id]
                if lock.node_id == self.node_id:
                    del self._job_locks[job_id]
                    self._save_locks()

    def is_leader(self) -> bool:
        """Check if this node is the leader.

        Returns:
            True if node is leader
        """
        with self._lock:
            return self._is_leader

    def get_leader_id(self) -> str | None:
        """Get current leader node ID.

        Returns:
            Leader node ID or None
        """
        with self._lock:
            self._load_nodes()
            for node in self._nodes.values():
                if node.is_leader:
                    return node.node_id
            return None

    def get_nodes(self) -> list[NodeInfo]:
        """Get list of all nodes.

        Returns:
            List of node information
        """
        with self._lock:
            self._load_nodes()
            return list(self._nodes.values())

    def get_alive_nodes(self) -> list[NodeInfo]:
        """Get list of alive nodes.

        Returns:
            List of alive node information
        """
        with self._lock:
            self._load_nodes()
            return [n for n in self._nodes.values() if n.is_alive()]

    def _save_nodes(self) -> None:
        """Save nodes to file."""
        try:
            data = {
                node_id: {
                    "node_id": node.node_id,
                    "hostname": node.hostname,
                    "last_heartbeat": node.last_heartbeat.isoformat(),
                    "is_leader": node.is_leader,
                }
                for node_id, node in self._nodes.items()
            }
            with open(self._nodes_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            raise DistributedSchedulingError(f"Failed to save nodes: {e}")

    def _load_nodes(self) -> None:
        """Load nodes from file."""
        try:
            if self._nodes_file.exists():
                with open(self._nodes_file) as f:
                    data = json.load(f)
                    self._nodes = {}
                    for node_id, node_data in data.items():
                        self._nodes[node_id] = NodeInfo(
                            node_id=node_data["node_id"],
                            hostname=node_data["hostname"],
                            last_heartbeat=datetime.fromisoformat(node_data["last_heartbeat"]),
                            is_leader=node_data["is_leader"],
                        )
        except Exception as e:
            raise DistributedSchedulingError(f"Failed to load nodes: {e}")

    def _save_locks(self) -> None:
        """Save locks to file."""
        try:
            data = {
                job_id: {
                    "job_id": lock.job_id,
                    "node_id": lock.node_id,
                    "acquired_at": lock.acquired_at.isoformat(),
                    "expires_at": lock.expires_at.isoformat(),
                }
                for job_id, lock in self._job_locks.items()
            }
            with open(self._locks_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            raise DistributedSchedulingError(f"Failed to save locks: {e}")

    def _load_locks(self) -> None:
        """Load locks from file."""
        try:
            if self._locks_file.exists():
                with open(self._locks_file) as f:
                    data = json.load(f)
                    self._job_locks = {}
                    for job_id, lock_data in data.items():
                        lock = JobLock(
                            job_id=lock_data["job_id"],
                            node_id=lock_data["node_id"],
                            acquired_at=datetime.fromisoformat(lock_data["acquired_at"]),
                            expires_at=datetime.fromisoformat(lock_data["expires_at"]),
                        )
                        # Only keep valid locks
                        if lock.is_valid():
                            self._job_locks[job_id] = lock
        except Exception as e:
            raise DistributedSchedulingError(f"Failed to load locks: {e}")

    def __repr__(self) -> str:
        """String representation."""
        return f"DistributedScheduler(node_id={self.node_id}, is_leader={self._is_leader})"
