"""Tests for type definitions."""

import pytest

from thomas.config_mgmt._types import (
    Connection,
    ConnectionType,
    Credential,
    DiffResult,
    ExecutionResult,
    Host,
    HostGroup,
    Inventory,
    Playbook,
    Role,
    Task,
    Template,
    Variable,
)


class TestCredential:
    """Tests for Credential type."""

    def test_credential_creation(self) -> None:
        """Test credential creation."""
        cred = Credential(username="admin", password="secret")
        assert cred.username == "admin"
        assert cred.password == "secret"

    def test_credential_validation_missing_username(self) -> None:
        """Test validation fails without username."""
        cred = Credential(username="", password="secret")
        with pytest.raises(ValueError):
            cred.validate()

    def test_credential_validation_no_auth(self) -> None:
        """Test validation fails without auth method."""
        cred = Credential(username="admin")
        with pytest.raises(ValueError):
            cred.validate()

    def test_credential_with_private_key(self) -> None:
        """Test credential with private key."""
        cred = Credential(username="admin", private_key_path="/root/.ssh/id_rsa")
        cred.validate()
        assert cred.private_key_path == "/root/.ssh/id_rsa"


class TestConnection:
    """Tests for Connection type."""

    def test_connection_creation(self) -> None:
        """Test connection creation."""
        cred = Credential(username="root", password="secret")
        conn = Connection(
            type=ConnectionType.SSH,
            host="192.168.1.1",
            port=22,
            credential=cred,
        )
        assert conn.host == "192.168.1.1"
        assert conn.type == ConnectionType.SSH

    def test_connection_validation_invalid_port(self) -> None:
        """Test validation with invalid port."""
        cred = Credential(username="root", password="secret")
        conn = Connection(
            type=ConnectionType.SSH,
            host="192.168.1.1",
            port=99999,
            credential=cred,
        )
        with pytest.raises(ValueError):
            conn.validate()


class TestVariable:
    """Tests for Variable type."""

    def test_variable_creation(self) -> None:
        """Test variable creation."""
        var = Variable(name="my_var", value="test_value", scope="host")
        assert var.name == "my_var"
        assert var.value == "test_value"

    def test_variable_hash(self) -> None:
        """Test variable hashing."""
        var1 = Variable(name="x", value=1, scope="host")
        var2 = Variable(name="x", value=2, scope="host")
        var3 = Variable(name="x", value=1, scope="group")

        assert hash(var1) == hash(var2)
        assert hash(var1) != hash(var3)

    def test_variable_equality(self) -> None:
        """Test variable equality."""
        var1 = Variable(name="x", value=1, scope="host")
        var2 = Variable(name="x", value=2, scope="host")
        var3 = Variable(name="y", value=1, scope="host")

        assert var1 == var2
        assert var1 != var3


class TestTemplate:
    """Tests for Template type."""

    def test_template_render(self) -> None:
        """Test template rendering."""
        template = Template(
            name="test",
            content="Hello {{ name }}, you are {{ age }} years old",
            variables={"name": "Alice", "age": "30"},
        )
        result = template.render()
        assert result == "Hello Alice, you are 30 years old"

    def test_template_partial_variables(self) -> None:
        """Test template with missing variables."""
        template = Template(
            name="test",
            content="{{ greeting }} {{ name }}",
            variables={"greeting": "Hello"},
        )
        result = template.render()
        assert "Hello" in result


class TestTask:
    """Tests for Task type."""

    def test_task_creation(self) -> None:
        """Test task creation."""
        task = Task(name="Install nginx", module="package", args={"name": "nginx"})
        assert task.name == "Install nginx"
        assert task.module == "package"

    def test_task_validation(self) -> None:
        """Test task validation."""
        task = Task(name="", module="package")
        with pytest.raises(ValueError):
            task.validate()

    def test_task_with_loop(self) -> None:
        """Test task with loop items."""
        task = Task(
            name="Create users",
            module="user",
            with_items=["alice", "bob", "charlie"],
        )
        assert len(task.with_items) == 3


class TestRole:
    """Tests for Role type."""

    def test_role_creation(self) -> None:
        """Test role creation."""
        task = Task(name="Setup", module="command", args={"cmd": "echo hello"})
        role = Role(name="webserver", tasks=[task])
        assert role.name == "webserver"
        assert len(role.tasks) == 1

    def test_role_with_dependencies(self) -> None:
        """Test role with dependencies."""
        role = Role(
            name="app",
            dependencies=["base", "python"],
        )
        assert "base" in role.dependencies


