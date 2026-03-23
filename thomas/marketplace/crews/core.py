"""Multi-agent crew system with roles, tasks, and delegation.

Implements a multi-agent coordination system for complex task execution.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AgentRole(str, Enum):
    """Roles for agents."""

    LEADER = "leader"
    EXECUTOR = "executor"
    VALIDATOR = "validator"
    COORDINATOR = "coordinator"
    SPECIALIST = "specialist"


@dataclass
class Task:
    """A task for agents to execute."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    assigned_agent_id: str | None = None
    status: str = "pending"  # pending, in_progress, completed, failed
    priority: int = 0
    dependencies: list[str] = field(default_factory=list)
    result: Any | None = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    def mark_completed(self, result: Any) -> None:
        """Mark task as completed."""
        self.status = "completed"
        self.result = result
        self.completed_at = datetime.now()

    def mark_failed(self) -> None:
        """Mark task as failed."""
        self.status = "failed"
        self.completed_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "assigned_to": self.assigned_agent_id,
            "priority": self.priority,
        }


class Agent:
    """An agent in the crew."""

    def __init__(self, name: str, role: AgentRole):
        self.id = str(uuid.uuid4())
        self.name = name
        self.role = role
        self.skills: list[str] = []
        self.assigned_tasks: list[str] = []
        self.completed_tasks: int = 0
        self.failed_tasks: int = 0
        self.is_available = True

    def add_skill(self, skill: str) -> None:
        """Add a skill to the agent."""
        if skill not in self.skills:
            self.skills.append(skill)

    def assign_task(self, task_id: str) -> None:
        """Assign a task to the agent."""
        if task_id not in self.assigned_tasks:
            self.assigned_tasks.append(task_id)
            self.is_available = False

    def complete_task(self, task_id: str) -> None:
        """Mark a task as completed."""
        if task_id in self.assigned_tasks:
            self.assigned_tasks.remove(task_id)
            self.completed_tasks += 1
            if not self.assigned_tasks:
                self.is_available = True

    def fail_task(self, task_id: str) -> None:
        """Mark a task as failed."""
        if task_id in self.assigned_tasks:
            self.assigned_tasks.remove(task_id)
            self.failed_tasks += 1
            if not self.assigned_tasks:
                self.is_available = True

    def get_workload(self) -> int:
        """Get current workload (number of assigned tasks)."""
        return len(self.assigned_tasks)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role.value,
            "skills": self.skills,
            "workload": self.get_workload(),
            "completed_tasks": self.completed_tasks,
        }


class Crew:
    """A crew of agents working together."""

    def __init__(self, name: str):
        self.id = str(uuid.uuid4())
        self.name = name
        self.agents: dict[str, Agent] = {}
        self.tasks: dict[str, Task] = {}
        self.leader: Agent | None = None
        self.execution_log: list[dict[str, Any]] = []

    def add_agent(self, agent: Agent) -> None:
        """Add an agent to the crew."""
        self.agents[agent.id] = agent
        if agent.role == AgentRole.LEADER and not self.leader:
            self.leader = agent

    def add_task(self, task: Task) -> None:
        """Add a task to the crew."""
        self.tasks[task.id] = task

    def assign_task(self, task_id: str, agent_id: str) -> bool:
        """Assign a task to an agent."""
        if task_id not in self.tasks or agent_id not in self.agents:
            return False

        task = self.tasks[task_id]
        agent = self.agents[agent_id]

        task.assigned_agent_id = agent_id
        agent.assign_task(task_id)
        task.status = "in_progress"

        self.execution_log.append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "task_assigned",
                "task_id": task_id,
                "agent_id": agent_id,
            }
        )

        return True

    def find_available_agent(self, required_skills: list[str] | None = None) -> Agent | None:
        """Find an available agent with required skills."""
        candidates = [a for a in self.agents.values() if a.is_available]

        if required_skills:
            candidates = [a for a in candidates if any(skill in a.skills for skill in required_skills)]

        if not candidates:
            return None

        # Return agent with least workload
        return min(candidates, key=lambda a: a.get_workload())

    def complete_task(self, task_id: str, result: Any) -> bool:
        """Mark a task as completed."""
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        task.mark_completed(result)

        if task.assigned_agent_id:
            agent = self.agents.get(task.assigned_agent_id)
            if agent:
                agent.complete_task(task_id)

        self.execution_log.append(
            {"timestamp": datetime.now().isoformat(), "action": "task_completed", "task_id": task_id}
        )

        return True

    def fail_task(self, task_id: str) -> bool:
        """Mark a task as failed."""
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        task.mark_failed()

        if task.assigned_agent_id:
            agent = self.agents.get(task.assigned_agent_id)
            if agent:
                agent.fail_task(task_id)

        return True

    async def execute(self) -> dict[str, Any]:
        """Execute all tasks in the crew."""
        pending_tasks = [t for t in self.tasks.values() if t.status == "pending"]

        for task in pending_tasks:
            agent = self.find_available_agent(None)
            if agent:
                self.assign_task(task.id, agent.id)
                # Simulate task execution
                self.complete_task(task.id, f"Executed by {agent.name}")

        return self.get_crew_status()

    def get_crew_status(self) -> dict[str, Any]:
        """Get the status of the crew."""
        completed = sum(1 for t in self.tasks.values() if t.status == "completed")
        failed = sum(1 for t in self.tasks.values() if t.status == "failed")
        pending = sum(1 for t in self.tasks.values() if t.status == "pending")

        return {
            "crew_id": self.id,
            "crew_name": self.name,
            "agents": len(self.agents),
            "tasks_total": len(self.tasks),
            "tasks_completed": completed,
            "tasks_failed": failed,
            "tasks_pending": pending,
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "agents": [agent.to_dict() for agent in self.agents.values()],
            "tasks": [task.to_dict() for task in self.tasks.values()],
            "leader": self.leader.name if self.leader else None,
        }
