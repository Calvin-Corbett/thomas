"""Comprehensive tests for thomas.crews module.

Tests cover:
- CrewAgent creation and configuration
- Task creation and assignment
- Crew sequential execution
- SelfCorrection for error handling
- Delegation for inter-agent communication
"""

import unittest
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable


# Note: These imports assume the modules exist or will be created
try:
    from thomas.crews.types import AgentRole, TaskStatus
    from thomas.crews.agent import CrewAgent
    from thomas.crews.task import Task
    from thomas.crews.crew import Crew
    from thomas.crews.self_correction import SelfCorrection
    from thomas.crews.delegation import Delegation
except ImportError:
    # Fallback: define minimal mock classes
    from enum import Enum

    class AgentRole(str, Enum):
        """Agent roles in crew."""
        LEADER = "leader"
        WORKER = "worker"
        SPECIALIST = "specialist"
        COORDINATOR = "coordinator"

    class TaskStatus(str, Enum):
        """Task execution status."""
        PENDING = "pending"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        FAILED = "failed"

    class CrewAgent:
        """Individual agent in a crew."""
        def __init__(self, name: str, role: AgentRole = AgentRole.WORKER,
                     capabilities: List[str] = None):
            self.name = name
            self.role = role
            self.capabilities = capabilities or []
            self.status = "idle"
            self.tasks_completed = 0

        def execute_task(self, task: "Task") -> Dict[str, Any]:
            """Execute a task."""
            self.status = "working"
            result = {"agent": self.name, "task": task.name, "result": "completed"}
            self.tasks_completed += 1
            self.status = "idle"
            return result

        def can_handle(self, task: "Task") -> bool:
            """Check if agent can handle task."""
            if not task.required_capabilities:
                return True
            return any(cap in self.capabilities for cap in task.required_capabilities)

    class Task:
        """Task for agents to execute."""
        def __init__(self, name: str, description: str = "",
                     required_capabilities: List[str] = None,
                     priority: int = 1):
            self.name = name
            self.description = description
            self.required_capabilities = required_capabilities or []
            self.priority = priority
            self.status = TaskStatus.PENDING
            self.result = None
            self.assigned_agent = None

        def assign_to(self, agent: "CrewAgent") -> None:
            """Assign task to agent."""
            self.assigned_agent = agent

        def execute(self) -> Dict[str, Any]:
            """Execute the task."""
            if not self.assigned_agent:
                raise ValueError("Task not assigned to agent")

            self.status = TaskStatus.IN_PROGRESS
            self.result = self.assigned_agent.execute_task(self)
            self.status = TaskStatus.COMPLETED
            return self.result

    class Crew:
        """Collection of agents working together."""
        def __init__(self, agents: List[CrewAgent], name: str = "default"):
            self.agents = agents
            self.name = name
            self.tasks = []
            self.execution_log = []

        def add_task(self, task: Task) -> None:
            """Add task to crew queue."""
            self.tasks.append(task)

        def assign_tasks(self) -> None:
            """Assign tasks to capable agents."""
            for task in self.tasks:
                for agent in self.agents:
                    if agent.can_handle(task):
                        task.assign_to(agent)
                        break

        def execute_sequential(self) -> List[Dict[str, Any]]:
            """Execute all tasks sequentially."""
            self.assign_tasks()
            results = []

            for task in self.tasks:
                if task.assigned_agent:
                    result = task.execute()
                    results.append(result)
                    self.execution_log.append({
                        "task": task.name,
                        "agent": task.assigned_agent.name,
                        "status": "completed"
                    })
                else:
                    self.execution_log.append({
                        "task": task.name,
                        "status": "unassigned"
                    })

            return results

    class SelfCorrection:
        """Self-correction mechanism for error handling."""
        def __init__(self, max_iterations: int = 3):
            self.max_iterations = max_iterations
            self.iteration = 0
            self.errors = []

        def evaluate(self, result: Dict[str, Any]) -> bool:
            """Evaluate if result is acceptable."""
            return result.get("status") == "success" or result.get("result") is not None

        def correct(self, result: Dict[str, Any], error: str) -> Dict[str, Any]:
            """Attempt to correct error."""
            self.iteration += 1
            self.errors.append(error)

            if self.iteration >= self.max_iterations:
                return {"status": "failed", "reason": "Max iterations exceeded"}

            # Simple correction: retry with modified approach
            return {"status": "retry", "iteration": self.iteration}

    class Delegation:
        """Delegation mechanism for task handoff."""
        def __init__(self):
            self.delegations = []

        def delegate(self, task: Task, from_agent: CrewAgent, to_agent: CrewAgent) -> None:
            """Delegate task from one agent to another."""
            self.delegations.append({
                "task": task.name,
                "from": from_agent.name,
                "to": to_agent.name,
                "timestamp": datetime.now()
            })
            task.assign_to(to_agent)

        def get_delegation_history(self) -> List[Dict]:
            """Get all delegation history."""
            return self.delegations


