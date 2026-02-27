"""Tools for job scheduling operations."""

from datetime import datetime
from typing import Any

from thomas.jobs import core
from thomas.tools.base import Tool, ToolResult


class JobManagementTool(Tool):
    """Manage scheduled jobs."""

    name = "jobs_management"
    category = "jobs"
    description = "Register and manage scheduled jobs"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["register_job", "schedule_job", "list_jobs", "job_stats"],
                "description": "Job action",
            },
            "job_id": {"type": "string", "description": "Job identifier"},
            "name": {"type": "string", "description": "Job name"},
            "job_type": {"type": "string", "enum": ["one_shot", "recurring", "cron"], "description": "Job type"},
            "schedule": {"type": "string", "description": "Schedule/cron expression"},
            "max_retries": {"type": "integer", "description": "Maximum retries"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.scheduler = core.Scheduler()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "register_job":
                job_id = args.get("job_id", "")
                name = args.get("name", "")
                job_type = args.get("job_type", "one_shot")
                schedule = args.get("schedule")
                max_retries = args.get("max_retries", 0)

                if not job_id or not name:
                    return ToolResult(ok=False, error="job_id and name required")

                definition = core.JobDefinition(
                    job_id=job_id, name=name, job_type=job_type, schedule=schedule, max_retries=max_retries
                )
                self.scheduler.register_job(definition)
                return ToolResult(ok=True, data={"job_id": job_id, "registered": True})

            elif action == "schedule_job":
                job_id = args.get("job_id", "")
                if not job_id:
                    return ToolResult(ok=False, error="job_id required")

                self.scheduler.schedule_job(job_id, datetime.now())
                return ToolResult(ok=True, data={"scheduled": True})

            elif action == "list_jobs":
                jobs = [
                    {
                        "id": j.definition.job_id,
                        "name": j.definition.name,
                        "type": j.definition.job_type,
                        "enabled": j.definition.enabled,
                    }
                    for j in self.scheduler.jobs.values()
                ]
                return ToolResult(ok=True, data={"jobs": jobs, "count": len(jobs)})

            elif action == "job_stats":
                job_id = args.get("job_id", "")
                if not job_id:
                    return ToolResult(ok=False, error="job_id required")

                job = self.scheduler.get_job(job_id)
                if not job:
                    return ToolResult(ok=False, error=f"Job {job_id} not found")

                stats = job.get_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class JobExecutionTool(Tool):
    """Execute and monitor jobs."""

    name = "jobs_execution"
    category = "jobs"
    description = "Execute jobs and monitor execution"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["execute_job", "get_ready_jobs", "get_execution_history", "scheduler_stats"],
                "description": "Execution action",
            },
            "job_id": {"type": "string", "description": "Job identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.scheduler = core.Scheduler()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "execute_job":
                job_id = args.get("job_id", "")
                if not job_id:
                    return ToolResult(ok=False, error="job_id required")

                execution = await self.scheduler.execute_job(job_id)
                return ToolResult(
                    ok=True,
                    data={
                        "execution_id": execution.execution_id,
                        "status": execution.status.value,
                        "duration_seconds": execution.duration_seconds,
                    },
                )

            elif action == "get_ready_jobs":
                ready = self.scheduler.get_ready_jobs()
                return ToolResult(ok=True, data={"ready_jobs": ready, "count": len(ready)})

            elif action == "get_execution_history":
                job_id = args.get("job_id", "")
                if not job_id:
                    return ToolResult(ok=False, error="job_id required")

                job = self.scheduler.get_job(job_id)
                if not job:
                    return ToolResult(ok=False, error=f"Job {job_id} not found")

                history = [
                    {"execution_id": e.execution_id, "status": e.status.value, "duration": e.duration_seconds}
                    for e in job.executions
                ]
                return ToolResult(ok=True, data={"history": history, "count": len(history)})

            elif action == "scheduler_stats":
                stats = self.scheduler.get_scheduler_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_jobs_tools(registry):
    """Register all job scheduling tools."""
    registry.register(JobManagementTool())
    registry.register(JobExecutionTool())
