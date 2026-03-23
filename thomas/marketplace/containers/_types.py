"""Core data types for container runtime simulation."""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ContainerStatus(Enum):
    """Container lifecycle states."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    EXITED = "exited"
    DEAD = "dead"


class RestartPolicy(Enum):
    """Container restart policies."""

    NO = "no"
    ALWAYS = "always"
    ON_FAILURE = "on-failure"
    UNLESS_STOPPED = "unless-stopped"


@dataclass
class Port:
    """Port mapping configuration."""

    container_port: int
    host_port: int | None = None
    protocol: str = "tcp"

    def __post_init__(self) -> None:
        """Validate port configuration."""
        if not 1 <= self.container_port <= 65535:
            raise ValueError(f"Invalid container port: {self.container_port}")
        if self.host_port is not None and not 1 <= self.host_port <= 65535:
            raise ValueError(f"Invalid host port: {self.host_port}")
        if self.protocol not in ("tcp", "udp"):
            raise ValueError(f"Invalid protocol: {self.protocol}")


@dataclass
class ResourceLimits:
    """Resource limit specifications."""

    cpu_shares: int = 1024
    memory_mb: int = 512
    pids_limit: int = 4096
    io_read_bps: int | None = None
    io_write_bps: int | None = None

    def __post_init__(self) -> None:
        """Validate resource limits."""
        if self.cpu_shares < 1 or self.cpu_shares > 262144:
            raise ValueError(f"Invalid cpu_shares: {self.cpu_shares}")
        if self.memory_mb < 4:
            raise ValueError(f"Memory limit must be at least 4MB, got {self.memory_mb}")
        if self.pids_limit < 1:
            raise ValueError(f"pids_limit must be positive, got {self.pids_limit}")


@dataclass
class HealthCheck:
    """Health check configuration."""

    test: list[str]
    interval_seconds: int = 30
    timeout_seconds: int = 10
    retries: int = 3
    start_period_seconds: int = 0

    def __post_init__(self) -> None:
        """Validate health check configuration."""
        if not self.test:
            raise ValueError("Health check test cannot be empty")
        if self.interval_seconds < 1:
            raise ValueError("interval_seconds must be positive")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if self.retries < 1:
            raise ValueError("retries must be positive")
        if self.start_period_seconds < 0:
            raise ValueError("start_period_seconds cannot be negative")


@dataclass
class Volume:
    """Volume specification."""

    name: str
    driver: str = "local"
    mountpoint: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    size_bytes: int = 0

    def __post_init__(self) -> None:
        """Validate volume configuration."""
        if not self.name:
            raise ValueError("Volume name cannot be empty")


@dataclass
class Network:
    """Network specification."""

    name: str
    driver: str = "bridge"
    subnet: str | None = None
    gateway: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        """Validate network configuration."""
        if not self.name:
            raise ValueError("Network name cannot be empty")
        if self.driver not in ("bridge", "host", "none", "overlay"):
            raise ValueError(f"Invalid network driver: {self.driver}")


@dataclass
class Layer:
    """Docker image layer."""

    digest: str
    size: int
    created_at: datetime = field(default_factory=datetime.utcnow)
    data: bytes = field(default_factory=bytes)

    @staticmethod
    def compute_digest(data: bytes) -> str:
        """Compute SHA256 digest of layer data."""
        return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass
class Image:
    """Docker image specification."""

    name: str
    tag: str = "latest"
    layers: list[Layer] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    labels: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    cmd: list[str] = field(default_factory=list)
    entrypoint: list[str] = field(default_factory=list)
    working_dir: str = "/app"
    exposed_ports: list[int] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    user: str = "root"

    @property
    def digest(self) -> str:
        """Compute image digest from layers."""
        layer_digests = "".join(layer.digest for layer in self.layers)
        return "sha256:" + hashlib.sha256(layer_digests.encode()).hexdigest()

    @property
    def full_name(self) -> str:
        """Get fully qualified image name."""
        return f"{self.name}:{self.tag}"

    @property
    def size_bytes(self) -> int:
        """Calculate total image size."""
        return sum(layer.size for layer in self.layers)


@dataclass
class Container:
    """Container specification and state."""

    id: str
    name: str
    image: Image
    status: ContainerStatus = ContainerStatus.CREATED
    pid: int | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    exit_code: int | None = None
    ports: list[Port] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    volumes: dict[str, str] = field(default_factory=dict)
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    labels: dict[str, str] = field(default_factory=dict)
    health_check: HealthCheck | None = None
    restart_policy: RestartPolicy = RestartPolicy.NO
    network_mode: str = "bridge"
    network_id: str | None = None
    ip_address: str | None = None
    hostname: str | None = None
    logs: list[str] = field(default_factory=list)
    restart_count: int = 0
    last_restart: datetime | None = None

    def __post_init__(self) -> None:
        """Validate container configuration."""
        if not self.id:
            raise ValueError("Container ID cannot be empty")
        if not self.name:
            raise ValueError("Container name cannot be empty")
        if self.hostname is None:
            self.hostname = self.name

    @property
    def uptime_seconds(self) -> int | None:
        """Calculate container uptime in seconds."""
        if self.started_at is None:
            return None
        end_time = self.stopped_at or datetime.utcnow()
        delta = end_time - self.started_at
        return int(delta.total_seconds())

    @property
    def is_running(self) -> bool:
        """Check if container is currently running."""
        return self.status == ContainerStatus.RUNNING
