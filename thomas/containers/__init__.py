"""Thomas Container Runtime - A Python container simulation library.

This module provides a complete container runtime simulation with support for:
- Container lifecycle management (create, start, stop, remove)
- Docker image management with layer-based storage
- Container networking (bridge, host, none modes)
- Volume management (named volumes, bind mounts)
- Service orchestration and Docker Compose support
- Health checking and resource limits
- Container logging and statistics
"""

from thomas.containers._exceptions import (
    ContainerException,
    ContainerNotFound,
    ImageNotFound,
    InvalidConfiguration,
    NetworkNotFound,
    RegistryException,
    VolumeNotFound,
)
from thomas.containers._types import (
    Container,
    ContainerStatus,
    HealthCheck,
    Image,
    Network,
    Port,
    ResourceLimits,
    RestartPolicy,
    Volume,
)
from thomas.containers.cgroups import CGroupManager
from thomas.containers.compose import ComposeParser
from thomas.containers.health import HealthChecker
from thomas.containers.images import DockerfileParser, ImageStore
from thomas.containers.logs import LogDriver
from thomas.containers.networking import ContainerNetworking
from thomas.containers.orchestrator import ServiceDefinition, SimpleOrchestrator
from thomas.containers.registry import ContainerRegistry
from thomas.containers.runtime import ContainerRuntime
from thomas.containers.volumes import VolumeManager

__version__ = "0.1.0"

__all__ = [
    # Types
    "Container",
    "ContainerStatus",
    "Image",
    "Volume",
    "Network",
    "Port",
    "ResourceLimits",
    "HealthCheck",
    "RestartPolicy",
    # Exceptions
    "ContainerException",
    "ContainerNotFound",
    "ImageNotFound",
    "NetworkNotFound",
    "VolumeNotFound",
    "RegistryException",
    "InvalidConfiguration",
    # Runtime components
    "ContainerRuntime",
    "ImageStore",
    "DockerfileParser",
    "ContainerNetworking",
    "VolumeManager",
    "SimpleOrchestrator",
    "ServiceDefinition",
    "ComposeParser",
    "ContainerRegistry",
    "HealthChecker",
    "LogDriver",
    "CGroupManager",
]
