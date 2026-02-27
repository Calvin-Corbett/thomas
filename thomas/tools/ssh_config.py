"""SSH config parser for resolving host aliases and connection parameters."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class SSHConfig:
    """Parser for ~/.ssh/config files."""

    def __init__(self, config_path: str | None = None):
        """Initialize SSH config parser.

        Args:
            config_path: Path to SSH config file. Defaults to ~/.ssh/config
        """
        if config_path is None:
            config_path = os.path.expanduser("~/.ssh/config")
        self.config_path = Path(config_path)
        self._hosts: dict[str, dict[str, Any]] = {}
        self._parse()

    def _parse(self) -> None:
        """Parse SSH config file."""
        if not self.config_path.exists():
            return

        current_host = None
        with open(self.config_path) as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue

                # Parse key-value pairs
                parts = line.split(None, 1)
                if not parts:
                    continue

                key = parts[0].lower()
                value = parts[1] if len(parts) > 1 else ""

                if key == "host":
                    current_host = value
                    if current_host not in self._hosts:
                        self._hosts[current_host] = {}
                elif current_host and value:
                    self._hosts[current_host][key] = value

    def get_host_config(self, host: str) -> dict[str, str]:
        """Get configuration for a specific host.

        Supports wildcards (Host *) and exact matches.
        Exact matches take precedence over wildcards.

        Args:
            host: Hostname or alias to look up

        Returns:
            Dictionary of resolved configuration parameters
        """
        config = {}

        # First apply wildcard config if it exists
        if "*" in self._hosts:
            config.update(self._hosts["*"])

        # Then apply host-specific config (overrides wildcards)
        if host in self._hosts:
            config.update(self._hosts[host])

        return config

    def resolve_connection_params(
        self,
        host: str,
        port: int | None = None,
        username: str | None = None,
        key_path: str | None = None,
        key_passphrase: str | None = None,
    ) -> dict[str, Any]:
        """Resolve SSH connection parameters from config.

        Merges provided parameters with SSH config file settings.
        Explicit parameters take precedence over config file values.

        Args:
            host: Hostname or SSH config alias
            port: SSH port (optional, overrides config)
            username: Username (optional, overrides config)
            key_path: Path to private key (optional, overrides config)
            key_passphrase: Key passphrase (optional)

        Returns:
            Dictionary with resolved connection parameters:
            - host: Actual hostname to connect to
            - port: SSH port
            - username: Username
            - key_path: Path to private key (if configured)
            - key_passphrase: Key passphrase (if provided)
            - proxy_jump: Bastion host configuration (if configured)
        """
        config = self.get_host_config(host)

        # Start with defaults
        result = {
            "host": config.get("hostname", host),
            "port": port or int(config.get("port", 22)),
            "username": username or config.get("user", "root"),
        }

        # Add optional parameters
        if key_path:
            result["key_path"] = key_path
        elif "identityfile" in config:
            # Expand ~ in identity file path
            identity = config["identityfile"]
            result["key_path"] = os.path.expanduser(identity)

        if key_passphrase:
            result["key_passphrase"] = key_passphrase

        # Handle ProxyJump for bastion hosts
        if "proxyjump" in config:
            proxy_jump = config["proxyjump"]
            result["proxy_jump"] = self._parse_proxy_jump(proxy_jump)

        # Additional config options
        if "compression" in config:
            result["compression"] = config["compression"].lower() == "yes"

        if "serveralivecountmax" in config:
            result["server_alive_count_max"] = int(config["serveralivecountmax"])

        if "serveraliveinterval" in config:
            result["server_alive_interval"] = int(config["serveraliveinterval"])

        if "connecttimeout" in config:
            result["timeout"] = int(config["connecttimeout"])

        return result

    def _parse_proxy_jump(self, proxy_spec: str) -> dict[str, Any]:
        """Parse ProxyJump specification.

        Supports formats like:
        - bastion
        - bastion:2222
        - user@bastion
        - user@bastion:2222

        Args:
            proxy_spec: ProxyJump specification string

        Returns:
            Dictionary with proxy host configuration
        """
        # Handle user@host:port format
        if "@" in proxy_spec:
            user_part, host_part = proxy_spec.rsplit("@", 1)
        else:
            user_part = None
            host_part = proxy_spec

        if ":" in host_part:
            host, port_str = host_part.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                host = host_part
                port = 22
        else:
            host = host_part
            port = 22

        result = {
            "host": host,
            "port": port,
        }

        if user_part:
            result["username"] = user_part

        return result

    def list_hosts(self) -> list[str]:
        """List all configured hosts (excluding wildcards).

        Returns:
            List of configured host aliases/names
        """
        return sorted([h for h in self._hosts.keys() if h != "*"])

    def has_host(self, host: str) -> bool:
        """Check if host is configured.

        Args:
            host: Hostname or alias

        Returns:
            True if host has configuration
        """
        return host in self._hosts

    def __repr__(self) -> str:
        return f"SSHConfig({self.config_path})"


def get_ssh_config(
    host: str,
    port: int | None = None,
    username: str | None = None,
    key_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Convenience function to resolve SSH config for a host.

    Args:
        host: Hostname or alias
        port: SSH port (optional, overrides config)
        username: Username (optional, overrides config)
        key_path: Path to private key (optional, overrides config)
        config_path: Path to SSH config file (optional)

    Returns:
        Dictionary with resolved connection parameters
    """
    ssh_config = SSHConfig(config_path)
    return ssh_config.resolve_connection_params(
        host=host,
        port=port,
        username=username,
        key_path=key_path,
    )


def resolve_proxy_chain(
    host: str,
    config_path: str | None = None,
) -> list[dict[str, Any]]:
    """Resolve a chain of proxy jumps from host to final destination.

    This follows the ProxyJump chain to build a list of all hops
    needed to reach the final host.

    Args:
        host: Final destination hostname
        config_path: Path to SSH config file (optional)

    Returns:
        List of host configurations in order (proxy hosts first, destination last)
    """
    ssh_config = SSHConfig(config_path)
    chain = []
    current = host
    visited = set()

    while current:
        if current in visited:
            break  # Prevent infinite loops
        visited.add(current)

        config = ssh_config.resolve_connection_params(current)
        chain.append(config)

        # Move to next proxy if configured
        if "proxy_jump" in config:
            current = config["proxy_jump"].get("host")
        else:
            current = None

    # Reverse to put proxies first
    chain.reverse()
    return chain
