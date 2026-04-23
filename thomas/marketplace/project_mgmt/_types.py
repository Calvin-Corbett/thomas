"""Core type definitions for project management module.

This module defines all data types used throughout the project management system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class ProjectStatus(Enum):
    """Project lifecycle status."""

    PLANNING = "planning"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TaskStatus(Enum):
    """Task workflow status."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"


class SprintStatus(Enum):
    """Sprint lifecycle status."""

    PLANNING = "planning"
    ACTIVE = "active"
    REVIEW = "review"
    RETROSPECTIVE = "retrospective"
    CLOSED = "closed"


class Priority(Enum):
    """Priority levels using Eisenhower matrix."""

    CRITICAL = 5  # Urgent + Important
    HIGH = 4  # Important, less urgent
    MEDIUM = 3  # Normal
    LOW = 2  # Neither urgent nor important
    BACKLOG = 1  # Can wait


class DependencyType(Enum):
    """Task dependency relationship types."""

    FINISH_TO_START = "fs"  # Predecessor finishes before successor starts
    START_TO_START = "ss"  # Predecessor starts before successor starts
    FINISH_TO_FINISH = "ff"  # Predecessor finishes before successor finishes
    START_TO_FINISH = "sf"  # Predecessor starts before successor finishes


class ResourceStatus(Enum):
    """Resource availability status."""

    AVAILABLE = "available"
    ALLOCATED = "allocated"
    OVERALLOCATED = "overallocated"
    ON_LEAVE = "on_leave"


class RiskStatus(Enum):
    """Risk tracking status."""

    IDENTIFIED = "identified"
    ASSESSED = "assessed"
    MONITORING = "monitoring"
    TRIGGERED = "triggered"
    CLOSED = "closed"


class RiskCategory(Enum):
    """Risk classification categories."""

    TECHNICAL = "technical"
    SCHEDULE = "schedule"
    COST = "cost"
    RESOURCE = "resource"
    SCOPE = "scope"
    ORGANIZATIONAL = "organizational"


