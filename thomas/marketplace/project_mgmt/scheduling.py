"""Project scheduling with critical path method and resource leveling.

Implements CPM forward/backward passes, slack calculation, resource leveling,
Gantt chart generation, and schedule compression analysis.
"""

from datetime import datetime, timedelta

from thomas.marketplace.project_mgmt._types import (
    Dependency,
    DependencyType,
    GanttBar,
    Task,
)


class ScheduleManager:
    """Manages project scheduling using Critical Path Method (CPM).

    Implements CPM forward/backward passes, slack calculation,
    resource leveling heuristics, and Gantt chart generation.
    """

    def __init__(self) -> None:
        """Initialize schedule manager."""
        self.tasks: dict[str, Task] = {}
        self.dependencies: dict[str, Dependency] = {}

    def _find_start_tasks(self, tasks: dict[str, Task]) -> list[str]:
        """Find tasks with no predecessors.

        Args:
            tasks: Dictionary of all tasks.

        Returns:
            List of start task IDs.
        """
        all_successors = {d.successor_task_id for d in self.dependencies.values() if d.predecessor_task_id in tasks}
        return [tid for tid in tasks if tid not in all_successors]

    def _find_end_tasks(self, tasks: dict[str, Task]) -> list[str]:
        """Find tasks with no successors.

        Args:
            tasks: Dictionary of all tasks.

        Returns:
            List of end task IDs.
        """
        all_predecessors = {d.predecessor_task_id for d in self.dependencies.values() if d.successor_task_id in tasks}
        return [tid for tid in tasks if tid not in all_predecessors]

    def calculate_critical_path(
        self,
        tasks: dict[str, Task],
    ) -> tuple[list[str], float]:
        """Calculate critical path using CPM forward/backward pass.

        Forward pass calculates early start (ES) and early finish (EF).
        Backward pass calculates late start (LS) and late finish (LF).
        Slack = LS - ES. Critical path has zero slack.

        Args:
            tasks: Dictionary of all tasks in project.

        Returns:
            Tuple of (critical_path_task_ids, critical_path_duration_days).
        """
        if not tasks:
            return ([], 0.0)

        # Initialize schedule attributes
        es: dict[str, datetime] = {}
        ef: dict[str, datetime] = {}
        ls: dict[str, datetime] = {}
        lf: dict[str, datetime] = {}

        # Forward pass
        start_tasks = self._find_start_tasks(tasks)
        if not start_tasks:
            return ([], 0.0)

        for task_id in start_tasks:
            es[task_id] = tasks[task_id].start_date

        # Topological sort for forward pass
        visited: set[str] = set()

        def forward_pass(task_id: str) -> None:
            if task_id in visited:
                return
            visited.add(task_id)

            task = tasks[task_id]
            if task_id not in es:
                es[task_id] = datetime.now()

            # Calculate EF
            duration = task.pert_estimate()
            ef[task_id] = es[task_id] + timedelta(hours=duration)

            # Process successors
            successors = [d.successor_task_id for d in self.dependencies.values() if d.predecessor_task_id == task_id]
            for succ_id in successors:
                if succ_id in tasks:
                    succ_es = ef[task_id]
                    if succ_id not in es or succ_es > es[succ_id]:
                        es[succ_id] = succ_es
                    forward_pass(succ_id)

        for task_id in tasks:
            forward_pass(task_id)

        # Backward pass
        end_tasks = self._find_end_tasks(tasks)
        if end_tasks:
            for task_id in end_tasks:
                lf[task_id] = ef.get(task_id, tasks[task_id].due_date)

        visited.clear()

        def backward_pass(task_id: str) -> None:
            if task_id in visited:
                return
            visited.add(task_id)

            task = tasks[task_id]
            if task_id not in lf:
                lf[task_id] = task.due_date

            # Calculate LS
            duration = task.pert_estimate()
            ls[task_id] = lf[task_id] - timedelta(hours=duration)

            # Process predecessors
            predecessors = [d.predecessor_task_id for d in self.dependencies.values() if d.successor_task_id == task_id]
            for pred_id in predecessors:
                if pred_id in tasks:
                    pred_lf = ls[task_id]
                    if pred_id not in lf or pred_lf < lf[pred_id]:
                        lf[pred_id] = pred_lf
                    backward_pass(pred_id)

        for task_id in tasks:
            backward_pass(task_id)

        # Find critical path (slack = 0)
        critical_path: list[str] = []
        for task_id in tasks:
            slack = (ls.get(task_id, datetime.now()) - es.get(task_id, datetime.now())).total_seconds()
            if abs(slack) < 1:  # Within 1 second
                critical_path.append(task_id)

        # Calculate critical path duration
        duration = 0.0
        if critical_path:
            earliest = min(es.get(tid, datetime.now()) for tid in critical_path)
            latest = max(ef.get(tid, datetime.now()) for tid in critical_path)
            duration = (latest - earliest).total_seconds() / 3600.0

        return (critical_path, duration)

    def generate_gantt_data(
        self,
        project_id: str,
        tasks: dict[str, Task],
    ) -> list[GanttBar]:
        """Generate Gantt chart data.

        Args:
            project_id: Project identifier.
            tasks: Dictionary of all tasks in project.

        Returns:
            List of GanttBar objects for visualization.
        """
        gantt_bars: list[GanttBar] = []

        for task in tasks.values():
            if task.project_id != project_id:
                continue

            # Get dependencies for this task
            deps = [d.predecessor_task_id for d in self.dependencies.values() if d.successor_task_id == task.id]

            duration = task.pert_estimate()
            duration_days = duration / 24.0

            bar = GanttBar(
                task_id=task.id,
                task_name=task.title,
                start_date=task.start_date,
                end_date=task.due_date,
                duration_days=duration_days,
                percent_complete=task.percent_complete,
                dependency_ids=deps,
                is_milestone=task.percent_complete >= 100.0,
            )
            gantt_bars.append(bar)

        # Sort by start date
        gantt_bars.sort(key=lambda b: b.start_date)
        return gantt_bars

    def level_resources(
        self,
        tasks: dict[str, Task],
        resource_capacities: dict[str, float],
    ) -> dict[str, list[tuple[str, datetime, datetime]]]:
        """Apply resource leveling to resolve overallocations.

        Uses heuristic: delay non-critical tasks when resources overallocated.

        Args:
            tasks: Dictionary of all tasks.
            resource_capacities: Dictionary mapping resource_id to max_hours.

        Returns:
            Dictionary mapping resource_id to list of (task_id, start, end) tuples.
        """
        # Get critical path
        critical_ids, _ = self.calculate_critical_path(tasks)
        critical_set = set(critical_ids)

        # Calculate daily resource usage
        resource_schedule: dict[str, list[tuple[str, datetime, datetime]]] = {rid: [] for rid in resource_capacities}

        # Schedule tasks respecting dependencies and resource availability
        scheduled: set[str] = set()
        task_times: dict[str, tuple[datetime, datetime]] = {}

        def can_schedule(task_id: str) -> bool:
            """Check if all predecessors are scheduled."""
            predecessors = [d.predecessor_task_id for d in self.dependencies.values() if d.successor_task_id == task_id]
            return all(p in scheduled for p in predecessors)

        # Schedule in topological order
        while len(scheduled) < len(tasks):
            scheduled_this_round = False
            for task_id, task in tasks.items():
                if task_id in scheduled or not can_schedule(task_id):
                    continue

                # Find earliest start time
                predecessors = [
                    d.predecessor_task_id for d in self.dependencies.values() if d.successor_task_id == task_id
                ]

                start = task.start_date
                if predecessors and predecessors[0] in task_times:
                    start = max(start, task_times[predecessors[0]][1])

                duration = task.pert_estimate()
                end = start + timedelta(hours=duration)

                # Try to schedule at earliest time, or delay if resource unavailable
                resource_id = task.assigned_to_id
                if resource_id and resource_id in resource_capacities:
                    # Check capacity at this time
                    used_hours = sum(
                        (et - st).total_seconds() / 3600.0
                        for (_, st, et) in resource_schedule[resource_id]
                        if st <= start < et
                    )
                    capacity = resource_capacities[resource_id]
                    duration_hours = duration

                    # If overallocated and not critical, delay this task
                    if used_hours + duration_hours > capacity and task_id not in critical_set:
                        # Delay by 1 day
                        start = start + timedelta(days=1)
                        end = start + timedelta(hours=duration)

                task_times[task_id] = (start, end)
                if resource_id and resource_id in resource_schedule:
                    resource_schedule[resource_id].append((task_id, start, end))
                scheduled.add(task_id)
                scheduled_this_round = True

            if not scheduled_this_round and len(scheduled) < len(tasks):
                # Fallback: force schedule remaining tasks
                for task_id, task in tasks.items():
                    if task_id not in scheduled:
                        task_times[task_id] = (task.start_date, task.due_date)
                        if task.assigned_to_id in resource_schedule:
                            resource_schedule[task.assigned_to_id].append(
                                (
                                    task_id,
                                    task.start_date,
                                    task.due_date,
                                )
                            )
                        scheduled.add(task_id)

        return resource_schedule

    def analyze_schedule_compression(
        self,
        project_id: str,
        tasks: dict[str, Task],
        target_duration_hours: float,
    ) -> dict[str, any]:
        """Analyze schedule compression options (fast-tracking, crashing).

        Fast-tracking: Run tasks in parallel (increases risk).
        Crashing: Add resources (increases cost).

        Args:
            project_id: Project identifier.
            tasks: Dictionary of all tasks.
            target_duration_hours: Target project duration.

        Returns:
            Dictionary with compression analysis:
            - current_duration: Current critical path duration
            - target_duration: Target duration
            - compression_needed: Hours to compress
            - fast_track_opportunities: Task pairs that could run in parallel
            - crash_analysis: Tasks suitable for resource addition
        """
        critical_ids, current_duration = self.calculate_critical_path(tasks)

        compression_needed = max(0.0, current_duration - target_duration_hours)

        # Find fast-track opportunities (dependent tasks that could overlap)
        fast_track_ops: list[tuple[str, str, float]] = []
        for dep in self.dependencies.values():
            if dep.predecessor_task_id in critical_ids and dep.dependency_type == DependencyType.FINISH_TO_START:
                pred_task = tasks.get(dep.predecessor_task_id)
                succ_task = tasks.get(dep.successor_task_id)
                if pred_task and succ_task:
                    overlap = min(
                        pred_task.pert_estimate(),
                        succ_task.pert_estimate(),
                    )
                    fast_track_ops.append(
                        (
                            dep.predecessor_task_id,
                            dep.successor_task_id,
                            overlap,
                        )
                    )

        # Find crash candidates (tasks with high effort on critical path)
        crash_candidates: list[tuple[str, float]] = []
        for task_id in critical_ids:
            task = tasks.get(task_id)
            if task:
                crash_candidates.append((task_id, task.pert_estimate()))

        crash_candidates.sort(key=lambda x: x[1], reverse=True)

        return {
            "current_duration": current_duration,
            "target_duration": target_duration_hours,
            "compression_needed": compression_needed,
            "fast_track_opportunities": fast_track_ops,
            "crash_analysis": crash_candidates,
        }

    def get_schedule_variance(
        self,
        tasks: dict[str, Task],
    ) -> float:
        """Calculate schedule variance: EV (% progress) vs PV (% time elapsed).

        Simplified calculation: average percent complete.

        Args:
            tasks: Dictionary of all tasks.

        Returns:
            Schedule variance (positive = ahead, negative = behind).
        """
        if not tasks:
            return 0.0

        avg_completion = sum(t.percent_complete for t in tasks.values()) / len(tasks)
        return avg_completion - 50.0  # Assume 50% expected at mid-point
