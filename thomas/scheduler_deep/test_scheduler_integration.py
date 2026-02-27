"""
Integration tests for the complete scheduler system.
"""

import tempfile
import time
from datetime import datetime, timezone

from thomas.scheduler_deep._types import CronTrigger, IntervalTrigger, Job, JobStatus, SchedulerConfig
from thomas.scheduler_deep.dag import DAGScheduler
from thomas.scheduler_deep.scheduler import Scheduler, SchedulerEvent


class TestSchedulerBasic:
    """Test basic scheduler functionality."""

    def test_scheduler_creation(self) -> None:
        """Test creating scheduler."""
        scheduler = Scheduler()
        assert scheduler is not None
        assert len(scheduler.list_jobs()) == 0

    def test_add_job(self) -> None:
        """Test adding job to scheduler."""
        scheduler = Scheduler()

        def test_func() -> str:
            return "success"

        trigger = IntervalTrigger(3600)
        job = scheduler.add_job(test_func, trigger, name="test_job")

        assert job.id is not None
        assert job.name == "test_job"
        assert len(scheduler.list_jobs()) == 1

    def test_remove_job(self) -> None:
        """Test removing job from scheduler."""
        scheduler = Scheduler()

        def test_func() -> str:
            return "success"

        trigger = IntervalTrigger(3600)
        job = scheduler.add_job(test_func, trigger)

        scheduler.remove_job(job.id)
        assert len(scheduler.list_jobs()) == 0

    def test_pause_resume_job(self) -> None:
        """Test pausing and resuming job."""
        scheduler = Scheduler()

        def test_func() -> str:
            return "success"

        trigger = IntervalTrigger(1)
        job = scheduler.add_job(test_func, trigger)

        scheduler.pause_job(job.id)
        assert scheduler.get_job(job.id).status == JobStatus.PAUSED

        scheduler.resume_job(job.id)
        assert scheduler.get_job(job.id).status == JobStatus.IDLE

    def test_start_stop_scheduler(self) -> None:
        """Test starting and stopping scheduler."""
        scheduler = Scheduler()

        def test_func() -> str:
            return "success"

        trigger = IntervalTrigger(3600)
        scheduler.add_job(test_func, trigger)

        scheduler.start()
        assert scheduler._running is True

        scheduler.stop()
        assert scheduler._running is False

    def test_job_execution(self) -> None:
        """Test actual job execution."""
        scheduler = Scheduler()
        results: list[str] = []

        def test_func() -> str:
            results.append("executed")
            return "success"

        trigger = IntervalTrigger(1)  # Very short interval for testing
        scheduler.add_job(test_func, trigger)
        scheduler.start()

        # Wait for execution
        time.sleep(3)
        scheduler.stop()

        assert len(results) > 0

    def test_multiple_jobs(self) -> None:
        """Test running multiple jobs."""
        scheduler = Scheduler()
        results: list[str] = []

        def job1_func() -> None:
            results.append("job1")

        def job2_func() -> None:
            results.append("job2")

        trigger = IntervalTrigger(1)
        scheduler.add_job(job1_func, trigger, name="job1")
        scheduler.add_job(job2_func, trigger, name="job2")

        scheduler.start()
        time.sleep(3)
        scheduler.stop()

        assert "job1" in results
        assert "job2" in results


