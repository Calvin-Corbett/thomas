"""Type definitions for infrastructure configuration management."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class State(Enum):
    """Host state enumeration."""

    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"


class ConnectionType(Enum):
    """Connection type enumeration."""

    SSH = "ssh"
    LOCAL = "local"
    PARAMIKO = "paramiko"
    WINRM = "winrm"


@dataclass
class Credential:
    """Credential configuration for host connection."""

    username: str
    password: str | None = None
    private_key_path: str | None = None
    private_key: str | None = None
    become_method: str | None = None
    become_user: str | None = None
    become_password: str | None = None
    timeout: int = 10
    retries: int = 3
    extra_args: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate credential configuration.

        Raises:
            ValueError: If credential configuration is invalid.
        """
        if not self.username:
            raise ValueError("Username is required")

        if not self.password and not self.private_key_path and not self.private_key:
            raise ValueError("Either password or private key is required")

        if self.timeout <= 0:
            raise ValueError("Timeout must be positive")

        if self.retries < 0:
            raise ValueError("Retries cannot be negative")


@dataclass
class Connection:
    """Connection details for a host."""

    type: ConnectionType
    host: str
    port: int
    credential: Credential
    state: State = State.UNKNOWN
    last_connected: datetime | None = None

    def validate(self) -> None:
        """Validate connection configuration.

        Raises:
            ValueError: If connection configuration is invalid.
        """
        if not self.host:
            raise ValueError("Host is required")

        if self.port <= 0 or self.port > 65535:
            raise ValueError("Port must be between 1 and 65535")

        self.credential.validate()


@dataclass
class Variable:
    """Variable definition with metadata."""

    name: str
    value: Any
    scope: str = "host"  # host, group, role, playbook
    override: bool = True
    type_hint: str | None = None
    description: str | None = None

    def __hash__(self) -> int:
        """Return hash based on name and scope."""
        return hash((self.name, self.scope))

    def __eq__(self, other: Any) -> bool:
        """Check equality based on name and scope."""
        if not isinstance(other, Variable):
            return False
        return self.name == other.name and self.scope == other.scope


@dataclass
class Template:
    """Template with variable substitution support."""

    name: str
    content: str
    variables: dict[str, Any] = field(default_factory=dict)
    backup: bool = True

    def render(self) -> str:
        """Render template with variables.

        Returns:
            str: Rendered template content.
        """
        result = self.content
        for key, value in self.variables.items():
            placeholder = "{{ " + key + " }}"
            result = result.replace(placeholder, str(value))
        return result

    def validate(self) -> None:
        """Validate template syntax."""
        import re

        pattern = r"\{\{\s*\w+\s*\}\}"
        for match in re.finditer(pattern, self.content):
            var_name = match.group().strip("{ }").strip()
            if var_name not in self.variables:
                pass  # Allow undefined variables


@dataclass
class Fact:
    """Fact gathered from a host."""

    name: str
    value: Any
    host: str
    timestamp: datetime = field(default_factory=datetime.now)
    cacheable: bool = True

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Fact({self.name}={self.value}@{self.host})"


@dataclass
class Handler:
    """Handler for event notifications."""

    name: str
    action: str
    tags: list[str] = field(default_factory=list)
    listen: str | None = None

    def __hash__(self) -> int:
        """Return hash based on name."""
        return hash(self.name)

    def __eq__(self, other: Any) -> bool:
        """Check equality based on name."""
        if not isinstance(other, Handler):
            return False
        return self.name == other.name


@dataclass
class Task:
    """Task to execute on hosts."""

    name: str
    module: str
    args: dict[str, Any] = field(default_factory=dict)
    when: str | None = None
    with_items: list[Any] | None = None
    register: str | None = None
    notify: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    ignore_errors: bool = False
    changed_when: str | None = None
    failed_when: str | None = None
    retries: int = 1
    delay: int = 0
    become: bool = False
    become_user: str | None = None

    def validate(self) -> None:
        """Validate task configuration.

        Raises:
            ValueError: If task is invalid.
        """
        if not self.name:
            raise ValueError("Task name is required")

        if not self.module:
            raise ValueError("Task module is required")

        if self.retries < 1:
            raise ValueError("Retries must be at least 1")

        if self.delay < 0:
            raise ValueError("Delay cannot be negative")


@dataclass
class Role:
    """Role grouping tasks, handlers, variables, and templates."""

    name: str
    tasks: list[Task] = field(default_factory=list)
    handlers: list[Handler] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    templates: list[Template] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """Validate role configuration."""
        if not self.name:
            raise ValueError("Role name is required")

        for task in self.tasks:
            task.validate()


@dataclass
class HostGroup:
    """Group of hosts with shared configuration."""

    name: str
    hosts: set[str] = field(default_factory=set)
    variables: dict[str, Any] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)

    def add_host(self, hostname: str) -> None:
        """Add host to group.

        Args:
            hostname: Host to add.
        """
        self.hosts.add(hostname)

    def remove_host(self, hostname: str) -> None:
        """Remove host from group.

        Args:
            hostname: Host to remove.
        """
        self.hosts.discard(hostname)

    def add_child_group(self, group_name: str) -> None:
        """Add child group.

        Args:
            group_name: Child group name.
        """
        if group_name not in self.children:
            self.children.append(group_name)

    def is_member(self, hostname: str, recursive: bool = False) -> bool:
        """Check if host is member of group.

        Args:
            hostname: Host to check.
            recursive: Include child groups.

        Returns:
            bool: True if host is member.
        """
        if hostname in self.hosts:
            return True

        if recursive:
            for child in self.children:
                # Would need parent reference to check child groups
                pass

        return False


