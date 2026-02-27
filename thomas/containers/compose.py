"""Docker Compose format parser and orchestration."""

from dataclasses import dataclass
from typing import Any

import yaml

from thomas.containers._exceptions import InvalidConfiguration
from thomas.containers._types import HealthCheck, Image, Port, ResourceLimits
from thomas.containers.orchestrator import ServiceDefinition, SimpleOrchestrator


@dataclass
class ComposeService:
    """Parsed compose service."""

    name: str
    image: str
    tag: str = "latest"
    container_name: str | None = None
    ports: list[Port] = None
    environment: dict[str, str] = None
    volumes: dict[str, str] = None
    depends_on: list[str] = None
    restart_policy: str = "unless-stopped"
    resources: dict[str, Any] = None
    healthcheck: dict[str, Any] = None


class ComposeParser:
    """Parser for docker-compose.yml format."""

    SUPPORTED_VERSION = "3"

    def __init__(self) -> None:
        """Initialize compose parser."""
        self.services: dict[str, ComposeService] = {}
        self.networks: dict[str, dict[str, Any]] = {}
        self.volumes: dict[str, dict[str, Any]] = {}
        self.version = "3"

    def parse(self, compose_content: str) -> dict[str, Any]:
        """Parse docker-compose.yml content.

        Args:
            compose_content: YAML compose file content.

        Returns:
            Parsed compose structure.

        Raises:
            InvalidConfiguration: If compose file is invalid.
        """
        try:
            compose_dict = yaml.safe_load(compose_content)
        except yaml.YAMLError as e:
            raise InvalidConfiguration(f"Invalid YAML: {e}")

        if not compose_dict:
            raise InvalidConfiguration("Empty compose file")

        # Validate version
        version = compose_dict.get("version", "3")
        if not str(version).startswith(self.SUPPORTED_VERSION):
            raise InvalidConfiguration(f"Unsupported version: {version}")

        self.version = str(version)

        # Parse services
        services_dict = compose_dict.get("services", {})
        if not services_dict:
            raise InvalidConfiguration("No services defined")

        for service_name, service_config in services_dict.items():
            self._parse_service(service_name, service_config)

        # Parse networks
        self.networks = compose_dict.get("networks", {})

        # Parse volumes
        self.volumes = compose_dict.get("volumes", {})

        return {
            "version": self.version,
            "services": self.services,
            "networks": self.networks,
            "volumes": self.volumes,
        }

    def _parse_service(self, name: str, config: dict[str, Any]) -> None:
        """Parse a service configuration.

        Args:
            name: Service name.
            config: Service configuration dictionary.

        Raises:
            InvalidConfiguration: If service config is invalid.
        """
        if "image" not in config:
            raise InvalidConfiguration(f"Service {name} missing image")

        image_str = config["image"]
        if ":" in image_str:
            image_name, tag = image_str.rsplit(":", 1)
        else:
            image_name = image_str
            tag = "latest"

        # Parse ports
        ports = []
        for port_config in config.get("ports", []):
            if isinstance(port_config, str):
                parts = port_config.split(":")
                if len(parts) == 2:
                    host_port = int(parts[0])
                    container_port = int(parts[1])
                else:
                    container_port = int(parts[0])
                    host_port = container_port
            else:
                host_port = port_config.get("published", port_config.get("target"))
                container_port = port_config.get("target", port_config.get("published"))

            ports.append(Port(container_port=container_port, host_port=host_port))

        # Parse environment
        env = {}
        env_config = config.get("environment", {})
        if isinstance(env_config, dict):
            env = env_config
        elif isinstance(env_config, list):
            for env_str in env_config:
                if "=" in env_str:
                    key, value = env_str.split("=", 1)
                    env[key] = value

        # Interpolate environment variables
        env = self._interpolate_env(env)

        # Parse volumes
        volumes = {}
        for vol_config in config.get("volumes", []):
            if isinstance(vol_config, str):
                parts = vol_config.split(":")
                if len(parts) >= 2:
                    host_path = parts[0]
                    container_path = parts[1]
                    volumes[container_path] = host_path
            else:
                volumes[vol_config.get("target")] = vol_config.get("source", "")

        # Parse resource limits
        resource_limits = ResourceLimits()
        resources = config.get("resources", {})
        if "limits" in resources:
            limits = resources["limits"]
            if "memory" in limits:
                mem_str = limits["memory"]
                resource_limits.memory_mb = self._parse_memory(mem_str)
            if "cpus" in limits:
                resource_limits.cpu_shares = int(float(limits["cpus"]) * 1024)

        # Parse health check
        health_check = None
        healthcheck_config = config.get("healthcheck")
        if healthcheck_config:
            test = healthcheck_config.get("test", [])
            if isinstance(test, str):
                test = [test]
            health_check = HealthCheck(
                test=test,
                interval_seconds=self._parse_duration(healthcheck_config.get("interval", "30s")),
                timeout_seconds=self._parse_duration(healthcheck_config.get("timeout", "10s")),
                retries=healthcheck_config.get("retries", 3),
                start_period_seconds=self._parse_duration(healthcheck_config.get("start_period", "0s")),
            )

        # Parse restart policy
        restart_policy = "unless-stopped"
        restart_config = config.get("restart_policy", {})
        if isinstance(restart_config, str):
            restart_policy = restart_config
        else:
            restart_policy = restart_config.get("condition", "unless-stopped")

        service = ComposeService(
            name=name,
            image=image_name,
            tag=tag,
            container_name=config.get("container_name"),
            ports=ports,
            environment=env,
            volumes=volumes,
            depends_on=config.get("depends_on", []),
            restart_policy=restart_policy,
            resources=resources,
            healthcheck=healthcheck_config,
        )

        self.services[name] = service

    def get_service_dependencies(self) -> dict[str, set[str]]:
        """Get service dependency graph.

        Returns:
            Dictionary mapping service name to set of dependencies.
        """
        deps = {}
        for service_name, service in self.services.items():
            deps[service_name] = set(service.depends_on or [])
        return deps

    def resolve_dependencies(self) -> list[str]:
        """Resolve service dependencies using topological sort.

        Returns:
            Ordered list of service names for deployment.

        Raises:
            InvalidConfiguration: If circular dependency detected.
        """
        dependencies = self.get_service_dependencies()
        resolved = []
        unresolved = set(self.services.keys())

        def visit(service_name: str, visiting: set[str]) -> None:
            if service_name in resolved:
                return

            if service_name in visiting:
                raise InvalidConfiguration(f"Circular dependency detected: {service_name}")

            visiting.add(service_name)

            for dep in dependencies.get(service_name, []):
                if dep in dependencies:
                    visit(dep, visiting)

            visiting.remove(service_name)
            resolved.append(service_name)

        while unresolved:
            service_name = unresolved.pop()
            visit(service_name, set())

        return resolved

    def compose_up(self, orchestrator: SimpleOrchestrator) -> None:
        """Deploy all services using orchestrator.

        Args:
            orchestrator: Service orchestrator.

        Raises:
            InvalidConfiguration: If deployment fails.
        """
        # Create networks first
        for network_name in self.networks:
            network_config = self.networks[network_name]
            orchestrator.networking.create_network(
                network_name,
                driver=network_config.get("driver", "bridge"),
                subnet=network_config.get("ipam", {}).get("config", [{}])[0].get("subnet"),
            )

        # Deploy services in dependency order
        for service_name in self.resolve_dependencies():
            service_config = self.services[service_name]

            # Create image
            image = Image(
                name=service_config.image,
                tag=service_config.tag,
            )

            # Create service definition
            service = ServiceDefinition(
                name=service_name,
                image=image,
                replicas=1,
                ports=service_config.ports or [],
                env=service_config.environment or {},
                volumes=service_config.volumes or {},
                restart_policy=service_config.restart_policy,
            )

            orchestrator.deploy_service(service)

    def compose_down(self, orchestrator: SimpleOrchestrator) -> None:
        """Stop and remove all services.

        Args:
            orchestrator: Service orchestrator.
        """
        for service_name in self.services:
            try:
                orchestrator.remove_service(service_name)
            except Exception:
                pass

    def compose_scale(self, orchestrator: SimpleOrchestrator, scale_config: dict[str, int]) -> None:
        """Scale services.

        Args:
            orchestrator: Service orchestrator.
            scale_config: Mapping of service name to replica count.

        Raises:
            InvalidConfiguration: If scaling fails.
        """
        for service_name, replicas in scale_config.items():
            if service_name in self.services:
                orchestrator.scale_service(service_name, replicas)

    @staticmethod
    def _interpolate_env(env: dict[str, str]) -> dict[str, str]:
        """Interpolate environment variables.

        Args:
            env: Environment variables.

        Returns:
            Interpolated environment variables.
        """
        import os

        interpolated = {}
        for key, value in env.items():
            if isinstance(value, str):
                # Replace ${VAR} with environment variable
                for env_var in os.environ:
                    value = value.replace(f"${{{env_var}}}", os.environ[env_var])
                    value = value.replace(f"${env_var}", os.environ.get(env_var, ""))
            interpolated[key] = value

        return interpolated

    @staticmethod
    def _parse_memory(mem_str: str) -> int:
        """Parse memory string to MB.

        Args:
            mem_str: Memory string (e.g., "512m", "1g").

        Returns:
            Memory in MB.
        """
        mem_str = mem_str.lower().strip()

        multipliers = {
            "b": 1 / (1024 * 1024),
            "k": 1 / 1024,
            "m": 1,
            "g": 1024,
            "t": 1024 * 1024,
        }

        for suffix, multiplier in multipliers.items():
            if mem_str.endswith(suffix):
                return int(float(mem_str[:-1]) * multiplier)

        return int(float(mem_str) / (1024 * 1024))

    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """Parse duration string to seconds.

        Args:
            duration_str: Duration string (e.g., "30s", "2m").

        Returns:
            Duration in seconds.
        """
        duration_str = duration_str.lower().strip()

        multipliers = {
            "s": 1,
            "m": 60,
            "h": 3600,
        }

        for suffix, multiplier in multipliers.items():
            if duration_str.endswith(suffix):
                return int(float(duration_str[:-1]) * multiplier)

        return int(float(duration_str))
