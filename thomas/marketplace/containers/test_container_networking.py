"""Tests for container networking."""

import pytest

from thomas.marketplace.containers._exceptions import InvalidConfiguration, NetworkNotFound
from thomas.marketplace.containers._types import Container, ContainerStatus, Image
from thomas.marketplace.containers.networking import ContainerNetworking


@pytest.fixture
def networking():
    """Create container networking instance."""
    return ContainerNetworking()


@pytest.fixture
def test_container():
    """Create a test container."""
    return Container(
        id="test123",
        name="test-container",
        image=Image(name="test"),
        status=ContainerStatus.RUNNING,
    )


class TestNetworkCreation:
    """Tests for network creation."""

    def test_create_bridge_network(self, networking):
        """Test creating a bridge network."""
        network = networking.create_network(
            "mynet",
            driver="bridge",
            subnet="172.18.0.0/16",
        )

        assert network.name == "mynet"
        assert network.driver == "bridge"
        assert network.subnet == "172.18.0.0/16"

    def test_create_host_network(self, networking):
        """Test that host network exists."""
        network = networking.get_network("host")
        assert network.name == "host"
        assert network.driver == "host"

    def test_create_none_network(self, networking):
        """Test that none network exists."""
        network = networking.get_network("none")
        assert network.name == "none"
        assert network.driver == "none"

    def test_create_duplicate_network(self, networking):
        """Test that duplicate network names are rejected."""
        networking.create_network("mynet")

        with pytest.raises(InvalidConfiguration):
            networking.create_network("mynet")

    def test_create_invalid_driver(self, networking):
        """Test creating network with invalid driver."""
        with pytest.raises(InvalidConfiguration):
            networking.create_network("mynet", driver="invalid")


class TestContainerConnection:
    """Tests for connecting containers to networks."""

    def test_connect_to_bridge_network(self, networking, test_container):
        """Test connecting container to bridge network."""
        ip = networking.connect_container(test_container, "bridge")

        assert ip
        assert test_container.ip_address == ip

    def test_connect_to_host_network(self, networking, test_container):
        """Test connecting container to host network."""
        ip = networking.connect_container(test_container, "host")

        assert ip == "127.0.0.1"

    def test_connect_to_none_network(self, networking, test_container):
        """Test connecting container to none network."""
        ip = networking.connect_container(test_container, "none")

        assert ip == ""

    def test_connect_nonexistent_network(self, networking, test_container):
        """Test connecting to nonexistent network fails."""
        with pytest.raises(NetworkNotFound):
            networking.connect_container(test_container, "nonexistent")

    def test_static_ip_assignment(self, networking, test_container):
        """Test static IP assignment."""
        ip = networking.connect_container(
            test_container,
            "bridge",
            ip_address="172.17.0.100",
        )

        assert ip == "172.17.0.100"

    def test_multiple_connections(self, networking, test_container):
        """Test connecting container to multiple networks."""
        networking.create_network("net1")
        networking.create_network("net2")

        ip1 = networking.connect_container(test_container, "net1")
        assert ip1

        # Container should maintain reference to network_id
        assert test_container.network_id == "net1"


class TestNetworkDisconnection:
    """Tests for disconnecting containers."""

    def test_disconnect_container(self, networking, test_container):
        """Test disconnecting container from network."""
        networking.connect_container(test_container, "bridge")
        networking.disconnect_container(test_container.id, "bridge")

        networks = networking.get_container_networks(test_container.id)
        assert "bridge" not in networks


class TestDNSResolution:
    """Tests for DNS resolution."""

    def test_resolve_hostname(self, networking, test_container):
        """Test DNS resolution within network."""
        networking.connect_container(test_container, "bridge")

        resolved_ip = networking.resolve_hostname(test_container.hostname, "bridge")

        assert resolved_ip == test_container.ip_address

    def test_resolve_nonexistent_hostname(self, networking):
        """Test resolving nonexistent hostname."""
        resolved_ip = networking.resolve_hostname("nonexistent", "bridge")

        assert resolved_ip is None

    def test_dns_isolation_between_networks(self, networking, test_container):
        """Test DNS records are isolated between networks."""
        networking.create_network("net1")
        networking.create_network("net2")

        networking.connect_container(test_container, "net1")

        resolved = networking.resolve_hostname(test_container.hostname, "net2")

        assert resolved is None


class TestPortPublishing:
    """Tests for port publishing."""

    def test_publish_port(self, networking, test_container):
        """Test publishing a port."""
        from thomas.marketplace.containers._types import Port

        port = Port(container_port=8080, host_port=80)

        host_addr, host_port = networking.publish_port(
            test_container.id,
            port,
            "bridge",
        )

        assert host_addr == "0.0.0.0"
        assert host_port == 80

    def test_auto_assign_host_port(self, networking, test_container):
        """Test auto-assigning host port."""
        from thomas.marketplace.containers._types import Port

        port = Port(container_port=8080)

        host_addr, host_port = networking.publish_port(
            test_container.id,
            port,
            "bridge",
        )

        assert host_addr == "0.0.0.0"
        assert host_port >= 32768


class TestNetworkListing:
    """Tests for listing networks."""

    def test_list_networks(self, networking):
        """Test listing all networks."""
        networking.create_network("mynet1")
        networking.create_network("mynet2")

        networks = networking.list_networks()

        names = [n.name for n in networks]
        assert "mynet1" in names
        assert "mynet2" in names

    def test_list_networks_with_filter(self, networking):
        """Test listing networks with name filter."""
        networking.create_network("mynet1")
        networking.create_network("mynet2")
        networking.create_network("appnet")

        networks = networking.list_networks(name_filter="mynet")

        assert len(networks) == 2

    def test_get_network(self, networking):
        """Test getting network by name."""
        networking.create_network("mynet")
        network = networking.get_network("mynet")

        assert network.name == "mynet"

    def test_get_nonexistent_network(self, networking):
        """Test getting nonexistent network fails."""
        with pytest.raises(NetworkNotFound):
            networking.get_network("nonexistent")


class TestNetworkRemoval:
    """Tests for removing networks."""

    def test_remove_network(self, networking):
        """Test removing an empty network."""
        networking.create_network("mynet")
        networking.remove_network("mynet")

        with pytest.raises(NetworkNotFound):
            networking.get_network("mynet")

    def test_remove_network_with_containers(self, networking, test_container):
        """Test that removing network with containers fails."""
        networking.create_network("mynet")
        networking.connect_container(test_container, "mynet")

        with pytest.raises(InvalidConfiguration):
            networking.remove_network("mynet")

    def test_remove_nonexistent_network(self, networking):
        """Test removing nonexistent network fails."""
        with pytest.raises(NetworkNotFound):
            networking.remove_network("nonexistent")


class TestNetworkInspection:
    """Tests for inspecting networks."""

    def test_inspect_network(self, networking, test_container):
        """Test inspecting network details."""
        networking.connect_container(test_container, "bridge")

        info = networking.inspect_network("bridge")

        assert info["name"] == "bridge"
        assert info["driver"] == "bridge"
        assert test_container.id in info["containers"]

    def test_get_container_networks(self, networking, test_container):
        """Test getting networks for a container."""
        networking.create_network("net1")
        networking.create_network("net2")

        networking.connect_container(test_container, "net1")
        networking.connect_container(test_container, "net2")

        networks = networking.get_container_networks(test_container.id)

        assert "net1" in networks
        assert "net2" in networks
