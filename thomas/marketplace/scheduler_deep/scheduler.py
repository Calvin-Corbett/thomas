"""
Main scheduler implementation with job management and execution loop.

Provides the core scheduler functionality with job registration, execution, and state management.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from thomas.marketplace.scheduler_deep._exceptions import JobAlreadyExists, JobNotFound
from thomas.marketplace.scheduler_deep._types import Job, JobHistory, JobStatus, SchedulerConfig, Trigger
from thomas.marketplace.scheduler_deep.distributed import DistributedScheduler
from thomas.marketplace.scheduler_deep.executor import JobExecutor
from thomas.marketplace.scheduler_deep.monitoring import SchedulerMonitor
from thomas.marketplace.scheduler_deep.persistence import FileJobStore, MemoryJobStore
from thomas.marketplace.scheduler_deep.rate_control import RateControl

logger = logging.getLogger(__name__)


class SchedulerEvent(Enum):
    """Scheduler lifecycle events."""

    STARTED = "started"
    STOPPED = "stopped"
    JOB_SCHEDULED = "job_scheduled"
    JOB_STARTED = "job_started"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"


class Scheduler:
    """Main job scheduler."""

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        """Initialize scheduler.

        Args:
            config: Scheduler configuration
        """
        self.config = config or SchedulerConfig()
        self._jobs: dict[str, Job] = {}
        self._running = False
        self._lock = threading.RLock()
        self._main_thread: threading.Thread | None = None
        self._callbacks: dict[SchedulerEvent, list[Callable]] = {event: [] for event in SchedulerEvent}

        # Initialize components
        self.executor = JobExecutor(
            max_workers=self.config.max_concurrent_jobs,
            timeout_seconds=self.config.job_timeout_seconds,
        )

        # Initialize persistence
        if self.config.persistence_enabled and self.config.persistence_path:
            self.job_store = FileJobStore(self.config.persistence_path)
        else:
            self.job_store = MemoryJobStore()

        # Initialize monitoring
        self.monitor = SchedulerMonitor()

        # Initialize rate control
        self.rate_control = RateControl(max_concurrent_jobs=self.config.max_concurrent_jobs)

        # Initialize distributed scheduler if needed
        self.distributed: DistributedScheduler | None = None
        if self.config.distributed_mode:
            self.distributed = DistributedScheduler()

    def add_job(
        self,
        func: Callable[..., Any],
        trigger: Trigger,
        name: str | None = None,
        job_id: str | None = None,
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
        max_instances: int = 1,
        tags: set[str] | None = None,
        description: str = "",
        max_retries: int = 0,
    ) -> Job:
        """Add job to scheduler.

        Args:
            func: Callable to execute
            trigger: Job trigger
            name: Job name
            job_id: Job ID
            args: Function arguments
            kwargs: Function keyword arguments
            max_instances: Max concurrent instances
            tags: Job tags
            description: Job description
            max_retries: Max retry attempts

        Returns:
            Created job

        Raises:
            JobAlreadyExists: If job ID already registered
            InvalidTrigger: If trigger is invalid
        """
        with self._lock:
            if job_id and job_id in self._jobs:
                raise JobAlreadyExists(job_id)

            job = Job(
                func=func,
                trigger=trigger,
                name=name,
                job_id=job_id,
                args=args,
                kwargs=kwargs or {},
                max_instances=max_instances,
                tags=tags or set(),
                description=description,
                max_retries=max_retries,
            )

            self._jobs[job.id] = job
            self.job_store.save_job(job)

            self._fire_event(SchedulerEvent.JOB_SCHEDULED, job)
            return job

    def remove_job(self, job_id: str) -> None:
        """Remove job from scheduler.

        Args:
            job_id: Job ID to remove

        Raises:
            JobNotFound: If job doesn't exist
        """
        with self._lock:
            if job_id not in self._jobs:
                raise JobNotFound(job_id)

            self._jobs[job_id]
            del self._jobs[job_id]
            self.job_store.delete_job(job_id)

    def get_job(self, job_id: str) -> Job:
        """Get job by ID.

        Args:
            job_id: Job ID

        Returns:
            Job object

        Raises:
            JobNotFound: If job doesn't exist
        """
        with self._lock:
            if job_id not in self._jobs:
                raise JobNotFound(job_id)
            return self._jobs[job_id]

    def list_jobs(self) -> list[Job]:
        """List all jobs.

        Returns:
            List of all jobs
        """
        with self._lock:
            return list(self._jobs.values())

    def pause_job(self, job_id: str) -> None:
        """Pause job execution.

        Args:
            job_id: Job ID to pause

        Raises:
            JobNotFound: If job doesn't exist
        """
        with self._lock:
            job = self.get_job(job_id)
            job.status = JobStatus.PAUSED
            self.job_store.save_job(job)

    def resume_job(self, job_id: str) -> None:
        """Resume paused job.

        Args:
            job_id: Job ID to resume

        Raises:
            JobNotFound: If job doesn't exist
        """
        with self._lock:
            job = self.get_job(job_id)
            job.status = JobStatus.IDLE
            job.next_run = None
            self.job_store.save_job(job)

    def start(self) -> None:
        """Start scheduler."""
        with self._lock:
            if self._running:
                return

            self._running = True

            # Start distributed scheduler if enabled
            if self.distributed:
                self.distributed.start()

            # Start main scheduler thread
            self._main_thread = threading.Thread(target=self._run_loop, daemon=False)
            self._main_thread.start()

            self._fire_event(SchedulerEvent.STARTED)
            logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop scheduler gracefully."""
        with self._lock:
            if not self._running:
                return

            self._running = False

        # Wait for main thread
        if self._main_thread:
            self._main_thread.join(timeout=self.config.graceful_shutdown_timeout)

        # Stop distributed scheduler
        if self.distributed:
            self.distributed.stop()

        self.executor.shutdown(wait=True)
        self.job_store.close()
        self._fire_event(SchedulerEvent.STOPPED)
        logger.info("Scheduler stopped")

    def _run_loop(self) -> None:
        """Main scheduler loop."""
        logger.info("Scheduler loop started")

        while self._running:
            try:
                # Update health check
                jobs = self.list_jobs()
                health = self.monitor.check_health(jobs)
                logger.debug(f"Health: {health}")

                # Get jobs ready to run
                ready_jobs = self._get_ready_jobs()

                # Try to execute each ready job
                for job in ready_jobs:
                    if not self._running:
                        break

                    try:
                        self._try_execute_job(job)
                    except Exception as e:
                        logger.error(f"Error executing job {job.id}: {e}")

                # Calculate sleep time to next job
                sleep_time = self._calculate_sleep_time()
                if sleep_time > 0:
                    time.sleep(min(sleep_time, 1.0))  # Check at least every second

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                time.sleep(1)

        logger.info("Scheduler loop stopped")

    def _get_ready_jobs(self) -> list[Job]:
        """Get jobs ready to run.

        Returns:
            List of ready jobs
        """
        with self._lock:
            ready = []
            now = datetime.now(timezone.utc)

            for job in self._jobs.values():
                # Skip paused or failed jobs
                if job.status in (JobStatus.PAUSED, JobStatus.CANCELLED):
                    continue

                # Check if next_run is due
                if job.next_run and job.next_run <= now:
                    ready.append(job)
                elif job.next_run is None and job.status == JobStatus.IDLE:
                    # First run
                    if job.trigger.should_run(job.last_run):
                        ready.append(job)

            return ready

    def _try_execute_job(self, job: Job) -> None:
        """Try to execute a job.

        Args:
            job: Job to execute
        """
        # Check distributed lock
        if self.distributed:
            if not self.distributed.try_acquire_lock(job.id):
                return

        try:
            # Check rate control
            if not self.rate_control.can_run(job.id):
                return

            # Check max instances
            running_count = sum(1 for j in self._jobs.values() if j.id == job.id and j.status == JobStatus.RUNNING)
            if running_count >= job.max_instances:
                return

            # Acquire rate control slot
            self.rate_control.acquire(job.id)

            # Mark as running
            with self._lock:
                job.status = JobStatus.RUNNING
                job.last_run = datetime.now(timezone.utc)

            self._fire_event(SchedulerEvent.JOB_STARTED, job)

            # Submit for execution
            execution_id = self.executor.submit_job(
                job,
                previous_result=job.result,
                retry_count=job.retry_count,
            )

            # Wait for result (non-blocking)
            self._handle_execution(job, execution_id)

        except Exception as e:
            logger.error(f"Error executing job {job.id}: {e}")
            with self._lock:
                job.status = JobStatus.FAILED
                job.error = str(e)
        finally:
            self.rate_control.release(job.id)
            if self.distributed:
                self.distributed.release_lock(job.id)

    def _handle_execution(self, job: Job, execution_id: str) -> None:
        """Handle job execution asynchronously.

        Args:
            job: Job being executed
            execution_id: Execution ID
        """
        start_time = datetime.now(timezone.utc)

        def wait_and_handle() -> None:
            try:
                result = self.executor.get_result(execution_id, timeout=job.timeout_seconds)
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()

                with self._lock:
                    job.status = JobStatus.SUCCESS
                    job.result = result
                    job.error = None
                    job.retry_count = 0

                # Save history
                history = JobHistory(
                    job_id=job.id,
                    executed_at=start_time,
                    status=JobStatus.SUCCESS,
                    duration_seconds=duration,
                    result=result,
                )
                self.job_store.save_history(history)
                self.monitor.record_execution(job, history)

                # Update next run
                self._update_next_run(job)
                self._fire_event(SchedulerEvent.JOB_COMPLETED, job)

            except Exception as e:
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()

                with self._lock:
                    if job.retry_count < job.max_retries:
                        job.retry_count += 1
                        job.status = JobStatus.IDLE
                    else:
                        job.status = JobStatus.FAILED
                        job.error = str(e)

                # Save history
                history = JobHistory(
                    job_id=job.id,
                    executed_at=start_time,
                    status=JobStatus.FAILED,
                    duration_seconds=duration,
                    error=str(e),
                )
                self.job_store.save_history(history)
                self.monitor.record_execution(job, history)

                self._update_next_run(job)
                self._fire_event(SchedulerEvent.JOB_FAILED, job)

        # Run in separate thread to not block scheduler
        handler_thread = threading.Thread(target=wait_and_handle, daemon=True)
        handler_thread.start()

    def _update_next_run(self, job: Job) -> None:
        """Update next run time for job.

        Args:
            job: Job to update
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            next_time = job.trigger.next_occurrence(now)
            job.next_run = next_time

            if next_time is None:
                job.status = JobStatus.IDLE

            self.job_store.save_job(job)

    def _calculate_sleep_time(self) -> float:
        """Calculate sleep time until next job.

        Returns:
            Sleep time in seconds
        """
        with self._lock:
            min_sleep = float("inf")

            for job in self._jobs.values():
                if job.next_run:
                    now = datetime.now(timezone.utc)
                    sleep_time = (job.next_run - now).total_seconds()
                    min_sleep = min(min_sleep, max(0, sleep_time))

            return min_sleep if min_sleep != float("inf") else 60

    def on(self, event: SchedulerEvent, callback: Callable) -> None:
        """Register event callback.

        Args:
            event: Event type
            callback: Callback function
        """
        with self._lock:
            self._callbacks[event].append(callback)

    def _fire_event(self, event: SchedulerEvent, data: Any = None) -> None:
        """Fire event and call callbacks.

        Args:
            event: Event type
            data: Event data
        """
        with self._lock:
            callbacks = self._callbacks[event].copy()

        for callback in callbacks:
            try:
                callback(data)
            except Exception as e:
                logger.error(f"Error in event callback: {e}")

    def __repr__(self) -> str:
        """String representation."""
        with self._lock:
            return f"Scheduler(jobs={len(self._jobs)}, running={self._running})"
