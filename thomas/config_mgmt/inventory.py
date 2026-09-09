"""Inventory management for hosts and groups."""

import json
import re
from fnmatch import fnmatch
from pathlib import Path
from re import Pattern
from typing import Any

from thomas.config_mgmt._exceptions import InventoryError, ValidationError
from thomas.config_mgmt._types import Connection, ConnectionType, Credential, Host, HostGroup, Inventory


class InventoryParser:
    """Parser for INI-style inventory files."""

    @staticmethod
    def parse(content: str) -> Inventory:
        """Parse INI-style inventory.

        Args:
            content: File content to parse.

        Returns:
            Inventory: Parsed inventory.

        Raises:
            InventoryError: If parsing fails.
        """
        inventory = Inventory(name="parsed_inventory")
        current_group: str | None = None
        lines = content.strip().split("\n")

        for line in lines:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            # Group header
            if line.startswith("[") and line.endswith("]"):
                current_group = line[1:-1]
                inventory.add_group(HostGroup(name=current_group))
                continue

            # Host definition
            if current_group:
                parts = line.split()
                if not parts:
                    continue

                hostname = parts[0]
                vars_dict = {}

                # Parse host variables
                for part in parts[1:]:
                    if "=" in part:
                        key, val = part.split("=", 1)
                        vars_dict[key] = val

                # Create host with basic connection
                cred = Credential(username="root")
                conn = Connection(
                    type=ConnectionType.SSH,
                    host=hostname,
                    port=22,
                    credential=cred,
                )

                host = Host(
                    hostname=hostname,
                    connection=conn,
                    variables=vars_dict,
                )
                host.add_group(current_group)

                inventory.add_host(host)
                group = inventory.get_group(current_group)
                if group:
                    group.add_host(hostname)

        return inventory


