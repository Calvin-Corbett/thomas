"""
Task scheduler for cron-based and interval scheduling.

Implements scheduling support for:
- Cron expressions
- Interval-based scheduling
- One-shot scheduled tasks
- Timezone-aware scheduling
- Schedule persistence
- Next-run time calculation
"""

import threading
import time
from datetime import datetime, timedelta

from thomas.task_queue._exceptions import SchedulerError
from thomas.task_queue._types import Task
from thomas.task_queue.queue import TaskQueue


class CronParser:
    """Parses and evaluates cron expressions."""

    CRON_PATTERN = (
        r"^(\*|([0-9]|1[0-9]|2[0-9]|3[0-9]|4[0-9]|5[0-9])|\*\/([0-9]|[1-5][0-9])) "
        r"(\*|([0-9]|1[0-9]|2[0-3])|\*\/([0-9]|1[0-9]|2[0-3])) "
        r"(\*|([1-9]|1[0-9]|2[0-9]|3[0-1])|\*\/([1-9]|1[0-9]|2[0-9]|3[0-1])) "
        r"(\*|([1-9]|1[0-2])|\*\/([1-9]|1[0-2])) "
        r"(\*|([0-6])|\*\/[0-6])$"
    )

    def __init__(self, expression: str) -> None:
        """
        Initialize a CronParser.

        Args:
            expression: Cron expression (5 fields: minute hour day month weekday).

        Raises:
            SchedulerError: If expression is invalid.
        """
        self.expression: str = expression
        self._parse()

    def _parse(self) -> None:
        """Parse and validate the cron expression."""
        parts = self.expression.split()
        if len(parts) != 5:
            raise SchedulerError(
                f"Invalid cron expression: {self.expression}. "
                "Must have exactly 5 fields (minute hour day month weekday)"
            )

        try:
            self.minutes = self._parse_field(parts[0], 0, 59)
            self.hours = self._parse_field(parts[1], 0, 23)
            self.days = self._parse_field(parts[2], 1, 31)
            self.months = self._parse_field(parts[3], 1, 12)
            self.weekdays = self._parse_field(parts[4], 0, 6)
        except ValueError as e:
            raise SchedulerError(f"Invalid cron expression: {e}")

    def _parse_field(self, field: str, min_val: int, max_val: int) -> set[int]:
        """
        Parse a single cron field.

        Args:
            field: Field string (e.g., "*", "5", "*/5", "1-5").
            min_val: Minimum value for this field.
            max_val: Maximum value for this field.

        Returns:
            Set of valid values for this field.
        """
        if field == "*":
            return set(range(min_val, max_val + 1))

        if "/" in field:
            base, step = field.split("/")
            step = int(step)
            if base == "*":
                return set(range(min_val, max_val + 1, step))
            else:
                start = int(base)
                return set(range(start, max_val + 1, step))

        if "-" in field:
            start, end = field.split("-")
            return set(range(int(start), int(end) + 1))

        return {int(field)}

    def matches(self, dt: datetime) -> bool:
        """
        Check if a datetime matches this cron expression.

        Args:
            dt: Datetime to check.

        Returns:
            True if datetime matches the cron expression.
        """
        return (
            dt.minute in self.minutes
            and dt.hour in self.hours
            and dt.day in self.days
            and dt.month in self.months
            and dt.weekday() in self.weekdays
        )

    def next_run(self, after: datetime) -> datetime:
        """
        Calculate the next scheduled run time.

        Args:
            after: Find next run after this datetime.

        Returns:
            Next datetime matching the cron expression.
        """
        current = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # Limit search to 4 years in the future
        deadline = after + timedelta(days=1460)

        while current <= deadline:
            if self.matches(current):
                return current
            current += timedelta(minutes=1)

        raise SchedulerError(f"No matching time found for expression: {self.expression}")