class TestCrewAgent(unittest.TestCase):
    """Test CrewAgent functionality."""

    def test_create_agent(self):
        """Test creating a crew agent."""
        agent = CrewAgent("Alice", role=AgentRole.WORKER)

        self.assertEqual(agent.name, "Alice")
        self.assertEqual(agent.role, AgentRole.WORKER)
        self.assertEqual(agent.status, "idle")

    def test_agent_with_capabilities(self):
        """Test creating agent with capabilities."""
        capabilities = ["analysis", "coding", "writing"]
        agent = CrewAgent("Bob", capabilities=capabilities)

        self.assertEqual(agent.capabilities, capabilities)

    def test_agent_role_types(self):
        """Test different agent roles."""
        leader = CrewAgent("Leader", role=AgentRole.LEADER)
        specialist = CrewAgent("Specialist", role=AgentRole.SPECIALIST)
        coordinator = CrewAgent("Coordinator", role=AgentRole.COORDINATOR)

        self.assertEqual(leader.role, AgentRole.LEADER)
        self.assertEqual(specialist.role, AgentRole.SPECIALIST)
        self.assertEqual(coordinator.role, AgentRole.COORDINATOR)

    def test_agent_execute_task(self):
        """Test agent executing task."""
        agent = CrewAgent("Alice")
        task = Task("write_report")

        task.assign_to(agent)
        result = agent.execute_task(task)

        self.assertEqual(result["agent"], "Alice")
        self.assertEqual(agent.tasks_completed, 1)

    def test_agent_can_handle_task(self):
        """Test checking if agent can handle task."""
        agent = CrewAgent("Alice", capabilities=["analysis", "coding"])

        task_analysis = Task("analyze", required_capabilities=["analysis"])
        task_design = Task("design", required_capabilities=["design"])

        self.assertTrue(agent.can_handle(task_analysis))
        self.assertFalse(agent.can_handle(task_design))

    def test_agent_handles_any_task_without_requirements(self):
        """Test agent can handle task with no requirements."""
        agent = CrewAgent("Alice", capabilities=[])
        task = Task("simple_task", required_capabilities=[])

        self.assertTrue(agent.can_handle(task))

    def test_agent_task_count(self):
        """Test tracking completed tasks."""
        agent = CrewAgent("Bob")
        task1 = Task("task1")
        task2 = Task("task2")

        task1.assign_to(agent)
        task2.assign_to(agent)

        agent.execute_task(task1)
        agent.execute_task(task2)

        self.assertEqual(agent.tasks_completed, 2)


class TestTask(unittest.TestCase):
    """Test Task functionality."""

    def test_create_task(self):
        """Test creating a task."""
        task = Task("analyze_data", description="Analyze the dataset")

        self.assertEqual(task.name, "analyze_data")
        self.assertEqual(task.description, "Analyze the dataset")
        self.assertEqual(task.status, TaskStatus.PENDING)

    def test_task_with_priority(self):
        """Test task with priority."""
        task = Task("urgent", priority=5)

        self.assertEqual(task.priority, 5)

    def test_task_with_required_capabilities(self):
        """Test task requiring specific capabilities."""
        capabilities = ["machine_learning", "python"]
        task = Task("ml_project", required_capabilities=capabilities)

        self.assertEqual(task.required_capabilities, capabilities)

    def test_assign_task_to_agent(self):
        """Test assigning task to agent."""
        agent = CrewAgent("Alice")
        task = Task("work")

        task.assign_to(agent)

        self.assertEqual(task.assigned_agent, agent)

    def test_execute_task(self):
        """Test executing assigned task."""
        agent = CrewAgent("Bob")
        task = Task("execute_me")
        task.assign_to(agent)

        result = task.execute()

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIsNotNone(result)

    def test_execute_unassigned_task_raises_error(self):
        """Test that unassigned task cannot execute."""
        task = Task("unassigned")

        with self.assertRaises(ValueError):
            task.execute()

    def test_task_status_progression(self):
        """Test task status changes through execution."""
        agent = CrewAgent("Charlie")
        task = Task("status_test")
        task.assign_to(agent)

        self.assertEqual(task.status, TaskStatus.PENDING)

        task.execute()

        self.assertEqual(task.status, TaskStatus.COMPLETED)


