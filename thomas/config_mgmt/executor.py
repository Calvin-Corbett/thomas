"""Task execution engine."""

import time
from datetime import datetime
from typing import Any

from thomas.config_mgmt._exceptions import (
    HostUnreachableError,
    TaskFailedError,
)
from thomas.config_mgmt._types import (
    ExecutionResult,
    Host,
    State,
    Task,
)
from thomas.config_mgmt.playbook import ExecutionContext


class TaskExecutor:
    """Executes tasks with error handling and retries."""

    def __init__(self, module_registry: Any) -> None:
        """Initialize task executor.

        Args:
            module_registry: Module registry for task execution.
        """
        self.module_registry = module_registry
        self.execution_history: list[ExecutionResult] = []

    def execute(
        self,
        task: Task,
        host: Host,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute task on host with retry logic.

        Args:
            task: Task to execute.
            host: Target host.
            context: Execution context.

        Returns:
            ExecutionResult: Execution result.

        Raises:
            ExecutionError: If task execution fails.
        """
        start_time = time.time()
        last_error: Exception | None = None

        for attempt in range(1, task.retries + 1):
            if attempt > 1 and task.delay > 0:
                time.sleep(task.delay)

            try:
                result = self.module_registry.execute(
                    task,
                    host,
                    context,
                )

                # Check failed_when condition
                if task.failed_when:
                    if self._evaluate_condition(task.failed_when, context):
                        result.failed = True
                        result.status = "failed"

                # Check changed_when condition
                if task.changed_when:
                    result.changed = self._evaluate_condition(task.changed_when, context)

                result.attempts = attempt
                result.duration = time.time() - start_time

                self.execution_history.append(result)
                return result

            except Exception as e:
                last_error = e
                if attempt == task.retries:
                    break
                continue

        # All retries exhausted
        if task.ignore_errors:
            result = ExecutionResult(
                task_name=task.name,
                host=host.hostname,
                status="ok",
                module=task.module,
                stderr=str(last_error),
                failed=False,
                attempts=task.retries,
            )
        else:
            raise TaskFailedError(
                task_name=task.name,
                host=host.hostname,
                stderr=str(last_error),
            )

        result.duration = time.time() - start_time
        self.execution_history.append(result)
        return result

    @staticmethod
    def _evaluate_condition(condition: str, context: ExecutionContext) -> bool:
        """Evaluate condition expression.

        Args:
            condition: Condition to evaluate.
            context: Execution context.

        Returns:
            bool: Condition result.
        """
        # Simple variable existence check
        if condition in context.variables:
            return bool(context.variables[condition])

        # Simple comparison
        if "==" in condition:
            left, right = condition.split("==", 1)
            left_val = context.variables.get(left.strip())
            right_val = right.strip().strip("'\"")
            return left_val == right_val

        return False

    def get_execution_history(self) -> list[ExecutionResult]:
        """Get execution history.

        Returns:
            List[ExecutionResult]: Execution history.
        """
        return self.execution_history.copy()

    def clear_history(self) -> None:
        """Clear execution history."""
        self.execution_history.clear()


class HostConnector:
    """Manages host connections and state tracking."""

    def __init__(self) -> None:
        """Initialize host connector."""
        self.host_states: dict[str, State] = {}
        self.connection_cache: dict[str, Any] = {}

    def establish_connection(self, host: Host) -> None:
        """Establish connection to host.

        Args:
            host: Host to connect to.

        Raises:
            HostUnreachableError: If connection fails.
        """
        try:
            # Simulate connection establishment
            host.connection.state = State.REACHABLE
            host.connection.last_connected = datetime.now()
            self.host_states[host.hostname] = State.REACHABLE
        except Exception as e:
            host.connection.state = State.UNREACHABLE
            self.host_states[host.hostname] = State.UNREACHABLE
            raise HostUnreachableError(f"Cannot connect to {host.hostname}: {e}")

    def close_connection(self, host: Host) -> None:
        """Close connection to host.

        Args:
            host: Host to disconnect.
        """
        if host.hostname in self.connection_cache:
            del self.connection_cache[host.hostname]

    def is_host_reachable(self, host: Host) -> bool:
        """Check if host is reachable.

        Args:
            host: Host to check.

        Returns:
            bool: True if reachable.
        """
        return self.host_states.get(host.hostname) == State.REACHABLE

    def get_host_state(self, hostname: str) -> State:
        """Get host connection state.

        Args:
            hostname: Hostname.

        Returns:
            State: Host state.
        """
        return self.host_states.get(hostname, State.UNKNOWN)
