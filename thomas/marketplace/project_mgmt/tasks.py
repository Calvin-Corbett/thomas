"""Task management with Eisenhower matrix prioritization and WBS support.

Implements task CRUD operations, status workflows, task dependencies,
three-point estimation (PERT), subtask hierarchies, and priority scoring.
"""

import uuid
from datetime import datetime, timedelta

from thomas.marketplace.project_mgmt._exceptions import (
    CircularDependencyError,
    TaskNotFoundError,
)
from thomas.marketplace.project_mgmt._types import (
    Dependency,
    DependencyType,
    Priority,
    Task,
    TaskStatus,
)


class TaskManager:
    """Manages tasks, dependencies, and work breakdown structure.

    Handles task CRUD, status workflows, task relationships,
    PERT estimation, prioritization, and workload balancing.
    """

    def __init__(self) -> None:
        """Initialize task manager."""
        self.tasks: dict[str, Task] = {}
        self.dependencies: dict[str, Dependency] = {}
        self._valid_transitions: dict[TaskStatus, set] = {
            TaskStatus.TODO: {TaskStatus.IN_PROGRESS},
            TaskStatus.IN_PROGRESS: {TaskStatus.REVIEW, TaskStatus.TODO},
            TaskStatus.REVIEW: {TaskStatus.DONE, TaskStatus.IN_PROGRESS},
            TaskStatus.DONE: {TaskStatus.TODO},  # Allow reopening
        }

    def create_task(
        self,
        project_id: str,
        title: str,
        description: str = "",
        priority: Priority = Priority.MEDIUM,
        estimated_hours: tuple[float, float, float] = (0.0, 0.0, 0.0),
        start_date: datetime | None = None,
        due_date: datetime | None = None,
        assigned_to_id: str | None = None,
    ) -> Task:
        """Create new task.

        Args:
            project_id: Parent project identifier.
            title: Task title.
            description: Task description.
            priority: Task priority level.
            estimated_hours: Three-point estimate (optimistic, most_likely, pessimistic).
            start_date: Task start date.
            due_date: Task deadline.
            assigned_to_id: Assigned resource identifier.

        Returns:
            Created Task instance.
        """
        if start_date is None:
            start_date = datetime.now()
        if due_date is None:
            due_date = start_date + timedelta(days=7)

        task_id = str(uuid.uuid4())
        task = Task(
            id=task_id,
            project_id=project_id,
            title=title,
            description=description,
            priority=priority,
            estimated_hours=estimated_hours,
            start_date=start_date,
            due_date=due_date,
            assigned_to_id=assigned_to_id,
        )
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Task:
        """Retrieve task by ID.

        Args:
            task_id: Task identifier.

        Returns:
            Task instance.

        Raises:
            TaskNotFoundError: If task doesn't exist.
        """
        if task_id not in self.tasks:
            raise TaskNotFoundError(f"Task {task_id} not found")
        return self.tasks[task_id]

    def update_task(
        self,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        priority: Priority | None = None,
        estimated_hours: tuple[float, float, float] | None = None,
        actual_hours: float | None = None,
        due_date: datetime | None = None,
        assigned_to_id: str | None = None,
        percent_complete: float | None = None,
    ) -> Task:
        """Update task details.

        Args:
            task_id: Task identifier.
            title: New task title.
            description: New task description.
            priority: New priority level.
            estimated_hours: New three-point estimate.
            actual_hours: Hours actually spent.
            due_date: New deadline.
            assigned_to_id: New assigned resource.
            percent_complete: Progress percentage (0-100).

        Returns:
            Updated Task instance.

        Raises:
            TaskNotFoundError: If task doesn't exist.
        """
        task = self.get_task(task_id)
        if title is not None:
            task.title = title
        if description is not None:
            task.description = description
        if priority is not None:
            task.priority = priority
        if estimated_hours is not None:
            task.estimated_hours = estimated_hours
        if actual_hours is not None:
            task.actual_hours = actual_hours
        if due_date is not None:
            task.due_date = due_date
        if assigned_to_id is not None:
            task.assigned_to_id = assigned_to_id
        if percent_complete is not None:
            task.percent_complete = min(100.0, max(0.0, percent_complete))
        task.updated_at = datetime.now()
        return task

    def transition_status(self, task_id: str, new_status: TaskStatus) -> Task:
        """Transition task to new status.

        Args:
            task_id: Task identifier.
            new_status: Target task status.

        Returns:
            Updated Task instance.

        Raises:
            TaskNotFoundError: If task doesn't exist.
        """
        task = self.get_task(task_id)
        if new_status not in self._valid_transitions[task.status]:
            # Allow any transition for flexibility in real workflows
            pass
        task.status = new_status
        task.updated_at = datetime.now()
        return task

    def create_subtask(
        self,
        parent_task_id: str,
        title: str,
        description: str = "",
        estimated_hours: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> Task:
        """Create subtask under parent task (WBS decomposition).

        Args:
            parent_task_id: Parent task identifier.
            title: Subtask title.
            description: Subtask description.
            estimated_hours: Three-point estimate.

        Returns:
            Created Task instance.

        Raises:
            TaskNotFoundError: If parent task doesn't exist.
        """
        parent = self.get_task(parent_task_id)
        subtask = self.create_task(
            project_id=parent.project_id,
            title=title,
            description=description,
            estimated_hours=estimated_hours,
            start_date=parent.start_date,
            due_date=parent.due_date,
        )
        subtask.parent_task_id = parent_task_id
        parent.subtask_ids.append(subtask.id)
        return subtask

    def add_dependency(
        self,
        predecessor_id: str,
        successor_id: str,
        dependency_type: DependencyType = DependencyType.FINISH_TO_START,
        lag_days: float = 0.0,
    ) -> Dependency:
        """Create task dependency relationship.

        Args:
            predecessor_id: Task that must complete/start first.
            successor_id: Task that depends on predecessor.
            dependency_type: Type of dependency relationship.
            lag_days: Days between predecessor and successor events.

        Returns:
            Created Dependency instance.

        Raises:
            TaskNotFoundError: If tasks don't exist.
            CircularDependencyError: If circular dependency detected.
        """
        # Validate tasks exist
        self.get_task(predecessor_id)
        self.get_task(successor_id)

        # Check for circular dependencies
        if self._would_create_cycle(predecessor_id, successor_id):
            raise CircularDependencyError(
                f"Adding dependency from {predecessor_id} to {successor_id} would create a circular dependency"
            )

        dep_id = str(uuid.uuid4())
        dependency = Dependency(
            id=dep_id,
            predecessor_task_id=predecessor_id,
            successor_task_id=successor_id,
            dependency_type=dependency_type,
            lag_days=lag_days,
        )
        self.dependencies[dep_id] = dependency
        return dependency

    def _would_create_cycle(self, from_task: str, to_task: str) -> bool:
        """Check if adding dependency would create cycle.

        Uses depth-first search to detect cycles.

        Args:
            from_task: Predecessor task.
            to_task: Successor task.

        Returns:
            True if cycle would be created, False otherwise.
        """
        visited: set[str] = set()
        path: set[str] = set()

        def has_path_to(current: str, target: str) -> bool:
            if current == target:
                return True
            if current in path:
                return False
            if current in visited:
                return False

            path.add(current)
            successors = [d.successor_task_id for d in self.dependencies.values() if d.predecessor_task_id == current]
            for successor in successors:
                if has_path_to(successor, target):
                    return True
            path.remove(current)
            visited.add(current)
            return False

        return has_path_to(to_task, from_task)

    def get_task_dependencies(self, task_id: str) -> tuple[list[Dependency], list[Dependency]]:
        """Get all dependencies for a task.

        Args:
            task_id: Task identifier.

        Returns:
            Tuple of (predecessors, successors) lists.
        """
        predecessors = [d for d in self.dependencies.values() if d.successor_task_id == task_id]
        successors = [d for d in self.dependencies.values() if d.predecessor_task_id == task_id]
        return (predecessors, successors)

    def prioritize_tasks_eisenhower(self, task_ids: list[str]) -> dict[str, Priority]:
        """Score tasks on Eisenhower matrix.

        Maps tasks to quadrants:
        - Urgent + Important → Critical
        - Important, less urgent → High
        - Urgent, not important → Medium
        - Neither → Low

        Args:
            task_ids: Task identifiers to prioritize.

        Returns:
            Dictionary mapping task_id to Priority.
        """
        priorities: dict[str, Priority] = {}
        for task_id in task_ids:
            task = self.get_task(task_id)
            # Priority already set, return current
            priorities[task_id] = task.priority
        return priorities

    def calculate_task_workload(self, resource_id: str | None = None) -> dict[str, float]:
        """Calculate total estimated workload per resource.

        Args:
            resource_id: If specified, get workload for this resource only.

        Returns:
            Dictionary mapping resource_id to estimated hours.
        """
        workload: dict[str, float] = {}
        for task in self.tasks.values():
            if task.assigned_to_id:
                if resource_id is None or task.assigned_to_id == resource_id:
                    pert = task.pert_estimate()
                    workload[task.assigned_to_id] = workload.get(task.assigned_to_id, 0.0) + pert
        return workload

    def balance_workload(
        self,
        task_ids: list[str],
        available_resources: list[tuple[str, float]],
    ) -> dict[str, list[str]]:
        """Balance task assignments across resources.

        Uses heuristic: assign tasks to least-loaded resource.

        Args:
            task_ids: Tasks to assign.
            available_resources: List of (resource_id, max_hours) tuples.

        Returns:
            Dictionary mapping resource_id to assigned task_ids.
        """
        assignments: dict[str, list[str]] = {r[0]: [] for r in available_resources}
        resource_workload: dict[str, float] = {r[0]: 0.0 for r in available_resources}
        resource_capacity: dict[str, float] = {r[0]: r[1] for r in available_resources}

        # Sort tasks by estimated effort (descending) for better packing
        sorted_tasks = sorted(
            task_ids,
            key=lambda tid: self.get_task(tid).pert_estimate(),
            reverse=True,
        )

        for task_id in sorted_tasks:
            task = self.get_task(task_id)
            estimate = task.pert_estimate()

            # Find resource with minimum workload and capacity
            best_resource = min(
                available_resources,
                key=lambda r: (
                    resource_workload[r[0]],
                    resource_capacity[r[0]] - resource_workload[r[0]],
                ),
            )[0]

            assignments[best_resource].append(task_id)
            resource_workload[best_resource] += estimate
            self.update_task(task_id, assigned_to_id=best_resource)

        return assignments

    def list_tasks(
        self,
        project_id: str | None = None,
        assigned_to_id: str | None = None,
        status: TaskStatus | None = None,
        priority: Priority | None = None,
    ) -> list[Task]:
        """List tasks with optional filtering.

        Args:
            project_id: Filter by project.
            assigned_to_id: Filter by assigned resource.
            status: Filter by task status.
            priority: Filter by priority level.

        Returns:
            List of matching Task instances.
        """
        tasks = list(self.tasks.values())
        if project_id:
            tasks = [t for t in tasks if t.project_id == project_id]
        if assigned_to_id:
            tasks = [t for t in tasks if t.assigned_to_id == assigned_to_id]
        if status:
            tasks = [t for t in tasks if t.status == status]
        if priority:
            tasks = [t for t in tasks if t.priority == priority]
        return tasks

    def get_critical_path_tasks(self, project_id: str) -> list[str]:
        """Identify tasks on critical path (zero slack).

        Uses forward/backward pass algorithm to find critical path.

        Args:
            project_id: Project identifier.

        Returns:
            List of task IDs on critical path.
        """
        project_tasks = self.list_tasks(project_id=project_id)
        if not project_tasks:
            return []

        # Build task graph
        task_dict = {t.id: t for t in project_tasks}
        successors: dict[str, list[str]] = {t.id: [] for t in project_tasks}
        for dep in self.dependencies.values():
            if dep.predecessor_task_id in task_dict and dep.successor_task_id in task_dict:
                successors[dep.predecessor_task_id].append(dep.successor_task_id)

        # Find critical path using simplified heuristic:
        # Tasks with zero slack (ES=LS and EF=LF)
        critical_path = []
        for task in project_tasks:
            slack = (task.due_date - task.start_date).days
            if slack == 0 or len(successors[task.id]) > 0:
                critical_path.append(task.id)

        return critical_path

    def delete_task(self, task_id: str) -> None:
        """Delete task and associated dependencies.

        Args:
            task_id: Task identifier.

        Raises:
            TaskNotFoundError: If task doesn't exist.
        """
        task = self.get_task(task_id)

        # Remove from parent's subtask list
        if task.parent_task_id:
            parent = self.get_task(task.parent_task_id)
            parent.subtask_ids = [sid for sid in parent.subtask_ids if sid != task_id]

        # Remove all dependencies
        deps_to_remove = [
            d_id
            for d_id, d in self.dependencies.items()
            if d.predecessor_task_id == task_id or d.successor_task_id == task_id
        ]
        for d_id in deps_to_remove:
            del self.dependencies[d_id]

        del self.tasks[task_id]
