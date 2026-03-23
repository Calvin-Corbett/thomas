"""Tests for container orchestration."""

import pytest

from thomas.marketplace.containers._exceptions import InvalidConfiguration
from thomas.marketplace.containers._types import Image, Port
from thomas.marketplace.containers.networking import ContainerNetworking
from thomas.marketplace.containers.orchestrator import ServiceDefinition, SimpleOrchestrator
from thomas.marketplace.containers.runtime import ContainerRuntime
from thomas.marketplace.containers.volumes import VolumeManager


@pytest.fixture
def orchestrator():
    """Create orchestrator with dependencies."""
    runtime = ContainerRuntime()
    networking = ContainerNetworking()
    volumes = VolumeManager()
    return SimpleOrchestrator(runtime, networking, volumes)


@pytest.fixture
def test_image():
    """Create test image."""
    return Image(name="nginx", tag="latest")


class TestServiceDefinition:
    """Tests for service definitions."""

    def test_create_service_definition(self, test_image):
        """Test creating service definition."""
        service = ServiceDefinition(
            name="web",
            image=test_image,
            replicas=3,
        )

        assert service.name == "web"
        assert service.replicas == 3

    def test_service_with_ports(self, test_image):
        """Test service with port mappings."""
        ports = [Port(container_port=80, host_port=8080)]
        service = ServiceDefinition(
            name="web",
            image=test_image,
            ports=ports,
        )

        assert len(service.ports) == 1

    def test_service_with_env(self, test_image):
        """Test service with environment."""
        env = {"LOG_LEVEL": "info"}
        service = ServiceDefinition(
            name="web",
            image=test_image,
            env=env,
        )

        assert service.env["LOG_LEVEL"] == "info"

    def test_invalid_replica_count(self, test_image):
        """Test that invalid replica count is rejected."""
        with pytest.raises(ValueError):
            ServiceDefinition(
                name="web",
                image=test_image,
                replicas=0,
            )

    def test_service_without_name(self, test_image):
        """Test that service without name is rejected."""
        with pytest.raises(ValueError):
            ServiceDefinition(
                name="",
                image=test_image,
            )


class TestServiceDeployment:
    """Tests for service deployment."""

    def test_deploy_service(self, orchestrator, test_image):
        """Test deploying a service."""
        service = ServiceDefinition(
            name="web",
            image=test_image,
            replicas=1,
        )

        orchestrator.deploy_service(service)

        services = orchestrator.list_services()
        assert len(services) == 1
        assert services[0]["name"] == "web"

    def test_deploy_multiple_services(self, orchestrator, test_image):
        """Test deploying multiple services."""
        service1 = ServiceDefinition(name="web", image=test_image, replicas=1)
        service2 = ServiceDefinition(name="db", image=test_image, replicas=1)

        orchestrator.deploy_service(service1)
        orchestrator.deploy_service(service2)

        services = orchestrator.list_services()
        assert len(services) == 2

    def test_deploy_duplicate_service(self, orchestrator, test_image):
        """Test that deploying duplicate service fails."""
        service = ServiceDefinition(name="web", image=test_image, replicas=1)
        orchestrator.deploy_service(service)

        with pytest.raises(InvalidConfiguration):
            orchestrator.deploy_service(service)

    def test_deploy_creates_replicas(self, orchestrator, test_image):
        """Test that deployment creates correct number of replicas."""
        service = ServiceDefinition(
            name="web",
            image=test_image,
            replicas=3,
        )

        orchestrator.deploy_service(service)

        info = orchestrator.get_service_info("web")
        assert info["desired_replicas"] == 3


