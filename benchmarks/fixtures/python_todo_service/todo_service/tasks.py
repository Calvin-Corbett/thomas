from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Task:
    title: str
    priority: str
    completed: bool = False


def sample_tasks() -> list[Task]:
    return [
        Task(title="Ship benchmark runner", priority="high", completed=False),
        Task(title="Split failing tests", priority="medium", completed=True),
        Task(title="Write report summary", priority="high", completed=False),
        Task(title="Clean stale runtime output", priority="low", completed=False),
    ]


def format_task(task: Task) -> str:
    marker = "x" if task.completed else " "
    return f"[{marker}] {task.title} ({task.priority})"


def summarize_tasks(tasks: list[Task]) -> dict[str, Any]:
    raise NotImplementedError("priority summary feature not implemented yet")