class InventoryManager:
    """Manages host inventory with static and dynamic sources."""

    def __init__(self) -> None:
        """Initialize inventory manager."""
        self.inventories: dict[str, Inventory] = {}
        self.hosts: dict[str, Host] = {}
        self.groups: dict[str, HostGroup] = {}
        self.host_patterns: dict[str, Pattern[str]] = {}
        self.dynamic_plugins: dict[str, Any] = {}

    def load_static_inventory(self, filepath: str) -> Inventory:
        """Load inventory from static INI file.

        Args:
            filepath: Path to inventory file.

        Returns:
            Inventory: Loaded inventory.

        Raises:
            InventoryError: If file cannot be read or parsed.
        """
        try:
            path = Path(filepath)
            if not path.exists():
                raise InventoryError(f"Inventory file not found: {filepath}")

            content = path.read_text()
            inventory = InventoryParser.parse(content)
            inventory.name = path.stem

            self.inventories[inventory.name] = inventory
            self._index_inventory(inventory)

            return inventory
        except Exception as e:
            raise InventoryError(f"Failed to load inventory: {e}")

    def load_dynamic_inventory(self, plugin_name: str, config: dict[str, Any]) -> Inventory:
        """Load inventory from dynamic plugin.

        Args:
            plugin_name: Plugin name (e.g., 'aws_ec2', 'azure_vm').
            config: Plugin configuration.

        Returns:
            Inventory: Loaded inventory.

        Raises:
            InventoryError: If plugin not available or fails.
        """
        if plugin_name not in self.dynamic_plugins:
            raise InventoryError(f"Dynamic plugin not found: {plugin_name}")

        try:
            plugin = self.dynamic_plugins[plugin_name]
            inventory = plugin.discover(config)
            self.inventories[plugin_name] = inventory
            self._index_inventory(inventory)
            return inventory
        except Exception as e:
            raise InventoryError(f"Dynamic inventory discovery failed: {e}")

    def register_dynamic_plugin(self, name: str, plugin: Any) -> None:
        """Register dynamic inventory plugin.

        Args:
            name: Plugin name.
            plugin: Plugin instance with discover() method.
        """
        self.dynamic_plugins[name] = plugin

    def _index_inventory(self, inventory: Inventory) -> None:
        """Index inventory for fast lookups.

        Args:
            inventory: Inventory to index.
        """
        for host in inventory.hosts.values():
            self.hosts[host.hostname] = host

        for group in inventory.groups.values():
            self.groups[group.name] = group

    def add_host(self, host: Host) -> None:
        """Add host to manager.

        Args:
            host: Host to add.
        """
        self.hosts[host.hostname] = host

    def add_group(self, group: HostGroup) -> None:
        """Add group to manager.

        Args:
            group: Group to add.
        """
        self.groups[group.name] = group

    def get_host(self, hostname: str) -> Host | None:
        """Get host by name.

        Args:
            hostname: Hostname.

        Returns:
            Optional[Host]: Host or None.
        """
        return self.hosts.get(hostname)

    def get_group(self, group_name: str) -> HostGroup | None:
        """Get group by name.

        Args:
            group_name: Group name.

        Returns:
            Optional[HostGroup]: Group or None.
        """
        return self.groups.get(group_name)

    def get_group_hosts(self, group_name: str, recursive: bool = False) -> list[Host]:
        """Get all hosts in group.

        Args:
            group_name: Group name.
            recursive: Include child groups.

        Returns:
            List[Host]: Hosts in group.
        """
        group = self.get_group(group_name)
        if not group:
            return []

        result = [self.hosts[h] for h in group.hosts if h in self.hosts]

        if recursive:
            for child_name in group.children:
                child_hosts = self.get_group_hosts(child_name, recursive=True)
                result.extend(child_hosts)

        return result

    def match_pattern(self, pattern: str) -> list[Host]:
        """Match hosts using glob or regex pattern.

        Args:
            pattern: Host pattern ('all', 'group_name', glob '*', or regex).

        Returns:
            List[Host]: Matching hosts.

        Raises:
            ValidationError: If pattern is invalid.
        """
        # Special case: all
        if pattern == "all":
            return list(self.hosts.values())

        # Group name
        if pattern in self.groups:
            return self.get_group_hosts(pattern, recursive=True)

        # Glob pattern
        if any(c in pattern for c in ["*", "?", "["]):
            result = []
            for hostname in self.hosts:
                if fnmatch(hostname, pattern):
                    result.append(self.hosts[hostname])
            return result

        # Regex pattern
        if pattern.startswith("~"):
            try:
                regex = re.compile(pattern[1:])
                result = []
                for hostname in self.hosts:
                    if regex.match(hostname):
                        result.append(self.hosts[hostname])
                return result
            except re.error as e:
                raise ValidationError(f"Invalid regex pattern: {e}")

        # Single host
        if pattern in self.hosts:
            return [self.hosts[pattern]]

        return []

    def match_patterns(self, patterns: list[str]) -> list[Host]:
        """Match multiple patterns.

        Args:
            patterns: List of patterns.

        Returns:
            List[Host]: Matching hosts (deduplicated).
        """
        seen: set[str] = set()
        result: list[Host] = []

        for pattern in patterns:
            for host in self.match_pattern(pattern):
                if host.hostname not in seen:
                    seen.add(host.hostname)
                    result.append(host)

        return result

    def set_host_variable(self, hostname: str, var_name: str, value: Any) -> None:
        """Set variable on host.

        Args:
            hostname: Hostname.
            var_name: Variable name.
            value: Variable value.

        Raises:
            InventoryError: If host not found.
        """
        host = self.get_host(hostname)
        if not host:
            raise InventoryError(f"Host not found: {hostname}")

        host.variables[var_name] = value

    def set_group_variable(self, group_name: str, var_name: str, value: Any) -> None:
        """Set variable on group.

        Args:
            group_name: Group name.
            var_name: Variable name.
            value: Variable value.

        Raises:
            InventoryError: If group not found.
        """
        group = self.get_group(group_name)
        if not group:
            raise InventoryError(f"Group not found: {group_name}")

        group.variables[var_name] = value

    def get_host_variables(self, hostname: str) -> dict[str, Any]:
        """Get all variables for host (merged with groups).

        Args:
            hostname: Hostname.

        Returns:
            Dict[str, Any]: Merged variables.

        Raises:
            InventoryError: If host not found.
        """
        host = self.get_host(hostname)
        if not host:
            raise InventoryError(f"Host not found: {hostname}")

        result = {}

        # Collect group variables (parent to child)
        for group_name in sorted(host.groups):
            group = self.get_group(group_name)
            if group:
                result.update(group.variables)

        # Host variables override group
        result.update(host.variables)

        return result

    def create_group_hierarchy(self, parent: str, children: list[str]) -> None:
        """Create parent-child relationship between groups.

        Args:
            parent: Parent group name.
            children: List of child group names.

        Raises:
            InventoryError: If groups not found.
        """
        parent_group = self.get_group(parent)
        if not parent_group:
            raise InventoryError(f"Parent group not found: {parent}")

        for child_name in children:
            child_group = self.get_group(child_name)
            if not child_group:
                raise InventoryError(f"Child group not found: {child_name}")

            parent_group.add_child_group(child_name)
            child_group.parents.append(parent)

    def validate_inventory(self) -> None:
        """Validate entire inventory.

        Raises:
            ValidationError: If inventory is invalid.
        """
        seen_hosts: set[str] = set()

        for hostname in self.hosts:
            if hostname in seen_hosts:
                raise ValidationError(f"Duplicate host: {hostname}")
            seen_hosts.add(hostname)

        for group in self.groups.values():
            for hostname in group.hosts:
                if hostname not in self.hosts:
                    raise ValidationError(f"Group '{group.name}' references unknown host: {hostname}")

            for child_name in group.children:
                if child_name not in self.groups:
                    raise ValidationError(f"Group '{group.name}' references unknown child group: {child_name}")

    def export_json(self) -> str:
        """Export inventory as JSON.

        Returns:
            str: JSON representation.
        """
        data = {
            "hosts": {
                hostname: {
                    "vars": host.variables,
                    "groups": list(host.groups),
                }
                for hostname, host in self.hosts.items()
            },
            "groups": {
                group_name: {
                    "hosts": list(group.hosts),
                    "vars": group.variables,
                    "children": group.children,
                }
                for group_name, group in self.groups.items()
            },
        }
        return json.dumps(data, indent=2)

    def merge_inventory(self, other: "InventoryManager") -> None:
        """Merge another inventory manager into this one.

        Args:
            other: Other inventory manager.
        """
        for hostname, host in other.hosts.items():
            if hostname in self.hosts:
                self.hosts[hostname].variables.update(host.variables)
            else:
                self.hosts[hostname] = host

        for group_name, group in other.groups.items():
            if group_name in self.groups:
                self.groups[group_name].hosts.update(group.hosts)
                self.groups[group_name].variables.update(group.variables)
            else:
                self.groups[group_name] = group
