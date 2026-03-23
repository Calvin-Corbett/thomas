"""
Pipeline scheduling framework.

Implements cron-based scheduling, dependency-based triggers, SLA monitoring,
backfill support, and concurrency control.
"""

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


class CronExpression:
    """Simple cron expression parser and evaluator."""

    def __init__(self, expression: str) -> None:
        """
        Initialize cron expression.

        Args:
            expression: Cron expression (5 fields: minute hour day month dow)
        """
        self.expression = expression
        parts = expression.split()
        if len(parts) != 5:
            raise ValueError("Cron expression must have 5 fields")

        self.minute = parts[0]
        self.hour = parts[1]
        self.day = parts[2]
        self.month = parts[3]
        self.dow = parts[4]

    def should_run(self, dt: datetime) -> bool:
        """Check if should run at given datetime."""
        return (
            self._match(self.minute, dt.minute, 0, 59)
            and self._match(self.hour, dt.hour, 0, 23)
            and self._match(self.day, dt.day, 1, 31)
            and self._match(self.month, dt.month, 1, 12)
            and self._match(self.dow, dt.weekday(), 0, 6)
        )

    @staticmethod
    def _match(pattern: str, value: int, min_val: int, max_val: int) -> bool:
        """Match value against cron pattern."""
        if pattern == "*":
            return True
        if "," in pattern:
            return any(CronExpression._match(p, value, min_val, max_val) for p in pattern.split(","))
        if "/" in pattern:
            parts = pattern.split("/")
            range_part = parts[0]
            step = int(parts[1])
            if range_part == "*":
                return value % step == 0
            return False
        if "-" in pattern:
            parts = pattern.split("-")
            return int(parts[0]) <= value <= int(parts[1])
        return int(pattern) == value


@dataclass
class ScheduleRun:
    """Represents a scheduled pipeline run."""

    run_id: str
    pipeline_name: str
    scheduled_time: datetime
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    status: str = "pending"  # "pending", "running", "completed", "failed"
    record_count: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> timedelta | None:
        """Get execution duration."""
        if self.actual_start and self.actual_end:
            return self.actual_end - self.actual_start
        return None


@dataclass
class SLA:
    """Service Level Agreement specification."""

    sla_id: str
    pipeline_name: str
    max_duration: timedelta
    max_retries: int = 3
    min_success_rate: float = 0.99
    alert_threshold_minutes: int = 0  # Alert if running longer than threshold


@dataclass
class BackfillRequest:
    """Request to backfill historical data."""

    backfill_id: str
    pipeline_name: str
    start_date: datetime
    end_date: datetime
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "pending"  # "pending", "running", "completed", "failed"
    runs_completed: int = 0
    runs_total: int = 0