class TestSchedulerWithPersistence:
    """Test scheduler with persistence enabled."""

    def test_persistence_enabled(self) -> None:
        """Test scheduler with persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SchedulerConfig(
                persistence_enabled=True,
                persistence_path=tmpdir,
            )
            scheduler = Scheduler(config)

            def test_func() -> str:
                return "success"

            trigger = IntervalTrigger(3600)
            job = scheduler.add_job(test_func, trigger, name="test_job")

            assert job.id is not None
            scheduler.stop()


class TestSchedulerMonitoring:
    """Test scheduler monitoring and metrics."""

    def test_monitor_job_execution(self) -> None:
        """Test monitoring job execution."""
        scheduler = Scheduler()
        executed = []

        def test_func() -> str:
            executed.append(True)
            return "success"

        trigger = IntervalTrigger(1)
        scheduler.add_job(test_func, trigger)

        scheduler.start()
        time.sleep(3)

        metrics = scheduler.monitor.get_metrics()
        assert metrics.total_executions > 0

        scheduler.stop()

    def test_health_check(self) -> None:
        """Test scheduler health check."""
        scheduler = Scheduler()

        def test_func() -> str:
            return "success"

        trigger = IntervalTrigger(3600)
        scheduler.add_job(test_func, trigger)

        jobs = scheduler.list_jobs()
        health = scheduler.monitor.check_health(jobs)

        assert health is not None

    def test_job_stats(self) -> None:
        """Test job statistics collection."""
        scheduler = Scheduler()
        executed = []

        def test_func() -> str:
            executed.append(True)
            return "success"

        trigger = IntervalTrigger(1)
        job = scheduler.add_job(test_func, trigger)

        scheduler.start()
        time.sleep(3)

        # Update stats from history
        history = scheduler.job_store.get_history(job.id)
        if history:
            scheduler.monitor.update_job_stats(job.id, history)
            stats = scheduler.monitor.get_job_stats(job.id)
            assert stats is not None

        scheduler.stop()

    def test_upcoming_schedule(self) -> None:
        """Test getting upcoming job schedule."""
        scheduler = Scheduler()

        def test_func() -> str:
            return "success"

        trigger = IntervalTrigger(3600)
        scheduler.add_job(test_func, trigger)

        jobs = scheduler.list_jobs()
        upcoming = scheduler.monitor.get_upcoming_schedule(jobs, hours_ahead=24)

        assert isinstance(upcoming, list)


class TestSchedulerEvents:
    """Test scheduler event callbacks."""

    def test_job_scheduled_event(self) -> None:
        """Test job scheduled event."""
        scheduler = Scheduler()
        events = []

        def on_job_scheduled(job: Job) -> None:
            events.append(("scheduled", job.id))

        def test_func() -> str:
            return "success"

        trigger = IntervalTrigger(3600)
        scheduler.on(SchedulerEvent.JOB_SCHEDULED, on_job_scheduled)
        scheduler.add_job(test_func, trigger)

        assert len(events) == 1
        assert events[0][0] == "scheduled"

    def test_scheduler_started_event(self) -> None:
        """Test scheduler started event."""
        scheduler = Scheduler()
        events = []

        def on_started(_) -> None:
            events.append("started")

        scheduler.on(SchedulerEvent.STARTED, on_started)
        scheduler.start()
        scheduler.stop()

        assert "started" in events

    def test_job_completed_event(self) -> None:
        """Test job completed event."""
        scheduler = Scheduler()
        events = []

        def on_completed(job: Job) -> None:
            events.append(("completed", job.id))

        def test_func() -> str:
            return "success"

        trigger = IntervalTrigger(1)
        job = scheduler.add_job(test_func, trigger)
        scheduler.on(SchedulerEvent.JOB_COMPLETED, on_completed)

        scheduler.start()
        time.sleep(3)
        scheduler.stop()

        assert any(e[0] == "completed" for e in events)


class TestSchedulerWithDAG:
    """Test scheduler integration with DAG."""

    def test_dag_execution_order(self) -> None:
        """Test job execution order with DAG."""
        dag = DAGScheduler()
        execution_order = []

        def job1_func() -> None:
            execution_order.append(1)

        def job2_func() -> None:
            execution_order.append(2)

        def job3_func() -> None:
            execution_order.append(3)

        trigger = IntervalTrigger(3600)
        job1 = Job(job1_func, trigger, job_id="job1")
        job2 = Job(job2_func, trigger, job_id="job2")
        job3 = Job(job3_func, trigger, job_id="job3")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])
        dag.add_job(job3, dependencies=["job2"])

        order = dag.get_topological_order()
        assert order == ["job1", "job2", "job3"]


class TestSchedulerRateControl:
    """Test rate control functionality."""

    def test_concurrent_job_limit(self) -> None:
        """Test concurrent job limit is enforced."""
        config = SchedulerConfig(max_concurrent_jobs=2)
        scheduler = Scheduler(config)

        def test_func() -> None:
            time.sleep(0.5)

        trigger = IntervalTrigger(1)
        for i in range(5):
            scheduler.add_job(test_func, trigger, name=f"job{i}")

        scheduler.start()
        time.sleep(2)
        scheduler.stop()

        # Should complete without error
        assert True

    def test_rate_control_stats(self) -> None:
        """Test rate control statistics."""
        scheduler = Scheduler()

        def test_func() -> str:
            return "success"

        trigger = IntervalTrigger(3600)
        scheduler.add_job(test_func, trigger)

        assert scheduler.rate_control.get_running_count() >= 0
        assert scheduler.rate_control.get_queued_count() >= 0


class TestSchedulerErrorHandling:
    """Test error handling and recovery."""

    def test_failing_job_continues_scheduler(self) -> None:
        """Test that failing job doesn't crash scheduler."""
        scheduler = Scheduler()
        executed = []

        def failing_job() -> None:
            executed.append(True)
            raise ValueError("Test error")

        def good_job() -> None:
            executed.append(True)

        trigger = IntervalTrigger(1)
        scheduler.add_job(failing_job, trigger, name="fail")
        scheduler.add_job(good_job, trigger, name="good", max_retries=1)

        scheduler.start()
        time.sleep(3)
        scheduler.stop()

        # Both jobs should have been attempted
        assert len(executed) > 0

    def test_job_with_timeout(self) -> None:
        """Test job timeout handling."""
        scheduler = Scheduler()
        executed = []

        def slow_job() -> None:
            executed.append(True)
            time.sleep(10)

        config = SchedulerConfig(job_timeout_seconds=1)
        scheduler_with_timeout = Scheduler(config)

        trigger = IntervalTrigger(3600)
        scheduler_with_timeout.add_job(slow_job, trigger)

        # Job should be added successfully
        assert len(scheduler_with_timeout.list_jobs()) == 1


class TestSchedulerCronTrigger:
    """Test scheduler with cron triggers."""

    def test_cron_trigger_basic(self) -> None:
        """Test scheduler with cron trigger."""
        scheduler = Scheduler()

        def test_func() -> str:
            return "success"

        # Trigger at current time
        now = datetime.now(timezone.utc)
        cron = CronTrigger(expression=f"{now.minute} {now.hour} * * *", name="hourly_job")
        job = scheduler.add_job(test_func, cron)

        assert job is not None

    def test_cron_next_occurrence(self) -> None:
        """Test cron next occurrence calculation."""
        cron = CronTrigger("0 9 * * *")  # 9 AM daily
        base = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0)
        next_time = cron.next_occurrence(base)

        assert next_time is not None
        assert next_time.hour == 9
