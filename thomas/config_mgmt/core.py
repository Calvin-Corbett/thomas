"""
Core configuration management entities and state management.

Provides foundational classes for resource management, state tracking,
and task execution within the configuration management platform.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ResourceState(Enum):
    """Enumeration of possible resource states."""

    UNMANAGED = "unmanaged"
    CONVERGING = "converging"
    CONVERGED = "converged"
    DRIFT = "drift"
    FAILED = "failed"
    PENDING = "pending"


class ResourceType(Enum):
    """Supported resource types in configuration management."""

    FILE = "file"
    PACKAGE = "package"
    SERVICE = "service"
    USER = "user"
    GROUP = "group"
    DIRECTORY = "directory"
    TEMPLATE = "template"
    FIREWALL_RULE = "firewall_rule"
    NETWORK_INTERFACE = "network_interface"
    ENVIRONMENT_VARIABLE = "environment_variable"
    CRON_JOB = "cron_job"
    CUSTOM = "custom"


@dataclass
class TaskResult:
    """Result of a task execution."""

    task_id: str
    success: bool
    output: str
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    changed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "task_id": self.task_id,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
            "changed": self.changed,
            "metadata": self.metadata,
        }


@dataclass
class ResourceAttribute:
    """Represents a single resource attribute with validation rules."""

    name: str
    value: Any
    expected: Any
    required: bool = False
    validator: callable | None = None

    def is_compliant(self) -> bool:
        """Check if attribute matches expected value."""
        if self.validator:
            return self.validator(self.value)
        return self.value == self.expected

    def get_drift(self) -> dict[str, Any] | None:
        """Get drift information if attribute is non-compliant."""
        if self.is_compliant():
            return None
        return {
            "name": self.name,
            "current": self.value,
            "expected": self.expected,
        }


@dataclass
class Resource:
    """Represents a managed infrastructure resource."""

    id: str
    resource_type: ResourceType
    name: str
    attributes: dict[str, ResourceAttribute] = field(default_factory=dict)
    state: ResourceState = ResourceState.UNMANAGED
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tags: dict[str, str] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    handlers: dict[str, callable] = field(default_factory=dict)

    def add_attribute(
        self,
        name: str,
        value: Any,
        expected: Any,
        required: bool = False,
        validator: callable | None = None,
    ) -> None:
        """Add or update a resource attribute."""
        self.attributes[name] = ResourceAttribute(
            name=name,
            value=value,
            expected=expected,
            required=required,
            validator=validator,
        )

    def check_compliance(self) -> tuple[bool, list[dict[str, Any]]]:
        """Check if resource meets expected state."""
        drift_list = []
        for attr in self.attributes.values():
            if not attr.is_compliant():
                drift_info = attr.get_drift()
                if drift_info:
                    drift_list.append(drift_info)

        is_compliant = len(drift_list) == 0
        return is_compliant, drift_list

    def update_state(self, new_state: ResourceState) -> None:
        """Update resource state with timestamp."""
        self.state = new_state
        self.timestamp = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Convert resource to dictionary representation."""
        return {
            "id": self.id,
            "resource_type": self.resource_type.value,
            "name": self.name,
            "attributes": {k: {"value": v.value, "expected": v.expected} for k, v in self.attributes.items()},
            "state": self.state.value,
            "timestamp": self.timestamp.isoformat(),
            "tags": self.tags,
            "depends_on": self.depends_on,
        }


@dataclass
class Task:
    """Represents a configuration task to be executed."""

    id: str
    name: str
    module: str
    resource_type: ResourceType
    parameters: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    when: str | None = None
    retries: int = 0
    delay_ms: int = 0
    notify: list[str] = field(default_factory=list)
    register: str | None = None
    ignore_errors: bool = False
    depends_on: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        name: str,
        module: str,
        resource_type: ResourceType,
        **params: Any,
    ) -> "Task":
        """Create a task with auto-generated ID."""
        task_id = str(uuid.uuid4())
        return cls(
            id=task_id,
            name=name,
            module=module,
            resource_type=resource_type,
            parameters=params,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "module": self.module,
            "resource_type": self.resource_type.value,
            "parameters": self.parameters,
            "enabled": self.enabled,
            "tags": self.tags,
            "retries": self.retries,
            "notify": self.notify,
        }


@dataclass
class Inventory:
    """Manages infrastructure inventory and host/group organization."""

    hosts: dict[str, dict[str, Any]] = field(default_factory=dict)
    groups: dict[str, list[str]] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add_host(self, hostname: str, **attributes: Any) -> None:
        """Add a host to inventory with attributes."""
        self.hosts[hostname] = attributes
        if "localhost" not in self.groups:
            self.groups["all"] = []
        if hostname not in self.groups.get("all", []):
            self.groups["all"].append(hostname)

    def add_group(self, group_name: str, hosts: list[str]) -> None:
        """Add a host group to inventory."""
        self.groups[group_name] = hosts

    def get_hosts_in_group(self, group_name: str) -> list[str]:
        """Get all hosts in a specific group."""
        return self.groups.get(group_name, [])

    def get_host_variables(self, hostname: str) -> dict[str, Any]:
        """Get all variables for a specific host."""
        host_vars = self.hosts.get(hostname, {}).copy()
        host_vars.update(self.variables)
        return host_vars

    def filter_hosts(self, **criteria: Any) -> list[str]:
        """Filter hosts based on attribute criteria."""
        matching_hosts = []
        for hostname, attributes in self.hosts.items():
            if all(attributes.get(k) == v for k, v in criteria.items()):
                matching_hosts.append(hostname)
        return matching_hosts

    def to_dict(self) -> dict[str, Any]:
        """Convert inventory to dictionary representation."""
        return {
            "hosts": self.hosts,
            "groups": self.groups,
            "variables": self.variables,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ConfigSnapshot:
    """Snapshot of configuration state at a point in time."""

    snapshot_id: str
    timestamp: datetime
    resources: dict[str, Resource]
    variables: dict[str, Any]
    checksum: str = ""

    @property
    def resource_count(self) -> int:
        """Get count of resources in snapshot."""
        return len(self.resources)

    def calculate_checksum(self) -> str:
        """Calculate checksum of snapshot state."""
        snapshot_data = json.dumps(
            {k: v.to_dict() for k, v in self.resources.items()},
            sort_keys=True,
        )
        import hashlib

        return hashlib.sha256(snapshot_data.encode()).hexdigest()

    def get_state_summary(self) -> dict[str, int]:
        """Get summary of resource states in snapshot."""
        summary: dict[str, int] = {}
        for resource in self.resources.values():
            state_key = resource.state.value
            summary[state_key] = summary.get(state_key, 0) + 1
        return summary