class PipelineScheduler:
    """
    Schedules and manages pipeline execution.

    Handles cron-based scheduling, dependency triggers, SLA monitoring,
    and backfill operations.
    """

    def __init__(self) -> None:
        """Initialize scheduler."""
        self._schedules: dict[str, CronExpression] = {}
        self._dependencies: dict[str, list[str]] = {}
        self._slas: dict[str, SLA] = {}
        self._scheduled_runs: list[ScheduleRun] = []
        self._backfill_requests: list[BackfillRequest] = []
        self._run_queue: list[tuple[datetime, str]] = []
        self._execution_history: list[ScheduleRun] = []
        self._max_concurrent_runs = 4
        self._active_runs: dict[str, ScheduleRun] = {}

    def add_schedule(self, pipeline_name: str, cron_expression: str) -> None:
        """
        Add cron-based schedule for pipeline.

        Args:
            pipeline_name: Name of pipeline
            cron_expression: Cron expression (5 fields)
        """
        try:
            self._schedules[pipeline_name] = CronExpression(cron_expression)
        except ValueError as e:
            raise ValueError(f"Invalid cron expression: {e}")

    def add_dependency(self, pipeline_name: str, depends_on: str) -> None:
        """
        Add execution dependency between pipelines.

        Args:
            pipeline_name: Pipeline to execute
            depends_on: Pipeline that must complete first
        """
        if pipeline_name not in self._dependencies:
            self._dependencies[pipeline_name] = []
        self._dependencies[pipeline_name].append(depends_on)

    def add_sla(self, sla: SLA) -> None:
        """
        Add SLA specification.

        Args:
            sla: SLA definition
        """
        self._slas[sla.sla_id] = sla

    def should_run(self, pipeline_name: str, dt: datetime) -> bool:
        """
        Check if pipeline should run at given time.

        Args:
            pipeline_name: Pipeline name
            dt: Datetime to check

        Returns:
            True if pipeline should run
        """
        if pipeline_name not in self._schedules:
            return False

        cron = self._schedules[pipeline_name]
        return cron.should_run(dt)

    def trigger_run(
        self,
        pipeline_name: str,
        scheduled_time: datetime,
        run_type: str = "scheduled",  # "scheduled", "manual", "backfill"
    ) -> ScheduleRun | None:
        """
        Trigger a pipeline run.

        Args:
            pipeline_name: Pipeline to run
            scheduled_time: Scheduled execution time
            run_type: Type of run

        Returns:
            ScheduleRun if queued, None if skipped
        """
        # Check dependencies
        if not self._dependencies_satisfied(pipeline_name):
            return None

        # Check if already running
        if self._is_running(pipeline_name):
            return None

        # Create run
        run = ScheduleRun(
            run_id=f"{pipeline_name}-{int(scheduled_time.timestamp())}",
            pipeline_name=pipeline_name,
            scheduled_time=scheduled_time,
        )

        self._scheduled_runs.append(run)
        heapq.heappush(self._run_queue, (scheduled_time, run.run_id))

        return run

    def _dependencies_satisfied(self, pipeline_name: str) -> bool:
        """Check if all dependencies are satisfied."""
        deps = self._dependencies.get(pipeline_name, [])

        for dep in deps:
            # Check if dependency completed recently
            if not self._last_run_succeeded(dep):
                return False

        return True

    def _last_run_succeeded(self, pipeline_name: str) -> bool:
        """Check if last run of pipeline succeeded."""
        history = [r for r in self._execution_history if r.pipeline_name == pipeline_name]
        if not history:
            return True  # No history, assume ok

        last_run = max(history, key=lambda r: r.scheduled_time)
        return last_run.status == "completed"

    def _is_running(self, pipeline_name: str) -> bool:
        """Check if pipeline is currently running."""
        for run in self._active_runs.values():
            if run.pipeline_name == pipeline_name:
                return True
        return False

    def get_next_run(self) -> ScheduleRun | None:
        """Get next run from queue."""
        if not self._run_queue:
            return None

        scheduled_time, run_id = heapq.heappop(self._run_queue)

        # Find the run
        for run in self._scheduled_runs:
            if run.run_id == run_id:
                # Check concurrency limit
                if len(self._active_runs) >= self._max_concurrent_runs:
                    heapq.heappush(self._run_queue, (scheduled_time, run_id))
                    return None

                # Mark as running
                run.status = "running"
                run.actual_start = datetime.utcnow()
                self._active_runs[run_id] = run
                return run

        return None

    def complete_run(
        self,
        run_id: str,
        status: str = "completed",
        record_count: int = 0,
        error: str | None = None,
    ) -> None:
        """
        Mark run as complete.

        Args:
            run_id: Run identifier
            status: Final status
            record_count: Records processed
            error: Error message if failed
        """
        if run_id in self._active_runs:
            run = self._active_runs[run_id]
            run.status = status
            run.actual_end = datetime.utcnow()
            run.record_count = record_count
            run.error = error

            self._execution_history.append(run)
            del self._active_runs[run_id]

    def request_backfill(
        self,
        pipeline_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> BackfillRequest:
        """
        Request backfill for historical date range.

        Args:
            pipeline_name: Pipeline to backfill
            start_date: Start date
            end_date: End date

        Returns:
            BackfillRequest
        """
        request = BackfillRequest(
            backfill_id=f"backfill-{pipeline_name}-{int(start_date.timestamp())}",
            pipeline_name=pipeline_name,
            start_date=start_date,
            end_date=end_date,
        )

        # Calculate number of runs
        request.runs_total = (end_date - start_date).days + 1

        self._backfill_requests.append(request)

        # Queue backfill runs
        current = start_date
        while current <= end_date:
            self.trigger_run(pipeline_name, current, "backfill")
            current += timedelta(days=1)

        return request

    def get_execution_history(
        self,
        pipeline_name: str | None = None,
        limit: int = 100,
    ) -> list[ScheduleRun]:
        """
        Get execution history.

        Args:
            pipeline_name: Optional filter by pipeline
            limit: Maximum results

        Returns:
            List of execution runs
        """
        history = self._execution_history
        if pipeline_name:
            history = [r for r in history if r.pipeline_name == pipeline_name]

        return sorted(history, key=lambda r: r.scheduled_time, reverse=True)[:limit]

    def check_sla_violations(self) -> list[tuple[str, str]]:
        """
        Check for SLA violations.

        Returns:
            List of (pipeline_name, violation_message) tuples
        """
        violations = []

        for sla_id, sla in self._slas.items():
            recent_runs = [
                r
                for r in self._execution_history
                if r.pipeline_name == sla.pipeline_name and r.actual_start and r.actual_end
            ][-10:]

            if not recent_runs:
                continue

            # Check success rate
            successful = sum(1 for r in recent_runs if r.status == "completed")
            success_rate = successful / len(recent_runs) if recent_runs else 0

            if success_rate < sla.min_success_rate:
                violations.append(
                    (sla.pipeline_name, f"Success rate {success_rate:.2%} below SLA {sla.min_success_rate:.2%}")
                )

            # Check duration
            for run in recent_runs:
                if run.duration and run.duration > sla.max_duration:
                    violations.append(
                        (sla.pipeline_name, f"Run duration {run.duration} exceeds SLA {sla.max_duration}")
                    )

        return violations

    def get_schedule_conflicts(self) -> list[tuple[str, str]]:
        """
        Detect schedule conflicts between pipelines.

        Returns:
            List of (pipeline_name1, pipeline_name2) conflicts
        """
        conflicts = []

        pipelines = list(self._schedules.keys())
        test_time = datetime.utcnow()

        for i, p1 in enumerate(pipelines):
            for p2 in pipelines[i + 1 :]:
                if self.should_run(p1, test_time) and self.should_run(p2, test_time):
                    conflicts.append((p1, p2))

        return conflicts

    def get_schedule_info(self, pipeline_name: str) -> dict[str, Any]:
        """Get schedule information for pipeline."""
        return {
            "pipeline": pipeline_name,
            "cron": self._schedules.get(pipeline_name, {}).expression if pipeline_name in self._schedules else None,
            "dependencies": self._dependencies.get(pipeline_name, []),
            "next_run": self._get_next_scheduled_time(pipeline_name),
            "recent_runs": [
                {
                    "run_id": r.run_id,
                    "status": r.status,
                    "scheduled": r.scheduled_time.isoformat(),
                    "duration": str(r.duration) if r.duration else None,
                }
                for r in self.get_execution_history(pipeline_name, limit=5)
            ],
        }

    def _get_next_scheduled_time(self, pipeline_name: str) -> str | None:
        """Get next scheduled run time."""
        if pipeline_name not in self._schedules:
            return None

        cron = self._schedules[pipeline_name]
        now = datetime.utcnow()

        for i in range(1440):  # Check next 24 hours
            check_time = now + timedelta(minutes=i)
            if cron.should_run(check_time):
                return check_time.isoformat()

        return None

    def set_max_concurrency(self, max_concurrent: int) -> None:
        """Set maximum concurrent pipeline runs."""
        self._max_concurrent_runs = max_concurrent
