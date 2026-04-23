"""
Tests for the Workflow implementation.

Tests DAG creation, dependency resolution, topological sort,
and workflow state management.
"""

import pytest

from thomas.marketplace.task_queue._exceptions import WorkflowError
from thomas.marketplace.task_queue._types import Task, TaskResult, TaskStatus
from thomas.marketplace.task_queue.workflows import Workflow, WorkflowNode


def dummy_func(x: int = 0):
    """Simple test function."""
    return x * 2


class TestWorkflowNode:
    """Tests for WorkflowNode."""

    def test_node_initialization(self) -> None:
        """Test workflow node creation."""
        task = Task("test", dummy_func)
        node = WorkflowNode("node1", task, dependencies=[])

        assert node.task_id == "node1"
        assert node.task == task
        assert len(node.dependencies) == 0
        assert node.status == TaskStatus.PENDING

    def test_node_dependencies(self) -> None:
        """Test node with dependencies."""
        task = Task("test", dummy_func)
        node = WorkflowNode("node1", task, dependencies=["dep1", "dep2"])

        assert "dep1" in node.dependencies
        assert "dep2" in node.dependencies

    def test_node_is_ready(self) -> None:
        """Test checking if node is ready."""
        task = Task("test", dummy_func)
        node = WorkflowNode("node1", task, dependencies=["dep1", "dep2"])

        # Not ready without dependencies
        assert not node.is_ready(set())

        # Ready with dependencies
        assert node.is_ready({"dep1", "dep2"})

        # Partially ready
        assert not node.is_ready({"dep1"})


