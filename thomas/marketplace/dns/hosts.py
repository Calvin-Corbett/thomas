"""
Hosts file parser: /etc/hosts format name and IP mapping.
"""

from ipaddress import IPv4Address, IPv6Address


class HostsFile:
    """Parser for /etc/hosts format files with bidirectional lookup."""

    def __init__(self) -> None:
        """Initialize hosts file."""
        self.name_to_ips: dict[str, list[str]] = {}
        self.ip_to_names: dict[str, list[str]] = {}

    def load(self, filepath: str) -> None:
        """Load hosts file.

        Args:
            filepath: Path to hosts file
        """
        with open(filepath) as f:
            self.parse(f.read())

    def parse(self, content: str) -> None:
        """Parse hosts file content.

        Args:
            content: Hosts file content
        """
        for line in content.split("\n"):
            # Remove comments
            line = line.split("#")[0].strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            ip = parts[0]
            names = parts[1:]

            # Validate IP
            try:
                IPv4Address(ip)
            except ValueError:
                try:
                    IPv6Address(ip)
                except ValueError:
                    continue

            # Add mappings
            for name in names:
                name = name.lower()

                if name not in self.name_to_ips:
                    self.name_to_ips[name] = []
                if ip not in self.name_to_ips[name]:
                    self.name_to_ips[name].append(ip)

                if ip not in self.ip_to_names:
                    self.ip_to_names[ip] = []
                if name not in self.ip_to_names[ip]:
                    self.ip_to_names[ip].append(name)

    def lookup(self, name: str) -> list[str]:
        """Look up IPs for name.

        Args:
            name: Host name

        Returns:
            List of IP addresses
        """
        return self.name_to_ips.get(name.lower(), [])

    def reverse_lookup(self, ip: str) -> list[str]:
        """Reverse look up names for IP.

        Args:
            ip: IP address

        Returns:
            List of host names
        """
        return self.ip_to_names.get(ip, [])

    def add_entry(self, ip: str, names: list[str]) -> None:
        """Add entry to hosts file.

        Args:
            ip: IP address
            names: List of host names
        """
        # Validate IP
        try:
            IPv4Address(ip)
        except ValueError:
            try:
                IPv6Address(ip)
            except ValueError:
                return

        for name in names:
            name = name.lower()

            if name not in self.name_to_ips:
                self.name_to_ips[name] = []
            if ip not in self.name_to_ips[name]:
                self.name_to_ips[name].append(ip)

            if ip not in self.ip_to_names:
                self.ip_to_names[ip] = []
            if name not in self.ip_to_names[ip]:
                self.ip_to_names[ip].append(name)

    def remove_entry(self, ip: str, name: str) -> bool:
        """Remove entry from hosts file.

        Args:
            ip: IP address
            name: Host name

        Returns:
            True if entry was removed
        """
        name = name.lower()

        removed = False

        if name in self.name_to_ips and ip in self.name_to_ips[name]:
            self.name_to_ips[name].remove(ip)
            if not self.name_to_ips[name]:
                del self.name_to_ips[name]
            removed = True

        if ip in self.ip_to_names and name in self.ip_to_names[ip]:
            self.ip_to_names[ip].remove(name)
            if not self.ip_to_names[ip]:
                del self.ip_to_names[ip]
            removed = True

        return removed

    def clear(self) -> None:
        """Clear all entries."""
        self.name_to_ips.clear()
        self.ip_to_names.clear()

    def to_string(self) -> str:
        """Convert to /etc/hosts format string.

        Returns:
            Hosts file format string
        """
        lines = []

        for ip, names in self.ip_to_names.items():
            if names:
                lines.append(f"{ip}\t{' '.join(sorted(names))}")

        return "\n".join(lines)
