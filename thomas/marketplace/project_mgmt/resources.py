"""Resource management with allocation, capacity planning, and skill matching.

Implements resource allocation, capacity planning, utilization tracking,
skill-based assignment, and resource conflict detection.
"""

import uuid
from datetime import datetime

from thomas.marketplace.project_mgmt._exceptions import (
    ResourceNotFoundError,
    ResourceOverallocationError,
)
from thomas.marketplace.project_mgmt._types import (
    Resource,
    ResourceStatus,
    Task,
)


class ResourceManager:
    """Manages resource allocation, capacity, and skills.

    Handles resource CRUD, allocation management, capacity planning,
    utilization tracking, skill matching, and conflict detection.
    """

    def __init__(self) -> None:
        """Initialize resource manager."""
        self.resources: dict[str, Resource] = {}
        self.allocations: dict[
            str, list[tuple[str, float, datetime, datetime]]
        ] = {}  # resource_id -> [(task_id, hours, start, end)]

    def create_resource(
        self,
        name: str,
        email: str,
        role: str = "",
        skills: set[str] | None = None,
        max_hours_per_week: float = 40.0,
    ) -> Resource:
        """Create new resource (team member).

        Args:
            name: Resource name.
            email: Email address.
            role: Job role/title.
            skills: Set of skill identifiers.
            max_hours_per_week: Maximum working hours per week.

        Returns:
            Created Resource instance.
        """
        resource_id = str(uuid.uuid4())
        resource = Resource(
            id=resource_id,
            name=name,
            email=email,
            role=role,
            skills=skills or set(),
            max_hours_per_week=max_hours_per_week,
        )
        self.resources[resource_id] = resource
        self.allocations[resource_id] = []
        return resource

    def get_resource(self, resource_id: str) -> Resource:
        """Retrieve resource by ID.

        Args:
            resource_id: Resource identifier.

        Returns:
            Resource instance.

        Raises:
            ResourceNotFoundError: If resource doesn't exist.
        """
        if resource_id not in self.resources:
            raise ResourceNotFoundError(f"Resource {resource_id} not found")
        return self.resources[resource_id]

    def update_resource(
        self,
        resource_id: str,
        name: str | None = None,
        role: str | None = None,
        skills: set[str] | None = None,
        max_hours_per_week: float | None = None,
        status: ResourceStatus | None = None,
    ) -> Resource:
        """Update resource details.

        Args:
            resource_id: Resource identifier.
            name: New name.
            role: New role.
            skills: New skill set.
            max_hours_per_week: New weekly capacity.
            status: New availability status.

        Returns:
            Updated Resource instance.

        Raises:
            ResourceNotFoundError: If resource doesn't exist.
        """
        resource = self.get_resource(resource_id)
        if name is not None:
            resource.name = name
        if role is not None:
            resource.role = role
        if skills is not None:
            resource.skills = skills
        if max_hours_per_week is not None:
            resource.max_hours_per_week = max_hours_per_week
        if status is not None:
            resource.status = status
        return resource

    def allocate_to_task(
        self,
        resource_id: str,
        task_id: str,
        estimated_hours: float,
        start_date: datetime,
        end_date: datetime,
    ) -> None:
        """Allocate resource to task.

        Args:
            resource_id: Resource identifier.
            task_id: Task identifier.
            estimated_hours: Estimated hours for this task.
            start_date: Allocation start date.
            end_date: Allocation end date.

        Raises:
            ResourceNotFoundError: If resource doesn't exist.
            ResourceOverallocationError: If allocation would exceed capacity.
        """
        resource = self.get_resource(resource_id)

        # Check capacity
        current_allocation = self._calculate_period_allocation(resource_id, start_date, end_date)
        capacity = self._get_period_capacity(resource, start_date, end_date)

        if current_allocation + estimated_hours > capacity:
            resource.status = ResourceStatus.OVERALLOCATED
            raise ResourceOverallocationError(
                f"Resource {resource_id} would be overallocated: "
                f"{current_allocation + estimated_hours} > {capacity} hours"
            )

        # Add allocation
        if resource_id not in self.allocations:
            self.allocations[resource_id] = []

        self.allocations[resource_id].append((task_id, estimated_hours, start_date, end_date))
        resource.allocated_hours = resource.allocated_hours + estimated_hours
        resource.status = ResourceStatus.ALLOCATED

    def deallocate_from_task(
        self,
        resource_id: str,
        task_id: str,
    ) -> None:
        """Remove resource from task allocation.

        Args:
            resource_id: Resource identifier.
            task_id: Task identifier.

        Raises:
            ResourceNotFoundError: If resource doesn't exist.
        """
        resource = self.get_resource(resource_id)
        if resource_id in self.allocations:
            original_count = len(self.allocations[resource_id])
            self.allocations[resource_id] = [
                (tid, hours, start, end) for tid, hours, start, end in self.allocations[resource_id] if tid != task_id
            ]
            removed_hours = sum(hours for tid, hours, _, _ in self.allocations[resource_id] if tid == task_id)
            if len(self.allocations[resource_id]) < original_count:
                resource.allocated_hours = max(0.0, resource.allocated_hours - removed_hours)

        # Update status based on allocation
        if resource.allocated_hours == 0.0:
            resource.status = ResourceStatus.AVAILABLE

    def _calculate_period_allocation(
        self,
        resource_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> float:
        """Calculate total allocation in period.

        Args:
            resource_id: Resource identifier.
            start_date: Period start.
            end_date: Period end.

        Returns:
            Total allocated hours in period.
        """
        if resource_id not in self.allocations:
            return 0.0

        total = 0.0
        for task_id, hours, alloc_start, alloc_end in self.allocations[resource_id]:
            # Check for time period overlap
            overlap_start = max(start_date, alloc_start)
            overlap_end = min(end_date, alloc_end)
            if overlap_start < overlap_end:
                total += hours

        return total

    def _get_period_capacity(
        self,
        resource: Resource,
        start_date: datetime,
        end_date: datetime,
    ) -> float:
        """Calculate available capacity in period.

        Args:
            resource: Resource instance.
            start_date: Period start.
            end_date: Period end.

        Returns:
            Available hours in period.
        """
        days = (end_date - start_date).days
        weeks = max(1, days / 7.0)
        return resource.max_hours_per_week * weeks

    def check_skill_match(
        self,
        resource_id: str,
        required_skills: set[str],
    ) -> tuple[bool, set[str]]:
        """Check if resource has required skills.

        Args:
            resource_id: Resource identifier.
            required_skills: Set of required skill identifiers.

        Returns:
            Tuple of (has_all_skills, missing_skills).

        Raises:
            ResourceNotFoundError: If resource doesn't exist.
        """
        resource = self.get_resource(resource_id)
        missing_skills = required_skills - resource.skills
        return (len(missing_skills) == 0, missing_skills)

    def find_resources_with_skills(
        self,
        required_skills: set[str],
    ) -> list[tuple[str, int]]:
        """Find resources matching skill requirements.

        Args:
            required_skills: Set of required skills.

        Returns:
            List of (resource_id, matching_skill_count) tuples, sorted by match count.
        """
        matches: list[tuple[str, int]] = []
        for resource_id, resource in self.resources.items():
            matching = len(required_skills & resource.skills)
            if matching > 0:
                matches.append((resource_id, matching))

        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def assign_task_with_skill_match(
        self,
        task: Task,
        required_skills: set[str],
    ) -> str | None:
        """Assign task to resource with best skill match.

        Args:
            task: Task to assign.
            required_skills: Required skills for task.

        Returns:
            Assigned resource_id, or None if no match found.
        """
        matches = self.find_resources_with_skills(required_skills)
        if not matches:
            return None

        best_resource_id = matches[0][0]
        task.assigned_to_id = best_resource_id
        return best_resource_id

    def get_resource_utilization(
        self,
        resource_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> float:
        """Calculate resource utilization percentage.

        Utilization = allocated_hours / available_hours * 100

        Args:
            resource_id: Resource identifier.
            period_start: Period start date.
            period_end: Period end date.

        Returns:
            Utilization percentage (0-100+).

        Raises:
            ResourceNotFoundError: If resource doesn't exist.
        """
        resource = self.get_resource(resource_id)
        capacity = self._get_period_capacity(resource, period_start, period_end)
        if capacity == 0:
            return 0.0

        allocation = self._calculate_period_allocation(resource_id, period_start, period_end)
        return (allocation / capacity) * 100.0

    def get_team_capacity(
        self,
        team_ids: list[str],
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, dict[str, float]]:
        """Calculate team-level capacity and utilization.

        Args:
            team_ids: Team member resource IDs.
            period_start: Period start date.
            period_end: Period end date.

        Returns:
            Dictionary with capacity metrics per team member.
        """
        team_capacity: dict[str, dict[str, float]] = {}
        for resource_id in team_ids:
            try:
                resource = self.get_resource(resource_id)
                capacity = self._get_period_capacity(resource, period_start, period_end)
                allocation = self._calculate_period_allocation(resource_id, period_start, period_end)
                available = capacity - allocation

                team_capacity[resource_id] = {
                    "capacity": capacity,
                    "allocated": allocation,
                    "available": max(0.0, available),
                    "utilization": (allocation / capacity * 100.0) if capacity > 0 else 0.0,
                }
            except ResourceNotFoundError:
                continue

        return team_capacity

    def detect_conflicts(
        self,
    ) -> list[tuple[str, list[tuple[str, str]]]]:
        """Detect resource conflicts (overlapping task assignments).

        Args:

        Returns:
            List of (resource_id, [(task1_id, task2_id)]) tuples for conflicts.
        """
        conflicts: list[tuple[str, list[tuple[str, str]]]] = []

        for resource_id, allocations_list in self.allocations.items():
            resource_conflicts: list[tuple[str, str]] = []

            # Check for overlapping allocations
            for i, (task1, hours1, start1, end1) in enumerate(allocations_list):
                for task2, hours2, start2, end2 in allocations_list[i + 1 :]:
                    # Check overlap
                    if start1 < end2 and start2 < end1:
                        resource_conflicts.append((task1, task2))

            if resource_conflicts:
                conflicts.append((resource_id, resource_conflicts))

        return conflicts

    def list_resources(
        self,
        status: ResourceStatus | None = None,
        skill: str | None = None,
    ) -> list[Resource]:
        """List resources with optional filtering.

        Args:
            status: Filter by resource status.
            skill: Filter by skill.

        Returns:
            List of matching Resource instances.
        """
        resources = list(self.resources.values())
        if status:
            resources = [r for r in resources if r.status == status]
        if skill:
            resources = [r for r in resources if skill in r.skills]
        return resources

    def delete_resource(self, resource_id: str) -> None:
        """Delete resource (must have no allocations).

        Args:
            resource_id: Resource identifier.

        Raises:
            ResourceNotFoundError: If resource doesn't exist.
        """
        resource = self.get_resource(resource_id)
        if resource_id in self.allocations and self.allocations[resource_id]:
            raise ResourceOverallocationError("Cannot delete resource with active allocations")
        del self.resources[resource_id]
        if resource_id in self.allocations:
            del self.allocations[resource_id]
