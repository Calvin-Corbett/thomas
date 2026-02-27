"""Tests for inventory management."""

import tempfile
from pathlib import Path

import pytest

from thomas.config_mgmt._exceptions import ValidationError
from thomas.config_mgmt._types import Connection, ConnectionType, Credential, Host, HostGroup
from thomas.config_mgmt.inventory import InventoryManager, InventoryParser


class TestInventoryParser:
    """Tests for inventory parsing."""

    def test_parse_ini_inventory(self) -> None:
        """Test parsing INI-style inventory."""
        content = """
[webservers]
web1 ansible_host=192.168.1.1
web2 ansible_host=192.168.1.2

[dbservers]
db1 ansible_host=192.168.2.1
"""
        inv = InventoryParser.parse(content)
        assert len(inv.hosts) == 3
        assert "web1" in inv.hosts
        assert "dbservers" in inv.groups

    def test_parse_with_comments(self) -> None:
        """Test parsing with comments."""
        content = """
# This is a comment
[webservers]
web1  # inline comment
web2
"""
        inv = InventoryParser.parse(content)
        assert len(inv.hosts) == 2

    def test_parse_host_variables(self) -> None:
        """Test parsing host variables."""
        content = """
[webservers]
web1 ansible_port=2222 app_port=8080
"""
        inv = InventoryParser.parse(content)
        host = inv.get_host("web1")
        assert host is not None
        assert host.variables.get("ansible_port") == "2222"


class TestInventoryManager:
    """Tests for inventory manager."""

    def test_add_host(self) -> None:
        """Test adding host to manager."""
        manager = InventoryManager()
        cred = Credential(username="root", password="secret")
        conn = Connection(
            type=ConnectionType.SSH,
            host="web1",
            port=22,
            credential=cred,
        )
        host = Host(hostname="web1", connection=conn)
        manager.add_host(host)
        assert manager.get_host("web1") is not None

    def test_add_group(self) -> None:
        """Test adding group to manager."""
        manager = InventoryManager()
        group = HostGroup(name="webservers")
        manager.add_group(group)
        assert manager.get_group("webservers") is not None

    def test_group_hosts(self) -> None:
        """Test getting group hosts."""
        manager = InventoryManager()
        group = HostGroup(name="webservers")
        manager.add_group(group)

        cred = Credential(username="root", password="secret")
        for i in range(3):
            conn = Connection(
                type=ConnectionType.SSH,
                host=f"web{i}",
                port=22,
                credential=cred,
            )
            host = Host(hostname=f"web{i}", connection=conn)
            manager.add_host(host)
            group.add_host(f"web{i}")

        hosts = manager.get_group_hosts("webservers")
        assert len(hosts) == 3

    def test_match_all_pattern(self) -> None:
        """Test matching all pattern."""
        manager = InventoryManager()
        cred = Credential(username="root", password="secret")

        for i in range(3):
            conn = Connection(
                type=ConnectionType.SSH,
                host=f"host{i}",
                port=22,
                credential=cred,
            )
            host = Host(hostname=f"host{i}", connection=conn)
            manager.add_host(host)

        hosts = manager.match_pattern("all")
        assert len(hosts) == 3

    def test_match_glob_pattern(self) -> None:
        """Test glob pattern matching."""
        manager = InventoryManager()
        cred = Credential(username="root", password="secret")

        for i in range(3):
            conn = Connection(
                type=ConnectionType.SSH,
                host=f"web{i}",
                port=22,
                credential=cred,
            )
            host = Host(hostname=f"web{i}", connection=conn)
            manager.add_host(host)

        hosts = manager.match_pattern("web*")
        assert len(hosts) == 3

    def test_match_regex_pattern(self) -> None:
        """Test regex pattern matching."""
        manager = InventoryManager()
        cred = Credential(username="root", password="secret")

        for name in ["web1", "web2", "db1", "db2"]:
            conn = Connection(
                type=ConnectionType.SSH,
                host=name,
                port=22,
                credential=cred,
            )
            host = Host(hostname=name, connection=conn)
            manager.add_host(host)

        hosts = manager.match_pattern("~web.*")
        assert len(hosts) == 2

    def test_host_variables(self) -> None:
        """Test getting host variables merged with groups."""
        manager = InventoryManager()

        group = HostGroup(name="webservers")
        group.variables["env"] = "prod"
        manager.add_group(group)

        cred = Credential(username="root", password="secret")
        conn = Connection(
            type=ConnectionType.SSH,
            host="web1",
            port=22,
            credential=cred,
        )
        host = Host(hostname="web1", connection=conn)
        host.variables["app_port"] = 8080
        host.add_group("webservers")
        manager.add_host(host)

        vars = manager.get_host_variables("web1")
        assert vars["env"] == "prod"
        assert vars["app_port"] == 8080

    def test_group_hierarchy(self) -> None:
        """Test group hierarchy."""
        manager = InventoryManager()

        parent = HostGroup(name="all_servers")
        manager.add_group(parent)

        child = HostGroup(name="webservers")
        manager.add_group(child)

        manager.create_group_hierarchy("all_servers", ["webservers"])
        assert "webservers" in manager.get_group("all_servers").children

    def test_load_static_inventory(self) -> None:
        """Test loading static inventory from file."""
        content = """
[webservers]
web1 ansible_host=192.168.1.1
web2 ansible_host=192.168.1.2
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write(content)
            f.flush()

            manager = InventoryManager()
            inv = manager.load_static_inventory(f.name)
            assert len(inv.hosts) == 2

            Path(f.name).unlink()

    def test_validate_inventory(self) -> None:
        """Test inventory validation."""
        manager = InventoryManager()

        group = HostGroup(name="servers")
        group.hosts.add("missing_host")
        manager.add_group(group)

        with pytest.raises(ValidationError):
            manager.validate_inventory()

    def test_merge_inventories(self) -> None:
        """Test merging inventory managers."""
        manager1 = InventoryManager()
        manager2 = InventoryManager()

        cred = Credential(username="root", password="secret")

        # Add to manager1
        conn1 = Connection(
            type=ConnectionType.SSH,
            host="host1",
            port=22,
            credential=cred,
        )
        host1 = Host(hostname="host1", connection=conn1)
        manager1.add_host(host1)

        # Add to manager2
        conn2 = Connection(
            type=ConnectionType.SSH,
            host="host2",
            port=22,
            credential=cred,
        )
        host2 = Host(hostname="host2", connection=conn2)
        manager2.add_host(host2)

        manager1.merge_inventory(manager2)
        assert len(manager1.hosts) == 2
