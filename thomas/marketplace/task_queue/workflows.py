"""
Workflow management for task DAGs with dependency resolution.

Implements workflow support for:
- Task DAGs with dependencies
- Parallel execution branches
- Join points for synchronization
- Topological sort for dependency resolution
- Workflow state machine
- Workflow visualization
"""

import threading
from datetime import datetime
from typing import Any
from uuid import uuid4

from thomas.marketplace.task_queue._exceptions import WorkflowError
from thomas.marketplace.task_queue._types import Task, TaskResult, TaskStatus


class WorkflowNode:
    """Represents a single task in a workflow graph."""

    def __init__(
        self,
        task_id: str,
        task: Task,
        dependencies: list[str] | None = None,
    ) -> None:
        """
        Initialize a WorkflowNode.

        Args:
            task_id: Unique ID for this node.
            task: The Task to execute.
            dependencies: List of task_ids this node depends on.
        """
        self.task_id: str = task_id
        self.task: Task = task
        self.dependencies: set[str] = set(dependencies or [])
        self.status: TaskStatus = TaskStatus.PENDING
        self.result: TaskResult | None = None
        self.retry_count: int = 0

    def is_ready(self, completed_tasks: set[str]) -> bool:
        """
        Check if all dependencies are completed.

        Args:
            completed_tasks: Set of completed task IDs.

        Returns:
            True if all dependencies are completed or no dependencies exist.
        """
        return self.dependencies.issubset(completed_tasks)

    def __repr__(self) -> str:
        return f"WorkflowNode(id={self.task_id}, status={self.status.value}, " f"dependencies={len(self.dependencies)})"


