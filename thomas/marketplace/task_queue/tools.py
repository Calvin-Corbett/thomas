"""Tools for task_queue module - background task scheduling."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class TaskQueueEnqueueTool(Tool):
    """Enqueue a task."""

    name = "task_queue_enqueue"
    category = "task_queue"
    description = "Add a task to the queue for execution."
    parameters = {
        "type": "object",
        "properties": {
            "task_name": {
                "type": "string",
                "description": "Task name/type",
            },
            "payload": {
                "type": "object",
                "description": "Task payload",
            },
            "priority": {
                "type": "integer",
                "description": "Priority (default: 0)",
            },
            "delay_seconds": {
                "type": "integer",
                "description": "Delay before execution in seconds",
            },
        },
        "required": ["task_name"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .queue import enqueue_task

            task_id = enqueue_task(
                task_name=args["task_name"],
                payload=args.get("payload", {}),
                priority=args.get("priority", 0),
                delay_seconds=args.get("delay_seconds", 0),
            )
            return ToolResult(ok=True, data={"task_id": task_id, "queued": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TaskQueueGetStatusTool(Tool):
    """Get task status."""

    name = "task_queue_get_status"
    category = "task_queue"
    description = "Get the status of an enqueued task."
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID",
            },
        },
        "required": ["task_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .queue import get_task_status

            status = get_task_status(args["task_id"])
            return ToolResult(ok=True, data=status or {"status": "unknown"})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TaskQueueCancelTool(Tool):
    """Cancel a task."""

    name = "task_queue_cancel"
    category = "task_queue"
    description = "Cancel an enqueued task."
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID to cancel",
            },
        },
        "required": ["task_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .queue import cancel_task

            cancel_task(args["task_id"])
            return ToolResult(ok=True, data={"cancelled": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TaskQueueListTool(Tool):
    """List queued tasks."""

    name = "task_queue_list"
    category = "task_queue"
    description = "List pending and running tasks."
    parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Filter by status (pending, running, completed, failed)",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default: 50)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .queue import list_tasks

            tasks = list_tasks(
                status=args.get("status"),
                limit=args.get("limit", 50),
            )
            return ToolResult(ok=True, data={"tasks": tasks or []})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_task_queue_tools(registry):
    """Register task_queue tools with the tool registry."""
    tools = [
        TaskQueueEnqueueTool(),
        TaskQueueGetStatusTool(),
        TaskQueueCancelTool(),
        TaskQueueListTool(),
    ]
    for tool in tools:
        registry.register(tool)
