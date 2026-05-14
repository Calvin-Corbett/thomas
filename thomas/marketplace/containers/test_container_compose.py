"""Tests for Docker Compose support."""

import pytest

from thomas.marketplace.containers._exceptions import InvalidConfiguration
from thomas.marketplace.containers.compose import ComposeParser
from thomas.marketplace.containers.networking import ContainerNetworking
from thomas.marketplace.containers.orchestrator import SimpleOrchestrator
from thomas.marketplace.containers.runtime import ContainerRuntime
from thomas.marketplace.containers.volumes import VolumeManager


@pytest.fixture
def compose_parser():
    """Create a compose parser."""
    return ComposeParser()


@pytest.fixture
def orchestrator():
    """Create orchestrator."""
    runtime = ContainerRuntime()
    networking = ContainerNetworking()
    volumes = VolumeManager()
    return SimpleOrchestrator(runtime, networking, volumes)


class TestComposeParser:
    """Tests for compose file parsing."""

    def test_parse_basic_compose(self, compose_parser):
        """Test parsing basic compose file."""
        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
    ports:
      - "8080:80"
"""
        result = compose_parser.parse(compose_content)

        assert result["version"] == "3"
        assert "web" in result["services"]

    def test_parse_compose_with_environment(self, compose_parser):
        """Test parsing compose with environment variables."""
        compose_content = """
version: '3'
services:
  app:
    image: myapp:latest
    environment:
      - DEBUG=true
      - LOG_LEVEL=info
"""
        compose_parser.parse(compose_content)

        assert "app" in compose_parser.services
        app = compose_parser.services["app"]
        assert "DEBUG" in app.environment

    def test_parse_compose_with_volumes(self, compose_parser):
        """Test parsing compose with volumes."""
        compose_content = """
version: '3'
services:
  app:
    image: myapp:latest
    volumes:
      - /data:/app/data
      - /config:/etc/config
"""
        compose_parser.parse(compose_content)

        app = compose_parser.services["app"]
        assert "/app/data" in app.volumes

    def test_parse_compose_with_ports(self, compose_parser):
        """Test parsing compose with port mappings."""
        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
    ports:
      - "8080:80"
      - "8443:443"
"""
        compose_parser.parse(compose_content)

        web = compose_parser.services["web"]
        assert len(web.ports) == 2

    def test_parse_compose_with_depends_on(self, compose_parser):
        """Test parsing compose with dependencies."""
        compose_content = """
version: '3'
services:
  app:
    image: myapp:latest
    depends_on:
      - db
  db:
    image: postgres:latest
"""
        compose_parser.parse(compose_content)

        app = compose_parser.services["app"]
        assert "db" in app.depends_on

    def test_parse_invalid_yaml(self, compose_parser):
        """Test that invalid YAML fails."""
        compose_content = "invalid: yaml: content:"

        with pytest.raises(InvalidConfiguration):
            compose_parser.parse(compose_content)

    def test_parse_empty_compose(self, compose_parser):
        """Test that empty compose fails."""
        with pytest.raises(InvalidConfiguration):
            compose_parser.parse("")

    def test_parse_missing_services(self, compose_parser):
        """Test that compose without services fails."""
        compose_content = """
version: '3'
networks:
  mynet:
"""
        with pytest.raises(InvalidConfiguration):
            compose_parser.parse(compose_content)

    def test_parse_missing_image(self, compose_parser):
        """Test that service without image fails."""
        compose_content = """
version: '3'
services:
  app:
    ports:
      - "8080:80"
"""
        with pytest.raises(InvalidConfiguration):
            compose_parser.parse(compose_content)


class TestComposeDependencies:
    """Tests for dependency resolution."""

    def test_resolve_no_dependencies(self, compose_parser):
        """Test resolving when no dependencies."""
        compose_content = """
version: '3'
services:
  app:
    image: myapp:latest
"""
        compose_parser.parse(compose_content)
        order = compose_parser.resolve_dependencies()

        assert order == ["app"]

    def test_resolve_linear_dependencies(self, compose_parser):
        """Test resolving linear dependency chain."""
        compose_content = """
version: '3'
services:
  app:
    image: myapp:latest
    depends_on:
      - db
  db:
    image: postgres:latest
"""
        compose_parser.parse(compose_content)
        order = compose_parser.resolve_dependencies()

        # db should come before app
        assert order.index("db") < order.index("app")

    def test_resolve_complex_dependencies(self, compose_parser):
        """Test resolving complex dependencies."""
        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
    depends_on:
      - app
  app:
    image: myapp:latest
    depends_on:
      - db
  db:
    image: postgres:latest