class Workflow:
    """
    Manages a directed acyclic graph (DAG) of tasks with dependencies.

    Supports task scheduling based on dependency resolution using
    topological sort and provides state machine for workflow execution.
    """

    def __init__(
        self,
        workflow_id: str | None = None,
        name: str = "workflow",
    ) -> None:
        """
        Initialize a Workflow.

        Args:
            workflow_id: Unique workflow ID. Generated if not provided.
            name: Human-readable workflow name.
        """
        self.workflow_id: str = workflow_id or str(uuid4())
        self.name: str = name
        self.nodes: dict[str, WorkflowNode] = {}
        self.status: TaskStatus = TaskStatus.PENDING
        self.created_at: datetime = datetime.utcnow()
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self._lock: threading.RLock = threading.RLock()
        self._completed_tasks: set[str] = set()
        self._failed_tasks: set[str] = set()

    def add_task(
        self,
        task_id: str,
        task: Task,
        dependencies: list[str] | None = None,
    ) -> WorkflowNode:
        """
        Add a task to the workflow.

        Args:
            task_id: Unique ID for this task in the workflow.
            task: Task to add.
            dependencies: List of task_ids this task depends on.

        Returns:
            The created WorkflowNode.

        Raises:
            WorkflowError: If task_id already exists or dependencies don't exist.
        """
        with self._lock:
            if task_id in self.nodes:
                raise WorkflowError(self.workflow_id, f"Task {task_id} already exists")

            dependencies = dependencies or []
            for dep in dependencies:
                if dep not in self.nodes:
                    raise WorkflowError(
                        self.workflow_id,
                        f"Dependency {dep} does not exist",
                    )

            node = WorkflowNode(task_id, task, dependencies)
            self.nodes[task_id] = node
            return node

    def remove_task(self, task_id: str) -> bool:
        """
        Remove a task from the workflow.

        Args:
            task_id: ID of task to remove.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            if task_id not in self.nodes:
                return False

            # Check if any tasks depend on this task
            for node in self.nodes.values():
                if task_id in node.dependencies:
                    raise WorkflowError(
                        self.workflow_id,
                        f"Cannot remove {task_id}: other tasks depend on it",
                    )

            del self.nodes[task_id]
            return True

    def get_ready_tasks(self) -> list[WorkflowNode]:
        """
        Get all tasks ready to execute (dependencies satisfied).

        Returns:
            List of WorkflowNodes with all dependencies completed.
        """
        with self._lock:
            return [
                node
                for node in self.nodes.values()
                if node.status == TaskStatus.PENDING and node.is_ready(self._completed_tasks)
            ]

    def mark_completed(self, task_id: str, result: TaskResult) -> None:
        """
        Mark a task as completed.

        Args:
            task_id: ID of completed task.
            result: TaskResult from execution.

        Raises:
            WorkflowError: If task not found.
        """
        with self._lock:
            if task_id not in self.nodes:
                raise WorkflowError(self.workflow_id, f"Task {task_id} not found")

            node = self.nodes[task_id]
            node.status = TaskStatus.COMPLETED
            node.result = result
            self._completed_tasks.add(task_id)

            # Check if workflow is complete
            if self._is_complete():
                self.status = TaskStatus.COMPLETED
                self.completed_at = datetime.utcnow()

    def mark_failed(self, task_id: str, error: str) -> None:
        """
        Mark a task as failed.

        Args:
            task_id: ID of failed task.
            error: Error message.

        Raises:
            WorkflowError: If task not found.
        """
        with self._lock:
            if task_id not in self.nodes:
                raise WorkflowError(self.workflow_id, f"Task {task_id} not found")

            node = self.nodes[task_id]
            node.status = TaskStatus.FAILED
            self._failed_tasks.add(task_id)
            self.status = TaskStatus.FAILED
            self.completed_at = datetime.utcnow()

    def is_complete(self) -> bool:
        """Check if workflow is complete."""
        with self._lock:
            return self._is_complete()

    def is_failed(self) -> bool:
        """Check if workflow has failed."""
        with self._lock:
            return len(self._failed_tasks) > 0

    def get_status(self) -> dict[str, Any]:
        """
        Get current workflow status.

        Returns:
            Dictionary with workflow state information.
        """
        with self._lock:
            return {
                "workflow_id": self.workflow_id,
                "name": self.name,
                "status": self.status.value,
                "total_tasks": len(self.nodes),
                "completed_tasks": len(self._completed_tasks),
                "failed_tasks": len(self._failed_tasks),
                "pending_tasks": len(self.nodes) - len(self._completed_tasks) - len(self._failed_tasks),
                "created_at": self.created_at.isoformat(),
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            }

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """
        Get status of a specific task in the workflow.

        Args:
            task_id: ID of the task.

        Returns:
            Task status information or None if not found.
        """
        with self._lock:
            if task_id not in self.nodes:
                return None

            node = self.nodes[task_id]
            return {
                "task_id": task_id,
                "status": node.status.value,
                "dependencies": list(node.dependencies),
                "result": {
                    "output": node.result.output if node.result else None,
                    "error": node.result.error if node.result else None,
                }
                if node.result
                else None,
            }

    def topological_sort(self) -> list[str]:
        """
        Get tasks in topological order (respecting dependencies).

        Returns:
            List of task IDs in execution order.

        Raises:
            WorkflowError: If workflow contains cycles.
        """
        with self._lock:
            # Build in-degree map
            in_degree: dict[str, int] = {}
            for task_id in self.nodes:
                in_degree[task_id] = len(self.nodes[task_id].dependencies)

            # Kahn's algorithm
            queue = [task_id for task_id in self.nodes if in_degree[task_id] == 0]
            result = []

            while queue:
                current = queue.pop(0)
                result.append(current)

                # Find tasks that depend on current task
                for task_id, node in self.nodes.items():
                    if current in node.dependencies:
                        in_degree[task_id] -= 1
                        if in_degree[task_id] == 0:
                            queue.append(task_id)

            if len(result) != len(self.nodes):
                raise WorkflowError(self.workflow_id, "Workflow contains a cycle")

            return result

    def to_dict(self) -> dict[str, Any]:
        """
        Convert workflow to dictionary representation.

        Returns:
            Dictionary containing workflow structure and state.
        """
        with self._lock:
            return {
                "workflow_id": self.workflow_id,
                "name": self.name,
                "status": self.status.value,
                "tasks": {
                    task_id: {
                        "status": node.status.value,
                        "dependencies": list(node.dependencies),
                    }
                    for task_id, node in self.nodes.items()
                },
                "timestamps": {
                    "created_at": self.created_at.isoformat(),
                    "started_at": self.started_at.isoformat() if self.started_at else None,
                    "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                },
            }

    def _is_complete(self) -> bool:
        """Check if all tasks are completed or failed."""
        return len(self._completed_tasks) + len(self._failed_tasks) == len(self.nodes)

    def __repr__(self) -> str:
        return (
            f"Workflow(id={self.workflow_id}, name={self.name}, "
            f"tasks={len(self.nodes)}, status={self.status.value})"
        )
