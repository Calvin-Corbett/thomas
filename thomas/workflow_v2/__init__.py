"""Workflow engine v2 with improved execution and state management.

Provides workflow definition, execution, state persistence,
and retry policies.
"""

from .core import (
    RetryPolicy,
    Task,
    TaskStatus,
    Workflow,
    WorkflowExecutor,
    WorkflowStateStore,
    WorkflowStatus,
)

__all__ = [
    "WorkflowStatus",
    "TaskStatus",
    "RetryPolicy",
    "Task",
    "Workflow",
    "WorkflowExecutor",
    "WorkflowStateStore",
]

__version__ = "2.0.0"
