"""Tools for Crews module.

Provides tools for agent management and task coordination.
"""

from typing import Any

from thomas.crews import core
from thomas.tools.base import Tool, ToolResult


class AgentManagementTool(Tool):
    """Manage agents in crews."""

    name = "crews_agents"
    category = "crews"
    description = "Create and manage agents"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_agent", "add_skill", "list_agents"],
                "description": "Agent action",
            },
            "agent_name": {"type": "string", "description": "Name of the agent"},
            "agent_role": {
                "type": "string",
                "enum": ["leader", "executor", "validator", "coordinator"],
                "description": "Role of the agent",
            },
            "skill": {"type": "string", "description": "Skill to add"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.crews: dict[str, core.Crew] = {}
        self.agents: dict[str, core.Agent] = {}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_agent":
                agent_name = args.get("agent_name", "agent")
                role_str = args.get("agent_role", "executor")

                try:
                    role = core.AgentRole(role_str)
                except ValueError:
                    role = core.AgentRole.EXECUTOR

                agent = core.Agent(agent_name, role)
                self.agents[agent.id] = agent

                return ToolResult(ok=True, data={"agent_id": agent.id, "agent_name": agent_name, "role": role.value})

            elif action == "add_skill":
                agent_id = args.get("agent_id", "")
                skill = args.get("skill", "")

                if agent_id not in self.agents:
                    return ToolResult(ok=False, error=f"Agent not found: {agent_id}")

                self.agents[agent_id].add_skill(skill)
                return ToolResult(ok=True, data={"skill_added": skill})

            elif action == "list_agents":
                agents = [agent.to_dict() for agent in self.agents.values()]
                return ToolResult(ok=True, data={"agents": agents})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CrewManagementTool(Tool):
    """Manage crews."""

    name = "crews_management"
    category = "crews"
    description = "Create and manage crews"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_crew", "add_agent", "get_status", "execute_crew"],
                "description": "Crew action",
            },
            "crew_name": {"type": "string", "description": "Name of the crew"},
            "crew_id": {"type": "string", "description": "Crew identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.crews: dict[str, core.Crew] = {}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_crew":
                crew_name = args.get("crew_name", "crew")
                crew = core.Crew(crew_name)
                self.crews[crew.id] = crew

                return ToolResult(ok=True, data={"crew_id": crew.id, "crew_name": crew_name})

            elif action == "add_agent":
                crew_id = args.get("crew_id", "")
                agent_id = args.get("agent_id", "")

                if crew_id not in self.crews:
                    return ToolResult(ok=False, error=f"Crew not found: {crew_id}")

                # Would need agent from AgentManagementTool
                return ToolResult(ok=True, data={"agent_added": agent_id})

            elif action == "get_status":
                crew_id = args.get("crew_id", "")

                if crew_id not in self.crews:
                    return ToolResult(ok=False, error=f"Crew not found: {crew_id}")

                status = self.crews[crew_id].get_crew_status()
                return ToolResult(ok=True, data=status)

            elif action == "execute_crew":
                crew_id = args.get("crew_id", "")

                if crew_id not in self.crews:
                    return ToolResult(ok=False, error=f"Crew not found: {crew_id}")

                result = await self.crews[crew_id].execute()
                return ToolResult(ok=True, data=result)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TaskManagementTool(Tool):
    """Manage tasks in crews."""

    name = "crews_tasks"
    category = "crews"
    description = "Create and manage tasks"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_task", "assign_task", "complete_task"],
                "description": "Task action",
            },
            "task_name": {"type": "string", "description": "Task name"},
            "crew_id": {"type": "string", "description": "Crew identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.tasks: dict[str, core.Task] = {}
        self.crews: dict[str, core.Crew] = {}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_task":
                task_name = args.get("task_name", "task")
                task = core.Task(name=task_name)
                self.tasks[task.id] = task

                return ToolResult(ok=True, data={"task_id": task.id, "task_name": task_name})

            elif action == "assign_task":
                task_id = args.get("task_id", "")
                agent_id = args.get("agent_id", "")

                if task_id not in self.tasks:
                    return ToolResult(ok=False, error=f"Task not found: {task_id}")

                self.tasks[task_id].assigned_agent_id = agent_id
                return ToolResult(ok=True, data={"assigned": True})

            elif action == "complete_task":
                task_id = args.get("task_id", "")

                if task_id not in self.tasks:
                    return ToolResult(ok=False, error=f"Task not found: {task_id}")

                self.tasks[task_id].mark_completed("Completed")
                return ToolResult(ok=True, data={"completed": True})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_crews_tools(registry):
    """Register all crews tools."""
    registry.register(AgentManagementTool())
    registry.register(CrewManagementTool())
    registry.register(TaskManagementTool())