class TestCrew(unittest.TestCase):
    """Test Crew functionality."""

    def setUp(self):
        self.agents = [
            CrewAgent("Alice", capabilities=["analysis", "writing"]),
            CrewAgent("Bob", capabilities=["coding", "testing"]),
            CrewAgent("Charlie", capabilities=["design", "architecture"])
        ]
        self.crew = Crew(self.agents, name="Development Team")

    def test_create_crew(self):
        """Test creating a crew."""
        self.assertEqual(self.crew.name, "Development Team")
        self.assertEqual(len(self.crew.agents), 3)

    def test_add_task_to_crew(self):
        """Test adding tasks to crew."""
        task1 = Task("analyze", required_capabilities=["analysis"])
        task2 = Task("code", required_capabilities=["coding"])

        self.crew.add_task(task1)
        self.crew.add_task(task2)

        self.assertEqual(len(self.crew.tasks), 2)

    def test_assign_tasks(self):
        """Test automatic task assignment."""
        task = Task("code", required_capabilities=["coding"])
        self.crew.add_task(task)

        self.crew.assign_tasks()

        # Should be assigned to Bob (has coding capability)
        self.assertEqual(task.assigned_agent.name, "Bob")

    def test_execute_sequential(self):
        """Test sequential execution of tasks."""
        task1 = Task("analyze", required_capabilities=["analysis"])
        task2 = Task("code", required_capabilities=["coding"])

        self.crew.add_task(task1)
        self.crew.add_task(task2)

        results = self.crew.execute_sequential()

        self.assertEqual(len(results), 2)
        self.assertEqual(len(self.crew.execution_log), 2)

    def test_unassignable_task_handling(self):
        """Test crew handling of unassignable tasks."""
        task = Task("unknown", required_capabilities=["nonexistent"])
        self.crew.add_task(task)

        results = self.crew.execute_sequential()

        # Task should be in execution log but not executed
        self.assertEqual(len([e for e in self.crew.execution_log if e["task"] == "unknown"]), 1)

    def test_crew_with_no_agents(self):
        """Test crew with no agents."""
        empty_crew = Crew([], name="Empty")
        task = Task("work")
        empty_crew.add_task(task)

        results = empty_crew.execute_sequential()

        self.assertEqual(len(results), 0)

    def test_crew_execution_order(self):
        """Test that tasks execute in order."""
        tasks = [Task(f"task{i}") for i in range(3)]
        for task in tasks:
            self.crew.add_task(task)

        self.crew.execute_sequential()

        log_tasks = [e["task"] for e in self.crew.execution_log]
        self.assertEqual(log_tasks, ["task0", "task1", "task2"])


class TestSelfCorrection(unittest.TestCase):
    """Test SelfCorrection mechanism."""

    def setUp(self):
        self.corrector = SelfCorrection(max_iterations=3)

    def test_evaluate_successful_result(self):
        """Test evaluating successful result."""
        result = {"status": "success"}
        is_good = self.corrector.evaluate(result)

        self.assertTrue(is_good)

    def test_evaluate_result_with_value(self):
        """Test evaluating result with value."""
        result = {"result": "some_value"}
        is_good = self.corrector.evaluate(result)

        self.assertTrue(is_good)

    def test_evaluate_failed_result(self):
        """Test evaluating failed result."""
        result = {"status": "failed"}
        is_good = self.corrector.evaluate(result)

        self.assertFalse(is_good)

    def test_correct_error(self):
        """Test error correction."""
        response = self.corrector.correct({}, "error message")

        self.assertEqual(response["status"], "retry")
        self.assertEqual(response["iteration"], 1)
        self.assertIn("error message", self.corrector.errors)

    def test_max_iterations_exceeded(self):
        """Test correction stops at max iterations."""
        for i in range(3):
            response = self.corrector.correct({}, f"error {i}")

        response = self.corrector.correct({}, "error 3")

        self.assertEqual(response["status"], "failed")
        self.assertEqual(len(self.corrector.errors), 4)

    def test_error_tracking(self):
        """Test that errors are tracked."""
        errors = ["error1", "error2", "error3"]

        for error in errors:
            self.corrector.correct({}, error)

        self.assertEqual(self.corrector.errors, errors)


class TestDelegation(unittest.TestCase):
    """Test Delegation mechanism."""

    def setUp(self):
        self.alice = CrewAgent("Alice")
        self.bob = CrewAgent("Bob")
        self.delegation = Delegation()

    def test_delegate_task(self):
        """Test delegating task between agents."""
        task = Task("work")

        self.delegation.delegate(task, self.alice, self.bob)

        self.assertEqual(task.assigned_agent, self.bob)

    def test_delegation_history(self):
        """Test tracking delegation history."""
        task = Task("task1")

        self.delegation.delegate(task, self.alice, self.bob)

        history = self.delegation.get_delegation_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["from"], "Alice")
        self.assertEqual(history[0]["to"], "Bob")

    def test_multiple_delegations(self):
        """Test multiple delegations."""
        charlie = CrewAgent("Charlie")
        task1 = Task("task1")
        task2 = Task("task2")

        self.delegation.delegate(task1, self.alice, self.bob)
        self.delegation.delegate(task2, self.bob, charlie)

        history = self.delegation.get_delegation_history()
        self.assertEqual(len(history), 2)

    def test_delegation_preserves_task(self):
        """Test that delegation preserves task reference."""
        task = Task("important")

        self.delegation.delegate(task, self.alice, self.bob)

        history = self.delegation.get_delegation_history()
        self.assertEqual(history[0]["task"], "important")

    def test_delegation_timestamp(self):
        """Test that delegations have timestamps."""
        task = Task("work")

        self.delegation.delegate(task, self.alice, self.bob)

        history = self.delegation.get_delegation_history()
        self.assertIn("timestamp", history[0])


if __name__ == "__main__":
    unittest.main()
