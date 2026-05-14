"""Tests for playbook execution."""

import pytest

from thomas.config_mgmt._exceptions import PlaybookError
from thomas.config_mgmt._types import (
    Connection,
    ConnectionType,
    Credential,
    Handler,
    Host,
    HostGroup,
    Playbook,
    Task,
)
from thomas.config_mgmt.inventory import InventoryManager
from thomas.config_mgmt.playbook import (
    ConditionalEvaluator,
    ExecutionContext,
    PlaybookEngine,
)


class TestConditionalEvaluator:
    """Tests for conditional evaluation."""

    def test_evaluate_variable_existence(self) -> None:
        """Test evaluating variable existence."""
        context = {"debug_mode": True}
        assert ConditionalEvaluator.evaluate("debug_mode", context)

    def test_evaluate_equality(self) -> None:
        """Test evaluating equality."""
        context = {"env": "prod"}
        assert ConditionalEvaluator.evaluate("env == 'prod'", context)

    def test_evaluate_inequality(self) -> None:
        """Test evaluating inequality."""
        context = {"env": "prod"}
        assert ConditionalEvaluator.evaluate("env != 'dev'", context)

    def test_evaluate_negation(self) -> None:
        """Test evaluating negation."""
        context = {"debug_mode": False}
        assert ConditionalEvaluator.evaluate("not debug_mode", context)

    def test_evaluate_empty_condition(self) -> None:
        """Test evaluating empty condition."""
        assert ConditionalEvaluator.evaluate("", {})


class TestExecutionContext:
    """Tests for execution context."""

    def test_set_and_get_variable(self) -> None:
        """Test setting and getting variables."""
        context = ExecutionContext()
        context.set_variable("my_var", "my_value")
        assert context.get_variable("my_var") == "my_value"

    def test_get_variable_default(self) -> None:
        """Test getting variable with default."""
        context = ExecutionContext()
        assert context.get_variable("missing", "default") == "default"

    def test_set_and_get_fact(self) -> None:
        """Test setting and getting facts."""
        context = ExecutionContext()
        context.set_fact("host1", "os", "Ubuntu")
        assert context.get_fact("host1", "os") == "Ubuntu"

    def test_pending_handlers(self) -> None:
        """Test handler notification."""
        context = ExecutionContext()
        context.pending_handlers.add("restart_nginx")
        assert "restart_nginx" in context.pending_handlers


class TestPlaybookEngine:
    """Tests for playbook engine."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.inventory = InventoryManager()
        self.engine = PlaybookEngine(self.inventory)

        # Add test hosts
        cred = Credential(username="root", password="secret")
        for i in range(2):
            conn = Connection(
                type=ConnectionType.SSH,
                host=f"host{i}",
                port=22,
                credential=cred,
            )
            host = Host(hostname=f"host{i}", connection=conn)
            self.inventory.add_host(host)

        # Add test group
        group = HostGroup(name="all")
        for i in range(2):
            group.add_host(f"host{i}")
        self.inventory.add_group(group)

    def test_register_handlers(self) -> None:
        """Test handler registration."""
        handler = Handler(name="restart_nginx", action="service")
        self.engine._register_handlers([handler])
        assert "restart_nginx" in self.engine.handlers

    def test_simple_playbook_validation(self) -> None:
        """Test playbook validation."""
        task = Task(name="Test", module="command", args={"cmd": "echo test"})
        playbook = Playbook(
            name="test",
            hosts="all",
            tasks=[task],
        )
        playbook.validate()

    def test_playbook_missing_hosts(self) -> None:
        """Test playbook execution with no matching hosts."""
        task = Task(name="Test", module="command", args={"cmd": "echo test"})
        playbook = Playbook(
            name="test",
            hosts="nonexistent",
            tasks=[task],
        )

        with pytest.raises(PlaybookError):
            self.engine.execute_playbook(playbook)

    def test_execution_context_initialization(self) -> None:
        """Test context initialization with variables."""
        task = Task(name="Test", module="command", args={"cmd": "echo test"})
        playbook = Playbook(
            name="test",
            hosts="all",
            tasks=[task],
            variables={"my_var": "my_value"},
        )

        context = ExecutionContext()
        context.variables.update(playbook.variables)

        assert context.get_variable("my_var") == "my_value"

    def test_conditional_task_skipping(self) -> None:
        """Test task skipping with when clause."""
        task = Task(
            name="Conditional",
            module="command",
            args={"cmd": "echo test"},
            when="undefined_var",
        )

        hosts = self.inventory.match_pattern("all")
        results = self.engine._execute_task(task, hosts, None)

        assert all(r.skipped for r in results)

    def test_task_with_items_execution(self) -> None:
        """Test task execution with loop items."""
        task = Task(
            name="Create users",
            module="user",
            args={"name": "{{ item }}"},
            with_items=["alice", "bob", "charlie"],
        )

        hosts = self.inventory.match_pattern("all")
        results = self.engine._execute_task(task, hosts, None)

        # Each host gets 3 results (one per item)
        assert len(results) >= 3

    def test_handler_notification(self) -> None:
        """Test handler notification."""
        handler = Handler(name="restart_service", action="service")
        Task(
            name="Update config",
            module="template",
            args={"src": "/tmp/conf.j2", "dest": "/etc/app.conf"},
            notify=["restart_service"],
        )

        self.engine._register_handlers([handler])

        context = ExecutionContext()
        assert "restart_service" not in context.pending_handlers

        context.pending_handlers.add("restart_service")
        assert "restart_service" in context.pending_handlers

    def test_execution_summary(self) -> None:
        """Test execution summary calculation."""
        task1 = Task(name="Task1", module="command", args={"cmd": "true"})
        task2 = Task(name="Task2", module="command", args={"cmd": "false"})

        Playbook(
            name="test",
            hosts="all",
            tasks=[task1, task2],
        )

        summary = self.engine.get_execution_summary()
        assert "total" in summary
        assert "ok" in summary
        assert "failed" in summary