class TaskScheduler:
    """
    Manages scheduled task execution with cron and interval support.

    Periodically checks for scheduled tasks that are ready to run and
    enqueues them into the task queue.
    """

    def __init__(self, queue: TaskQueue, poll_interval: float = 60.0) -> None:
        """
        Initialize a TaskScheduler.

        Args:
            queue: TaskQueue to enqueue scheduled tasks into.
            poll_interval: How often to check for scheduled tasks (seconds).
        """
        self.queue: TaskQueue = queue
        self.poll_interval: float = poll_interval

        self._scheduled_tasks: dict[str, Task] = {}
        self._cron_parsers: dict[str, CronParser] = {}
        self._next_run_times: dict[str, datetime] = {}
        self._running: bool = False
        self._lock: threading.RLock = threading.RLock()

    def add_scheduled_task(self, task: Task) -> None:
        """
        Add a task with schedule to the scheduler.

        Args:
            task: Task with schedule configuration.

        Raises:
            SchedulerError: If schedule is invalid.
        """
        if not task.schedule:
            raise SchedulerError("Task must have schedule configuration")

        with self._lock:
            task_id = str(task.task_id)
            self._scheduled_tasks[task_id] = task

            if task.schedule.cron_expression:
                parser = CronParser(task.schedule.cron_expression)
                self._cron_parsers[task_id] = parser
                self._next_run_times[task_id] = parser.next_run(datetime.utcnow())
            elif task.schedule.interval_seconds:
                self._next_run_times[task_id] = datetime.utcnow() + timedelta(seconds=task.schedule.interval_seconds)
            elif task.schedule.one_shot_at:
                self._next_run_times[task_id] = task.schedule.one_shot_at

    def remove_scheduled_task(self, task_id: str) -> bool:
        """
        Remove a scheduled task.

        Args:
            task_id: ID of the scheduled task.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            if task_id in self._scheduled_tasks:
                del self._scheduled_tasks[task_id]
                self._cron_parsers.pop(task_id, None)
                self._next_run_times.pop(task_id, None)
                return True
        return False

    def start(self) -> None:
        """Start the scheduler."""
        with self._lock:
            if self._running:
                raise SchedulerError("Scheduler already running")
            self._running = True

        self._scheduler_thread = threading.Thread(
            target=self._run_loop,
            daemon=False,
            name="task-scheduler",
        )
        self._scheduler_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the scheduler gracefully.

        Args:
            timeout: Seconds to wait for scheduler to stop.
        """
        with self._lock:
            self._running = False

        if hasattr(self, "_scheduler_thread"):
            self._scheduler_thread.join(timeout=timeout)

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        with self._lock:
            return self._running

    def get_next_runs(self) -> dict[str, datetime]:
        """Get the next scheduled run time for all tasks."""
        with self._lock:
            return dict(self._next_run_times)

    def _run_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                self._check_and_enqueue_tasks()
                time.sleep(self.poll_interval)
            except Exception as e:
                self._log_error(f"Scheduler error: {e}")

    def _check_and_enqueue_tasks(self) -> None:
        """Check for tasks ready to run and enqueue them."""
        now = datetime.utcnow()

        with self._lock:
            tasks_to_run = [
                (task_id, task)
                for task_id, task in self._scheduled_tasks.items()
                if self._next_run_times.get(task_id, datetime.max) <= now
            ]

        for task_id, task in tasks_to_run:
            try:
                # Create a new task instance for this run
                run_task = Task(
                    name=task.name,
                    func=task.func,
                    args=task.args,
                    kwargs=task.kwargs,
                    priority=task.priority,
                    timeout=task.timeout,
                    retry_policy=task.retry_policy,
                    schedule=task.schedule,
                    tags=task.tags,
                    metadata=dict(task.metadata),
                )

                self.queue.enqueue(run_task)

                # Calculate next run time
                with self._lock:
                    if task_id in self._cron_parsers:
                        parser = self._cron_parsers[task_id]
                        self._next_run_times[task_id] = parser.next_run(now)
                    elif task.schedule and task.schedule.interval_seconds:
                        self._next_run_times[task_id] = now + timedelta(seconds=task.schedule.interval_seconds)
                    else:
                        # One-shot task, remove it
                        self.remove_scheduled_task(task_id)

            except Exception as e:
                self._log_error(f"Error enqueueing scheduled task {task_id}: {e}")

    def _log_error(self, message: str) -> None:
        """Log an error message."""
        print(f"[Scheduler] {message}")

    def __repr__(self) -> str:
        return f"TaskScheduler(running={self.is_running()}, " f"scheduled_tasks={len(self._scheduled_tasks)})"
