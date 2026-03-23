"""Linux cgroup simulation for resource management."""

import threading
from dataclasses import dataclass
from datetime import datetime


@dataclass
class CPUStats:
    """CPU statistics."""

    usage_ns: int = 0
    throttled_count: int = 0
    throttled_time_ns: int = 0
    user_time_ns: int = 0
    system_time_ns: int = 0


@dataclass
class MemoryStats:
    """Memory statistics."""

    usage_bytes: int = 0
    max_usage_bytes: int = 0
    limit_bytes: int = 0
    swap_usage_bytes: int = 0
    page_faults: int = 0
    major_page_faults: int = 0


@dataclass
class PIDs:
    """PID limit statistics."""

    current: int = 0
    limit: int = 0


@dataclass
class IOStats:
    """I/O statistics."""

    read_bytes: int = 0
    write_bytes: int = 0
    read_ops: int = 0
    write_ops: int = 0


@dataclass
class CGroupLimits:
    """cgroup resource limits."""

    cpu_period: int = 100000  # microseconds
    cpu_quota: int = -1  # microseconds (-1 = unlimited)
    memory_limit: int = -1  # bytes (-1 = unlimited)
    memory_soft_limit: int = -1
    pid_limit: int = -1
    io_weight: int = 100


class CGroupManager:
    """Manages Linux cgroup for resource limits."""

    def __init__(self) -> None:
        """Initialize cgroup manager."""
        self._cgroups: dict[str, dict] = {}
        self._stats: dict[str, dict] = {}
        self._enforcement_threads: dict[str, threading.Thread] = {}

    def create_cgroup(
        self,
        cgroup_id: str,
        cpu_shares: int = 1024,
        memory_mb: int = 512,
        pids_limit: int = 4096,
        io_read_bps: int | None = None,
        io_write_bps: int | None = None,
    ) -> None:
        """Create a cgroup.

        Args:
            cgroup_id: cgroup identifier.
            cpu_shares: CPU shares (1-262144).
            memory_mb: Memory limit in MB.
            pids_limit: Process ID limit.
            io_read_bps: I/O read bandwidth limit (bytes/sec).
            io_write_bps: I/O write bandwidth limit (bytes/sec).
        """
        limits = CGroupLimits(
            cpu_quota=(cpu_shares * 100000) // 1024,  # Convert shares to quota
            memory_limit=memory_mb * 1024 * 1024,
            pid_limit=pids_limit,
        )

        self._cgroups[cgroup_id] = {
            "limits": limits,
            "io_read_bps": io_read_bps,
            "io_write_bps": io_write_bps,
            "created_at": datetime.utcnow(),
        }

        self._stats[cgroup_id] = {
            "cpu": CPUStats(),
            "memory": MemoryStats(limit_bytes=memory_mb * 1024 * 1024),
            "pids": PIDs(limit=pids_limit),
            "io": IOStats(),
        }

    def remove_cgroup(self, cgroup_id: str) -> None:
        """Remove a cgroup.

        Args:
            cgroup_id: cgroup identifier.
        """
        if cgroup_id in self._enforcement_threads:
            self._enforcement_threads[cgroup_id].join(timeout=1)
            del self._enforcement_threads[cgroup_id]

        if cgroup_id in self._cgroups:
            del self._cgroups[cgroup_id]
        if cgroup_id in self._stats:
            del self._stats[cgroup_id]

    def set_cpu_limit(self, cgroup_id: str, cpu_quota: int, cpu_period: int = 100000) -> None:
        """Set CPU limit.

        Args:
            cgroup_id: cgroup identifier.
            cpu_quota: CPU quota in microseconds.
            cpu_period: CPU period in microseconds.
        """
        if cgroup_id not in self._cgroups:
            return

        self._cgroups[cgroup_id]["limits"].cpu_quota = cpu_quota
        self._cgroups[cgroup_id]["limits"].cpu_period = cpu_period

    def set_memory_limit(self, cgroup_id: str, memory_bytes: int) -> None:
        """Set memory limit.

        Args:
            cgroup_id: cgroup identifier.
            memory_bytes: Memory limit in bytes.
        """
        if cgroup_id not in self._cgroups:
            return

        self._cgroups[cgroup_id]["limits"].memory_limit = memory_bytes
        self._stats[cgroup_id]["memory"].limit_bytes = memory_bytes

    def set_pid_limit(self, cgroup_id: str, pid_limit: int) -> None:
        """Set PID limit.

        Args:
            cgroup_id: cgroup identifier.
            pid_limit: Maximum number of processes.
        """
        if cgroup_id not in self._cgroups:
            return

        self._cgroups[cgroup_id]["limits"].pid_limit = pid_limit
        self._stats[cgroup_id]["pids"].limit = pid_limit

    def get_cpu_stats(self, cgroup_id: str) -> CPUStats:
        """Get CPU statistics.

        Args:
            cgroup_id: cgroup identifier.

        Returns:
            CPU statistics.
        """
        if cgroup_id not in self._stats:
            return CPUStats()

        return self._stats[cgroup_id]["cpu"]

    def get_memory_stats(self, cgroup_id: str) -> MemoryStats:
        """Get memory statistics.

        Args:
            cgroup_id: cgroup identifier.

        Returns:
            Memory statistics.
        """
        if cgroup_id not in self._stats:
            return MemoryStats()

        return self._stats[cgroup_id]["memory"]

    def get_pid_stats(self, cgroup_id: str) -> PIDs:
        """Get PID statistics.

        Args:
            cgroup_id: cgroup identifier.

        Returns:
            PID statistics.
        """
        if cgroup_id not in self._stats:
            return PIDs()

        return self._stats[cgroup_id]["pids"]

    def get_io_stats(self, cgroup_id: str) -> IOStats:
        """Get I/O statistics.

        Args:
            cgroup_id: cgroup identifier.

        Returns:
            I/O statistics.
        """
        if cgroup_id not in self._stats:
            return IOStats()

        return self._stats[cgroup_id]["io"]

    def update_cpu_usage(self, cgroup_id: str, usage_ns: int) -> None:
        """Update CPU usage.

        Args:
            cgroup_id: cgroup identifier.
            usage_ns: CPU time used in nanoseconds.
        """
        if cgroup_id not in self._stats:
            return

        self._stats[cgroup_id]["cpu"].usage_ns = usage_ns

    def update_memory_usage(self, cgroup_id: str, usage_bytes: int) -> None:
        """Update memory usage.

        Args:
            cgroup_id: cgroup identifier.
            usage_bytes: Memory used in bytes.
        """
        if cgroup_id not in self._stats:
            return

        mem_stats = self._stats[cgroup_id]["memory"]
        mem_stats.usage_bytes = usage_bytes

        if usage_bytes > mem_stats.max_usage_bytes:
            mem_stats.max_usage_bytes = usage_bytes

    def update_pids_count(self, cgroup_id: str, count: int) -> None:
        """Update number of processes.

        Args:
            cgroup_id: cgroup identifier.
            count: Current process count.
        """
        if cgroup_id not in self._stats:
            return

        self._stats[cgroup_id]["pids"].current = count

    def enforce_limits(self, cgroup_id: str) -> bool:
        """Enforce resource limits for cgroup.

        Args:
            cgroup_id: cgroup identifier.

        Returns:
            True if limits are being enforced.
        """
        if cgroup_id not in self._cgroups:
            return False

        # Check memory limit
        mem_stats = self._stats[cgroup_id]["memory"]
        limits = self._cgroups[cgroup_id]["limits"]

        if limits.memory_limit > 0 and mem_stats.usage_bytes > limits.memory_limit:
            mem_stats.page_faults += 1
            return True

        # Check PID limit
        pid_stats = self._stats[cgroup_id]["pids"]
        if limits.pid_limit > 0 and pid_stats.current > limits.pid_limit:
            return True

        return False

    def is_memory_exceeded(self, cgroup_id: str) -> bool:
        """Check if memory limit exceeded.

        Args:
            cgroup_id: cgroup identifier.

        Returns:
            True if memory limit exceeded.
        """
        if cgroup_id not in self._stats:
            return False

        if cgroup_id not in self._cgroups:
            return False

        mem_stats = self._stats[cgroup_id]["memory"]
        limits = self._cgroups[cgroup_id]["limits"]

        return limits.memory_limit > 0 and mem_stats.usage_bytes > limits.memory_limit

    def get_cgroup_info(self, cgroup_id: str) -> dict:
        """Get cgroup information.

        Args:
            cgroup_id: cgroup identifier.

        Returns:
            cgroup information dictionary.
        """
        if cgroup_id not in self._cgroups:
            return {}

        limits = self._cgroups[cgroup_id]["limits"]
        stats = self._stats[cgroup_id]

        return {
            "id": cgroup_id,
            "limits": {
                "cpu_quota": limits.cpu_quota,
                "cpu_period": limits.cpu_period,
                "memory": limits.memory_limit,
                "pids": limits.pid_limit,
            },
            "stats": {
                "cpu": {
                    "usage_ns": stats["cpu"].usage_ns,
                    "throttled_count": stats["cpu"].throttled_count,
                },
                "memory": {
                    "usage": stats["memory"].usage_bytes,
                    "max_usage": stats["memory"].max_usage_bytes,
                    "limit": stats["memory"].limit_bytes,
                    "page_faults": stats["memory"].page_faults,
                },
                "pids": {
                    "current": stats["pids"].current,
                    "limit": stats["pids"].limit,
                },
                "io": {
                    "read_bytes": stats["io"].read_bytes,
                    "write_bytes": stats["io"].write_bytes,
                },
            },
        }
