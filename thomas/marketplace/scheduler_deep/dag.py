"""
Directed acyclic graph (DAG) scheduling system.

Enables job dependency management with topological sorting and parallel execution.
"""

import threading
from collections import defaultdict, deque
from typing import Any

from thomas.marketplace.scheduler_deep._exceptions import CycleDetected, InvalidDAG
from thomas.marketplace.scheduler_deep._types import Job, JobStatus


class DAGNode:
    """Node in execution DAG."""

    def __init__(self, job: Job) -> None:
        """Initialize DAG node.

        Args:
            job: Job for this node
        """
        self.job = job
        self.dependencies: set[str] = set()
        self.dependents: set[str] = set()
        self.in_degree = 0


class DAGScheduler:
    """Schedule and execute jobs with dependency management."""

    def __init__(self) -> None:
        """Initialize DAG scheduler."""
        self._nodes: dict[str, DAGNode] = {}
        self._results: dict[str, Any] = {}
        self._execution_order: list[str] = []
        self._lock = threading.RLock()

    def add_job(self, job: Job, dependencies: list[str] | None = None) -> None:
        """Add job to DAG.

        Args:
            job: Job to add
            dependencies: Job IDs this job depends on

        Raises:
            InvalidDAG: If job already exists
        """
        with self._lock:
            if job.id in self._nodes:
                raise InvalidDAG(f"Job {job.id} already exists")

            node = DAGNode(job)
            self._nodes[job.id] = node

            if dependencies:
                for dep_id in dependencies:
                    if dep_id not in self._nodes:
                        raise InvalidDAG(f"Dependency {dep_id} not found")

                    node.dependencies.add(dep_id)
                    self._nodes[dep_id].dependents.add(job.id)
                    node.in_degree += 1

            self._validate_no_cycles()

    def remove_job(self, job_id: str) -> None:
        """Remove job from DAG.

        Args:
            job_id: Job ID to remove

        Raises:
            InvalidDAG: If job not found or has dependents
        """
        with self._lock:
            if job_id not in self._nodes:
                raise InvalidDAG(f"Job {job_id} not found")

            node = self._nodes[job_id]

            # Check for dependents
            if node.dependents:
                raise InvalidDAG(f"Cannot remove job {job_id}: other jobs depend on it")

            # Remove from dependencies
            for dep_id in node.dependencies:
                dep_node = self._nodes[dep_id]
                dep_node.dependents.discard(job_id)

            del self._nodes[job_id]

    def add_dependency(self, job_id: str, dependency_id: str) -> None:
        """Add dependency relationship.

        Args:
            job_id: Job that depends on another
            dependency_id: Job ID to depend on

        Raises:
            InvalidDAG: If dependency is invalid or creates cycle
        """
        with self._lock:
            if job_id not in self._nodes:
                raise InvalidDAG(f"Job {job_id} not found")
            if dependency_id not in self._nodes:
                raise InvalidDAG(f"Dependency {dependency_id} not found")

            node = self._nodes[job_id]
            if dependency_id not in node.dependencies:
                node.dependencies.add(dependency_id)
                node.in_degree += 1
                self._nodes[dependency_id].dependents.add(job_id)

            self._validate_no_cycles()

    def get_ready_jobs(self) -> list[Job]:
        """Get jobs ready to run (all dependencies satisfied).

        Returns:
            List of ready jobs
        """
        with self._lock:
            ready = []
            for node in self._nodes.values():
                # All dependencies must be complete
                if node.in_degree == 0 and node.job.status == JobStatus.IDLE:
                    ready.append(node.job)
            return ready

    def mark_job_complete(self, job_id: str, result: Any = None) -> None:
        """Mark job as complete and update dependents.

        Args:
            job_id: Job ID that completed
            result: Execution result
        """
        with self._lock:
            if job_id not in self._nodes:
                return

            self._results[job_id] = result
            node = self._nodes[job_id]

            # Reduce in-degree for dependents
            for dependent_id in node.dependents:
                dependent_node = self._nodes[dependent_id]
                dependent_node.in_degree -= 1

    def get_topological_order(self) -> list[str]:
        """Get topological execution order.

        Returns:
            List of job IDs in execution order

        Raises:
            InvalidDAG: If cycle exists
        """
        with self._lock:
            self._validate_no_cycles()

            in_degree = {}
            for job_id, node in self._nodes.items():
                in_degree[job_id] = len(node.dependencies)

            queue = deque([jid for jid, degree in in_degree.items() if degree == 0])
            order = []

            while queue:
                job_id = queue.popleft()
                order.append(job_id)

                for dependent_id in self._nodes[job_id].dependents:
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        queue.append(dependent_id)

            return order

    def get_critical_path(self) -> list[str]:
        """Calculate critical path (longest dependency chain).

        Returns:
            List of job IDs forming critical path
        """
        with self._lock:
            # Calculate longest path to each node
            longest_path: dict[str, int] = defaultdict(int)
            parent: dict[str, str | None] = {jid: None for jid in self._nodes}

            order = self.get_topological_order()

            for job_id in order:
                node = self._nodes[job_id]
                max_dep_path = 0

                for dep_id in node.dependencies:
                    dep_path = longest_path[dep_id] + 1
                    if dep_path > max_dep_path:
                        max_dep_path = dep_path
                        parent[job_id] = dep_id

                longest_path[job_id] = max_dep_path

            # Find job with longest path
            end_job = max(self._nodes.keys(), key=lambda jid: longest_path[jid])

            # Reconstruct path
            path = []
            current = end_job
            while current:
                path.insert(0, current)
                current = parent[current]

            return path

    def get_job_dependencies(self, job_id: str) -> set[str]:
        """Get all dependencies for a job.

        Args:
            job_id: Job ID

        Returns:
            Set of dependency job IDs

        Raises:
            InvalidDAG: If job not found
        """
        with self._lock:
            if job_id not in self._nodes:
                raise InvalidDAG(f"Job {job_id} not found")

            return self._nodes[job_id].dependencies.copy()

    def get_job_dependents(self, job_id: str) -> set[str]:
        """Get all jobs that depend on this job.

        Args:
            job_id: Job ID

        Returns:
            Set of dependent job IDs

        Raises:
            InvalidDAG: If job not found
        """
        with self._lock:
            if job_id not in self._nodes:
                raise InvalidDAG(f"Job {job_id} not found")

            return self._nodes[job_id].dependents.copy()

    def get_result(self, job_id: str) -> Any:
        """Get job execution result.

        Args:
            job_id: Job ID

        Returns:
            Execution result or None
        """
        with self._lock:
            return self._results.get(job_id)

    def _validate_no_cycles(self) -> None:
        """Validate that DAG has no cycles.

        Raises:
            CycleDetected: If cycle is found
        """
        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycle_path: list[str] = []

        def has_cycle(job_id: str) -> bool:
            visited.add(job_id)
            rec_stack.add(job_id)
            cycle_path.append(job_id)

            for dep_id in self._nodes[job_id].dependencies:
                if dep_id not in visited:
                    if has_cycle(dep_id):
                        return True
                elif dep_id in rec_stack:
                    # Found cycle
                    cycle_start = cycle_path.index(dep_id)
                    raise CycleDetected(cycle_path[cycle_start:] + [dep_id])

            cycle_path.pop()
            rec_stack.remove(job_id)
            return False

        for job_id in self._nodes:
            if job_id not in visited:
                try:
                    has_cycle(job_id)
                except CycleDetected:
                    raise

    def get_execution_stats(self) -> dict[str, Any]:
        """Get DAG execution statistics.

        Returns:
            Dictionary of stats
        """
        with self._lock:
            total_jobs = len(self._nodes)
            completed_jobs = sum(1 for node in self._nodes.values() if node.job.status == JobStatus.SUCCESS)
            failed_jobs = sum(1 for node in self._nodes.values() if node.job.status == JobStatus.FAILED)

            return {
                "total_jobs": total_jobs,
                "completed_jobs": completed_jobs,
                "failed_jobs": failed_jobs,
                "pending_jobs": total_jobs - completed_jobs - failed_jobs,
                "critical_path_length": len(self.get_critical_path()),
            }

    def __repr__(self) -> str:
        """String representation."""
        with self._lock:
            return f"DAGScheduler(jobs={len(self._nodes)})"
