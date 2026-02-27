"""Container runtime management and lifecycle control."""

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from thomas.containers._exceptions import (
    ContainerException,
    ContainerNotFound,
    InvalidConfiguration,
)
from thomas.containers._types import (
    Container,
    ContainerStatus,
    HealthCheck,
    Image,
    Port,
    ResourceLimits,
    RestartPolicy,
)


@dataclass
class ProcessInfo:
    """Simulated process information."""

    pid: int
    ppid: int
    command: list[str]
    status: str
    start_time: datetime
    cpu_time: float = 0.0
    memory_usage: int = 0
    num_threads: int = 1


class ContainerRuntime:
    """Container runtime engine for managing container lifecycle.

    This class simulates a complete container runtime with process isolation,
    resource limits, and lifecycle management.
    """

    def __init__(self, data_root: str = "/var/lib/containers") -> None:
        """Initialize the container runtime.

        Args:
            data_root: Root directory for container data storage.
        """
        self.data_root = data_root
        self._containers: dict[str, Container] = {}
        self._processes: dict[str, ProcessInfo] = {}
        self._next_pid = 1000
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

    def create_container(
        self,
        image: Image,
        name: str | None = None,
        cmd: list[str] | None = None,
        env: dict[str, str] | None = None,
        ports: list[Port] | None = None,
        volumes: dict[str, str] | None = None,
        resource_limits: ResourceLimits | None = None,
        labels: dict[str, str] | None = None,
        health_check: HealthCheck | None = None,
        restart_policy: RestartPolicy = RestartPolicy.NO,
        network_mode: str = "bridge",
    ) -> Container:
        """Create a new container.

        Args:
            image: Container image.
            name: Container name. Auto-generated if not provided.
            cmd: Command to run in container.
            env: Environment variables.
            ports: Port mappings.
            volumes: Volume mounts (container_path -> host_path).
            resource_limits: Resource constraints.
            labels: Container labels.
            health_check: Health check configuration.
            restart_policy: Restart behavior.
            network_mode: Network mode (bridge, host, none).

        Returns:
            Created container.

        Raises:
            InvalidConfiguration: If configuration is invalid.
        """
        with self._lock:
            container_id = str(uuid.uuid4())[:12]
            if name is None:
                name = f"container_{container_id}"

            if name in self._containers:
                raise InvalidConfiguration(f"Container name already exists: {name}")

            if network_mode not in ("bridge", "host", "none"):
                raise InvalidConfiguration(f"Invalid network mode: {network_mode}")

            container = Container(
                id=container_id,
                name=name,
                image=image,
                ports=ports or [],
                env=env or {},
                volumes=volumes or {},
                resource_limits=resource_limits or ResourceLimits(),
                labels=labels or {},
                health_check=health_check,
                restart_policy=restart_policy,
                network_mode=network_mode,
                status=ContainerStatus.CREATED,
            )

            if cmd:
                image.cmd = cmd
            if env:
                container.env.update(env)

            self._containers[container_id] = container
            return container

    def start_container(self, container_id: str) -> Container:
        """Start a stopped or created container.

        Args:
            container_id: Container ID or name.

        Returns:
            Started container.

        Raises:
            ContainerNotFound: If container not found.
            ContainerException: If container cannot be started.
        """
        with self._lock:
            container = self._get_container(container_id)

            if container.status == ContainerStatus.RUNNING:
                raise ContainerException(f"Container already running: {container_id}")

            # Simulate process creation
            pid = self._allocate_pid()
            container.pid = pid
            container.status = ContainerStatus.RUNNING
            container.started_at = datetime.utcnow()
            container.restart_count = 0

            # Create process info
            self._processes[container.id] = ProcessInfo(
                pid=pid,
                ppid=1,
                command=container.image.cmd or ["sh"],
                status="S",
                start_time=datetime.utcnow(),
                memory_usage=int(container.resource_limits.memory_mb * 0.1),
            )

            return container

    def stop_container(self, container_id: str, timeout_seconds: int = 10) -> Container:
        """Stop a running container.

        Args:
            container_id: Container ID or name.
            timeout_seconds: Timeout before force killing.

        Returns:
            Stopped container.

        Raises:
            ContainerNotFound: If container not found.
        """
        with self._lock:
            container = self._get_container(container_id)

            if container.status != ContainerStatus.RUNNING:
                return container

            # Simulate graceful shutdown
            if container.id in self._processes:
                self._processes[container.id].status = "S"

            time.sleep(min(timeout_seconds, 1) / 1000)

            container.status = ContainerStatus.STOPPED
            container.stopped_at = datetime.utcnow()
            container.exit_code = 0

            if container.id in self._processes:
                del self._processes[container.id]

            return container

    def kill_container(self, container_id: str, signal_num: int = 9) -> Container:
        """Kill a container with a signal.

        Args:
            container_id: Container ID or name.
            signal_num: Signal number (default SIGKILL).

        Returns:
            Killed container.

        Raises:
            ContainerNotFound: If container not found.
        """
        with self._lock:
            container = self._get_container(container_id)

            if container.status == ContainerStatus.RUNNING:
                container.status = ContainerStatus.EXITED
                container.stopped_at = datetime.utcnow()
                container.exit_code = 137 if signal_num == 9 else signal_num

            if container.id in self._processes:
                del self._processes[container.id]

            return container

    def remove_container(self, container_id: str, force: bool = False) -> None:
        """Remove a container.

        Args:
            container_id: Container ID or name.
            force: Force remove running container.

        Raises:
            ContainerNotFound: If container not found.
            ContainerException: If container is running and force=False.
        """
        with self._lock:
            container = self._get_container(container_id)

            if container.status == ContainerStatus.RUNNING and not force:
                raise ContainerException(f"Container is running, stop before removing: {container_id}")

            if container.status == ContainerStatus.RUNNING:
                self.kill_container(container_id)

            del self._containers[container.id]

    def pause_container(self, container_id: str) -> Container:
        """Pause a running container.

        Args:
            container_id: Container ID or name.

        Returns:
            Paused container.

        Raises:
            ContainerNotFound: If container not found.
        """
        with self._lock:
            container = self._get_container(container_id)

            if container.status != ContainerStatus.RUNNING:
                raise ContainerException(f"Container is not running: {container_id}")

            container.status = ContainerStatus.PAUSED
            return container

    def unpause_container(self, container_id: str) -> Container:
        """Resume a paused container.

        Args:
            container_id: Container ID or name.

        Returns:
            Resumed container.

        Raises:
            ContainerNotFound: If container not found.
        """
        with self._lock:
            container = self._get_container(container_id)

            if container.status != ContainerStatus.PAUSED:
                raise ContainerException(f"Container is not paused: {container_id}")

            container.status = ContainerStatus.RUNNING
            return container

    def list_containers(self, all: bool = False, filters: dict[str, str] | None = None) -> list[Container]:
        """List containers.

        Args:
            all: Include stopped containers.
            filters: Filter by status, label, etc.

        Returns:
            List of containers.
        """
        with self._lock:
            containers = list(self._containers.values())

            if not all:
                containers = [c for c in containers if c.status == ContainerStatus.RUNNING]

            if filters:
                if "status" in filters:
                    status = ContainerStatus(filters["status"])
                    containers = [c for c in containers if c.status == status]

                if "label" in filters:
                    label_filter = filters["label"]
                    key, _, value = label_filter.partition("=")
                    containers = [c for c in containers if c.labels.get(key) == value]

            return sorted(containers, key=lambda c: c.created_at, reverse=True)

    def get_container(self, container_id: str) -> Container:
        """Get container by ID or name.

        Args:
            container_id: Container ID or name.

        Returns:
            Container.

        Raises:
            ContainerNotFound: If container not found.
        """
        with self._lock:
            return self._get_container(container_id)

    def get_container_logs(
        self,
        container_id: str,
        tail: int | None = None,
        follow: bool = False,
    ) -> list[str]:
        """Get container logs.

        Args:
            container_id: Container ID or name.
            tail: Number of recent lines to return.
            follow: Stream logs.

        Returns:
            Log lines.

        Raises:
            ContainerNotFound: If container not found.
        """
        with self._lock:
            container = self._get_container(container_id)
            logs = container.logs

            if tail is not None:
                logs = logs[-tail:]

            return logs

    def container_exec(self, container_id: str, cmd: list[str], user: str = "root") -> tuple[int, str, str]:
        """Execute a command in a running container.

        Args:
            container_id: Container ID or name.
            cmd: Command to execute.
            user: User to execute as.

        Returns:
            Tuple of (exit_code, stdout, stderr).

        Raises:
            ContainerNotFound: If container not found.
            ContainerException: If container is not running.
        """
        with self._lock:
            container = self._get_container(container_id)

            if container.status != ContainerStatus.RUNNING:
                raise ContainerException(f"Container is not running: {container_id}")

            # Simulate command execution
            exit_code = 0 if cmd[0] != "false" else 1
            stdout = f"Executed: {' '.join(cmd)}\n"
            stderr = "" if exit_code == 0 else "Command failed\n"

            log_entry = f"[{datetime.utcnow().isoformat()}] {' '.join(cmd)}"
            container.logs.append(log_entry)

            return (exit_code, stdout, stderr)

    def container_stats(self, container_id: str) -> dict[str, any]:
        """Get container resource statistics.

        Args:
            container_id: Container ID or name.

        Returns:
            Statistics dictionary.

        Raises:
            ContainerNotFound: If container not found.
        """
        with self._lock:
            container = self._get_container(container_id)

            if container.id not in self._processes:
                return {
                    "cpu_percent": 0.0,
                    "memory_usage": 0,
                    "memory_limit": container.resource_limits.memory_mb * 1024 * 1024,
                }

            process = self._processes[container.id]
            memory_limit = container.resource_limits.memory_mb * 1024 * 1024

            return {
                "cpu_percent": min(
                    100.0,
                    (process.cpu_time / (datetime.utcnow() - process.start_time).total_seconds()) * 100,
                ),
                "memory_usage": process.memory_usage,
                "memory_limit": memory_limit,
                "memory_percent": (process.memory_usage / memory_limit) * 100,
                "net_input": 0,
                "net_output": 0,
                "pids_count": process.num_threads,
            }

    def handle_restart_policy(self, container_id: str) -> Container | None:
        """Handle container restart based on restart policy.

        Args:
            container_id: Container ID or name.

        Returns:
            Restarted container, or None if not restarted.

        Raises:
            ContainerNotFound: If container not found.
        """
        with self._lock:
            container = self._get_container(container_id)

            policy = container.restart_policy
            if policy == RestartPolicy.NO:
                return None

            if policy == RestartPolicy.ALWAYS:
                return self.start_container(container_id)

            if policy == RestartPolicy.ON_FAILURE:
                if container.exit_code != 0:
                    container.restart_count += 1
                    container.last_restart = datetime.utcnow()
                    return self.start_container(container_id)

            return None

    def _get_container(self, container_id: str) -> Container:
        """Get container by ID or name.

        Args:
            container_id: Container ID or name.

        Returns:
            Container.

        Raises:
            ContainerNotFound: If container not found.
        """
        # Try direct ID lookup
        if container_id in self._containers:
            return self._containers[container_id]

        # Try name lookup
        for container in self._containers.values():
            if container.name == container_id:
                return container

        raise ContainerNotFound(container_id)

    def _allocate_pid(self) -> int:
        """Allocate a new PID.

        Returns:
            New process ID.
        """
        pid = self._next_pid
        self._next_pid += 1
        return pid

    def cleanup(self) -> None:
        """Clean up runtime resources."""
        with self._lock:
            for container in list(self._containers.values()):
                if container.status == ContainerStatus.RUNNING:
                    self.stop_container(container.id)
