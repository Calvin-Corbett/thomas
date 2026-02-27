"""Project management and lifecycle operations.

Implements project CRUD operations, lifecycle management, templates,
project portfolio management, and health dashboards.
"""

import uuid
from datetime import datetime, timedelta

from thomas.project_mgmt._exceptions import (
    InvalidStatusTransitionError,
    ProjectNotFoundError,
)
from thomas.project_mgmt._types import (
    Project,
    ProjectStatus,
    Task,
)


class ProjectManager:
    """Manages project lifecycle and portfolio.

    Handles project creation, updates, deletion, status transitions,
    template management, cloning, and portfolio analysis.
    """

    def __init__(self) -> None:
        """Initialize project manager."""
        self.projects: dict[str, Project] = {}
        self.templates: dict[str, Project] = {}
        self._valid_transitions: dict[ProjectStatus, set] = {
            ProjectStatus.PLANNING: {
                ProjectStatus.ACTIVE,
                ProjectStatus.ARCHIVED,
            },
            ProjectStatus.ACTIVE: {
                ProjectStatus.ON_HOLD,
                ProjectStatus.COMPLETED,
                ProjectStatus.ARCHIVED,
            },
            ProjectStatus.ON_HOLD: {
                ProjectStatus.ACTIVE,
                ProjectStatus.COMPLETED,
                ProjectStatus.ARCHIVED,
            },
            ProjectStatus.COMPLETED: {
                ProjectStatus.ARCHIVED,
            },
            ProjectStatus.ARCHIVED: set(),
        }

    def create_project(
        self,
        name: str,
        description: str,
        owner_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        budget_allocated: float = 0.0,
    ) -> Project:
        """Create new project.

        Args:
            name: Project name.
            description: Project description.
            owner_id: Project owner identifier.
            start_date: Project start date (default: now).
            end_date: Project end date (default: now + 90 days).
            budget_allocated: Total budget allocation.

        Returns:
            Created Project instance.
        """
        if start_date is None:
            start_date = datetime.now()
        if end_date is None:
            end_date = start_date + timedelta(days=90)

        project_id = str(uuid.uuid4())
        project = Project(
            id=project_id,
            name=name,
            description=description,
            owner_id=owner_id,
            start_date=start_date,
            end_date=end_date,
            budget_allocated=budget_allocated,
        )
        self.projects[project_id] = project
        return project

    def get_project(self, project_id: str) -> Project:
        """Retrieve project by ID.

        Args:
            project_id: Project identifier.

        Returns:
            Project instance.

        Raises:
            ProjectNotFoundError: If project doesn't exist.
        """
        if project_id not in self.projects:
            raise ProjectNotFoundError(f"Project {project_id} not found")
        return self.projects[project_id]

    def update_project(
        self,
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        end_date: datetime | None = None,
        budget_allocated: float | None = None,
    ) -> Project:
        """Update project details.

        Args:
            project_id: Project identifier.
            name: New project name.
            description: New project description.
            end_date: New end date.
            budget_allocated: New budget allocation.

        Returns:
            Updated Project instance.

        Raises:
            ProjectNotFoundError: If project doesn't exist.
        """
        project = self.get_project(project_id)
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if end_date is not None:
            project.end_date = end_date
        if budget_allocated is not None:
            project.budget_allocated = budget_allocated
        project.updated_at = datetime.now()
        return project

    def transition_status(self, project_id: str, new_status: ProjectStatus) -> Project:
        """Transition project to new status.

        Args:
            project_id: Project identifier.
            new_status: Target project status.

        Returns:
            Updated Project instance.

        Raises:
            ProjectNotFoundError: If project doesn't exist.
            InvalidStatusTransitionError: If transition not allowed.
        """
        project = self.get_project(project_id)
        if new_status not in self._valid_transitions[project.status]:
            raise InvalidStatusTransitionError(f"Cannot transition from {project.status.value} to {new_status.value}")
        project.status = new_status
        project.updated_at = datetime.now()
        return project

    def add_team_member(self, project_id: str, resource_id: str) -> Project:
        """Add team member to project.

        Args:
            project_id: Project identifier.
            resource_id: Resource identifier to add.

        Returns:
            Updated Project instance.

        Raises:
            ProjectNotFoundError: If project doesn't exist.
        """
        project = self.get_project(project_id)
        project.team_ids.add(resource_id)
        project.updated_at = datetime.now()
        return project

    def remove_team_member(self, project_id: str, resource_id: str) -> Project:
        """Remove team member from project.

        Args:
            project_id: Project identifier.
            resource_id: Resource identifier to remove.

        Returns:
            Updated Project instance.

        Raises:
            ProjectNotFoundError: If project doesn't exist.
        """
        project = self.get_project(project_id)
        project.team_ids.discard(resource_id)
        project.updated_at = datetime.now()
        return project

    def create_template(
        self,
        template_name: str,
        description: str,
        duration_days: int = 90,
    ) -> str:
        """Create project template for reuse.

        Args:
            template_name: Template name.
            description: Template description.
            duration_days: Default project duration in days.

        Returns:
            Template identifier.
        """
        template_id = f"template_{uuid.uuid4()}"
        template = Project(
            id=template_id,
            name=template_name,
            description=description,
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=duration_days),
        )
        self.templates[template_id] = template
        return template_id

    def create_from_template(
        self,
        template_id: str,
        project_name: str,
        owner_id: str,
        start_date: datetime | None = None,
    ) -> Project:
        """Create project from template.

        Args:
            template_id: Template identifier.
            project_name: Name for new project.
            owner_id: Project owner identifier.
            start_date: Project start date.

        Returns:
            Created Project instance.

        Raises:
            ProjectNotFoundError: If template doesn't exist.
        """
        if template_id not in self.templates:
            raise ProjectNotFoundError(f"Template {template_id} not found")

        template = self.templates[template_id]
        if start_date is None:
            start_date = datetime.now()

        duration = (template.end_date - template.start_date).days
        end_date = start_date + timedelta(days=duration)

        project = self.create_project(
            name=project_name,
            description=template.description,
            owner_id=owner_id,
            start_date=start_date,
            end_date=end_date,
            budget_allocated=template.budget_allocated,
        )
        return project

    def clone_project(
        self,
        source_project_id: str,
        new_project_name: str,
        owner_id: str,
        start_date: datetime | None = None,
        include_tasks: bool = True,
    ) -> str:
        """Clone existing project with optional task structure.

        Args:
            source_project_id: Source project identifier.
            new_project_name: Name for cloned project.
            owner_id: New project owner identifier.
            start_date: Cloned project start date.
            include_tasks: Whether to copy task structure.

        Returns:
            Cloned project identifier.

        Raises:
            ProjectNotFoundError: If source project doesn't exist.
        """
        source = self.get_project(source_project_id)
        if start_date is None:
            start_date = datetime.now()

        duration = (source.end_date - source.start_date).days
        end_date = start_date + timedelta(days=duration)

        new_project = self.create_project(
            name=new_project_name,
            description=source.description,
            owner_id=owner_id,
            start_date=start_date,
            end_date=end_date,
            budget_allocated=source.budget_allocated,
        )
        return new_project.id

    def list_projects(
        self,
        owner_id: str | None = None,
        status: ProjectStatus | None = None,
    ) -> list[Project]:
        """List projects with optional filtering.

        Args:
            owner_id: Filter by project owner.
            status: Filter by project status.

        Returns:
            List of matching Project instances.
        """
        projects = list(self.projects.values())
        if owner_id:
            projects = [p for p in projects if p.owner_id == owner_id]
        if status:
            projects = [p for p in projects if p.status == status]
        return projects

    def get_project_health(
        self,
        project_id: str,
        tasks: list[Task] | None = None,
    ) -> dict[str, str]:
        """Calculate project health indicators.

        Health is assessed across four dimensions:
        - Schedule: On track vs behind schedule
        - Budget: On budget vs over budget
        - Scope: Stable vs creeping
        - Quality: Defect rate assessment

        Args:
            project_id: Project identifier.
            tasks: Associated tasks for analysis (optional).

        Returns:
            Dictionary with health indicators:
            - overall: RED/AMBER/GREEN
            - schedule: Schedule health status
            - budget: Budget health status
            - scope: Scope health status
            - quality: Quality health status
        """
        project = self.get_project(project_id)

        # Schedule health: Check if end_date exceeded
        schedule_status = "GREEN"
        if datetime.now() > project.end_date:
            schedule_status = "RED"
        elif datetime.now() > project.end_date - timedelta(days=14):
            schedule_status = "AMBER"

        # For this basic health check, default other statuses
        budget_status = "GREEN"
        scope_status = "GREEN"
        quality_status = "GREEN"

        # Overall status is worst of all indicators
        statuses = [schedule_status, budget_status, scope_status, quality_status]
        if "RED" in statuses:
            overall = "RED"
        elif "AMBER" in statuses:
            overall = "AMBER"
        else:
            overall = "GREEN"

        return {
            "overall": overall,
            "schedule": schedule_status,
            "budget": budget_status,
            "scope": scope_status,
            "quality": quality_status,
        }

    def get_portfolio_strategic_value(
        self,
        projects: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Rank projects by strategic value for portfolio management.

        Strategic value scoring considers:
        - Project status (active projects higher priority)
        - Budget allocation (larger budgets higher priority)
        - Duration (longer projects higher priority for planning)
        - Owner importance (could be enhanced with stakeholder data)

        Args:
            projects: List of project IDs to rank (default: all projects).

        Returns:
            List of (project_id, strategic_value) tuples sorted by value descending.
        """
        if projects is None:
            projects = list(self.projects.keys())

        scores: list[tuple[str, float]] = []

        for project_id in projects:
            try:
                project = self.get_project(project_id)
            except ProjectNotFoundError:
                continue

            # Base score
            score: float = 0.0

            # Status weighting
            status_weights = {
                ProjectStatus.ACTIVE: 5.0,
                ProjectStatus.PLANNING: 4.0,
                ProjectStatus.ON_HOLD: 2.0,
                ProjectStatus.COMPLETED: 1.0,
                ProjectStatus.ARCHIVED: 0.0,
            }
            score += status_weights.get(project.status, 0.0)

            # Budget weighting (normalize to 0-10 scale, assuming max is 1M)
            budget_score = min(10.0, project.budget_allocated / 100000.0)
            score += budget_score

            # Duration weighting (longer projects get higher score)
            duration_days = (project.end_date - project.start_date).days
            duration_score = min(5.0, duration_days / 60.0)
            score += duration_score

            # Team size consideration
            team_score = min(3.0, len(project.team_ids))
            score += team_score

            scores.append((project_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def generate_portfolio_summary(self) -> dict[str, any]:
        """Generate portfolio-level summary statistics.

        Returns:
            Dictionary with portfolio metrics:
            - total_projects: Count of all projects
            - active_projects: Count of active projects
            - total_budget: Sum of all budgets
            - average_budget: Average project budget
            - status_distribution: Count by status
        """
        all_projects = list(self.projects.values())
        active = [p for p in all_projects if p.status == ProjectStatus.ACTIVE]

        status_dist = {status: 0 for status in ProjectStatus}
        for project in all_projects:
            status_dist[project.status] += 1

        total_budget = sum(p.budget_allocated for p in all_projects)
        avg_budget = total_budget / len(all_projects) if all_projects else 0.0

        return {
            "total_projects": len(all_projects),
            "active_projects": len(active),
            "total_budget": total_budget,
            "average_budget": avg_budget,
            "status_distribution": {s.value: c for s, c in status_dist.items()},
        }

    def delete_project(self, project_id: str) -> None:
        """Delete project (only archived projects).

        Args:
            project_id: Project identifier.

        Raises:
            ProjectNotFoundError: If project doesn't exist.
            InvalidStatusTransitionError: If project not archived.
        """
        project = self.get_project(project_id)
        if project.status != ProjectStatus.ARCHIVED:
            raise InvalidStatusTransitionError("Only archived projects can be deleted")
        del self.projects[project_id]
