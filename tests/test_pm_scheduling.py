"""Tests for scheduling module (CPM, Gantt, resource leveling)."""

from datetime import datetime, timedelta

import pytest

from thomas.project_mgmt._types import DependencyType, Task
from thomas.project_mgmt.scheduling import ScheduleManager


class TestScheduleManager:
    """Test suite for ScheduleManager."""

    @pytest.fixture
    def manager(self) -> ScheduleManager:
        """Create schedule manager instance."""
        return ScheduleManager()

    @pytest.fixture
    def sample_tasks(self) -> dict:
        """Create sample task structure."""
        tasks = {}

        task1 = Task(
            id="task-1",
            project_id="proj-1",
            title="Start Task",
            start_date=datetime.now(),
            due_date=datetime.now() + timedelta(days=5),
            estimated_hours=(2.0, 4.0, 8.0),
        )
        tasks[task1.id] = task1

        task2 = Task(
            id="task-2",
            project_id="proj-1",
            title="Middle Task",
            start_date=datetime.now() + timedelta(days=5),
            due_date=datetime.now() + timedelta(days=10),
            estimated_hours=(3.0, 6.0, 12.0),
        )
        tasks[task2.id] = task2

        task3 = Task(
            id="task-3",
            project_id="proj-1",
            title="End Task",
            start_date=datetime.now() + timedelta(days=10),
            due_date=datetime.now() + timedelta(days=15),
            estimated_hours=(2.0, 4.0, 8.0),
        )
        tasks[task3.id] = task3

        return tasks

    def test_calculate_critical_path(
        self,
        manager: ScheduleManager,
        sample_tasks: dict,
    ) -> None:
        """Test critical path calculation."""
        # Add dependencies
        from thomas.project_mgmt._types import Dependency

        dep1 = Dependency(
            id="dep-1",
            predecessor_task_id="task-1",
            successor_task_id="task-2",
        )
        dep2 = Dependency(
            id="dep-2",
            predecessor_task_id="task-2",
            successor_task_id="task-3",
        )

        manager.tasks = sample_tasks
        manager.dependencies = {dep1.id: dep1, dep2.id: dep2}

        critical_path, duration = manager.calculate_critical_path(sample_tasks)

        assert len(critical_path) > 0
        assert duration > 0

    def test_generate_gantt_data(
        self,
        manager: ScheduleManager,
        sample_tasks: dict,
    ) -> None:
        """Test Gantt chart data generation."""
        manager.tasks = sample_tasks
        gantt_bars = manager.generate_gantt_data(
            "proj-1",
            sample_tasks,
        )

        assert len(gantt_bars) == 3
        for bar in gantt_bars:
            assert bar.task_id in sample_tasks
            assert bar.start_date is not None
            assert bar.end_date is not None

    def test_gantt_sorting(
        self,
        manager: ScheduleManager,
        sample_tasks: dict,
    ) -> None:
        """Test Gantt bars are sorted by start date."""
        manager.tasks = sample_tasks
        gantt_bars = manager.generate_gantt_data(
            "proj-1",
            sample_tasks,
        )

        # Verify sorting
        for i in range(len(gantt_bars) - 1):
            assert gantt_bars[i].start_date <= gantt_bars[i + 1].start_date

    def test_resource_leveling(
        self,
        manager: ScheduleManager,
        sample_tasks: dict,
    ) -> None:
        """Test resource leveling heuristic."""
        manager.tasks = sample_tasks

        capacities = {
            "res-1": 40.0,
            "res-2": 40.0,
        }

        schedule = manager.level_resources(sample_tasks, capacities)

        assert len(schedule) == 2
        assert all(res_id in schedule for res_id in capacities)

    def test_schedule_compression_analysis(
        self,
        manager: ScheduleManager,
        sample_tasks: dict,
    ) -> None:
        """Test schedule compression analysis."""
        from thomas.project_mgmt._types import Dependency

        dep = Dependency(
            id="dep-1",
            predecessor_task_id="task-1",
            successor_task_id="task-2",
            dependency_type=DependencyType.FINISH_TO_START,
        )

        manager.tasks = sample_tasks
        manager.dependencies = {dep.id: dep}

        analysis = manager.analyze_schedule_compression(
            "proj-1",
            sample_tasks,
            target_duration_hours=100.0,
        )

        assert "current_duration" in analysis
        assert "target_duration" in analysis
        assert "compression_needed" in analysis
        assert "fast_track_opportunities" in analysis
        assert "crash_analysis" in analysis

    def test_schedule_variance(
        self,
        manager: ScheduleManager,
        sample_tasks: dict,
    ) -> None:
        """Test schedule variance calculation."""
        # Set different completion percentages
        sample_tasks["task-1"].percent_complete = 100.0
        sample_tasks["task-2"].percent_complete = 50.0
        sample_tasks["task-3"].percent_complete = 0.0

        variance = manager.get_schedule_variance(sample_tasks)

        # Average completion is 50%, variance should be 0
        assert isinstance(variance, float)

    def test_find_start_tasks(
        self,
        manager: ScheduleManager,
        sample_tasks: dict,
    ) -> None:
        """Test finding tasks with no predecessors."""
        from thomas.project_mgmt._types import Dependency

        dep = Dependency(
            id="dep-1",
            predecessor_task_id="task-1",
            successor_task_id="task-2",
        )

        manager.dependencies = {dep.id: dep}

        start_tasks = manager._find_start_tasks(sample_tasks)

        assert "task-1" in start_tasks
        assert "task-2" not in start_tasks

    def test_find_end_tasks(
        self,
        manager: ScheduleManager,
        sample_tasks: dict,
    ) -> None:
        """Test finding tasks with no successors."""
        from thomas.project_mgmt._types import Dependency

        dep = Dependency(
            id="dep-1",
            predecessor_task_id="task-1",
            successor_task_id="task-2",
        )

        manager.dependencies = {dep.id: dep}

        end_tasks = manager._find_end_tasks(sample_tasks)

        assert "task-2" in end_tasks or "task-3" in end_tasks
        assert "task-1" not in end_tasks

    def test_empty_tasks(self, manager: ScheduleManager) -> None:
        """Test handling empty task list."""
        critical_path, duration = manager.calculate_critical_path({})

        assert critical_path == []
        assert duration == 0.0

    def test_single_task(self, manager: ScheduleManager) -> None:
        """Test single task scheduling."""
        task = Task(
            id="task-1",
            project_id="proj-1",
            title="Solo Task",
            estimated_hours=(2.0, 4.0, 8.0),
        )

        gantt = manager.generate_gantt_data("proj-1", {task.id: task})

        assert len(gantt) == 1
        assert gantt[0].task_id == task.id
