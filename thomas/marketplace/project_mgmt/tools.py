"""Tools for Project Management system - exposes project, task, sprint, and resource management."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from thomas.tools.base import Tool, ToolResult


class PMCreateProjectTool(Tool):
    """Create a new project."""

    name = "pm.create_project"
    category = "project_management"
    description = "Create a new project with name, description, start and end dates"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Project name"},
            "description": {"type": "string", "description": "Project description"},
            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
            "methodology": {
                "type": "string",
                "enum": ["waterfall", "agile", "hybrid"],
                "description": "Project methodology",
            },
            "budget": {"type": "number", "description": "Project budget"},
        },
        "required": ["name", "description", "start_date", "end_date"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.project_mgmt.projects import ProjectManager

        pm = ProjectManager()
        try:
            start = datetime.fromisoformat(args["start_date"]).date()
            end = datetime.fromisoformat(args["end_date"]).date()
            project = pm.create_project(
                name=args["name"],
                description=args["description"],
                start_date=start,
                end_date=end,
                methodology=args.get("methodology", "hybrid"),
                budget=Decimal(str(args.get("budget", 0))),
            )
            return ToolResult(
                ok=True,
                data={
                    "id": project.id,
                    "name": project.name,
                    "start_date": str(project.start_date),
                    "end_date": str(project.end_date),
                    "status": project.status.name if hasattr(project.status, "name") else str(project.status),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PMGetProjectTool(Tool):
    """Get project details."""

    name = "pm.get_project"
    category = "project_management"
    description = "Retrieve project details including status, timeline, and team members"
    parameters = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "Project ID"},
        },
        "required": ["project_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.project_mgmt.projects import ProjectManager

        pm = ProjectManager()
        try:
            project = pm.get_project(args["project_id"])
            return ToolResult(
                ok=True,
                data={
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "start_date": str(project.start_date),
                    "end_date": str(project.end_date),
                    "status": project.status.name if hasattr(project.status, "name") else str(project.status),
                    "methodology": project.methodology,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PMListProjectsTool(Tool):
    """List all projects."""

    name = "pm.list_projects"
    category = "project_management"
    description = "Retrieve a list of all projects"
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by status (optional)"},
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.project_mgmt.projects import ProjectManager

        pm = ProjectManager()
        try:
            projects = pm.list_projects(status=args.get("status"))
            return ToolResult(
                ok=True,
                data=[
                    {
                        "id": p.id,
                        "name": p.name,
                        "start_date": str(p.start_date),
                        "end_date": str(p.end_date),
                        "status": p.status.name if hasattr(p.status, "name") else str(p.status),
                    }
                    for p in projects
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PMCreateTaskTool(Tool):
    """Create a new task in a project."""

    name = "pm.create_task"
    category = "project_management"
    description = "Create a new task with title, description, assignee, and due date"
    parameters = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "Project ID"},
            "title": {"type": "string", "description": "Task title"},
            "description": {"type": "string", "description": "Task description"},
            "assigned_to": {"type": "string", "description": "Assignee ID"},
            "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD)"},
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
                "description": "Task priority",
            },
            "estimated_hours": {"type": "number", "description": "Estimated hours (optional)"},
        },
        "required": ["project_id", "title", "assigned_to", "due_date"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.project_mgmt._types import Priority
        from thomas.marketplace.project_mgmt.tasks import TaskManager

        tm = TaskManager()
        try:
            due = datetime.fromisoformat(args["due_date"]).date()
            task = tm.create_task(
                project_id=args["project_id"],
                title=args["title"],
                description=args.get("description", ""),
                assigned_to=args["assigned_to"],
                due_date=due,
                priority=Priority[args.get("priority", "medium").upper()],
                estimated_hours=float(args.get("estimated_hours", 0)),
            )
            return ToolResult(
                ok=True,
                data={
                    "id": task.id,
                    "title": task.title,
                    "assigned_to": task.assigned_to,
                    "due_date": str(task.due_date),
                    "priority": task.priority.name if hasattr(task.priority, "name") else str(task.priority),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PMListTasksTool(Tool):
    """List tasks in a project."""

    name = "pm.list_tasks"
    category = "project_management"
    description = "Retrieve all tasks in a project with their status and assignees"
    parameters = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "Project ID"},
            "status": {"type": "string", "description": "Filter by status (optional)"},
        },
        "required": ["project_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.project_mgmt.tasks import TaskManager

        tm = TaskManager()
        try:
            tasks = tm.list_tasks(args["project_id"], status=args.get("status"))
            return ToolResult(
                ok=True,
                data=[
                    {
                        "id": t.id,
                        "title": t.title,
                        "assigned_to": t.assigned_to,
                        "due_date": str(t.due_date),
                        "status": t.status.name if hasattr(t.status, "name") else str(t.status),
                        "priority": t.priority.name if hasattr(t.priority, "name") else str(t.priority),
                    }
                    for t in tasks
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PMGetProjectHealthTool(Tool):
    """Get project health status."""

    name = "pm.get_project_health"
    category = "project_management"
    description = "Retrieve project health metrics including schedule, budget, and quality status"
    parameters = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "Project ID"},
        },
        "required": ["project_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.project_mgmt.projects import ProjectManager

        pm = ProjectManager()
        try:
            health = pm.get_project_health(args["project_id"])
            return ToolResult(ok=True, data=health)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PMCreateSprintTool(Tool):
    """Create a new sprint for agile projects."""

    name = "pm.create_sprint"
    category = "project_management"
    description = "Create a new sprint with name, start date, and end date"
    parameters = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "Project ID"},
            "name": {"type": "string", "description": "Sprint name"},
            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
            "goal": {"type": "string", "description": "Sprint goal (optional)"},
        },
        "required": ["project_id", "name", "start_date", "end_date"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.project_mgmt.agile import AgileManager

        am = AgileManager()
        try:
            start = datetime.fromisoformat(args["start_date"]).date()
            end = datetime.fromisoformat(args["end_date"]).date()
            sprint = am.create_sprint(
                project_id=args["project_id"],
                name=args["name"],
                start_date=start,
                end_date=end,
                goal=args.get("goal", ""),
            )
            return ToolResult(
                ok=True,
                data={
                    "id": sprint.id,
                    "name": sprint.name,
                    "start_date": str(sprint.start_date),
                    "end_date": str(sprint.end_date),
                    "goal": sprint.goal,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PMGetResourcesTool(Tool):
    """Get project resources and team members."""

    name = "pm.get_resources"
    category = "project_management"
    description = "Retrieve project resources and team member allocations"
    parameters = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "Project ID"},
        },
        "required": ["project_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.project_mgmt.resources import ResourceManager

        rm = ResourceManager()
        try:
            resources = rm.get_project_resources(args["project_id"])
            return ToolResult(
                ok=True,
                data=[
                    {
                        "id": r.id,
                        "name": r.name,
                        "role": r.role,
                        "allocation": r.allocation,
                    }
                    for r in resources
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_project_mgmt_tools(registry, sandbox=None):
    """Register all project management tools."""
    registry.register(PMCreateProjectTool())
    registry.register(PMGetProjectTool())
    registry.register(PMListProjectsTool())
    registry.register(PMCreateTaskTool())
    registry.register(PMListTasksTool())
    registry.register(PMGetProjectHealthTool())
    registry.register(PMCreateSprintTool())
    registry.register(PMGetResourcesTool())
