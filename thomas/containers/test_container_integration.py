"""Integration tests for container runtime."""

import pytest

from thomas.containers._types import (
    HealthCheck,
    Image,
    Port,
    ResourceLimits,
)
from thomas.containers.cgroups import CGroupManager
from thomas.containers.compose import ComposeParser
from thomas.containers.health import HealthChecker
from thomas.containers.images import ImageStore
from thomas.containers.logs import LogDriver, LogLevel
from thomas.containers.networking import ContainerNetworking
from thomas.containers.orchestrator import ServiceDefinition, SimpleOrchestrator
from thomas.containers.registry import ContainerRegistry
from thomas.containers.runtime import ContainerRuntime
from thomas.containers.volumes import VolumeManager


@pytest.fixture
def runtime():
    """Container runtime."""
    return ContainerRuntime()


@pytest.fixture
def image_store():
    """Image store."""
    return ImageStore()


@pytest.fixture
def networking():
    """Container networking."""
    return ContainerNetworking()


@pytest.fixture
def volumes():
    """Volume manager."""
    return VolumeManager()


@pytest.fixture
def orchestrator(runtime, networking, volumes):
    """Service orchestrator."""
    return SimpleOrchestrator(runtime, networking, volumes)


@pytest.fixture
def registry():
    """Container registry."""
    return ContainerRegistry()


@pytest.fixture
def health_checker():
    """Health checker."""
    return HealthChecker()


@pytest.fixture
def log_driver():
    """Log driver."""
    return LogDriver()


@pytest.fixture
def cgroup_manager():
    """cgroup manager."""
    return CGroupManager()


class TestEndToEndContainerWorkflow:
    """Test complete container workflow."""

    def test_build_image_create_run_container(self, image_store, runtime, networking):
        """Test building image and running container."""
        # Build image
        dockerfile = """
FROM ubuntu:20.04
RUN apt-get update
ENV APP_NAME=myapp
CMD ["python", "app.py"]
"""
        image = image_store.build_from_dockerfile(
            dockerfile,
            "myapp",
            tag="1.0",
        )

        # Create container
        container = runtime.create_container(
            image=image,
            name="myapp-1",
            ports=[Port(container_port=8080, host_port=8080)],
        )

        # Connect to network
        ip = networking.connect_container(container, "bridge")

        # Start container
        started = runtime.start_container(container.id)

        assert started.status.value == "running"
        assert container.ip_address is not None

    def test_multi_container_service(self, runtime, networking):
        """Test multi-container service setup."""
        # Create network
        networking.create_network("app-network", subnet="172.20.0.0/16")

        # Create and start containers
        containers = []
        for i in range(3):
            image = Image(name="nginx", tag="latest")
            container = runtime.create_container(
                image=image,
                name=f"nginx-{i}",
                ports=[Port(container_port=80, host_port=8080 + i)],
            )
            networking.connect_container(container, "app-network")
            runtime.start_container(container.id)
            containers.append(container)

        # Verify all running
        running = runtime.list_containers(all=False)
        assert len(running) == 3

        # Verify network connectivity
        for container in containers:
            network_info = networking.inspect_network("app-network")
            assert container.id in network_info["containers"]


class TestOrchestrationWorkflow:
    """Test service orchestration workflow."""

    def test_deploy_scale_update_service(self, orchestrator):
        """Test full service lifecycle."""
        image = Image(name="nginx", tag="latest")
        service = ServiceDefinition(
            name="web",
            image=image,
            replicas=1,
            ports=[Port(container_port=80, host_port=8080)],
        )

        # Deploy
        orchestrator.deploy_service(service)
        info = orchestrator.get_service_info("web")
        assert info["desired_replicas"] == 1

        # Scale up
        orchestrator.scale_service("web", 3)
        info = orchestrator.get_service_info("web")
        assert info["replicas"] == 3

        # Scale down
        orchestrator.scale_service("web", 1)
        info = orchestrator.get_service_info("web")
        assert info["replicas"] == 1

        # Update
        new_image = Image(name="nginx", tag="1.19")
        orchestrator.rolling_update("web", new_image)
        info = orchestrator.get_service_info("web")
        assert info["replicas"] == 1

        # Remove
        orchestrator.remove_service("web")
        services = orchestrator.list_services()
        assert len(services) == 0


class TestComposeWorkflow:
    """Test Docker Compose workflow."""

    def test_full_compose_deployment(self, orchestrator):
        """Test deploying complete compose stack."""
        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
    ports:
      - "8080:80"
    environment:
      - SERVER_NAME=example.com
  app:
    image: myapp:latest
    depends_on:
      - web
    environment:
      - UPSTREAM=web:80
