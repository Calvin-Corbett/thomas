"""Tests for container runtime."""

import pytest

from thomas.containers._exceptions import ContainerNotFound, InvalidConfiguration
from thomas.containers._types import (
    ContainerStatus,
    Image,
    Port,
    ResourceLimits,
    RestartPolicy,
)
from thomas.containers.runtime import ContainerRuntime


@pytest.fixture
def runtime():
    """Create a container runtime instance."""
    return ContainerRuntime()


@pytest.fixture
def test_image():
    """Create a test image."""
    return Image(
        name="test",
        tag="latest",
        cmd=["python", "app.py"],
        env={"LOG_LEVEL": "INFO"},
    )


class TestContainerCreation:
    """Tests for container creation."""

    def test_create_container_basic(self, runtime, test_image):
        """Test basic container creation."""
        container = runtime.create_container(test_image, name="test-container")

        assert container.id
        assert container.name == "test-container"
        assert container.image == test_image
        assert container.status == ContainerStatus.CREATED

    def test_create_container_auto_name(self, runtime, test_image):
        """Test container creation with auto-generated name."""
        container = runtime.create_container(test_image)

        assert container.id
        assert container.name.startswith("container_")

    def test_create_container_with_ports(self, runtime, test_image):
        """Test container creation with port mappings."""
        ports = [Port(container_port=8080, host_port=80)]
        container = runtime.create_container(test_image, ports=ports)

        assert container.ports == ports

    def test_create_container_with_env(self, runtime, test_image):
        """Test container creation with environment variables."""
        env = {"APP_ENV": "production", "DEBUG": "false"}
        container = runtime.create_container(test_image, env=env)

        assert "APP_ENV" in container.env
        assert container.env["APP_ENV"] == "production"

    def test_create_container_with_resource_limits(self, runtime, test_image):
        """Test container creation with resource limits."""
        limits = ResourceLimits(cpu_shares=2048, memory_mb=1024, pids_limit=512)
        container = runtime.create_container(test_image, resource_limits=limits)

        assert container.resource_limits.cpu_shares == 2048
        assert container.resource_limits.memory_mb == 1024

    def test_create_duplicate_container_name(self, runtime, test_image):
        """Test that duplicate container names are rejected."""
        runtime.create_container(test_image, name="test")

        with pytest.raises(InvalidConfiguration):
            runtime.create_container(test_image, name="test")

    def test_create_container_invalid_network_mode(self, runtime, test_image):
        """Test creation with invalid network mode."""
        with pytest.raises(InvalidConfiguration):
            runtime.create_container(test_image, network_mode="invalid")


class TestContainerLifecycle:
    """Tests for container lifecycle management."""

    def test_start_container(self, runtime, test_image):
        """Test starting a container."""
        container = runtime.create_container(test_image)
        started = runtime.start_container(container.id)

        assert started.status == ContainerStatus.RUNNING
        assert started.pid is not None
        assert started.started_at is not None

    def test_start_already_running(self, runtime, test_image):
        """Test that starting an already running container fails."""
        container = runtime.create_container(test_image)
        runtime.start_container(container.id)

        with pytest.raises(Exception):
            runtime.start_container(container.id)

    def test_stop_container(self, runtime, test_image):
        """Test stopping a running container."""
        container = runtime.create_container(test_image)
        runtime.start_container(container.id)

        stopped = runtime.stop_container(container.id)

        assert stopped.status == ContainerStatus.STOPPED
        assert stopped.stopped_at is not None
        assert stopped.exit_code == 0

    def test_kill_container(self, runtime, test_image):
        """Test killing a container."""
        container = runtime.create_container(test_image)
        runtime.start_container(container.id)

        killed = runtime.kill_container(container.id)

        assert killed.status == ContainerStatus.EXITED
        assert killed.exit_code == 137

    def test_pause_resume_container(self, runtime, test_image):
        """Test pausing and resuming a container."""
        container = runtime.create_container(test_image)
        runtime.start_container(container.id)

        paused = runtime.pause_container(container.id)
        assert paused.status == ContainerStatus.PAUSED

        resumed = runtime.unpause_container(container.id)
        assert resumed.status == ContainerStatus.RUNNING

    def test_remove_container(self, runtime, test_image):
        """Test removing a container."""
        container = runtime.create_container(test_image)
        runtime.stop_container(container.id)

        runtime.remove_container(container.id)

        with pytest.raises(ContainerNotFound):
            runtime.get_container(container.id)

    def test_remove_running_container_fails(self, runtime, test_image):
        """Test that removing a running container fails without force."""
        container = runtime.create_container(test_image)
        runtime.start_container(container.id)

        with pytest.raises(Exception):
            runtime.remove_container(container.id, force=False)

    def test_remove_container_force(self, runtime, test_image):
        """Test force removing a container."""
        container = runtime.create_container(test_image)
        runtime.start_container(container.id)

        runtime.remove_container(container.id, force=True)

        with pytest.raises(ContainerNotFound):
            runtime.get_container(container.id)


