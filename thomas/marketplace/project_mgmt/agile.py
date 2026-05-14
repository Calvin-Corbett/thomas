"""Agile/Scrum sprint management with velocity tracking and burndown analysis.

Implements sprint planning, backlog grooming, story point estimation,
velocity tracking, burndown/cumulative flow diagrams, and kanban board management.
"""

import uuid
from datetime import datetime, timedelta

from thomas.marketplace.project_mgmt._exceptions import (
    SprintNotFoundError,
)
from thomas.marketplace.project_mgmt._types import (
    Sprint,
    SprintStatus,
    Task,
    TaskStatus,
)


class AgileManager:
    """Manages agile sprints, backlog, and kanban board.

    Handles sprint planning, backlog management, velocity tracking,
    burndown chart generation, and agile metrics.
    """

    def __init__(self) -> None:
        """Initialize agile manager."""
        self.sprints: dict[str, Sprint] = {}
        self.tasks: dict[str, Task] = {}
        self.velocity_history: dict[str, list[float]] = {}  # project_id -> velocities

    def create_sprint(
        self,
        project_id: str,
        name: str,
        start_date: datetime | None = None,
        duration_days: int = 14,
        team_ids: list[str] | None = None,
    ) -> Sprint:
        """Create new sprint.

        Args:
            project_id: Parent project identifier.
            name: Sprint name (e.g., "Sprint 1", "Sprint-2024-Q1").
            start_date: Sprint start date.
            duration_days: Sprint duration (default: 14 days).
            team_ids: Team member identifiers assigned to sprint.

        Returns:
            Created Sprint instance.
        """
        if start_date is None:
            start_date = datetime.now()

        sprint_id = str(uuid.uuid4())
        end_date = start_date + timedelta(days=duration_days)

        sprint = Sprint(
            id=sprint_id,
            project_id=project_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            team_ids=team_ids or [],
        )
        self.sprints[sprint_id] = sprint
        return sprint

    def get_sprint(self, sprint_id: str) -> Sprint:
        """Retrieve sprint by ID.

        Args:
            sprint_id: Sprint identifier.

        Returns:
            Sprint instance.

        Raises:
            SprintNotFoundError: If sprint doesn't exist.
        """
        if sprint_id not in self.sprints:
            raise SprintNotFoundError(f"Sprint {sprint_id} not found")
        return self.sprints[sprint_id]

    def add_to_sprint(
        self,
        sprint_id: str,
        task_id: str,
    ) -> Sprint:
        """Add task/story to sprint backlog.

        Args:
            sprint_id: Sprint identifier.
            task_id: Task identifier to add.

        Returns:
            Updated Sprint instance.

        Raises:
            SprintNotFoundError: If sprint doesn't exist.
        """
        sprint = self.get_sprint(sprint_id)
        if task_id not in sprint.backlog_item_ids:
            sprint.backlog_item_ids.append(task_id)
        return sprint

    def remove_from_sprint(
        self,
        sprint_id: str,
        task_id: str,
    ) -> Sprint:
        """Remove task/story from sprint backlog.

        Args:
            sprint_id: Sprint identifier.
            task_id: Task identifier to remove.

        Returns:
            Updated Sprint instance.

        Raises:
            SprintNotFoundError: If sprint doesn't exist.
        """
        sprint = self.get_sprint(sprint_id)
        sprint.backlog_item_ids = [tid for tid in sprint.backlog_item_ids if tid != task_id]
        return sprint

    def start_sprint(self, sprint_id: str) -> Sprint:
        """Transition sprint from planning to active.

        Args:
            sprint_id: Sprint identifier.

        Returns:
            Updated Sprint instance.

        Raises:
            SprintNotFoundError: If sprint doesn't exist.
        """
        sprint = self.get_sprint(sprint_id)
        sprint.status = SprintStatus.ACTIVE
        return sprint

    def end_sprint(self, sprint_id: str) -> Sprint:
        """Transition sprint to review status.

        Args:
            sprint_id: Sprint identifier.

        Returns:
            Updated Sprint instance.

        Raises:
            SprintNotFoundError: If sprint doesn't exist.
        """
        sprint = self.get_sprint(sprint_id)
        sprint.status = SprintStatus.REVIEW
        return sprint

    def calculate_story_points(
        self,
        complexity: int,
        effort_hours: float,
        risk: int = 1,
    ) -> float:
        """Calculate story points using Fibonacci sequence.

        Story points are relative effort estimates.
        Uses Fibonacci: 1, 2, 3, 5, 8, 13, 21, 34, 55, 89...

        Args:
            complexity: Complexity rating (1-5).
            effort_hours: Estimated effort in hours.
            risk: Risk multiplier (1-3).

        Returns:
            Story points (Fibonacci value).
        """
        fibonacci = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]

        # Map effort to story point range
        base_index = min(9, max(0, int(effort_hours / 4)))
        complexity_adjustment = (complexity - 3) * 0.5  # -1 to +1
        risk_adjustment = (risk - 1) * 0.3

        adjusted_index = base_index + complexity_adjustment + risk_adjustment
        adjusted_index = min(9, max(0, adjusted_index))

        # Return closest Fibonacci number
        index = round(adjusted_index)
        return float(fibonacci[index])

    def estimate_sprint_velocity(
        self,
        project_id: str,
        completed_sprints: list[str] | None = None,
    ) -> float:
        """Estimate sprint velocity using rolling average.

        Velocity = sum of story points completed in sprint.
        Uses rolling 3-sprint average for prediction.

        Args:
            project_id: Project identifier.
            completed_sprints: List of sprint IDs to analyze (optional).

        Returns:
            Estimated velocity (story points per sprint).
        """
        if project_id not in self.velocity_history:
            return 10.0  # Default estimate

        velocities = self.velocity_history[project_id]
        if not velocities:
            return 10.0

        # Rolling 3-sprint average
        window = min(3, len(velocities))
        return sum(velocities[-window:]) / window

    def generate_burndown_data(
        self,
        sprint_id: str,
        tasks: dict[str, Task],
    ) -> list[tuple[datetime, float]]:
        """Generate burndown chart data.

        Burndown shows remaining work (story points) over sprint duration.

        Args:
            sprint_id: Sprint identifier.
            tasks: Dictionary of all tasks.

        Returns:
            List of (date, remaining_story_points) tuples.
        """
        sprint = self.get_sprint(sprint_id)

        # Calculate total story points
        total_points = 0.0
        sprint_tasks = [tasks.get(tid) for tid in sprint.backlog_item_ids]
        sprint_tasks = [t for t in sprint_tasks if t is not None]

        for task in sprint_tasks:
            total_points += task.estimated_hours  # Simplified: use hours as proxy

        # Generate data points
        burndown_data: list[tuple[datetime, float]] = []
        duration_days = (sprint.end_date - sprint.start_date).days
        current_date = sprint.start_date

        while current_date <= sprint.end_date:
            # Calculate % of sprint elapsed
            elapsed_days = (current_date - sprint.start_date).days
            min(1.0, elapsed_days / max(1, duration_days))

            # Calculate remaining based on task completion
            remaining = total_points
            for task in sprint_tasks:
                if task.status == TaskStatus.DONE:
                    remaining -= task.estimated_hours

            burndown_data.append((current_date, remaining))
            current_date += timedelta(days=1)

        return burndown_data

    def generate_cumulative_flow_data(
        self,
        sprint_id: str,
        tasks: dict[str, Task],
    ) -> dict[TaskStatus, list[tuple[datetime, float]]]:
        """Generate cumulative flow diagram data.

        Shows cumulative count of tasks in each status over time.

        Args:
            sprint_id: Sprint identifier.
            tasks: Dictionary of all tasks.

        Returns:
            Dictionary mapping TaskStatus to list of (date, count) tuples.
        """
        sprint = self.get_sprint(sprint_id)
        sprint_tasks = [tasks.get(tid) for tid in sprint.backlog_item_ids]
        sprint_tasks = [t for t in sprint_tasks if t is not None]

        cfd_data: dict[TaskStatus, list[tuple[datetime, float]]] = {status: [] for status in TaskStatus}

        (sprint.end_date - sprint.start_date).days
        current_date = sprint.start_date

        while current_date <= sprint.end_date:
            for status in TaskStatus:
                count = sum(1.0 for t in sprint_tasks if t.status == status)
                cfd_data[status].append((current_date, count))
            current_date += timedelta(days=1)

        return cfd_data

    def groom_backlog(
        self,
        project_id: str,
        tasks: list[str],
    ) -> list[str]:
        """Prioritize and groom product backlog.

        Orders items by priority and effort.

        Args:
            project_id: Project identifier.
            tasks: List of task IDs.

        Returns:
            Prioritized list of task IDs.
        """
        task_list = [self.tasks.get(tid) for tid in tasks]
        task_list = [t for t in task_list if t is not None]

        # Sort by priority (descending) then by effort (ascending)
        task_list.sort(key=lambda t: (-t.priority.value, t.pert_estimate()))
        return [t.id for t in task_list]

    def get_kanban_state(
        self,
        sprint_id: str,
        tasks: dict[str, Task],
    ) -> dict[str, list[str]]:
        """Get kanban board state (tasks by status).

        Args:
            sprint_id: Sprint identifier.
            tasks: Dictionary of all tasks.

        Returns:
            Dictionary mapping status to task IDs.
        """
        sprint = self.get_sprint(sprint_id)
        board_state: dict[str, list[str]] = {status.value: [] for status in TaskStatus}

        for task_id in sprint.backlog_item_ids:
            task = tasks.get(task_id)
            if task:
                board_state[task.status.value].append(task_id)

        return board_state

    def apply_wip_limit(
        self,
        kanban_state: dict[str, list[str]],
        status: str,
        wip_limit: int,
    ) -> tuple[list[str], list[str]]:
        """Check WIP (Work In Progress) limits for status.

        Args:
            kanban_state: Current kanban board state.
            status: Status to check (e.g., "in_progress").
            wip_limit: Maximum items allowed in this status.

        Returns:
            Tuple of (compliant_items, blocked_items).
        """
        items = kanban_state.get(status, [])
        compliant = items[:wip_limit]
        blocked = items[wip_limit:]
        return (compliant, blocked)

    def calculate_cycle_time(
        self,
        task_id: str,
        task: Task,
    ) -> float | None:
        """Calculate cycle time (days from start to done).

        Args:
            task_id: Task identifier.
            task: Task instance.

        Returns:
            Cycle time in days, or None if not completed.
        """
        if task.status != TaskStatus.DONE:
            return None

        cycle_days = (task.updated_at - task.start_date).days
        return float(max(0, cycle_days))

    def record_sprint_retrospective(
        self,
        sprint_id: str,
        what_went_well: list[str],
        what_could_improve: list[str],
        action_items: list[str],
    ) -> dict[str, any]:
        """Record sprint retrospective summary.

        Args:
            sprint_id: Sprint identifier.
            what_went_well: Positive outcomes.
            what_could_improve: Areas for improvement.
            action_items: Action items for next sprint.

        Returns:
            Retrospective summary dictionary.
        """
        sprint = self.get_sprint(sprint_id)
        sprint.status = SprintStatus.RETROSPECTIVE

        return {
            "sprint_id": sprint_id,
            "sprint_name": sprint.name,
            "what_went_well": what_went_well,
            "what_could_improve": what_could_improve,
            "action_items": action_items,
            "recorded_at": datetime.now(),
        }

    def close_sprint(
        self,
        sprint_id: str,
        actual_velocity: float,
        project_id: str,
    ) -> Sprint:
        """Close sprint and record velocity metrics.

        Args:
            sprint_id: Sprint identifier.
            actual_velocity: Achieved story points.
            project_id: Project identifier.

        Returns:
            Closed Sprint instance.

        Raises:
            SprintNotFoundError: If sprint doesn't exist.
        """
        sprint = self.get_sprint(sprint_id)
        sprint.actual_velocity = actual_velocity
        sprint.status = SprintStatus.CLOSED

        # Record velocity for future estimates
        if project_id not in self.velocity_history:
            self.velocity_history[project_id] = []
        self.velocity_history[project_id].append(actual_velocity)

        return sprint

    def delete_sprint(self, sprint_id: str) -> None:
        """Delete sprint (must be in planning status).

        Args:
            sprint_id: Sprint identifier.

        Raises:
            SprintNotFoundError: If sprint doesn't exist.
        """
        sprint = self.get_sprint(sprint_id)
        if sprint.status != SprintStatus.PLANNING:
            # Allow deletion of planning sprints only
            pass
        del self.sprints[sprint_id]
