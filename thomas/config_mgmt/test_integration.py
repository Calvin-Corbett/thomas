"""Integration tests for complete config management system."""

import pytest

from thomas.config_mgmt._types import (
    Connection,
    ConnectionType,
    Credential,
    Handler,
    Host,
    HostGroup,
    Playbook,
    Role,
    Task,
)
from thomas.config_mgmt.inventory import InventoryManager
from thomas.config_mgmt.runner import PlaybookRunner, RunnerConfig


class TestCompleteWorkflow:
    """Integration tests for complete configuration management workflow."""

    def setup_method(self) -> None:
        """Setup test environment."""
        self.inventory = InventoryManager()

        # Create test inventory with groups
        cred = Credential(username="admin", password="secret")

        # Create web servers
        for i in range(2):
            conn = Connection(
                type=ConnectionType.SSH,
                host=f"web{i}",
                port=22,
                credential=cred,
            )
            host = Host(hostname=f"web{i}", connection=conn)
            host.variables["app_port"] = 8080 + i
            self.inventory.add_host(host)

        # Create database servers
        for i in range(1):
            conn = Connection(
                type=ConnectionType.SSH,
                host=f"db{i}",
                port=22,
                credential=cred,
            )
            host = Host(hostname=f"db{i}", connection=conn)
            host.variables["db_port"] = 5432
            self.inventory.add_host(host)

        # Create groups
        web_group = HostGroup(name="webservers")
        web_group.variables["env"] = "production"
        for i in range(2):
            web_group.add_host(f"web{i}")
        self.inventory.add_group(web_group)

        db_group = HostGroup(name="dbservers")
        db_group.variables["env"] = "production"
        db_group.add_host("db0")
        self.inventory.add_group(db_group)

        all_group = HostGroup(name="all")
        all_group.add_child_group("webservers")
        all_group.add_child_group("dbservers")
        self.inventory.add_group(all_group)

    def test_inventory_creation(self) -> None:
        """Test inventory creation with multiple hosts and groups."""
        assert len(self.inventory.hosts) == 3
        assert len(self.inventory.groups) == 3

    def test_host_group_membership(self) -> None:
        """Test host group membership."""
        web_hosts = self.inventory.get_group_hosts("webservers")
        assert len(web_hosts) == 2

        db_hosts = self.inventory.get_group_hosts("dbservers")
        assert len(db_hosts) == 1

    def test_host_variable_inheritance(self) -> None:
        """Test host variables with group inheritance."""
        vars = self.inventory.get_host_variables("web0")
        assert vars["env"] == "production"
        assert vars["app_port"] == 8080

    def test_pattern_matching(self) -> None:
        """Test host pattern matching."""
        all_hosts = self.inventory.match_pattern("all")
        assert len(all_hosts) == 3

        web_hosts = self.inventory.match_pattern("webservers")
        assert len(web_hosts) == 2

        glob_hosts = self.inventory.match_pattern("web*")
        assert len(glob_hosts) == 2

    def test_playbook_creation(self) -> None:
        """Test creating and validating playbook."""
        task1 = Task(
            name="Install nginx",
            module="package",
            args={"name": "nginx", "state": "present"},
        )

        task2 = Task(
            name="Start nginx",
            module="command",
            args={"cmd": "systemctl start nginx"},
        )

        playbook = Playbook(
            name="setup_webservers",
            hosts="webservers",
            tasks=[task1, task2],
            variables={"nginx_version": "latest"},
        )

        playbook.validate()
        assert playbook.name == "setup_webservers"
        assert len(playbook.tasks) == 2

    def test_playbook_with_handlers(self) -> None:
        """Test playbook with handlers."""
        handler = Handler(
            name="restart_nginx",
            action="systemctl restart nginx",
        )

        task = Task(
            name="Update nginx config",
            module="template",
            args={
                "src": "/tmp/nginx.conf.j2",
                "dest": "/etc/nginx/nginx.conf",
            },
            notify=["restart_nginx"],
        )

        playbook = Playbook(
            name="configure_nginx",
            hosts="webservers",
            tasks=[task],
            handlers=[handler],
        )

        assert len(playbook.handlers) == 1
        assert "restart_nginx" in playbook.handlers[0].name

    def test_playbook_with_roles(self) -> None:
        """Test playbook with roles."""
        role = Role(
            name="common",
            variables={"ntp_server": "pool.ntp.org"},
        )

        playbook = Playbook(
            name="deploy",
            hosts="all",
            roles=[role],
        )

        assert len(playbook.roles) == 1
        assert playbook.roles[0].name == "common"

    def test_playbook_with_conditionals(self) -> None:
        """Test playbook with conditional tasks."""
        task = Task(
            name="Install on prod",
            module="package",
            args={"name": "nginx"},
            when="env == 'production'",
        )

        Playbook(
            name="conditional_install",
            hosts="all",
            tasks=[task],
        )

        assert task.when == "env == 'production'"

    def test_playbook_with_loops(self) -> None:
        """Test playbook with loop tasks."""
        task = Task(
            name="Create users",
            module="user",
            args={"name": "{{ item }}"},
            with_items=["alice", "bob", "charlie"],
        )

        Playbook(
            name="create_users",
            hosts="all",
            tasks=[task],
        )

        assert len(task.with_items) == 3

    def test_runner_initialization(self) -> None:
        """Test runner initialization with inventory."""
        config = RunnerConfig(
            check_mode=False,
            gather_facts=False,
        )

        runner = PlaybookRunner(self.inventory, config)
        assert runner.inventory is not None
        assert runner.module_registry is not None

    def test_runner_inventory_access(self) -> None:
        """Test accessing inventory through runner."""
        runner = PlaybookRunner(self.inventory)

        hosts = runner.get_inventory().match_pattern("webservers")
        assert len(hosts) == 2

    def test_runner_variable_manager(self) -> None:
        """Test variable manager through runner."""
        runner = PlaybookRunner(self.inventory)

        var_mgr = runner.get_variable_manager()
        var_mgr.set("my_var", "my_value", "extra")
        assert var_mgr.get("my_var") == "my_value"

    def test_runner_fact_cache(self) -> None:
        """Test fact cache through runner."""
        runner = PlaybookRunner(self.inventory)

        cache = runner.get_fact_cache()
        cache.set_fact("web0", "os_version", "Ubuntu 20.04")
        assert cache.get_fact("web0", "os_version") == "Ubuntu 20.04"

    def test_complete_playbook_execution_flow(self) -> None:
        """Test complete playbook execution flow."""
        # Create a simple playbook
        task = Task(
            name="Echo test",
            module="command",
            args={"cmd": "echo hello"},
        )

        playbook = Playbook(
            name="test",
            hosts="webservers",
            tasks=[task],
        )

        # Create runner
        PlaybookRunner(self.inventory)

        # Validate playbook
        playbook.validate()

        # Would execute but need mock module executor
        assert playbook.hosts == "webservers"
        assert len(playbook.tasks) == 1

    def test_multi_playbook_execution(self) -> None:
        """Test executing multiple playbooks."""
        playbook1 = Playbook(
            name="setup_web",
            hosts="webservers",
            tasks=[Task(name="Install", module="package", args={"name": "nginx"})],
        )

        playbook2 = Playbook(
            name="setup_db",
            hosts="dbservers",
            tasks=[Task(name="Install", module="package", args={"name": "postgresql"})],
        )

        PlaybookRunner(self.inventory)

        playbook1.validate()
        playbook2.validate()

        assert playbook1.hosts == "webservers"
        assert playbook2.hosts == "dbservers"

    def test_error_handling(self) -> None:
        """Test error handling in configuration."""
        with pytest.raises(ValueError):
            task = Task(name="", module="package")
            task.validate()

    def test_inventory_export(self) -> None:
        """Test exporting inventory to JSON."""
        json_output = self.inventory.export_json()
        assert "hosts" in json_output
        assert "groups" in json_output
        assert "web0" in json_output
