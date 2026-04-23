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

from thomas.marketplace.containers._exceptions import (
    ContainerException,
    ContainerNotFound,
    ImageNotFound,
    InvalidConfiguration,
    NetworkNotFound,
    RegistryException,
    VolumeNotFound,
)
from thomas.marketplace.containers._types import (
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
from thomas.marketplace.containers.cgroups import CGroupManager
from thomas.marketplace.containers.compose import ComposeParser
from thomas.marketplace.containers.health import HealthChecker
from thomas.marketplace.containers.images import DockerfileParser, ImageStore
from thomas.marketplace.containers.logs import LogDriver
from thomas.marketplace.containers.networking import ContainerNetworking
from thomas.marketplace.containers.orchestrator import ServiceDefinition, SimpleOrchestrator
from thomas.marketplace.containers.registry import ContainerRegistry
from thomas.marketplace.containers.runtime import ContainerRuntime
from thomas.marketplace.containers.volumes import VolumeManager

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
