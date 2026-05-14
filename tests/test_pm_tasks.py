"""Tests for task management module."""

import pytest

from thomas.marketplace.project_mgmt._exceptions import (
    CircularDependencyError,
    TaskNotFoundError,
)
from thomas.marketplace.project_mgmt._types import DependencyType, Priority, TaskStatus
from thomas.marketplace.project_mgmt.tasks import TaskManager


class TestTaskManager:
    """Test suite for TaskManager."""

    @pytest.fixture
    def manager(self) -> TaskManager:
        """Create task manager instance."""
        return TaskManager()

    def test_create_task(self, manager: TaskManager) -> None:
        """Test task creation."""
        task = manager.create_task(
            project_id="proj-1",
            title="Test Task",
            description="Test description",
            priority=Priority.HIGH,
            estimated_hours=(4.0, 8.0, 16.0),
        )

        assert task.id is not None
        assert task.title == "Test Task"
        assert task.project_id == "proj-1"
        assert task.priority == Priority.HIGH
        assert task.status == TaskStatus.TODO

    def test_get_task(self, manager: TaskManager) -> None:
        """Test retrieving task."""
        task = manager.create_task(
            project_id="proj-1",
            title="Task 1",
        )

        retrieved = manager.get_task(task.id)
        assert retrieved.id == task.id
        assert retrieved.title == "Task 1"

    def test_get_task_not_found(self, manager: TaskManager) -> None:
        """Test get task with invalid ID."""
        with pytest.raises(TaskNotFoundError):
            manager.get_task("invalid-id")

    def test_update_task(self, manager: TaskManager) -> None:
        """Test updating task."""
        task = manager.create_task(
            project_id="proj-1",
            title="Original",
        )

        updated = manager.update_task(
            task.id,
            title="Updated",
            priority=Priority.CRITICAL,
            percent_complete=50.0,
        )

        assert updated.title == "Updated"
        assert updated.priority == Priority.CRITICAL
        assert updated.percent_complete == 50.0

    def test_transition_status(self, manager: TaskManager) -> None:
        """Test task status transitions."""
        task = manager.create_task(
            project_id="proj-1",
            title="Task",
        )

        assert task.status == TaskStatus.TODO

        manager.transition_status(task.id, TaskStatus.IN_PROGRESS)
        task = manager.get_task(task.id)
        assert task.status == TaskStatus.IN_PROGRESS

        manager.transition_status(task.id, TaskStatus.REVIEW)
        task = manager.get_task(task.id)
        assert task.status == TaskStatus.REVIEW

        manager.transition_status(task.id, TaskStatus.DONE)
        task = manager.get_task(task.id)
        assert task.status == TaskStatus.DONE

    def test_create_subtask(self, manager: TaskManager) -> None:
        """Test subtask creation (WBS)."""
        parent = manager.create_task(
            project_id="proj-1",
            title="Parent Task",
        )

        subtask = manager.create_subtask(
            parent_task_id=parent.id,
            title="Subtask 1",
        )

        assert subtask.parent_task_id == parent.id
        assert subtask.id in parent.subtask_ids
        assert subtask.project_id == parent.project_id

    def test_pert_estimation(self, manager: TaskManager) -> None:
        """Test PERT expected value calculation."""
        task = manager.create_task(
            project_id="proj-1",
            title="Task",
            estimated_hours=(4.0, 8.0, 20.0),
        )

        pert = task.pert_estimate()
        # (4 + 4*8 + 20) / 6 = (4 + 32 + 20) / 6 = 56/6 = 9.33
        assert abs(pert - 9.33) < 0.01

    def test_add_dependency(self, manager: TaskManager) -> None:
        """Test creating task dependency."""
        task1 = manager.create_task(
            project_id="proj-1",
            title="Task 1",
        )
        task2 = manager.create_task(
            project_id="proj-1",
            title="Task 2",
        )

        dep = manager.add_dependency(
            predecessor_id=task1.id,
            successor_id=task2.id,
            dependency_type=DependencyType.FINISH_TO_START,
        )

        assert dep.predecessor_task_id == task1.id
        assert dep.successor_task_id == task2.id

    def test_circular_dependency_detection(
        self,
        manager: TaskManager,
    ) -> None:
        """Test detection of circular dependencies."""
        task1 = manager.create_task(
            project_id="proj-1",
            title="Task 1",
        )
        task2 = manager.create_task(
            project_id="proj-1",
            title="Task 2",
        )

        manager.add_dependency(
            predecessor_id=task1.id,
            successor_id=task2.id,
        )

        # Try to create circular dependency
        with pytest.raises(CircularDependencyError):
            manager.add_dependency(
                predecessor_id=task2.id,
                successor_id=task1.id,
            )

    def test_calculate_workload(self, manager: TaskManager) -> None:
        """Test workload calculation."""
        manager.create_task(
            project_id="proj-1",
            title="Task 1",
            estimated_hours=(4.0, 8.0, 12.0),
            assigned_to_id="res-1",
        )
        manager.create_task(
            project_id="proj-1",
            title="Task 2",
            estimated_hours=(2.0, 4.0, 6.0),
            assigned_to_id="res-1",
        )
        manager.create_task(
            project_id="proj-1",
            title="Task 3",
            estimated_hours=(1.0, 2.0, 3.0),
            assigned_to_id="res-2",
        )

        workload = manager.calculate_task_workload()

        assert "res-1" in workload
        assert "res-2" in workload
        assert workload["res-1"] > workload["res-2"]

    def test_balance_workload(self, manager: TaskManager) -> None:
        """Test workload balancing across resources."""
        tasks = []
        for i in range(3):
            task = manager.create_task(
                project_id="proj-1",
                title=f"Task {i}",
                estimated_hours=(2.0, 4.0, 6.0),
            )
            tasks.append(task.id)

        available = [
            ("res-1", 40.0),
            ("res-2", 40.0),
            ("res-3", 40.0),
        ]

        assignments = manager.balance_workload(tasks, available)

        assert len(assignments) == 3
        assert all(len(v) > 0 for v in assignments.values())

    def test_list_tasks_filtering(self, manager: TaskManager) -> None:
        """Test listing tasks with filters."""
        proj1_high = manager.create_task(
            project_id="proj-1",
            title="High Priority Task",
            priority=Priority.HIGH,
            assigned_to_id="res-1",
        )
        manager.create_task(
            project_id="proj-2",
            title="Low Priority Task",
            priority=Priority.LOW,
            assigned_to_id="res-2",
        )

        # Filter by project
        proj1_tasks = manager.list_tasks(project_id="proj-1")
        assert len(proj1_tasks) == 1
        assert proj1_tasks[0].id == proj1_high.id

        # Filter by assigned resource
        res1_tasks = manager.list_tasks(assigned_to_id="res-1")
        assert len(res1_tasks) == 1
        assert res1_tasks[0].id == proj1_high.id

        # Filter by priority
        high_tasks = manager.list_tasks(priority=Priority.HIGH)
        assert len(high_tasks) == 1

    def test_get_critical_path(self, manager: TaskManager) -> None:
        """Test critical path identification."""
        task1 = manager.create_task(
            project_id="proj-1",
            title="Task 1",
        )
        task2 = manager.create_task(
            project_id="proj-1",
            title="Task 2",
        )

        manager.add_dependency(
            predecessor_id=task1.id,
            successor_id=task2.id,
        )

        critical = manager.get_critical_path_tasks("proj-1")
        assert len(critical) > 0

    def test_delete_task(self, manager: TaskManager) -> None:
        """Test task deletion."""
        task = manager.create_task(
            project_id="proj-1",
            title="Task to delete",
        )

        manager.delete_task(task.id)

        with pytest.raises(TaskNotFoundError):
            manager.get_task(task.id)

    def test_delete_task_with_dependencies(
        self,
        manager: TaskManager,
    ) -> None:
        """Test deletion of task with dependencies."""
        task1 = manager.create_task(
            project_id="proj-1",
            title="Task 1",
        )
        task2 = manager.create_task(
            project_id="proj-1",
            title="Task 2",
        )

        manager.add_dependency(
            predecessor_id=task1.id,
            successor_id=task2.id,
        )

        # Delete task1 - should remove dependency
        manager.delete_task(task1.id)
        assert len(manager.dependencies) == 0