@dataclass
class Project:
    """Project definition.

    Attributes:
        id: Unique project identifier.
        name: Project name.
        description: Project description.
        status: Current project status.
        start_date: Scheduled project start.
        end_date: Scheduled project completion.
        owner_id: Project manager/owner identifier.
        team_ids: Set of team member identifiers.
        budget_allocated: Total budget allocation in currency units.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
        metadata: Custom key-value metadata.
    """

    id: str
    name: str
    description: str
    status: ProjectStatus = ProjectStatus.PLANNING
    start_date: datetime = field(default_factory=datetime.now)
    end_date: datetime = field(default_factory=lambda: datetime.now() + timedelta(days=90))
    owner_id: str = ""
    team_ids: set[str] = field(default_factory=set)
    budget_allocated: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class Task:
    """Task definition with full estimation and tracking.

    Attributes:
        id: Unique task identifier.
        project_id: Parent project identifier.
        title: Task title.
        description: Task description.
        status: Current task status.
        priority: Task priority (Eisenhower matrix).
        assigned_to_id: Resource identifier assigned to task.
        parent_task_id: Parent task for WBS hierarchy.
        subtask_ids: Child task identifiers.
        estimated_hours: Three-point estimation tuple (optimistic, most_likely, pessimistic).
        actual_hours: Hours actually spent.
        start_date: Scheduled start date.
        due_date: Task deadline.
        percent_complete: Progress percentage (0-100).
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    id: str
    project_id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    priority: Priority = Priority.MEDIUM
    assigned_to_id: str | None = None
    parent_task_id: str | None = None
    subtask_ids: list[str] = field(default_factory=list)
    estimated_hours: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (O, M, P)
    actual_hours: float = 0.0
    start_date: datetime = field(default_factory=datetime.now)
    due_date: datetime = field(default_factory=lambda: datetime.now() + timedelta(days=7))
    percent_complete: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def pert_estimate(self) -> float:
        """Calculate PERT expected duration: (O + 4M + P) / 6."""
        o, m, p = self.estimated_hours
        return (o + 4 * m + p) / 6.0


@dataclass
class Milestone:
    """Project milestone for phase tracking.

    Attributes:
        id: Unique milestone identifier.
        project_id: Parent project identifier.
        name: Milestone name.
        description: Milestone description.
        due_date: Target completion date.
        status: Completion status.
        tasks_ids: Associated task identifiers.
        created_at: Creation timestamp.
    """

    id: str
    project_id: str
    name: str
    description: str = ""
    due_date: datetime = field(default_factory=lambda: datetime.now() + timedelta(days=30))
    status: TaskStatus = TaskStatus.TODO
    tasks_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Sprint:
    """Agile sprint definition.

    Attributes:
        id: Unique sprint identifier.
        project_id: Parent project identifier.
        name: Sprint name.
        status: Current sprint status.
        start_date: Sprint start date.
        end_date: Sprint end date.
        planned_velocity: Target story points for sprint.
        actual_velocity: Achieved story points.
        backlog_item_ids: Story/task identifiers in sprint.
        team_ids: Team member identifiers assigned to sprint.
        created_at: Creation timestamp.
    """

    id: str
    project_id: str
    name: str
    status: SprintStatus = SprintStatus.PLANNING
    start_date: datetime = field(default_factory=datetime.now)
    end_date: datetime = field(default_factory=lambda: datetime.now() + timedelta(days=14))
    planned_velocity: float = 0.0
    actual_velocity: float = 0.0
    backlog_item_ids: list[str] = field(default_factory=list)
    team_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Epic:
    """High-level feature grouping for agile.

    Attributes:
        id: Unique epic identifier.
        project_id: Parent project identifier.
        name: Epic name.
        description: Epic description.
        status: Epic status.
        story_ids: Associated story identifiers.
        priority: Epic priority.
        target_completion: Target delivery date.
    """

    id: str
    project_id: str
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    story_ids: list[str] = field(default_factory=list)
    priority: Priority = Priority.MEDIUM
    target_completion: datetime | None = None


@dataclass
class Story:
    """User story for agile development.

    Attributes:
        id: Unique story identifier.
        epic_id: Parent epic identifier.
        title: Story title (As a user, I want...).
        description: Story description and acceptance criteria.
        story_points: Fibonacci estimation.
        status: Story status.
        assigned_to_ids: Developer identifiers.
        sprint_id: Sprint assignment.
        priority: Story priority.
    """

    id: str
    epic_id: str
    title: str
    description: str = ""
    story_points: float = 0.0
    status: TaskStatus = TaskStatus.TODO
    assigned_to_ids: list[str] = field(default_factory=list)
    sprint_id: str | None = None
    priority: Priority = Priority.MEDIUM


@dataclass
class Bug:
    """Defect/bug tracking.

    Attributes:
        id: Unique bug identifier.
        project_id: Parent project identifier.
        title: Bug title.
        description: Reproduction steps and expected vs actual behavior.
        severity: Impact level (1=low to 5=critical).
        status: Bug status.
        assigned_to_id: Developer identifier.
        reporter_id: Reporter identifier.
        created_at: Discovery timestamp.
        resolved_at: Resolution timestamp.
    """

    id: str
    project_id: str
    title: str
    description: str = ""
    severity: int = 3  # 1-5 scale
    status: TaskStatus = TaskStatus.TODO
    assigned_to_id: str | None = None
    reporter_id: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: datetime | None = None


@dataclass
class Resource:
    """Team member or resource.

    Attributes:
        id: Unique resource identifier.
        name: Resource name.
        email: Email address.
        role: Job role/title.
        skills: Set of skill identifiers.
        max_hours_per_day: Maximum working hours per day.
        max_hours_per_week: Maximum working hours per week.
        allocated_hours: Hours currently allocated in this period.
        status: Current availability status.
    """

    id: str
    name: str
    email: str
    role: str = ""
    skills: set[str] = field(default_factory=set)
    max_hours_per_day: float = 8.0
    max_hours_per_week: float = 40.0
    allocated_hours: float = 0.0
    status: ResourceStatus = ResourceStatus.AVAILABLE


@dataclass
class TimeEntry:
    """Time tracking entry.

    Attributes:
        id: Unique time entry identifier.
        task_id: Associated task identifier.
        resource_id: Resource who logged time.
        date: Date of work.
        hours: Hours worked.
        description: Work description.
        created_at: Entry creation timestamp.
    """

    id: str
    task_id: str
    resource_id: str
    date: datetime
    hours: float
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Dependency:
    """Task dependency relationship.

    Attributes:
        id: Unique dependency identifier.
        predecessor_task_id: Task that must finish/start first.
        successor_task_id: Task that depends on predecessor.
        dependency_type: Type of dependency relationship.
        lag_days: Days between predecessor and successor events.
    """

    id: str
    predecessor_task_id: str
    successor_task_id: str
    dependency_type: DependencyType = DependencyType.FINISH_TO_START
    lag_days: float = 0.0


@dataclass
class GanttBar:
    """Gantt chart visualization bar.

    Attributes:
        task_id: Associated task identifier.
        task_name: Task name for display.
        start_date: Bar start date.
        end_date: Bar end date.
        duration_days: Duration in days.
        percent_complete: Progress percentage.
        dependency_ids: Predecessor task identifiers.
        is_milestone: Whether this is a milestone.
    """

    task_id: str
    task_name: str
    start_date: datetime
    end_date: datetime
    duration_days: float
    percent_complete: float = 0.0
    dependency_ids: list[str] = field(default_factory=list)
    is_milestone: bool = False


@dataclass
class RiskItem:
    """Risk register entry.

    Attributes:
        id: Unique risk identifier.
        project_id: Parent project identifier.
        description: Risk description.
        category: Risk category.
        probability: Probability 0-1.
        impact: Impact 0-1 (usually 1-5 scale normalized).
        status: Risk tracking status.
        owner_id: Risk owner identifier.
        mitigation_strategy: Planned response.
        contingency_plan: Fallback plan.
        trigger: Condition that indicates risk occurred.
        identified_date: When risk was identified.
    """

    id: str
    project_id: str
    description: str
    category: RiskCategory = RiskCategory.TECHNICAL
    probability: float = 0.5  # 0-1
    impact: float = 0.5  # 0-1
    status: RiskStatus = RiskStatus.IDENTIFIED
    owner_id: str | None = None
    mitigation_strategy: str = ""
    contingency_plan: str = ""
    trigger: str = ""
    identified_date: datetime = field(default_factory=datetime.now)

    def risk_score(self) -> float:
        """Calculate risk score: probability × impact."""
        return self.probability * self.impact


@dataclass
class Stakeholder:
    """Project stakeholder.

    Attributes:
        id: Unique stakeholder identifier.
        name: Stakeholder name.
        role: Role in project.
        influence: Influence level (1-5).
        interest: Interest level (1-5).
        communication_frequency: How often to communicate (days).
        preferred_channel: Communication preference.
    """

    id: str
    name: str
    role: str = ""
    influence: int = 3  # 1-5
    interest: int = 3  # 1-5
    communication_frequency: int = 7  # days
    preferred_channel: str = "email"


@dataclass
class Budget:
    """Project budget and cost tracking.

    Attributes:
        id: Unique budget identifier.
        project_id: Parent project identifier.
        work_package_id: Work package identifier.
        planned_value: Planned cost (PV).
        actual_cost: Actual cost incurred (AC).
        earned_value: Earned value of completed work (EV).
        period_start: Budget period start date.
        period_end: Budget period end date.
    """

    id: str
    project_id: str
    work_package_id: str
    planned_value: float = 0.0
    actual_cost: float = 0.0
    earned_value: float = 0.0
    period_start: datetime = field(default_factory=datetime.now)
    period_end: datetime = field(default_factory=lambda: datetime.now() + timedelta(days=30))

    def cost_variance(self) -> float:
        """Calculate cost variance: EV - AC."""
        return self.earned_value - self.actual_cost

    def schedule_variance(self, planned_value: float) -> float:
        """Calculate schedule variance: EV - PV."""
        return self.earned_value - planned_value

    def cost_performance_index(self) -> float:
        """Calculate CPI: EV / AC. Values > 1 indicate under budget."""
        return self.earned_value / self.actual_cost if self.actual_cost > 0 else 0.0

    def schedule_performance_index(self) -> float:
        """Calculate SPI: EV / PV. Values > 1 indicate ahead of schedule."""
        return self.earned_value / self.planned_value if self.planned_value > 0 else 0.0


@dataclass
class StatusReport:
    """Project status report.

    Attributes:
        id: Unique report identifier.
        project_id: Parent project identifier.
        report_date: Report generation date.
        overall_status: RAG status (red/amber/green).
        schedule_status: Schedule RAG status.
        budget_status: Budget RAG status.
        scope_status: Scope RAG status.
        quality_status: Quality RAG status.
        summary: Executive summary.
        achievements: Items completed since last report.
        risks: Active risks.
        blockers: Current blockers/issues.
    """

    id: str
    project_id: str
    report_date: datetime = field(default_factory=datetime.now)
    overall_status: str = "AMBER"  # RED, AMBER, GREEN
    schedule_status: str = "AMBER"
    budget_status: str = "AMBER"
    scope_status: str = "AMBER"
    quality_status: str = "AMBER"
    summary: str = ""
    achievements: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


@dataclass
class WorkBreakdownItem:
    """Work breakdown structure (WBS) item.

    Attributes:
        id: Unique item identifier.
        project_id: Parent project identifier.
        parent_id: Parent WBS item identifier.
        code: WBS code (e.g., "1.2.3").
        name: Work package name.
        description: Work package description.
        budget: Allocated budget.
        responsible_id: Responsible party identifier.
        estimated_hours: Estimated effort hours.
        task_ids: Associated task identifiers.
    """

    id: str
    project_id: str
    parent_id: str | None
    code: str
    name: str
    description: str = ""
    budget: float = 0.0
    responsible_id: str | None = None
    estimated_hours: float = 0.0
    task_ids: list[str] = field(default_factory=list)
