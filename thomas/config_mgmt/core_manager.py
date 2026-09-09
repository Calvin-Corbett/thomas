"""
Main configuration manager orchestrating all management operations.

Provides high-level API for configuration management including resource
tracking, state convergence, change validation, and execution management.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from thomas.config_mgmt.core import (
    ConfigSnapshot,
    Inventory,
    Resource,
    ResourceState,
    ResourceType,
    Task,
    TaskResult,
)
from thomas.config_mgmt.modules import ModuleRegistry
from thomas.config_mgmt.playbook import (
    Playbook,
    PlaybookExecution,
    PlaybookState,
    TaskExecution,
)
from thomas.config_mgmt.templates import TemplateEngine
from thomas.config_mgmt.validation import ValidationResult, Validator


@dataclass
class ConfigManager:
    """Main configuration management engine."""

    manager_id: str
    resources: dict[str, Resource] = field(default_factory=dict)
    inventory: Inventory = field(default_factory=Inventory)
    playbook_history: list[PlaybookExecution] = field(default_factory=list)
    snapshots: dict[str, ConfigSnapshot] = field(default_factory=dict)
    validator: Validator = field(default_factory=Validator)
    module_registry: ModuleRegistry = field(default_factory=ModuleRegistry)
    template_engine: TemplateEngine = field(default_factory=TemplateEngine)
    created_at: datetime = field(default_factory=datetime.utcnow)
    dry_run_mode: bool = False
    strict_mode: bool = False

    @classmethod
    def create(cls, dry_run: bool = False, strict: bool = False) -> "ConfigManager":
        """Create a configuration manager instance."""
        manager_id = str(uuid.uuid4())
        return cls(
            manager_id=manager_id,
            dry_run_mode=dry_run,
            strict_mode=strict,
        )

    def add_resource(self, resource: Resource) -> None:
        """Register a managed resource."""
        self.resources[resource.id] = resource
        resource.update_state(ResourceState.PENDING)

    def get_resource(self, resource_id: str) -> Resource | None:
        """Get a resource by ID."""
        return self.resources.get(resource_id)

    def list_resources(
        self, resource_type: ResourceType | None = None, tags: dict[str, str] | None = None
    ) -> list[Resource]:
        """List resources with optional filtering."""
        resources = list(self.resources.values())

        if resource_type:
            resources = [r for r in resources if r.resource_type == resource_type]

        if tags:
            resources = [r for r in resources if all(r.tags.get(k) == v for k, v in tags.items())]

        return resources

    def check_compliance(self) -> dict[str, Any]:
        """Check compliance of all managed resources."""
        compliance_report = {
            "total_resources": len(self.resources),
            "compliant_resources": 0,
            "non_compliant_resources": 0,
            "drift_summary": [],
        }

        for resource in self.resources.values():
            is_compliant, drift_list = resource.check_compliance()
            if is_compliant:
                resource.update_state(ResourceState.CONVERGED)
                compliance_report["compliant_resources"] += 1
            else:
                resource.update_state(ResourceState.DRIFT)
                compliance_report["non_compliant_resources"] += 1
                compliance_report["drift_summary"].append(
                    {
                        "resource_id": resource.id,
                        "resource_name": resource.name,
                        "drift": drift_list,
                    }
                )

        return compliance_report

    def execute_task(self, task: Task, host: str = "localhost", check_mode: bool = False) -> TaskResult:
        """Execute a single task."""
        start_time = datetime.utcnow()

        # Validate task parameters
        module = self.module_registry.get_module(task.module)
        if not module:
            return TaskResult(
                task_id=task.id,
                success=False,
                output="",
                error=f"Module '{task.module}' not found",
            )

        # Render parameters with template engine
        rendered_params = self._render_parameters(task.parameters)

        # Execute module
        module_result = module.execute(rendered_params, check_mode)

        # Create task result
        end_time = datetime.utcnow()
        duration_ms = (end_time - start_time).total_seconds() * 1000

        result = TaskResult(
            task_id=task.id,
            success=module_result.success,
            output=module_result.output,
            error=module_result.error,
            duration_ms=duration_ms,
            changed=module_result.changed,
            metadata=module_result.metadata,
        )

        # Update resource state if successful
        if module_result.success:
            resource = self._get_or_create_resource(task, host)
            if resource:
                new_state = ResourceState.CONVERGED if module_result.success else ResourceState.FAILED
                resource.update_state(new_state)

        return result

    def execute_playbook(
        self, playbook: Playbook, inventory: Inventory | None = None, tags: list[str] | None = None
    ) -> PlaybookExecution:
        """Execute a playbook across inventory."""
        inv = inventory or self.inventory
        execution = PlaybookExecution.create(
            playbook,
            inv,
            dry_run=self.dry_run_mode,
        )

        # Validate playbook
        if not playbook.validate_dependencies():
            execution.state = PlaybookState.FAILED
            return execution

        # Get target hosts
        hosts = playbook.hosts or inv.get_hosts_in_group("all")

        # Execute pre-tasks
        for task in playbook.pre_tasks:
            if not self._should_execute_task(task, tags):
                continue
            for host in hosts:
                self._execute_task_for_host(task, host, execution)

        # Execute main tasks
        for task in playbook.tasks:
            if not self._should_execute_task(task, tags):
                continue

            # Check dependencies
            if task.depends_on:
                if not self._are_dependencies_met(task.depends_on, execution):
                    task_exec = TaskExecution(
                        task_id=task.id,
                        task_name=task.name,
                        host="all",
                        state=PlaybookState.FAILED,
                        skipped=True,
                        skip_reason="Dependency not met",
                    )
                    execution.add_task_execution(task_exec)
                    continue

            for host in hosts:
                self._execute_task_for_host(task, host, execution)

        # Execute post-tasks
        for task in playbook.post_tasks:
            if not self._should_execute_task(task, tags):
                continue
            for host in hosts:
                self._execute_task_for_host(task, host, execution)

        # Mark execution as completed
        execution.mark_completed()
        self.playbook_history.append(execution)

        return execution

    def create_snapshot(self, name: str = "") -> ConfigSnapshot:
        """Create snapshot of current configuration state."""
        snapshot_id = str(uuid.uuid4())
        snapshot = ConfigSnapshot(
            snapshot_id=snapshot_id,
            timestamp=datetime.utcnow(),
            resources=self.resources.copy(),
            variables=self.template_engine.get_variables(),
        )
        snapshot.checksum = snapshot.calculate_checksum()
        self.snapshots[snapshot_id] = snapshot
        return snapshot

    def compare_snapshots(self, snapshot1_id: str, snapshot2_id: str) -> dict[str, Any]:
        """Compare two snapshots."""
        snap1 = self.snapshots.get(snapshot1_id)
        snap2 = self.snapshots.get(snapshot2_id)

        if not snap1 or not snap2:
            return {}

        return {
            "snapshot1_id": snapshot1_id,
            "snapshot2_id": snapshot2_id,
            "timestamp1": snap1.timestamp.isoformat(),
            "timestamp2": snap2.timestamp.isoformat(),
            "added_resources": [r for r in snap2.resources if r not in snap1.resources],
            "removed_resources": [r for r in snap1.resources if r not in snap2.resources],
            "modified_resources": self._find_modified_resources(snap1, snap2),
        }

    def validate_configuration(self, config_schema: dict[str, Any]) -> ValidationResult:
        """Validate configuration against schema."""
        config_dict = {r.id: r.to_dict() for r in self.resources.values()}
        return self.validator.validate_schema(config_dict, config_schema)

    def rollback_to_snapshot(self, snapshot_id: str) -> bool:
        """Rollback to a previous snapshot."""
        snapshot = self.snapshots.get(snapshot_id)
        if not snapshot:
            return False

        self.resources = snapshot.resources.copy()
        return True

    def get_statistics(self) -> dict[str, Any]:
        """Get configuration management statistics."""
        resources = self.resources.values()
        states = [r.state for r in resources]

        return {
            "manager_id": self.manager_id,
            "total_resources": len(self.resources),
            "resource_types": len(set(r.resource_type for r in resources)),
            "resource_states": {state.value: states.count(state) for state in ResourceState},
            "playbook_executions": len(self.playbook_history),
            "successful_executions": sum(1 for e in self.playbook_history if e.state == PlaybookState.SUCCESS),
            "snapshots_count": len(self.snapshots),
            "created_at": self.created_at.isoformat(),
        }

    def _render_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Render task parameters with template engine."""
        rendered = {}
        for key, value in parameters.items():
            if isinstance(value, str):
                rendered[key] = self.template_engine.render(value)
            else:
                rendered[key] = value
        return rendered

    def _get_or_create_resource(self, task: Task, host: str) -> Resource | None:
        """Get or create resource from task."""
        resource_name = task.parameters.get("name", task.id)
        resource = Resource(
            id=f"{host}:{resource_name}",
            resource_type=task.resource_type,
            name=resource_name,
        )
        self.add_resource(resource)
        return resource

    def _should_execute_task(self, task: Task, tags: list[str] | None = None) -> bool:
        """Determine if task should be executed."""
        if not task.enabled:
            return False
        if tags and not any(t in task.tags for t in tags):
            return False
        return True

    def _execute_task_for_host(self, task: Task, host: str, execution: PlaybookExecution) -> None:
        """Execute a task for a specific host."""
        task_exec = TaskExecution(
            task_id=task.id,
            task_name=task.name,
            host=host,
            state=PlaybookState.RUNNING,
            started_at=datetime.utcnow(),
        )

        result = self.execute_task(task, host, self.dry_run_mode)
        task_exec.result = result
        task_exec.duration_ms = result.duration_ms
        task_exec.state = PlaybookState.SUCCESS if result.success else PlaybookState.FAILED
        task_exec.completed_at = datetime.utcnow()

        execution.add_task_execution(task_exec)

    def _are_dependencies_met(self, depends_on: list[str], execution: PlaybookExecution) -> bool:
        """Check if all task dependencies are met."""
        completed_ids = {t.task_id for t in execution.task_executions if t.state == PlaybookState.SUCCESS}
        return all(dep_id in completed_ids for dep_id in depends_on)

    def _find_modified_resources(self, snap1: ConfigSnapshot, snap2: ConfigSnapshot) -> list[dict[str, Any]]:
        """Find resources that were modified between snapshots."""
        modified = []
        for res_id in snap1.resources:
            if res_id in snap2.resources:
                res1 = snap1.resources[res_id]
                res2 = snap2.resources[res_id]
                if res1.to_dict() != res2.to_dict():
                    modified.append(
                        {
                            "resource_id": res_id,
                            "before": res1.to_dict(),
                            "after": res2.to_dict(),
                        }
                    )
        return modified
