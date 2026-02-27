"""Tools for ETL monitoring."""

from datetime import datetime
from typing import Any

from thomas.etl_monitor import core
from thomas.tools.base import Tool, ToolResult


class JobMonitoringTool(Tool):
    """Monitor ETL job execution and metrics."""

    name = "etl_monitor_jobs"
    category = "etl_monitor"
    description = "Monitor ETL job execution and record metrics"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["register_job", "record_execution", "job_stats", "check_sla"],
                "description": "Monitoring action",
            },
            "job_id": {"type": "string", "description": "Job identifier"},
            "name": {"type": "string", "description": "Job name"},
            "source": {"type": "string", "description": "Source system"},
            "target": {"type": "string", "description": "Target system"},
            "status": {
                "type": "string",
                "enum": ["pending", "running", "success", "failed", "skipped"],
                "description": "Execution status",
            },
            "rows_processed": {"type": "integer", "description": "Rows processed"},
            "rows_failed": {"type": "integer", "description": "Rows failed"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.store = core.MonitoringStore()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "register_job":
                job_id = args.get("job_id", "")
                name = args.get("name", "")
                source = args.get("source", "")
                target = args.get("target", "")

                if not all([job_id, name, source, target]):
                    return ToolResult(ok=False, error="job_id, name, source, target required")

                job = core.ETLJob(job_id, name, source, target)
                self.store.register_job(job)
                return ToolResult(ok=True, data={"job_id": job_id, "registered": True})

            elif action == "record_execution":
                job_id = args.get("job_id", "")
                status_str = args.get("status", "success")
                rows_processed = args.get("rows_processed", 0)
                rows_failed = args.get("rows_failed", 0)

                if not job_id:
                    return ToolResult(ok=False, error="job_id required")

                metrics = core.JobMetrics(
                    job_id=job_id,
                    start_time=datetime.now(),
                    end_time=datetime.now(),
                    status=core.JobStatus(status_str),
                    rows_processed=rows_processed,
                    rows_failed=rows_failed,
                )
                self.store.record_execution(job_id, metrics)
                return ToolResult(ok=True, data={"recorded": True})

            elif action == "job_stats":
                job_id = args.get("job_id", "")
                if not job_id:
                    return ToolResult(ok=False, error="job_id required")

                job = self.store.jobs.get(job_id)
                if not job:
                    return ToolResult(ok=False, error=f"Job {job_id} not found")

                stats = job.get_stats()
                return ToolResult(ok=True, data=stats)

            elif action == "check_sla":
                job_id = args.get("job_id", "")
                if not job_id:
                    return ToolResult(ok=False, error="job_id required")

                job = self.store.jobs.get(job_id)
                if not job:
                    return ToolResult(ok=False, error=f"Job {job_id} not found")

                sla_check = job.check_sla()
                return ToolResult(ok=True, data=sla_check)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DataFreshnessTool(Tool):
    """Monitor data freshness and staleness."""

    name = "etl_monitor_freshness"
    category = "etl_monitor"
    description = "Monitor dataset freshness and update timestamps"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["register_dataset", "update_freshness", "check_freshness", "list_stale"],
                "description": "Freshness action",
            },
            "dataset_id": {"type": "string", "description": "Dataset identifier"},
            "max_age_hours": {"type": "integer", "description": "Maximum acceptable age in hours"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.store = core.MonitoringStore()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            dataset_id = args.get("dataset_id", "")
            max_age_hours = args.get("max_age_hours", 24)

            if action == "register_dataset":
                if not dataset_id:
                    return ToolResult(ok=False, error="dataset_id required")
                self.store.register_dataset(dataset_id, max_age_hours)
                return ToolResult(ok=True, data={"dataset_id": dataset_id, "registered": True})

            elif action == "update_freshness":
                if not dataset_id:
                    return ToolResult(ok=False, error="dataset_id required")
                self.store.update_freshness(dataset_id)
                return ToolResult(ok=True, data={"dataset_id": dataset_id, "updated": True})

            elif action == "check_freshness":
                if not dataset_id:
                    return ToolResult(ok=False, error="dataset_id required")
                freshness = self.store.freshness.get(dataset_id)
                if not freshness:
                    return ToolResult(ok=False, error=f"Dataset {dataset_id} not registered")
                return ToolResult(
                    ok=True,
                    data={
                        "dataset_id": dataset_id,
                        "is_fresh": freshness.is_fresh,
                        "age_hours": round(freshness.age_hours, 2),
                        "freshness_percentage": round(freshness.freshness_percentage, 1),
                    },
                )

            elif action == "list_stale":
                stale = self.store.get_stale_datasets()
                return ToolResult(ok=True, data={"stale_datasets": stale, "count": len(stale)})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_etl_monitor_tools(registry):
    """Register all ETL monitoring tools."""
    registry.register(JobMonitoringTool())
    registry.register(DataFreshnessTool())