class TestServiceScaling:
    """Tests for service scaling."""

    def test_scale_service_up(self, orchestrator, test_image):
        """Test scaling service up."""
        service = ServiceDefinition(name="web", image=test_image, replicas=1)
        orchestrator.deploy_service(service)

        orchestrator.scale_service("web", 3)

        info = orchestrator.get_service_info("web")
        assert info["replicas"] == 3

    def test_scale_service_down(self, orchestrator, test_image):
        """Test scaling service down."""
        service = ServiceDefinition(name="web", image=test_image, replicas=5)
        orchestrator.deploy_service(service)

        orchestrator.scale_service("web", 2)

        info = orchestrator.get_service_info("web")
        assert info["replicas"] == 2

    def test_scale_nonexistent_service(self, orchestrator):
        """Test scaling nonexistent service fails."""
        with pytest.raises(InvalidConfiguration):
            orchestrator.scale_service("nonexistent", 3)

    def test_scale_to_zero_fails(self, orchestrator, test_image):
        """Test that scaling to zero fails."""
        service = ServiceDefinition(name="web", image=test_image, replicas=1)
        orchestrator.deploy_service(service)

        with pytest.raises(InvalidConfiguration):
            orchestrator.scale_service("web", 0)


class TestServiceRemoval:
    """Tests for service removal."""

    def test_remove_service(self, orchestrator, test_image):
        """Test removing a service."""
        service = ServiceDefinition(name="web", image=test_image, replicas=1)
        orchestrator.deploy_service(service)

        orchestrator.remove_service("web")

        services = orchestrator.list_services()
        assert len(services) == 0

    def test_remove_nonexistent_service(self, orchestrator):
        """Test removing nonexistent service fails."""
        with pytest.raises(InvalidConfiguration):
            orchestrator.remove_service("nonexistent")


class TestRollingUpdate:
    """Tests for rolling updates."""

    def test_rolling_update(self, orchestrator, test_image):
        """Test rolling update of service."""
        service = ServiceDefinition(name="web", image=test_image, replicas=2)
        orchestrator.deploy_service(service)

        new_image = Image(name="nginx", tag="1.19")
        orchestrator.rolling_update("web", new_image)

        info = orchestrator.get_service_info("web")
        assert info["replicas"] == 2

    def test_rolling_update_nonexistent_service(self, orchestrator, test_image):
        """Test rolling update of nonexistent service fails."""
        image = Image(name="nginx", tag="latest")

        with pytest.raises(InvalidConfiguration):
            orchestrator.rolling_update("nonexistent", image)


class TestServiceDiscovery:
    """Tests for service discovery."""

    def test_service_discovery_endpoints(self, orchestrator, test_image):
        """Test getting service endpoints."""
        service = ServiceDefinition(name="web", image=test_image, replicas=3)
        orchestrator.deploy_service(service)

        endpoints = orchestrator.service_discovery("web")

        assert len(endpoints) > 0

    def test_service_discovery_nonexistent(self, orchestrator):
        """Test service discovery for nonexistent service fails."""
        with pytest.raises(InvalidConfiguration):
            orchestrator.service_discovery("nonexistent")


class TestLoadBalancing:
    """Tests for load balancing."""

    def test_load_balance_service(self, orchestrator, test_image):
        """Test load balancing across replicas."""
        service = ServiceDefinition(name="web", image=test_image, replicas=3)
        orchestrator.deploy_service(service)

        container_id = orchestrator.load_balance("web")

        assert container_id is not None

    def test_load_balance_empty_service(self, orchestrator):
        """Test load balancing on empty service."""
        with pytest.raises(InvalidConfiguration):
            orchestrator.load_balance("nonexistent")


class TestServiceInfo:
    """Tests for service information."""

    def test_get_service_info(self, orchestrator, test_image):
        """Test getting service information."""
        service = ServiceDefinition(name="web", image=test_image, replicas=2)
        orchestrator.deploy_service(service)

        info = orchestrator.get_service_info("web")

        assert info["name"] == "web"
        assert info["desired_replicas"] == 2
        assert "containers" in info

    def test_list_services(self, orchestrator, test_image):
        """Test listing all services."""
        service1 = ServiceDefinition(name="web", image=test_image)
        service2 = ServiceDefinition(name="api", image=test_image)

        orchestrator.deploy_service(service1)
        orchestrator.deploy_service(service2)

        services = orchestrator.list_services()

        assert len(services) == 2
        names = [s["name"] for s in services]
        assert "web" in names
        assert "api" in names
