"""Fact gathering and management."""

import os
import platform
import socket
from datetime import datetime
from typing import Any

from thomas.config_mgmt._types import Fact, Host


class FactGatherer:
    """Gathers facts from hosts."""

    @staticmethod
    def gather_local_facts() -> dict[str, Any]:
        """Gather facts from local system.

        Returns:
            Dict[str, Any]: Gathered facts.
        """
        return {
            "ansible_system": platform.system(),
            "ansible_os_family": FactGatherer._get_os_family(),
            "ansible_distribution": platform.release(),
            "ansible_processor": platform.processor(),
            "ansible_hostname": socket.gethostname(),
            "ansible_fqdn": socket.getfqdn(),
            "ansible_python_version": platform.python_version(),
            "ansible_kernel": platform.release(),
            "ansible_architecture": platform.machine(),
            "ansible_userspace_architecture": platform.machine(),
            "ansible_userspace_bits": "64" if platform.machine().endswith("64") else "32",
        }

    @staticmethod
    def _get_os_family() -> str:
        """Get OS family.

        Returns:
            str: OS family.
        """
        system = platform.system()
        if system == "Linux":
            return "Debian" if os.path.exists("/etc/debian_version") else "RedHat"
        elif system == "Darwin":
            return "Darwin"
        elif system == "Windows":
            return "Windows"
        return "Unknown"

    @staticmethod
    def gather_host_facts(host: Host) -> dict[str, Fact]:
        """Gather facts for specific host.

        Args:
            host: Host to gather facts from.

        Returns:
            Dict[str, Fact]: Gathered facts.
        """
        facts_dict = FactGatherer.gather_local_facts()
        facts = {}

        for name, value in facts_dict.items():
            fact = Fact(
                name=name,
                value=value,
                host=host.hostname,
                timestamp=datetime.now(),
                cacheable=True,
            )
            facts[name] = fact

        return facts


class FactCache:
    """Caches gathered facts."""

    def __init__(self) -> None:
        """Initialize fact cache."""
        self.cache: dict[str, dict[str, Any]] = {}

    def set_fact(self, hostname: str, fact_name: str, value: Any) -> None:
        """Set fact in cache.

        Args:
            hostname: Hostname.
            fact_name: Fact name.
            value: Fact value.
        """
        if hostname not in self.cache:
            self.cache[hostname] = {}

        self.cache[hostname][fact_name] = value

    def get_fact(
        self,
        hostname: str,
        fact_name: str,
        default: Any = None,
    ) -> Any:
        """Get fact from cache.

        Args:
            hostname: Hostname.
            fact_name: Fact name.
            default: Default value.

        Returns:
            Any: Fact value or default.
        """
        if hostname not in self.cache:
            return default

        return self.cache[hostname].get(fact_name, default)

    def get_host_facts(self, hostname: str) -> dict[str, Any]:
        """Get all facts for host.

        Args:
            hostname: Hostname.

        Returns:
            Dict[str, Any]: All facts for host.
        """
        return self.cache.get(hostname, {}).copy()

    def set_host_facts(
        self,
        hostname: str,
        facts: dict[str, Any],
    ) -> None:
        """Set all facts for host.

        Args:
            hostname: Hostname.
            facts: Facts dictionary.
        """
        self.cache[hostname] = facts.copy()

    def clear_host_facts(self, hostname: str) -> None:
        """Clear facts for host.

        Args:
            hostname: Hostname.
        """
        if hostname in self.cache:
            del self.cache[hostname]

    def clear_all(self) -> None:
        """Clear all cached facts."""
        self.cache.clear()
