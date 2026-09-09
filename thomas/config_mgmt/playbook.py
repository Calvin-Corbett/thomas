"""Playbook execution engine."""

import copy
import time
from dataclasses import dataclass, field
from typing import Any

from thomas.config_mgmt._exceptions import (
    ExecutionError,
    PlaybookError,
)
from thomas.config_mgmt._types import (
    ExecutionResult,
    Handler,
    Host,
    Playbook,
    Task,
)
from thomas.config_mgmt.inventory import InventoryManager


@dataclass
class ExecutionContext:
    """Context for playbook execution."""

    variables: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    registered: dict[str, Any] = field(default_factory=dict)
    pending_handlers: set[str] = field(default_factory=set)
    results: list[ExecutionResult] = field(default_factory=list)

    def set_variable(self, name: str, value: Any) -> None:
        """Set variable in context.

        Args:
            name: Variable name.
            value: Variable value.
        """
        self.variables[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get variable from context.

        Args:
            name: Variable name.
            default: Default value.

        Returns:
            Any: Variable value or default.
        """
        return self.variables.get(name, default)

    def set_fact(self, hostname: str, name: str, value: Any) -> None:
        """Set fact for host.

        Args:
            hostname: Hostname.
            name: Fact name.
            value: Fact value.
        """
        if hostname not in self.facts:
            self.facts[hostname] = {}
        self.facts[hostname][name] = value

    def get_fact(self, hostname: str, name: str, default: Any = None) -> Any:
        """Get fact for host.

        Args:
            hostname: Hostname.
            name: Fact name.
            default: Default value.

        Returns:
            Any: Fact value or default.
        """
        if hostname not in self.facts:
            return default
        return self.facts[hostname].get(name, default)


class ConditionalEvaluator:
    """Evaluates conditional expressions."""

    @staticmethod
    def evaluate(condition: str, context: dict[str, Any]) -> bool:
        """Evaluate when clause.

        Args:
            condition: Condition expression.
            context: Variable context.

        Returns:
            bool: True if condition is true.

        Raises:
            ValidationError: If condition is invalid.
        """
        if not condition:
            return True

        # Simple variable existence check
        if condition in context:
            return bool(context[condition])

        # Simple equality checks
        if "==" in condition:
            left, right = condition.split("==", 1)
            left_val = context.get(left.strip())
            right_val = right.strip().strip("'\"")
            return left_val == right_val

        if "!=" in condition:
            left, right = condition.split("!=", 1)
            left_val = context.get(left.strip())
            right_val = right.strip().strip("'\"")
            return left_val != right_val

        # Negation
        if condition.startswith("not "):
            inner = condition[4:].strip()
            return not ConditionalEvaluator.evaluate(inner, context)

        # Default: treat as variable check
        return bool(context.get(condition))


class VariablePrecedenceResolver:
    """Resolves variables with proper precedence."""

    PRECEDENCE = [
        "command_line",
        "playbook",
        "role",
        "inventory",
        "defaults",
    ]

    @staticmethod
    def resolve(
        var_name: str,
        sources: dict[str, dict[str, Any]],
    ) -> Any:
        """Resolve variable with precedence.

        Args:
            var_name: Variable name.
            sources: Dict mapping source names to variable dicts.

        Returns:
            Any: Resolved value or None.
        """
        for source_name in VariablePrecedenceResolver.PRECEDENCE:
            if source_name in sources and var_name in sources[source_name]:
                return sources[source_name][var_name]

        return None


class PlaybookEngine:
    """Executes playbooks on inventory."""

    def __init__(self, inventory: InventoryManager) -> None:
        """Initialize playbook engine.

        Args:
            inventory: Inventory manager.
        """
        self.inventory = inventory
        self.context = ExecutionContext()
        self.handlers: dict[str, Handler] = {}
        self.module_executor: Any | None = None

    def set_module_executor(self, executor: Any) -> None:
        """Set module executor for task execution.

        Args:
            executor: Module executor instance.
        """
        self.module_executor = executor

    def execute_playbook(
        self,
        playbook: Playbook,
        extra_vars: dict[str, Any] | None = None,
    ) -> list[ExecutionResult]:
        """Execute playbook.

        Args:
            playbook: Playbook to execute.
            extra_vars: Extra variables to set.

        Returns:
            List[ExecutionResult]: Execution results.

        Raises:
            PlaybookError: If playbook execution fails.
        """
        playbook.validate()

        # Initialize context with variable precedence
        self.context = ExecutionContext()
        self.context.variables.update(playbook.variables)
        if extra_vars:
            self.context.variables.update(extra_vars)

        # Register handlers
        self._register_handlers(playbook.handlers)

        # Get target hosts
        target_hosts = self.inventory.match_pattern(playbook.hosts)
        if not target_hosts:
            raise PlaybookError(f"No hosts matched pattern: {playbook.hosts}")

        all_results: list[ExecutionResult] = []

        # Execute pre_tasks
        results = self._execute_tasks(playbook.pre_tasks, target_hosts, playbook)
        all_results.extend(results)

        # Execute main tasks
        results = self._execute_tasks(playbook.tasks, target_hosts, playbook)
        all_results.extend(results)

        # Execute post_tasks
        results = self._execute_tasks(playbook.post_tasks, target_hosts, playbook)
        all_results.extend(results)

        # Flush handlers
        self._flush_handlers(target_hosts, playbook)

        self.context.results = all_results
        return all_results

    def _execute_tasks(
        self,
        tasks: list[Task],
        hosts: list[Host],
        playbook: Playbook,
    ) -> list[ExecutionResult]:
        """Execute list of tasks.

        Args:
            tasks: Tasks to execute.
            hosts: Target hosts.
            playbook: Parent playbook.

        Returns:
            List[ExecutionResult]: Execution results.
        """
        results: list[ExecutionResult] = []

        for task in tasks:
            task_results = self._execute_task(task, hosts, playbook)
            results.extend(task_results)

        return results

    def _execute_task(
        self,
        task: Task,
        hosts: list[Host],
        playbook: Playbook,
    ) -> list[ExecutionResult]:
        """Execute single task on all hosts.

        Args:
            task: Task to execute.
            hosts: Target hosts.
            playbook: Parent playbook.

        Returns:
            List[ExecutionResult]: Execution results.
        """
        results: list[ExecutionResult] = []
        skip_task = False

        # Check when clause
        if task.when:
            if not ConditionalEvaluator.evaluate(task.when, self.context.variables):
                skip_task = True

        for host in hosts:
            if skip_task:
                result = ExecutionResult(
                    task_name=task.name,
                    host=host.hostname,
                    status="skipped",
                    module=task.module,
                    skipped=True,
                )
                results.append(result)
                continue

            # Handle with_items
            if task.with_items:
                item_results = self._execute_task_with_items(task, host, playbook)
                results.extend(item_results)
            else:
                result = self._execute_single_task(task, host, playbook)
                results.append(result)

                # Register variable if specified
                if task.register and not result.failed:
                    self.context.registered[task.register] = result.return_data

                # Notify handlers if task changed
                if result.changed:
                    for handler_name in task.notify:
                        self.context.pending_handlers.add(handler_name)

        return results

    def _execute_task_with_items(
        self,
        task: Task,
        host: Host,
        playbook: Playbook,
    ) -> list[ExecutionResult]:
        """Execute task with items loop.

        Args:
            task: Task with with_items.
            host: Target host.
            playbook: Parent playbook.

        Returns:
            List[ExecutionResult]: Execution results.
        """
        results: list[ExecutionResult] = []

        if not task.with_items:
            return results

        for item in task.with_items:
            # Create copy with item variable
            task_copy = copy.deepcopy(task)
            self.context.set_variable("item", item)

            result = self._execute_single_task(task_copy, host, playbook)
            results.append(result)

            if task.register and not result.failed:
                if task.register not in self.context.registered:
                    self.context.registered[task.register] = []
                self.context.registered[task.register].append(result.return_data)

        return results

    def _execute_single_task(
        self,
        task: Task,
        host: Host,
        playbook: Playbook,
    ) -> ExecutionResult:
        """Execute single task on single host.

        Args:
            task: Task to execute.
            host: Target host.
            playbook: Parent playbook.

        Returns:
            ExecutionResult: Execution result.
        """
        start_time = time.time()
        attempts = 0

        # Retry logic
        for attempt in range(1, task.retries + 1):
            attempts = attempt

            if attempt > 1:
                time.sleep(task.delay)

            try:
                result = self._run_module(task, host)
                duration = time.time() - start_time
                result.duration = duration
                result.attempts = attempt
                return result
            except Exception as e:
                if attempt == task.retries:
                    result = ExecutionResult(
                        task_name=task.name,
                        host=host.hostname,
                        status="failed",
                        module=task.module,
                        stderr=str(e),
                        failed=True,
                        attempts=attempt,
                    )
                    result.duration = time.time() - start_time

                    if task.ignore_errors:
                        result.failed = False
                        result.status = "ok"

                    return result
                continue

        # Should not reach here
        return ExecutionResult(
            task_name=task.name,
            host=host.hostname,
            status="failed",
            module=task.module,
            failed=True,
            attempts=attempts,
        )

    def _run_module(self, task: Task, host: Host) -> ExecutionResult:
        """Run module executor.

        Args:
            task: Task to execute.
            host: Target host.

        Returns:
            ExecutionResult: Execution result.

        Raises:
            ExecutionError: If module execution fails.
        """
        if not self.module_executor:
            raise ExecutionError("Module executor not set")

        return self.module_executor.execute(task, host, self.context)

    def _register_handlers(self, handlers: list[Handler]) -> None:
        """Register handlers for notification.

        Args:
            handlers: Handlers to register.
        """
        for handler in handlers:
            self.handlers[handler.name] = handler

    def _flush_handlers(
        self,
        hosts: list[Host],
        playbook: Playbook,
    ) -> None:
        """Execute pending handlers.

        Args:
            hosts: Target hosts.
            playbook: Parent playbook.
        """
        if not self.context.pending_handlers:
            return

        for handler_name in self.context.pending_handlers:
            if handler_name not in self.handlers:
                continue

            handler = self.handlers[handler_name]
            task = Task(
                name=handler_name,
                module=handler.action,
                args={},
            )

            self._execute_task(task, hosts, playbook)

        self.context.pending_handlers.clear()

    def get_execution_results(self) -> list[ExecutionResult]:
        """Get all execution results.

        Returns:
            List[ExecutionResult]: Execution results.
        """
        return self.context.results

    def get_execution_summary(self) -> dict[str, Any]:
        """Get execution summary.

        Returns:
            Dict[str, Any]: Summary statistics.
        """
        results = self.context.results

        return {
            "total": len(results),
            "ok": len([r for r in results if not r.failed and not r.skipped]),
            "failed": len([r for r in results if r.failed]),
            "skipped": len([r for r in results if r.skipped]),
            "changed": len([r for r in results if r.changed]),
        }
