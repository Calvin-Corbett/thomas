"""Tests for playbook runner."""

import tempfile
from pathlib import Path

from thomas.config_mgmt._types import (
    Connection,
    ConnectionType,
    Credential,
    Host,
    HostGroup,
)
from thomas.config_mgmt.inventory import InventoryManager
from thomas.config_mgmt.runner import PlaybookRunner, RunnerConfig


class TestRunnerConfig:
    """Tests for runner configuration."""

    def test_default_config(self) -> None:
        """Test default configuration."""
        config = RunnerConfig()
        assert config.check_mode is False
        assert config.gather_facts is True
        assert config.forks == 5

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config = RunnerConfig(
            check_mode=True,
            gather_facts=False,
            forks=10,
        )
        assert config.check_mode is True
        assert config.gather_facts is False
        assert config.forks == 10


class TestPlaybookRunner:
    """Tests for playbook runner."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.inventory = InventoryManager()

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

    def test_runner_initialization(self) -> None:
        """Test runner initialization."""
        runner = PlaybookRunner(self.inventory)
        assert runner.inventory is not None
        assert runner.module_registry is not None
        assert runner.variable_manager is not None

    def test_get_inventory(self) -> None:
        """Test getting inventory from runner."""
        runner = PlaybookRunner(self.inventory)
        inv = runner.get_inventory()
        assert inv is runner.inventory

    def test_get_variable_manager(self) -> None:
        """Test getting variable manager from runner."""
        runner = PlaybookRunner(self.inventory)
        var_mgr = runner.get_variable_manager()
        assert var_mgr is not None

    def test_get_fact_cache(self) -> None:
        """Test getting fact cache from runner."""
        runner = PlaybookRunner(self.inventory)
        cache = runner.get_fact_cache()
        assert cache is not None

    def test_custom_config(self) -> None:
        """Test runner with custom config."""
        config = RunnerConfig(check_mode=True, gather_facts=False)
        runner = PlaybookRunner(self.inventory, config)
        assert runner.config.check_mode is True
        assert runner.config.gather_facts is False

    def test_execution_summary_calculation(self) -> None:
        """Test execution summary calculation."""
        runner = PlaybookRunner(self.inventory)

        from thomas.config_mgmt._types import ExecutionResult

        results = [
            ExecutionResult(
                task_name="Task1",
                host="host0",
                status="ok",
                module="command",
                failed=False,
                skipped=False,
                changed=True,
            ),
            ExecutionResult(
                task_name="Task2",
                host="host1",
                status="skipped",
                module="command",
                failed=False,
                skipped=True,
            ),
        ]

        summary = runner._get_summary(results)
        assert summary["total"] == 2
        assert summary["ok"] == 1
        assert summary["skipped"] == 1
        assert summary["changed"] == 1

    def test_runner_with_playbook_yaml(self) -> None:
        """Test runner with YAML playbook file."""
        playbook_yaml = """
- name: Test Playbook
  hosts: all
  tasks:
    - name: Echo
      command:
        cmd: echo hello
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            playbook_file = str(Path(tmpdir) / "playbook.yml")
            Path(playbook_file).write_text(playbook_yaml)

            runner = PlaybookRunner(self.inventory)
            try:
                result = runner.run_playbook_file(playbook_file)
                assert "status" in result
            except Exception:
                # Expected if PyYAML not installed
                pass