"""
        parser = ComposeParser()
        parser.parse(compose_content)

        # Deploy
        parser.compose_up(orchestrator)

        # Verify services
        services = orchestrator.list_services()
        assert len(services) == 2

        # Scale
        parser.compose_scale(orchestrator, {"web": 2})
        web_info = orchestrator.get_service_info("web")
        assert web_info["replicas"] == 2

        # Cleanup
        parser.compose_down(orchestrator)
        assert len(orchestrator.list_services()) == 0


class TestRegistryWorkflow:
    """Test image registry operations."""

    def test_push_pull_images(self, image_store, registry):
        """Test pushing and pulling images."""
        # Create image
        image = image_store.create_image(
            "myapp",
            tag="1.0",
            env={"VERSION": "1.0"},
        )

        # Push to registry
        registry.push_image(image, "localhost:5000")

        # List repositories
        repos = registry.list_images()
        assert len(repos) > 0

        # Pull from registry
        pulled = registry.pull_image("localhost:5000", "myapp", "1.0")
        assert pulled.name == "myapp"


class TestHealthCheckingWorkflow:
    """Test health checking workflow."""

    def test_health_checks_with_container(self, runtime, health_checker):
        """Test health checking on container."""
        image = Image(name="myapp", tag="latest")
        container = runtime.create_container(
            image=image,
            name="myapp-1",
            health_check=HealthCheck(
                test=["curl", "http://localhost:8080"],
                interval_seconds=10,
                retries=3,
            ),
        )
        runtime.start_container(container.id)

        # Start health checks
        health_checker.start_health_checks(container)

        # Get status (won't be updated immediately in test)
        status = health_checker.get_health_status(container.id)
        assert status is not None

        # Stop checks
        health_checker.stop_health_checks(container.id)


class TestLoggingWorkflow:
    """Test container logging workflow."""

    def test_logging_and_log_analysis(self, runtime, log_driver):
        """Test logging and log analysis."""
        image = Image(name="myapp", tag="latest")
        container = runtime.create_container(
            image=image,
            name="myapp-1",
        )

        # Write logs
        log_driver.write_log(container.id, "Application started")
        log_driver.write_log(container.id, "Processing request", LogLevel.INFO)
        log_driver.write_log(container.id, "Connection timeout", LogLevel.WARN)
        log_driver.write_log(container.id, "Critical error", LogLevel.ERROR)

        # Read logs
        logs = log_driver.read_logs(container.id)
        assert len(logs) == 4

        # Filter by pattern
        warnings = log_driver.filter_logs(container.id, "Connection")
        assert len(warnings) == 1

        # Get statistics
        stats = log_driver.stats()
        assert stats["total_entries"] == 4


class TestResourceManagement:
    """Test resource management workflow."""

    def test_resource_limits_enforcement(self, runtime, cgroup_manager):
        """Test resource limits and enforcement."""
        limits = ResourceLimits(
            cpu_shares=2048,
            memory_mb=1024,
            pids_limit=256,
        )

        image = Image(name="myapp", tag="latest")
        container = runtime.create_container(
            image=image,
            name="myapp-1",
            resource_limits=limits,
        )

        # Create cgroup
        cgroup_manager.create_cgroup(
            container.id,
            cpu_shares=limits.cpu_shares,
            memory_mb=limits.memory_mb,
            pids_limit=limits.pids_limit,
        )

        # Update usage
        cgroup_manager.update_memory_usage(container.id, 512 * 1024 * 1024)
        cgroup_manager.update_pids_count(container.id, 50)

        # Get info
        info = cgroup_manager.get_cgroup_info(container.id)
        assert info["stats"]["memory"]["usage"] == 512 * 1024 * 1024
        assert info["stats"]["pids"]["current"] == 50

        # Check enforcement
        is_enforced = cgroup_manager.enforce_limits(container.id)
        assert not is_enforced


class TestVolumeManagement:
    """Test volume management workflow."""

    def test_volumes_and_mounts(self, runtime, volumes):
        """Test volume creation and mounting."""
        # Create volume
        volume = volumes.create_volume("app-data")

        # Create container
        image = Image(name="myapp", tag="latest")
        container = runtime.create_container(image=image, name="myapp-1")

        # Mount volume
        mount = volumes.mount_volume(
            volume.name,
            container.id,
            "/app/data",
        )

        # Inspect volume
        info = volumes.inspect_volume(volume.name)
        assert container.id in info["containers"]

        # Get container volumes
        container_volumes = volumes.get_container_volumes(container.id)
        assert len(container_volumes) == 1

    def test_bind_mounts(self, runtime, volumes):
        """Test bind mount workflow."""
        import tempfile

        # Create temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create bind mount
            image = Image(name="myapp", tag="latest")
            container = runtime.create_container(image=image, name="myapp-1")

            mount = volumes.bind_mount(
                tmpdir,
                container.id,
                "/app/data",
            )

            # Verify mount
            assert mount.container_path == "/app/data"
            assert mount.read_only is False


class TestNetworkingAdvanced:
    """Test advanced networking scenarios."""

    def test_multi_network_container(self, runtime, networking):
        """Test container on multiple networks."""
        # Create networks
        networking.create_network("frontend")
        networking.create_network("backend")

        image = Image(name="myapp", tag="latest")
        container = runtime.create_container(image=image, name="myapp-1")

        # Connect to multiple networks
        ip1 = networking.connect_container(container, "frontend")
        ip2 = networking.connect_container(container, "backend")

        # Verify connections
        networks = networking.get_container_networks(container.id)
        assert "frontend" in networks
        assert "backend" in networks

    def test_dns_service_discovery(self, runtime, networking):
        """Test DNS-based service discovery."""
        networking.create_network("app-network")

        image = Image(name="nginx", tag="latest")

        # Create multiple containers with same hostname
        containers = []
        for i in range(3):
            container = runtime.create_container(
                image=image,
                name=f"web-{i}",
            )
            networking.connect_container(container, "app-network")
            containers.append(container)

        # Verify DNS resolution
        for container in containers:
            resolved_ip = networking.resolve_hostname(
                container.hostname,
                "app-network",
            )
            assert resolved_ip == container.ip_address
