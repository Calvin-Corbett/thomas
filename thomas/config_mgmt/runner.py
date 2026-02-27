"""High-level orchestration runner."""

from dataclasses import dataclass
from typing import Any

from thomas.config_mgmt._exceptions import (
    ConfigError,
    ExecutionError,
)
from thomas.config_mgmt._types import Playbook
from thomas.config_mgmt.executor import HostConnector, TaskExecutor
from thomas.config_mgmt.facts import FactCache, FactGatherer
from thomas.config_mgmt.inventory import InventoryManager
from thomas.config_mgmt.modules import ModuleRegistry
from thomas.config_mgmt.parser import PlaybookParser
from thomas.config_mgmt.playbook import PlaybookEngine
from thomas.config_mgmt.variables import VariableManager


@dataclass
class RunnerConfig:
    """Configuration for playbook runner."""

    become: bool = False
    become_method: str = "sudo"
    become_user: str = "root"
    check_mode: bool = False
    diff_mode: bool = False
    verbosity: int = 0
    connection_timeout: int = 10
    gather_facts: bool = True
    forks: int = 5


class PlaybookRunner:
    """Orchestrates playbook execution."""

    def __init__(
        self,
        inventory: InventoryManager,
        config: RunnerConfig | None = None,
    ) -> None:
        """Initialize playbook runner.

        Args:
            inventory: Inventory manager.
            config: Runner configuration.
        """
        self.inventory = inventory
        self.config = config or RunnerConfig()
        self.variable_manager = VariableManager()
        self.module_registry = ModuleRegistry()
        self.task_executor = TaskExecutor(self.module_registry)
        self.host_connector = HostConnector()
        self.fact_cache = FactCache()
        self.playbook_engine = PlaybookEngine(inventory)
        self._setup_engine()

    def _setup_engine(self) -> None:
        """Setup playbook engine."""
        self.playbook_engine.set_module_executor(self.task_executor)

    def run_playbook_file(
        self,
        filepath: str,
        extra_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run playbook from file.

        Args:
            filepath: Path to playbook file.
            extra_vars: Extra variables.

        Returns:
            Dict[str, Any]: Execution results.

        Raises:
            ConfigError: If execution fails.
        """
        try:
            playbooks = PlaybookParser.parse_from_file(filepath)
            all_results = []

            for playbook in playbooks:
                results = self.run_playbook(playbook, extra_vars)
                all_results.extend(results)

            return {
                "status": "success",
                "results": all_results,
                "summary": self._get_summary(all_results),
            }
        except Exception as e:
            raise ConfigError(f"Playbook execution failed: {e}")

    def run_playbook(
        self,
        playbook: Playbook,
        extra_vars: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Run playbook.

        Args:
            playbook: Playbook to run.
            extra_vars: Extra variables.

        Returns:
            List[Any]: Execution results.

        Raises:
            ExecutionError: If execution fails.
        """
        # Set extra variables
        if extra_vars:
            self.variable_manager.set_variable("all", extra_vars, "extra")

        # Get target hosts
        target_hosts = self.inventory.match_pattern(playbook.hosts)
        if not target_hosts:
            raise ExecutionError(f"No hosts matched pattern: {playbook.hosts}")

        # Gather facts if enabled
        if self.config.gather_facts:
            self._gather_facts(target_hosts)

        # Execute playbook
        results = self.playbook_engine.execute_playbook(playbook, extra_vars)

        return results

    def _gather_facts(self, hosts: list[Any]) -> None:
        """Gather facts from hosts.

        Args:
            hosts: Hosts to gather facts from.
        """
        for host in hosts:
            try:
                facts = FactGatherer.gather_local_facts()
                self.fact_cache.set_host_facts(host.hostname, facts)
            except Exception:
                pass  # Continue even if fact gathering fails

    def _get_summary(self, results: list[Any]) -> dict[str, Any]:
        """Get execution summary.

        Args:
            results: Execution results.

        Returns:
            Dict[str, Any]: Summary statistics.
        """
        return {
            "total": len(results),
            "ok": len([r for r in results if not r.failed and not r.skipped]),
            "failed": len([r for r in results if r.failed]),
            "skipped": len([r for r in results if r.skipped]),
            "changed": len([r for r in results if r.changed]),
        }

    def get_inventory(self) -> InventoryManager:
        """Get inventory manager.

        Returns:
            InventoryManager: Inventory manager.
        """
        return self.inventory

    def get_variable_manager(self) -> VariableManager:
        """Get variable manager.

        Returns:
            VariableManager: Variable manager.
        """
        return self.variable_manager

    def get_fact_cache(self) -> FactCache:
        """Get fact cache.

        Returns:
            FactCache: Fact cache.
        """
        return self.fact_cache
