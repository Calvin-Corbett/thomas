"""Exception types for configuration management."""


class ConfigError(Exception):
    """Base exception for configuration errors."""

    pass


class ValidationError(ConfigError):
    """Raised when configuration validation fails."""

    pass


class ExecutionError(ConfigError):
    """Raised when task execution fails."""

    pass


class InventoryError(ConfigError):
    """Raised when inventory operations fail."""

    pass


class PlaybookError(ConfigError):
    """Raised when playbook operations fail."""

    pass


class ModuleError(ConfigError):
    """Raised when module operations fail."""

    pass


class HostUnreachableError(ExecutionError):
    """Raised when host cannot be reached."""

    pass


class TaskFailedError(ExecutionError):
    """Raised when task execution fails on host."""

    def __init__(self, task_name: str, host: str, stderr: str = "", stdout: str = "") -> None:
        """Initialize TaskFailedError.

        Args:
            task_name: Name of failed task.
            host: Host where task failed.
            stderr: Standard error output.
            stdout: Standard output.
        """
        self.task_name = task_name
        self.host = host
        self.stderr = stderr
        self.stdout = stdout
        msg = f"Task '{task_name}' failed on host '{host}'"
        if stderr:
            msg += f": {stderr}"
        super().__init__(msg)


class InvalidPlaybookError(PlaybookError):
    """Raised when playbook format is invalid."""

    pass


class RoleNotFoundError(ConfigError):
    """Raised when role cannot be found."""

    pass


class TemplateRenderError(ConfigError):
    """Raised when template rendering fails."""

    pass
