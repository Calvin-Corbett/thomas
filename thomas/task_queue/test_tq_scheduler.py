"""
Tests for the TaskScheduler implementation.

Tests cron parsing, schedule calculation, and task scheduling.
"""

import time
from datetime import datetime, timedelta

import pytest

from thomas.task_queue._exceptions import SchedulerError
from thomas.task_queue._types import Schedule, Task
from thomas.task_queue.queue import TaskQueue
from thomas.task_queue.scheduler import CronParser, TaskScheduler


def dummy_func():
    """Simple test function."""
    pass


class TestCronParser:
    """Tests for CronParser."""

    def test_simple_cron(self) -> None:
        """Test parsing simple cron expression."""
        parser = CronParser("0 9 * * *")
        assert 0 in parser.minutes
        assert 9 in parser.hours
        assert all(i in parser.days for i in range(1, 32))

    def test_wildcard(self) -> None:
        """Test wildcard in cron."""
        parser = CronParser("* * * * *")
        assert len(parser.minutes) == 60
        assert len(parser.hours) == 24

    def test_range(self) -> None:
        """Test range in cron."""
        parser = CronParser("0 9-17 * * *")
        assert 9 in parser.hours
        assert 17 in parser.hours
        assert 8 not in parser.hours

    def test_step(self) -> None:
        """Test step in cron."""
        parser = CronParser("*/15 * * * *")
        assert 0 in parser.minutes
        assert 15 in parser.minutes
        assert 30 in parser.minutes
        assert 45 in parser.minutes

    def test_invalid_cron(self) -> None:
        """Test invalid cron expression raises error."""
        with pytest.raises(SchedulerError):
            CronParser("invalid cron")

    def test_cron_matching(self) -> None:
        """Test cron expression matching."""
        parser = CronParser("0 9 * * 1")  # 9 AM on Mondays

        # Monday at 9 AM
        monday_9am = datetime(2024, 1, 1, 9, 0)  # Jan 1, 2024 is Monday
        assert parser.matches(monday_9am)

        # Monday at 10 AM
        monday_10am = datetime(2024, 1, 1, 10, 0)
        assert not parser.matches(monday_10am)

    def test_next_run_calculation(self) -> None:
        """Test next run time calculation."""
        parser = CronParser("0 9 * * *")  # Daily at 9 AM
        now = datetime(2024, 1, 1, 8, 0)

        next_run = parser.next_run(now)
        assert next_run.hour == 9
        assert next_run.day == 1


class TestTaskScheduler:
    """Tests for TaskScheduler."""

    def test_scheduler_initialization(self) -> None:
        """Test scheduler initialization."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue)

        assert not scheduler.is_running()

    def test_scheduler_start_stop(self) -> None:
        """Test scheduler start and stop."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue, poll_interval=0.1)

        scheduler.start()
        assert scheduler.is_running()

        scheduler.stop(timeout=1)
        assert not scheduler.is_running()

    def test_add_scheduled_task(self) -> None:
        """Test adding a scheduled task."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue)

        schedule = Schedule(cron_expression="0 9 * * *")
        task = Task("daily", dummy_func, schedule=schedule)

        scheduler.add_scheduled_task(task)
        assert task.task_id in scheduler._scheduled_tasks

    def test_scheduled_task_without_schedule(self) -> None:
        """Test adding task without schedule raises error."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue)

        task = Task("no_schedule", dummy_func)

        with pytest.raises(SchedulerError):
            scheduler.add_scheduled_task(task)

    def test_interval_scheduling(self) -> None:
        """Test interval-based scheduling."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue)

        schedule = Schedule(interval_seconds=60)
        task = Task("interval", dummy_func, schedule=schedule)

        scheduler.add_scheduled_task(task)
        next_runs = scheduler.get_next_runs()

        assert task.task_id in next_runs

    def test_one_shot_scheduling(self) -> None:
        """Test one-shot scheduled task."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue)

        future = datetime.utcnow() + timedelta(hours=1)
        schedule = Schedule(one_shot_at=future)
        task = Task("one_shot", dummy_func, schedule=schedule)

        scheduler.add_scheduled_task(task)
        next_runs = scheduler.get_next_runs()

        assert task.task_id in next_runs
        assert next_runs[task.task_id] > datetime.utcnow()

    def test_remove_scheduled_task(self) -> None:
        """Test removing a scheduled task."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue)

        schedule = Schedule(cron_expression="0 9 * * *")
        task = Task("daily", dummy_func, schedule=schedule)

        scheduler.add_scheduled_task(task)
        assert scheduler.remove_scheduled_task(str(task.task_id))
        assert task.task_id not in scheduler._scheduled_tasks

    def test_scheduler_enqueues_due_tasks(self) -> None:
        """Test scheduler enqueues tasks when due."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue, poll_interval=0.1)

        # Schedule task for now
        schedule = Schedule(one_shot_at=datetime.utcnow())
        task = Task("now", dummy_func, schedule=schedule)

        scheduler.add_scheduled_task(task)
        scheduler.start()

        time.sleep(0.5)

        # Task should be in queue
        assert queue.size() >= 1

        scheduler.stop()

    def test_scheduler_repr(self) -> None:
        """Test scheduler string representation."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue)

        repr_str = repr(scheduler)
        assert "TaskScheduler" in repr_str

    def test_get_next_runs(self) -> None:
        """Test getting next run times."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue)

        schedule = Schedule(cron_expression="0 9 * * *")
        task1 = Task("task1", dummy_func, schedule=schedule)
        task2 = Task("task2", dummy_func, schedule=Schedule(interval_seconds=60))

        scheduler.add_scheduled_task(task1)
        scheduler.add_scheduled_task(task2)

        next_runs = scheduler.get_next_runs()
        assert len(next_runs) == 2