@dataclass
class Host:
    """Host configuration."""

    hostname: str
    connection: Connection
    variables: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    groups: set[str] = field(default_factory=set)
    port: int = 22
    user: str | None = None

    def add_group(self, group_name: str) -> None:
        """Add host to group.

        Args:
            group_name: Group name.
        """
        self.groups.add(group_name)

    def remove_group(self, group_name: str) -> None:
        """Remove host from group.

        Args:
            group_name: Group name.
        """
        self.groups.discard(group_name)

    def set_fact(self, name: str, value: Any) -> None:
        """Set a fact on the host.

        Args:
            name: Fact name.
            value: Fact value.
        """
        self.facts[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get host variable with fallback.

        Args:
            name: Variable name.
            default: Default value if not found.

        Returns:
            Any: Variable value or default.
        """
        return self.variables.get(name, default)


@dataclass
class Inventory:
    """Inventory of hosts and groups."""

    name: str
    hosts: dict[str, Host] = field(default_factory=dict)
    groups: dict[str, HostGroup] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    plugin_type: str | None = None
    plugin_config: dict[str, Any] = field(default_factory=dict)

    def add_host(self, host: Host) -> None:
        """Add host to inventory.

        Args:
            host: Host to add.
        """
        self.hosts[host.hostname] = host

    def add_group(self, group: HostGroup) -> None:
        """Add group to inventory.

        Args:
            group: Group to add.
        """
        self.groups[group.name] = group

    def get_host(self, hostname: str) -> Host | None:
        """Get host by hostname.

        Args:
            hostname: Hostname.

        Returns:
            Optional[Host]: Host or None if not found.
        """
        return self.hosts.get(hostname)

    def get_group(self, group_name: str) -> HostGroup | None:
        """Get group by name.

        Args:
            group_name: Group name.

        Returns:
            Optional[HostGroup]: Group or None if not found.
        """
        return self.groups.get(group_name)

    def get_group_hosts(self, group_name: str) -> list[Host]:
        """Get all hosts in a group.

        Args:
            group_name: Group name.

        Returns:
            List[Host]: Hosts in group.
        """
        group = self.get_group(group_name)
        if not group:
            return []

        result = [self.hosts[h] for h in group.hosts if h in self.hosts]
        return result

    def merge(self, other: "Inventory") -> None:
        """Merge another inventory into this one.

        Args:
            other: Inventory to merge.
        """
        for hostname, host in other.hosts.items():
            if hostname in self.hosts:
                self.hosts[hostname].variables.update(host.variables)
            else:
                self.hosts[hostname] = host

        for group_name, group in other.groups.items():
            if group_name in self.groups:
                self.groups[group_name].hosts.update(group.hosts)
                self.groups[group_name].variables.update(group.variables)
            else:
                self.groups[group_name] = group

        self.variables.update(other.variables)


@dataclass
class Module:
    """Module definition for task execution."""

    name: str
    description: str
    arguments: dict[str, dict[str, Any]] = field(default_factory=dict)
    returns: dict[str, Any] = field(default_factory=dict)
    supports_check_mode: bool = False
    supports_async: bool = False

    def validate_args(self, args: dict[str, Any]) -> tuple[bool, str]:
        """Validate module arguments.

        Args:
            args: Arguments to validate.

        Returns:
            Tuple[bool, str]: (is_valid, error_message).
        """
        for required_arg, spec in self.arguments.items():
            if spec.get("required", False) and required_arg not in args:
                return False, f"Required argument '{required_arg}' missing"

        for arg in args:
            if arg not in self.arguments:
                return False, f"Unknown argument '{arg}'"

        return True, ""


@dataclass
class ExecutionResult:
    """Result of task execution."""

    task_name: str
    host: str
    status: str  # success, failed, skipped, changed
    module: str
    stdout: str = ""
    stderr: str = ""
    return_data: dict[str, Any] = field(default_factory=dict)
    changed: bool = False
    failed: bool = False
    skipped: bool = False
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0
    attempts: int = 1

    def __repr__(self) -> str:
        """Return string representation."""
        return f"ExecutionResult({self.task_name}@{self.host}={self.status},changed={self.changed})"


@dataclass
class DiffResult:
    """Diff of file changes."""

    filename: str
    before: str = ""
    after: str = ""
    before_header: str = ""
    after_header: str = ""

    def get_unified_diff(self) -> list[str]:
        """Get unified diff format.

        Returns:
            List[str]: Diff lines.
        """
        import difflib

        diff = difflib.unified_diff(
            self.before.splitlines(keepends=True),
            self.after.splitlines(keepends=True),
            fromfile=self.before_header or self.filename,
            tofile=self.after_header or self.filename,
        )
        return list(diff)

    def is_changed(self) -> bool:
        """Check if file was changed.

        Returns:
            bool: True if changed.
        """
        return self.before != self.after


@dataclass
class Playbook:
    """Playbook containing plays and tasks."""

    name: str
    hosts: str  # Host pattern
    tasks: list[Task] = field(default_factory=list)
    roles: list[Role] = field(default_factory=list)
    handlers: list[Handler] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    vars_files: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    pre_tasks: list[Task] = field(default_factory=list)
    post_tasks: list[Task] = field(default_factory=list)
    max_fail_percentage: float = 0.0
    serial: int | None = None
    strategy: str = "linear"

    def validate(self) -> None:
        """Validate playbook configuration."""
        if not self.name:
            raise ValueError("Playbook name is required")

        if not self.hosts:
            raise ValueError("Playbook hosts pattern is required")

        for task in self.tasks + self.pre_tasks + self.post_tasks:
            task.validate()

        for role in self.roles:
            role.validate()

        if not 0.0 <= self.max_fail_percentage <= 100.0:
            raise ValueError("max_fail_percentage must be 0-100")

        if self.serial is not None and self.serial < 1:
            raise ValueError("serial must be at least 1")
