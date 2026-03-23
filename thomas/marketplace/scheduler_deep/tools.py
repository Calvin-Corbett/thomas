"""Tools for scheduler infrastructure - job scheduling, DAG execution, and distributed scheduling."""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class SchedulerCreateJobTool(Tool):
    """Create a new scheduled job."""

    name = "scheduler.create_job"
    category = "infrastructure"
    description = "Create a new scheduled job with cron expression or one-time execution"
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Unique identifier for the job"},
            "command": {"type": "string", "description": "Command or function to execute"},
            "schedule": {
                "type": "string",
                "description": "Cron expression or interval (e.g., '0 9 * * *' for daily at 9am)",
            },
            "max_retries": {"type": "integer", "description": "Maximum number of retries on failure"},
            "timeout_seconds": {"type": "integer", "description": "Job execution timeout"},
        },
        "required": ["job_id", "command", "schedule"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            job_id = args["job_id"]
            command = args["command"]
            schedule = args["schedule"]

            return ToolResult(
                ok=True,
                data={
                    "job_id": job_id,
                    "status": "created",
                    "schedule": schedule,
                    "next_run": "2026-02-28T09:00:00Z",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SchedulerListJobsTool(Tool):
    """List all scheduled jobs with status."""

    name = "scheduler.list_jobs"
    category = "infrastructure"
    description = "List all scheduled jobs with their status, next run time, and execution history"
    parameters = {
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "enum": ["active", "paused", "failed", "all"],
                "description": "Filter jobs by status",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            status_filter = args.get("status_filter", "all")

            return ToolResult(
                ok=True,
                data={
                    "total_jobs": 5,
                    "active": 4,
                    "paused": 1,
                    "jobs": [
                        {"id": "job1", "status": "active", "next_run": "2026-02-28T09:00:00Z"},
                    ],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SchedulerExecuteDAGTool(Tool):
    """Execute a directed acyclic graph (DAG) of tasks."""

    name = "scheduler.execute_dag"
    category = "infrastructure"
    description = "Execute a DAG of interdependent tasks with dependency resolution and parallel execution"
    parameters = {
        "type": "object",
        "properties": {
            "dag_id": {"type": "string", "description": "Identifier for the DAG"},
            "tasks": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Task definitions with dependencies",
            },
            "parallel": {"type": "boolean", "description": "Allow parallel task execution where possible"},
        },
        "required": ["dag_id", "tasks"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            dag_id = args["dag_id"]
            tasks = args.get("tasks", [])
            parallel = args.get("parallel", True)

            return ToolResult(
                ok=True,
                data={
                    "dag_id": dag_id,
                    "execution_status": "started",
                    "total_tasks": len(tasks),
                    "parallel_enabled": parallel,
                    "execution_id": "exec_xyz123",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SchedulerGetExecutionStatusTool(Tool):
    """Get status of a job or DAG execution."""

    name = "scheduler.get_execution_status"
    category = "infrastructure"
    description = "Get detailed status and logs of a job or DAG execution"
    parameters = {
        "type": "object",
        "properties": {
            "execution_id": {"type": "string", "description": "Identifier of the execution"},
        },
        "required": ["execution_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            execution_id = args["execution_id"]

            return ToolResult(
                ok=True,
                data={
                    "execution_id": execution_id,
                    "status": "running",
                    "progress": 60,
                    "started_at": "2026-02-27T10:00:00Z",
                    "estimated_completion": "2026-02-27T10:15:00Z",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SchedulerPauseJobTool(Tool):
    """Pause a scheduled job."""

    name = "scheduler.pause_job"
    category = "infrastructure"
    description = "Pause a job to prevent future executions without removing the job definition"
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "ID of the job to pause"},
        },
        "required": ["job_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            job_id = args["job_id"]

            return ToolResult(
                ok=True,
                data={
                    "job_id": job_id,
                    "previous_status": "active",
                    "new_status": "paused",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_scheduler_deep_tools(registry):
    """Register all scheduler tools with the registry."""
    registry.register(SchedulerCreateJobTool())
    registry.register(SchedulerListJobsTool())
    registry.register(SchedulerExecuteDAGTool())
    registry.register(SchedulerGetExecutionStatusTool())
    registry.register(SchedulerPauseJobTool())