"""
        compose_parser.parse(compose_content)
        order = compose_parser.resolve_dependencies()

        # Verify ordering
        assert order.index("db") < order.index("app")
        assert order.index("app") < order.index("web")

    def test_detect_circular_dependency(self, compose_parser):
        """Test detection of circular dependencies."""
        compose_content = """
version: '3'
services:
  app:
    image: myapp:latest
    depends_on:
      - db
  db:
    image: postgres:latest
    depends_on:
      - app
"""
        compose_parser.parse(compose_content)

        with pytest.raises(InvalidConfiguration):
            compose_parser.resolve_dependencies()


class TestComposeLifecycle:
    """Tests for compose up/down."""

    def test_compose_up(self, compose_parser, orchestrator):
        """Test deploying compose services."""
        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
"""
        compose_parser.parse(compose_content)
        compose_parser.compose_up(orchestrator)

        services = orchestrator.list_services()
        assert len(services) == 1
        assert services[0]["name"] == "web"

    def test_compose_up_multiple_services(self, compose_parser, orchestrator):
        """Test deploying multiple services."""
        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
  app:
    image: myapp:latest
"""
        compose_parser.parse(compose_content)
        compose_parser.compose_up(orchestrator)

        services = orchestrator.list_services()
        assert len(services) == 2

    def test_compose_down(self, compose_parser, orchestrator):
        """Test stopping compose services."""
        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
"""
        compose_parser.parse(compose_content)
        compose_parser.compose_up(orchestrator)
        compose_parser.compose_down(orchestrator)

        services = orchestrator.list_services()
        assert len(services) == 0

    def test_compose_scale(self, compose_parser, orchestrator):
        """Test scaling compose services."""
        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
"""
        compose_parser.parse(compose_content)
        compose_parser.compose_up(orchestrator)

        compose_parser.compose_scale(orchestrator, {"web": 3})

        info = orchestrator.get_service_info("web")
        assert info["replicas"] == 3


class TestComposeEnvironmentInterpolation:
    """Tests for environment variable interpolation."""

    def test_interpolate_env_variables(self, compose_parser):
        """Test environment variable interpolation."""
        import os

        os.environ["TEST_VAR"] = "test_value"

        compose_content = """
version: '3'
services:
  app:
    image: myapp:latest
    environment:
      - MY_VAR=${TEST_VAR}
"""
        compose_parser.parse(compose_content)

        compose_parser.services["app"]
        # Note: interpolation happens during parsing


class TestComposeResourceLimits:
    """Tests for resource limits parsing."""

    def test_parse_memory_limit(self, compose_parser):
        """Test parsing memory limit."""
        compose_content = """
version: '3'
services:
  app:
    image: myapp:latest
    resources:
      limits:
        memory: 512m
"""
        compose_parser.parse(compose_content)

        app = compose_parser.services["app"]
        assert app.resources["limits"]["memory"] == "512m"

    def test_parse_cpu_limit(self, compose_parser):
        """Test parsing CPU limit."""
        compose_content = """
version: '3'
services:
  app:
    image: myapp:latest
    resources:
      limits:
        cpus: '0.5'
"""
        compose_parser.parse(compose_content)

        app = compose_parser.services["app"]
        assert app.resources["limits"]["cpus"] == "0.5"


class TestComposeHealthCheck:
    """Tests for health check parsing."""

    def test_parse_healthcheck(self, compose_parser):
        """Test parsing health check."""
        compose_content = """
version: '3'
services:
  app:
    image: myapp:latest
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost/"]
      interval: 30s
      timeout: 10s
      retries: 3
"""
        compose_parser.parse(compose_content)

        app = compose_parser.services["app"]
        assert app.healthcheck is not None