class TestHostGroup:
    """Tests for HostGroup type."""

    def test_group_creation(self) -> None:
        """Test group creation."""
        group = HostGroup(name="webservers")
        assert group.name == "webservers"

    def test_group_add_host(self) -> None:
        """Test adding host to group."""
        group = HostGroup(name="webservers")
        group.add_host("web1")
        assert "web1" in group.hosts

    def test_group_hierarchy(self) -> None:
        """Test group hierarchy."""
        parent = HostGroup(name="all")
        child = HostGroup(name="webservers")
        parent.add_child_group("webservers")
        assert "webservers" in parent.children


class TestHost:
    """Tests for Host type."""

    def test_host_creation(self) -> None:
        """Test host creation."""
        cred = Credential(username="root", password="secret")
        conn = Connection(
            type=ConnectionType.SSH,
            host="web1",
            port=22,
            credential=cred,
        )
        host = Host(hostname="web1", connection=conn)
        assert host.hostname == "web1"

    def test_host_variables(self) -> None:
        """Test host variables."""
        cred = Credential(username="root", password="secret")
        conn = Connection(
            type=ConnectionType.SSH,
            host="web1",
            port=22,
            credential=cred,
        )
        host = Host(hostname="web1", connection=conn)
        host.variables["app_port"] = 8080
        assert host.get_variable("app_port") == 8080

    def test_host_facts(self) -> None:
        """Test host facts."""
        cred = Credential(username="root", password="secret")
        conn = Connection(
            type=ConnectionType.SSH,
            host="web1",
            port=22,
            credential=cred,
        )
        host = Host(hostname="web1", connection=conn)
        host.set_fact("os_version", "Ubuntu 20.04")
        assert host.facts["os_version"] == "Ubuntu 20.04"


class TestInventory:
    """Tests for Inventory type."""

    def test_inventory_creation(self) -> None:
        """Test inventory creation."""
        inv = Inventory(name="production")
        assert inv.name == "production"

    def test_inventory_add_host(self) -> None:
        """Test adding host to inventory."""
        inv = Inventory(name="prod")
        cred = Credential(username="root", password="secret")
        conn = Connection(
            type=ConnectionType.SSH,
            host="web1",
            port=22,
            credential=cred,
        )
        host = Host(hostname="web1", connection=conn)
        inv.add_host(host)
        assert inv.get_host("web1") is not None

    def test_inventory_merge(self) -> None:
        """Test inventory merging."""
        inv1 = Inventory(name="inv1")
        inv2 = Inventory(name="inv2")

        cred = Credential(username="root", password="secret")
        conn = Connection(
            type=ConnectionType.SSH,
            host="web1",
            port=22,
            credential=cred,
        )
        host1 = Host(hostname="web1", connection=conn)
        host1.variables["env"] = "prod"

        inv1.add_host(host1)
        inv2.variables["datacenter"] = "us-east"

        inv1.merge(inv2)
        assert inv1.variables["datacenter"] == "us-east"


class TestExecutionResult:
    """Tests for ExecutionResult type."""

    def test_result_creation(self) -> None:
        """Test result creation."""
        result = ExecutionResult(
            task_name="Install nginx",
            host="web1",
            status="ok",
            module="package",
        )
        assert result.task_name == "Install nginx"
        assert not result.failed

    def test_result_with_changes(self) -> None:
        """Test result with changes."""
        result = ExecutionResult(
            task_name="Update config",
            host="web1",
            status="ok",
            module="template",
            changed=True,
        )
        assert result.changed


class TestDiffResult:
    """Tests for DiffResult type."""

    def test_diff_changed(self) -> None:
        """Test diff detection."""
        diff = DiffResult(
            filename="/etc/nginx/nginx.conf",
            before="worker_processes 4;",
            after="worker_processes 8;",
        )
        assert diff.is_changed()

    def test_diff_unchanged(self) -> None:
        """Test unchanged diff."""
        diff = DiffResult(
            filename="/etc/nginx/nginx.conf",
            before="worker_processes 4;",
            after="worker_processes 4;",
        )
        assert not diff.is_changed()


class TestPlaybook:
    """Tests for Playbook type."""

    def test_playbook_creation(self) -> None:
        """Test playbook creation."""
        task = Task(name="Install", module="package", args={"name": "nginx"})
        playbook = Playbook(
            name="setup_web",
            hosts="webservers",
            tasks=[task],
        )
        assert playbook.name == "setup_web"

    def test_playbook_validation(self) -> None:
        """Test playbook validation."""
        playbook = Playbook(name="", hosts="all")
        with pytest.raises(ValueError):
            playbook.validate()