class TestWorkflow:
    """Tests for Workflow."""

    def test_workflow_initialization(self) -> None:
        """Test workflow creation."""
        workflow = Workflow()

        assert workflow.name == "workflow"
        assert workflow.status == TaskStatus.PENDING
        assert len(workflow.nodes) == 0

    def test_add_task(self) -> None:
        """Test adding tasks to workflow."""
        workflow = Workflow()
        task = Task("test", dummy_func)

        node = workflow.add_task("node1", task)

        assert node.task_id == "node1"
        assert len(workflow.nodes) == 1

    def test_add_task_with_dependencies(self) -> None:
        """Test adding task with dependencies."""
        workflow = Workflow()
        task1 = Task("task1", dummy_func)
        task2 = Task("task2", dummy_func)

        workflow.add_task("node1", task1)
        node2 = workflow.add_task("node2", task2, dependencies=["node1"])

        assert "node1" in node2.dependencies

    def test_add_task_missing_dependency(self) -> None:
        """Test adding task with non-existent dependency raises error."""
        workflow = Workflow()
        task = Task("test", dummy_func)

        with pytest.raises(WorkflowError):
            workflow.add_task("node1", task, dependencies=["nonexistent"])

    def test_remove_task(self) -> None:
        """Test removing task from workflow."""
        workflow = Workflow()
        task = Task("test", dummy_func)
        workflow.add_task("node1", task)

        assert workflow.remove_task("node1")
        assert len(workflow.nodes) == 0

    def test_remove_task_dependency_exists(self) -> None:
        """Test cannot remove task that has dependents."""
        workflow = Workflow()
        task1 = Task("task1", dummy_func)
        task2 = Task("task2", dummy_func)

        workflow.add_task("node1", task1)
        workflow.add_task("node2", task2, dependencies=["node1"])

        with pytest.raises(WorkflowError):
            workflow.remove_task("node1")

    def test_get_ready_tasks(self) -> None:
        """Test getting tasks ready to execute."""
        workflow = Workflow()
        task1 = Task("task1", dummy_func)
        task2 = Task("task2", dummy_func)
        task3 = Task("task3", dummy_func)

        workflow.add_task("node1", task1)
        workflow.add_task("node2", task2, dependencies=["node1"])
        workflow.add_task("node3", task3, dependencies=["node2"])

        # Only node1 is ready
        ready = workflow.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == "node1"

    def test_mark_completed(self) -> None:
        """Test marking task as completed."""
        workflow = Workflow()
        task = Task("test", dummy_func)
        workflow.add_task("node1", task)

        result = TaskResult(task.task_id, TaskStatus.COMPLETED, output=42)
        workflow.mark_completed("node1", result)

        node = workflow.nodes["node1"]
        assert node.status == TaskStatus.COMPLETED
        assert "node1" in workflow._completed_tasks

    def test_mark_failed(self) -> None:
        """Test marking task as failed."""
        workflow = Workflow()
        task = Task("test", dummy_func)
        workflow.add_task("node1", task)

        workflow.mark_failed("node1", "Test error")

        assert workflow.status == TaskStatus.FAILED
        assert "node1" in workflow._failed_tasks

    def test_workflow_complete(self) -> None:
        """Test workflow completion detection."""
        workflow = Workflow()
        task1 = Task("task1", dummy_func)
        task2 = Task("task2", dummy_func)

        workflow.add_task("node1", task1)
        workflow.add_task("node2", task2)

        result1 = TaskResult(task1.task_id, TaskStatus.COMPLETED)
        result2 = TaskResult(task2.task_id, TaskStatus.COMPLETED)

        workflow.mark_completed("node1", result1)
        assert not workflow.is_complete()

        workflow.mark_completed("node2", result2)
        assert workflow.is_complete()

    def test_topological_sort(self) -> None:
        """Test topological sort of workflow tasks."""
        workflow = Workflow()

        workflow.add_task("a", Task("a", dummy_func))
        workflow.add_task("b", Task("b", dummy_func), dependencies=["a"])
        workflow.add_task("c", Task("c", dummy_func), dependencies=["b"])

        sorted_tasks = workflow.topological_sort()
        assert sorted_tasks == ["a", "b", "c"]

    def test_topological_sort_parallel(self) -> None:
        """Test topological sort with parallel tasks."""
        workflow = Workflow()

        workflow.add_task("root", Task("root", dummy_func))
        workflow.add_task("left", Task("left", dummy_func), dependencies=["root"])
        workflow.add_task("right", Task("right", dummy_func), dependencies=["root"])
        workflow.add_task("join", Task("join", dummy_func), dependencies=["left", "right"])

        sorted_tasks = workflow.topological_sort()
        assert sorted_tasks[0] == "root"
        assert sorted_tasks[-1] == "join"
        assert sorted_tasks.index("left") < sorted_tasks.index("join")
        assert sorted_tasks.index("right") < sorted_tasks.index("join")

    def test_topological_sort_cycle_detection(self) -> None:
        """Test cycle detection in workflow."""
        workflow = Workflow()

        workflow.add_task("a", Task("a", dummy_func))
        workflow.add_task("b", Task("b", dummy_func), dependencies=["a"])

        # Manually create a cycle
        workflow.nodes["a"].dependencies.add("b")

        with pytest.raises(WorkflowError):
            workflow.topological_sort()

    def test_get_status(self) -> None:
        """Test getting workflow status."""
        workflow = Workflow()
        workflow.add_task("node1", Task("task1", dummy_func))

        status = workflow.get_status()
        assert status["workflow_id"] == workflow.workflow_id
        assert status["total_tasks"] == 1
        assert status["completed_tasks"] == 0

    def test_get_task_status(self) -> None:
        """Test getting individual task status."""
        workflow = Workflow()
        task = Task("test", dummy_func)
        workflow.add_task("node1", task)

        task_status = workflow.get_task_status("node1")
        assert task_status is not None
        assert task_status["task_id"] == "node1"
        assert task_status["status"] == TaskStatus.PENDING.value

    def test_to_dict(self) -> None:
        """Test workflow serialization to dict."""
        workflow = Workflow(name="test_workflow")
        workflow.add_task("node1", Task("task1", dummy_func))

        workflow_dict = workflow.to_dict()
        assert workflow_dict["name"] == "test_workflow"
        assert "tasks" in workflow_dict
        assert "node1" in workflow_dict["tasks"]

    def test_workflow_repr(self) -> None:
        """Test workflow string representation."""
        workflow = Workflow(name="test")
        workflow.add_task("node1", Task("task1", dummy_func))

        repr_str = repr(workflow)
        assert "Workflow" in repr_str
        assert "test" in repr_str
        assert "1" in repr_str
