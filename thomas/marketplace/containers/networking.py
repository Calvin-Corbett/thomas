"""Container networking management."""

import ipaddress
from dataclasses import dataclass

from thomas.marketplace.containers._exceptions import InvalidConfiguration, NetworkNotFound
from thomas.marketplace.containers._types import Container, Network, Port


@dataclass
class NetworkInterface:
    """Virtual network interface."""

    name: str
    ip_address: str
    mac_address: str
    container_id: str | None = None


@dataclass
class DNSRecord:
    """DNS record."""

    hostname: str
    ip_address: str
    container_id: str


class ContainerNetworking:
    """Manages container networking."""

    def __init__(self) -> None:
        """Initialize container networking."""
        self._networks: dict[str, Network] = {}
        self._interfaces: dict[str, list[NetworkInterface]] = {}
        self._dns_records: dict[str, list[DNSRecord]] = {}
        self._port_mappings: dict[str, list[tuple[Port, str]]] = {}
        self._next_ip_index: dict[str, int] = {}

        # Create default networks
        self.create_network(
            "bridge",
            driver="bridge",
            subnet="172.17.0.0/16",
            gateway="172.17.0.1",
        )
        self.create_network("host", driver="host")
        self.create_network("none", driver="none")

    def create_network(
        self,
        name: str,
        driver: str = "bridge",
        subnet: str | None = None,
        gateway: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> Network:
        """Create a network.

        Args:
            name: Network name.
            driver: Network driver (bridge, host, none, overlay).
            subnet: Network subnet.
            gateway: Network gateway.
            labels: Network labels.

        Returns:
            Created network.

        Raises:
            InvalidConfiguration: If network already exists.
        """
        if name in self._networks:
            raise InvalidConfiguration(f"Network already exists: {name}")

        network = Network(
            name=name,
            driver=driver,
            subnet=subnet,
            gateway=gateway,
            labels=labels or {},
        )

        self._networks[name] = network
        self._interfaces[name] = []
        self._dns_records[name] = []
        self._next_ip_index[name] = 2

        return network

    def connect_container(
        self,
        container: Container,
        network_name: str,
        ip_address: str | None = None,
    ) -> str:
        """Connect container to network.

        Args:
            container: Container to connect.
            network_name: Target network name.
            ip_address: Static IP address (optional).

        Returns:
            Assigned IP address.

        Raises:
            NetworkNotFound: If network not found.
        """
        if network_name not in self._networks:
            raise NetworkNotFound(network_name)

        network = self._networks[network_name]

        if network.driver == "host":
            ip = "127.0.0.1"
        elif network.driver == "none":
            ip = ""
        else:
            if ip_address is None:
                # Auto-assign IP from subnet
                if network.subnet:
                    ip = self._allocate_ip(network.subnet, network_name)
                else:
                    ip = f"172.17.0.{2 + self._next_ip_index[network_name]}"
                    self._next_ip_index[network_name] += 1
            else:
                ip = ip_address

        # Create network interface
        mac = self._generate_mac()
        interface = NetworkInterface(
            name=f"eth{len(self._interfaces[network_name])}",
            ip_address=ip,
            mac_address=mac,
            container_id=container.id,
        )

        self._interfaces[network_name].append(interface)
        container.ip_address = ip
        container.network_id = network_name

        # Register DNS record
        if container.hostname:
            self._register_dns(network_name, container.hostname, ip, container.id)

        return ip

    def disconnect_container(self, container_id: str, network_name: str) -> None:
        """Disconnect container from network.

        Args:
            container_id: Container ID.
            network_name: Network name.

        Raises:
            NetworkNotFound: If network not found.
        """
        if network_name not in self._networks:
            raise NetworkNotFound(network_name)

        self._interfaces[network_name] = [i for i in self._interfaces[network_name] if i.container_id != container_id]

        self._dns_records[network_name] = [r for r in self._dns_records[network_name] if r.container_id != container_id]

    def publish_port(self, container_id: str, port: Port, network_name: str) -> tuple[str, int]:
        """Publish a container port to the host.

        Args:
            container_id: Container ID.
            port: Port mapping.
            network_name: Network name.

        Returns:
            Tuple of (host_address, host_port).
        """
        if network_name not in self._port_mappings:
            self._port_mappings[network_name] = []

        if port.host_port is None:
            port.host_port = 32768 + len(self._port_mappings[network_name])

        self._port_mappings[network_name].append((port, container_id))

        return ("0.0.0.0", port.host_port)

    def resolve_hostname(self, hostname: str, network_name: str) -> str | None:
        """Resolve hostname within network.

        Args:
            hostname: Hostname to resolve.
            network_name: Network name.

        Returns:
            IP address, or None if not found.
        """
        if network_name not in self._dns_records:
            return None

        for record in self._dns_records[network_name]:
            if record.hostname == hostname:
                return record.ip_address

        return None

    def list_networks(self, name_filter: str | None = None) -> list[Network]:
        """List networks.

        Args:
            name_filter: Filter by name.

        Returns:
            List of networks.
        """
        networks = list(self._networks.values())

        if name_filter:
            networks = [n for n in networks if name_filter in n.name]

        return sorted(networks, key=lambda n: n.created_at, reverse=True)

    def get_network(self, name: str) -> Network:
        """Get network by name.

        Args:
            name: Network name.

        Returns:
            Network.

        Raises:
            NetworkNotFound: If network not found.
        """
        if name not in self._networks:
            raise NetworkNotFound(name)

        return self._networks[name]

    def remove_network(self, name: str) -> None:
        """Remove a network.

        Args:
            name: Network name.

        Raises:
            NetworkNotFound: If network not found.
            InvalidConfiguration: If network has connected containers.
        """
        if name not in self._networks:
            raise NetworkNotFound(name)

        if name in self._interfaces and self._interfaces[name]:
            raise InvalidConfiguration(f"Network has connected containers: {name}")

        del self._networks[name]
        if name in self._interfaces:
            del self._interfaces[name]
        if name in self._dns_records:
            del self._dns_records[name]

    def inspect_network(self, name: str) -> dict:
        """Get detailed network information.

        Args:
            name: Network name.

        Returns:
            Network details dictionary.

        Raises:
            NetworkNotFound: If network not found.
        """
        network = self.get_network(name)
        containers = {}

        if name in self._interfaces:
            for interface in self._interfaces[name]:
                if interface.container_id:
                    containers[interface.container_id] = {
                        "ip_address": interface.ip_address,
                        "mac_address": interface.mac_address,
                    }

        return {
            "name": network.name,
            "driver": network.driver,
            "subnet": network.subnet,
            "gateway": network.gateway,
            "containers": containers,
            "created_at": network.created_at.isoformat(),
        }

    def get_container_networks(self, container_id: str) -> list[str]:
        """Get networks connected to container.

        Args:
            container_id: Container ID.

        Returns:
            List of network names.
        """
        networks = []
        for network_name, interfaces in self._interfaces.items():
            if any(i.container_id == container_id for i in interfaces):
                networks.append(network_name)
        return networks

    def _allocate_ip(self, subnet: str, network_name: str) -> str:
        """Allocate IP address from subnet.

        Args:
            subnet: Subnet in CIDR notation.
            network_name: Network name.

        Returns:
            Allocated IP address.
        """
        try:
            network = ipaddress.ip_network(subnet, strict=False)
            index = self._next_ip_index.get(network_name, 2)
            ip = network[index]
            self._next_ip_index[network_name] = index + 1
            return str(ip)
        except Exception:
            return f"172.17.0.{2 + self._next_ip_index.get(network_name, 0)}"

    @staticmethod
    def _generate_mac() -> str:
        """Generate a MAC address.

        Returns:
            MAC address string.
        """
        import random

        octets = [0x02] + [random.randint(0x00, 0xFF) for _ in range(5)]
        return ":".join(f"{octet:02x}" for octet in octets)

    def _register_dns(self, network_name: str, hostname: str, ip_address: str, container_id: str) -> None:
        """Register DNS record.

        Args:
            network_name: Network name.
            hostname: Hostname.
            ip_address: IP address.
            container_id: Container ID.
        """
        self._dns_records[network_name].append(
            DNSRecord(
                hostname=hostname,
                ip_address=ip_address,
                container_id=container_id,
            )
        )