class TestContainerListing:
    """Tests for container listing and retrieval."""

    def test_list_containers_empty(self, runtime):
        """Test listing when no containers exist."""
        containers = runtime.list_containers()
        assert containers == []

    def test_list_containers(self, runtime, test_image):
        """Test listing all containers."""
        c1 = runtime.create_container(test_image, name="c1")
        c2 = runtime.create_container(test_image, name="c2")

        containers = runtime.list_containers(all=True)

        assert len(containers) == 2
        assert c1.id in [c.id for c in containers]
        assert c2.id in [c.id for c in containers]

    def test_list_running_containers(self, runtime, test_image):
        """Test listing only running containers."""
        c1 = runtime.create_container(test_image, name="c1")
        c2 = runtime.create_container(test_image, name="c2")

        runtime.start_container(c1.id)

        containers = runtime.list_containers(all=False)

        assert len(containers) == 1
        assert containers[0].id == c1.id

    def test_get_container_by_id(self, runtime, test_image):
        """Test retrieving container by ID."""
        container = runtime.create_container(test_image)
        retrieved = runtime.get_container(container.id)

        assert retrieved.id == container.id

    def test_get_container_by_name(self, runtime, test_image):
        """Test retrieving container by name."""
        container = runtime.create_container(test_image, name="mycontainer")
        retrieved = runtime.get_container("mycontainer")

        assert retrieved.name == "mycontainer"

    def test_get_nonexistent_container(self, runtime):
        """Test that retrieving nonexistent container fails."""
        with pytest.raises(ContainerNotFound):
            runtime.get_container("nonexistent")


class TestContainerExec:
    """Tests for container exec."""

    def test_exec_in_running_container(self, runtime, test_image):
        """Test executing command in running container."""
        container = runtime.create_container(test_image)
        runtime.start_container(container.id)

        exit_code, stdout, stderr = runtime.container_exec(container.id, ["echo", "hello"])

        assert exit_code == 0
        assert "hello" in stdout

    def test_exec_in_stopped_container(self, runtime, test_image):
        """Test that exec in stopped container fails."""
        container = runtime.create_container(test_image)

        with pytest.raises(Exception):
            runtime.container_exec(container.id, ["echo", "hello"])


class TestContainerStats:
    """Tests for container statistics."""

    def test_stats_created_container(self, runtime, test_image):
        """Test stats for non-running container."""
        container = runtime.create_container(test_image)
        stats = runtime.container_stats(container.id)

        assert stats["cpu_percent"] == 0.0
        assert stats["memory_usage"] == 0

    def test_stats_running_container(self, runtime, test_image):
        """Test stats for running container."""
        container = runtime.create_container(test_image)
        runtime.start_container(container.id)

        stats = runtime.container_stats(container.id)

        assert "cpu_percent" in stats
        assert "memory_usage" in stats
        assert "memory_limit" in stats

    def test_stats_with_resource_limits(self, runtime, test_image):
        """Test stats respects resource limits."""
        limits = ResourceLimits(memory_mb=2048)
        container = runtime.create_container(test_image, resource_limits=limits)
        runtime.start_container(container.id)

        stats = runtime.container_stats(container.id)

        assert stats["memory_limit"] == 2048 * 1024 * 1024


class TestRestartPolicy:
    """Tests for container restart policy."""

    def test_restart_policy_no(self, runtime, test_image):
        """Test NO restart policy."""
        container = runtime.create_container(
            test_image,
            restart_policy=RestartPolicy.NO,
        )
        runtime.start_container(container.id)
        runtime.kill_container(container.id)

        result = runtime.handle_restart_policy(container.id)

        assert result is None

    def test_restart_policy_always(self, runtime, test_image):
        """Test ALWAYS restart policy."""
        container = runtime.create_container(
            test_image,
            restart_policy=RestartPolicy.ALWAYS,
        )
        runtime.start_container(container.id)
        runtime.kill_container(container.id)

        result = runtime.handle_restart_policy(container.id)

        assert result is not None
        assert result.status == ContainerStatus.RUNNING

    def test_restart_policy_on_failure(self, runtime, test_image):
        """Test ON_FAILURE restart policy."""
        container = runtime.create_container(
            test_image,
            restart_policy=RestartPolicy.ON_FAILURE,
        )
        runtime.start_container(container.id)
        runtime.kill_container(container.id)

        result = runtime.handle_restart_policy(container.id)

        assert result is not None
        assert result.status == ContainerStatus.RUNNING


class TestContainerLogs:
    """Tests for container logs."""

    def test_get_container_logs(self, runtime, test_image):
        """Test retrieving container logs."""
        container = runtime.create_container(test_image)
        container.logs.append("Log line 1")
        container.logs.append("Log line 2")

        logs = runtime.get_container_logs(container.id)

        assert len(logs) == 2

    def test_get_logs_tail(self, runtime, test_image):
        """Test getting last N log lines."""
        container = runtime.create_container(test_image)
        for i in range(10):
            container.logs.append(f"Log line {i}")

        logs = runtime.get_container_logs(container.id, tail=3)

        assert len(logs) == 3
