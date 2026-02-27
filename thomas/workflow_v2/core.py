"""Workflow engine v2 with improved execution and state management.

Provides workflow definition, execution, state persistence, and retry policies.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class WorkflowStatus(Enum):
    """Workflow status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class TaskStatus(Enum):
    """Task status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


@dataclass
class RetryPolicy:
    """Retry policy for tasks."""

    max_attempts: int = 3
    backoff_seconds: int = 1
    backoff_multiplier: float = 2.0
    max_backoff_seconds: int = 300


@dataclass
class Task:
    """Workflow task."""

    name: str
    handler: Callable
    status: TaskStatus = TaskStatus.PENDING
    result: Any | None = None
    error: str | None = None
    attempts: int = 0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    depends_on: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    async def execute(self) -> Any:
        """Execute task."""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.utcnow()
        self.attempts += 1

        try:
            self.result = await self.handler()
            self.status = TaskStatus.SUCCESS
            self.completed_at = datetime.utcnow()
            return self.result
        except Exception as e:
            self.error = str(e)
            self.status = TaskStatus.FAILED
            self.completed_at = datetime.utcnow()
            raise


@dataclass
class Workflow:
    """Workflow definition."""

    name: str
    version: str
    tasks: dict[str, Task] = field(default_factory=dict)
    status: WorkflowStatus = WorkflowStatus.PENDING
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    context: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)

    def add_task(self, task: Task) -> None:
        """Add task to workflow."""
        self.tasks[task.name] = task

    def get_task(self, name: str) -> Task | None:
        """Get task by name."""
        return self.tasks.get(name)

    def get_ready_tasks(self) -> list[Task]:
        """Get tasks ready to execute."""
        ready = []
        for task in self.tasks.values():
            if task.status != TaskStatus.PENDING:
                continue

            # Check dependencies
            deps_satisfied = True
            for dep in task.depends_on:
                dep_task = self.get_task(dep)
                if not dep_task or dep_task.status != TaskStatus.SUCCESS:
                    deps_satisfied = False
                    break

            if deps_satisfied:
                ready.append(task)

        return ready


class WorkflowExecutor:
    """Executes workflows."""

    def __init__(self):
        self.workflows: dict[str, Workflow] = {}
        self.execution_history: list[dict[str, Any]] = []

    async def execute_workflow(self, workflow: Workflow) -> Workflow:
        """Execute workflow."""
        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = datetime.utcnow()
        self.workflows[workflow.execution_id] = workflow

        try:
            while True:
                ready_tasks = workflow.get_ready_tasks()
                if not ready_tasks:
                    break

                for task in ready_tasks:
                    try:
                        await task.execute()
                        workflow.results[task.name] = task.result
                    except Exception:
                        # Handle retry
                        if task.attempts < task.retry_policy.max_attempts:
                            task.status = TaskStatus.RETRYING
                            await task.execute()
                        else:
                            workflow.status = WorkflowStatus.FAILED
                            raise

            workflow.status = WorkflowStatus.COMPLETED
            workflow.completed_at = datetime.utcnow()

            self.execution_history.append(
                {
                    "workflow": workflow.name,
                    "execution_id": workflow.execution_id,
                    "status": "completed",
                    "timestamp": datetime.utcnow(),
                }
            )

            return workflow

        except Exception as e:
            workflow.status = WorkflowStatus.FAILED
            self.execution_history.append(
                {
                    "workflow": workflow.name,
                    "execution_id": workflow.execution_id,
                    "status": "failed",
                    "error": str(e),
                    "timestamp": datetime.utcnow(),
                }
            )
            return workflow

    def get_workflow(self, execution_id: str) -> Workflow | None:
        """Get workflow by execution ID."""
        return self.workflows.get(execution_id)

    def get_execution_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get execution history."""
        return self.execution_history[-limit:]


class WorkflowStateStore:
    """Persists workflow state."""

    def __init__(self):
        self.states: dict[str, dict[str, Any]] = {}

    def save_state(self, workflow_id: str, state: dict[str, Any]) -> None:
        """Save workflow state."""
        self.states[workflow_id] = state

    def load_state(self, workflow_id: str) -> dict[str, Any] | None:
        """Load workflow state."""
        return self.states.get(workflow_id)

    def delete_state(self, workflow_id: str) -> bool:
        """Delete workflow state."""
        if workflow_id in self.states:
            del self.states[workflow_id]
            return True
        return False

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        """Get all workflow states."""
        return self.states.copy()
