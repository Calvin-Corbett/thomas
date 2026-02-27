"""Simple container orchestration and service management."""

from dataclasses import dataclass, field

from thomas.containers._exceptions import (
    ContainerNotFound,
    InvalidConfiguration,
)
from thomas.containers._types import HealthCheck, Image, Port, ResourceLimits
from thomas.containers.networking import ContainerNetworking
from thomas.containers.runtime import ContainerRuntime
from thomas.containers.volumes import VolumeManager


@dataclass
class ServiceDefinition:
    """Service definition for orchestration."""

    name: str
    image: Image
    replicas: int = 1
    ports: list[Port] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    volumes: dict[str, str] = field(default_factory=dict)
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    health_check: HealthCheck | None = None
    labels: dict[str, str] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    restart_policy: str = "always"

    def __post_init__(self) -> None:
        """Validate service definition."""
        if self.replicas < 1:
            raise ValueError("replicas must be at least 1")
        if not self.name:
            raise ValueError("Service name cannot be empty")


class SimpleOrchestrator:
    """Simple service orchestrator."""

    def __init__(
        self,
        runtime: ContainerRuntime,
        networking: ContainerNetworking,
        volume_manager: VolumeManager,
    ) -> None:
        """Initialize orchestrator.

        Args:
            runtime: Container runtime.
            networking: Container networking.
            volume_manager: Volume manager.
        """
        self.runtime = runtime
        self.networking = networking
        self.volume_manager = volume_manager
        self._services: dict[str, ServiceDefinition] = {}
        self._containers: dict[str, list[str]] = {}

    def deploy_service(self, service: ServiceDefinition, network: str = "bridge") -> None:
        """Deploy a service.

        Args:
            service: Service definition.
            network: Network to deploy to.

        Raises:
            InvalidConfiguration: If service is invalid.
        """
        if service.name in self._services:
            raise InvalidConfiguration(f"Service already exists: {service.name}")

        self._services[service.name] = service
        self._containers[service.name] = []

        # Create replicas
        for i in range(service.replicas):
            container_name = f"{service.name}.{i}"
            container = self.runtime.create_container(
                image=service.image,
                name=container_name,
                env=service.env,
                ports=service.ports,
                volumes=service.volumes,
                resource_limits=service.resource_limits,
                labels={
                    **service.labels,
                    "service": service.name,
                    "replica": str(i),
                },
                health_check=service.health_check,
            )

            # Connect to network
            self.networking.connect_container(container, network)

            # Mount volumes
            for container_path, host_path in service.volumes.items():
                if host_path.startswith("/"):
                    self.volume_manager.bind_mount(host_path, container.id, container_path)

            # Start container
            self.runtime.start_container(container.id)
            self._containers[service.name].append(container.id)

    def scale_service(self, service_name: str, replicas: int, network: str = "bridge") -> None:
        """Scale a service to desired replica count.

        Args:
            service_name: Service name.
            replicas: Desired replica count.

        Raises:
            InvalidConfiguration: If service not found or replicas invalid.
        """
        if service_name not in self._services:
            raise InvalidConfiguration(f"Service not found: {service_name}")

        if replicas < 1:
            raise InvalidConfiguration("replicas must be at least 1")

        service = self._services[service_name]
        current_replicas = len(self._containers[service_name])

        if replicas > current_replicas:
            # Scale up
            for i in range(current_replicas, replicas):
                container_name = f"{service_name}.{i}"
                container = self.runtime.create_container(
                    image=service.image,
                    name=container_name,
                    env=service.env,
                    ports=service.ports,
                    volumes=service.volumes,
                    resource_limits=service.resource_limits,
                    labels={
                        **service.labels,
                        "service": service_name,
                        "replica": str(i),
                    },
                )
                self.networking.connect_container(container, network)
                self.runtime.start_container(container.id)
                self._containers[service_name].append(container.id)

        elif replicas < current_replicas:
            # Scale down
            containers_to_remove = self._containers[service_name][replicas:]
            for container_id in containers_to_remove:
                self.runtime.stop_container(container_id)
                self.runtime.remove_container(container_id, force=True)
            self._containers[service_name] = self._containers[service_name][:replicas]

    def remove_service(self, service_name: str) -> None:
        """Remove a service.

        Args:
            service_name: Service name.

        Raises:
            InvalidConfiguration: If service not found.
        """
        if service_name not in self._services:
            raise InvalidConfiguration(f"Service not found: {service_name}")

        # Stop and remove all containers
        for container_id in self._containers[service_name]:
            try:
                self.runtime.stop_container(container_id)
                self.runtime.remove_container(container_id, force=True)
            except ContainerNotFound:
                pass

        del self._services[service_name]
        del self._containers[service_name]

    def rolling_update(
        self,
        service_name: str,
        image: Image,
        max_surge: int = 1,
        max_unavailable: int = 0,
    ) -> None:
        """Perform rolling update of service.

        Args:
            service_name: Service name.
            image: New image.
            max_surge: Max additional containers during update.
            max_unavailable: Max containers unavailable during update.

        Raises:
            InvalidConfiguration: If service not found.
        """
        if service_name not in self._services:
            raise InvalidConfiguration(f"Service not found: {service_name}")

        service = self._services[service_name]
        old_containers = self._containers[service_name][:]
        replicas = len(old_containers)

        # Temporarily scale up to handle surge
        target_replicas = replicas + max_surge
        service.image = image

        for i in range(replicas, target_replicas):
            container_name = f"{service_name}.{i}"
            container = self.runtime.create_container(
                image=image,
                name=container_name,
                env=service.env,
                ports=service.ports,
                volumes=service.volumes,
                resource_limits=service.resource_limits,
                labels={
                    **service.labels,
                    "service": service_name,
                    "replica": str(i),
                },
            )
            self.networking.connect_container(container, "bridge")
            self.runtime.start_container(container.id)
            self._containers[service_name].append(container.id)

        # Gradually remove old containers
        for container_id in old_containers:
            self.runtime.stop_container(container_id)
            self.runtime.remove_container(container_id, force=True)
            self._containers[service_name].remove(container_id)

    def get_service_info(self, service_name: str) -> dict:
        """Get service information.

        Args:
            service_name: Service name.

        Returns:
            Service information dictionary.

        Raises:
            InvalidConfiguration: If service not found.
        """
        if service_name not in self._services:
            raise InvalidConfiguration(f"Service not found: {service_name}")

        service = self._services[service_name]
        containers = []

        for container_id in self._containers[service_name]:
            try:
                container = self.runtime.get_container(container_id)
                containers.append(
                    {
                        "id": container.id,
                        "name": container.name,
                        "status": container.status.value,
                        "ip_address": container.ip_address,
                    }
                )
            except ContainerNotFound:
                pass

        return {
            "name": service_name,
            "image": service.image.full_name,
            "replicas": len(containers),
            "desired_replicas": service.replicas,
            "containers": containers,
        }

    def list_services(self) -> list[dict]:
        """List all services.

        Returns:
            List of service information.
        """
        services = []
        for service_name in self._services:
            services.append(self.get_service_info(service_name))
        return services

    def load_balance(self, service_name: str) -> str | None:
        """Get next container for load balancing (round-robin).

        Args:
            service_name: Service name.

        Returns:
            Container ID, or None if no healthy containers.

        Raises:
            InvalidConfiguration: If service not found.
        """
        if service_name not in self._services:
            raise InvalidConfiguration(f"Service not found: {service_name}")

        containers = self._containers[service_name]
        if not containers:
            return None

        # Round-robin selection
        return containers[hash(service_name) % len(containers)]

    def service_discovery(self, service_name: str) -> list[str]:
        """Discover service endpoints.

        Args:
            service_name: Service name.

        Returns:
            List of IP addresses.

        Raises:
            InvalidConfiguration: If service not found.
        """
        if service_name not in self._services:
            raise InvalidConfiguration(f"Service not found: {service_name}")

        endpoints = []
        for container_id in self._containers[service_name]:
            try:
                container = self.runtime.get_container(container_id)
                if container.ip_address:
                    endpoints.append(container.ip_address)
            except ContainerNotFound:
                pass

        return endpoints
