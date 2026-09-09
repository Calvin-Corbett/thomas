"""Variable management and precedence resolution."""

from typing import Any

from thomas.config_mgmt._exceptions import ValidationError


class VariableManager:
    """Manages variables with precedence and scope."""

    PRECEDENCE_ORDER = [
        "extra",  # Command-line extra vars (highest)
        "task",  # Task variables
        "block",  # Block variables
        "role",  # Role variables
        "group",  # Group variables
        "host",  # Host variables
        "defaults",  # Default variables (lowest)
    ]

    def __init__(self) -> None:
        """Initialize variable manager."""
        self.variables: dict[str, dict[str, Any]] = {scope: {} for scope in self.PRECEDENCE_ORDER}

    def set(self, name: str, value: Any, scope: str = "extra") -> None:
        """Set variable with scope.

        Args:
            name: Variable name.
            value: Variable value.
            scope: Scope of variable.

        Raises:
            ValidationError: If scope is invalid.
        """
        if scope not in self.PRECEDENCE_ORDER:
            raise ValidationError(f"Invalid scope: {scope}")

        self.variables[scope][name] = value

    def get(self, name: str, default: Any = None) -> Any:
        """Get variable with precedence resolution.

        Args:
            name: Variable name.
            default: Default value if not found.

        Returns:
            Any: Variable value or default.
        """
        for scope in self.PRECEDENCE_ORDER:
            if name in self.variables[scope]:
                return self.variables[scope][name]

        return default

    def get_all_variables(self) -> dict[str, Any]:
        """Get all variables merged with precedence.

        Returns:
            Dict[str, Any]: Merged variables.
        """
        result: dict[str, Any] = {}

        # Merge from lowest to highest precedence
        for scope in reversed(self.PRECEDENCE_ORDER):
            result.update(self.variables[scope])

        return result

    def get_scope_variables(self, scope: str) -> dict[str, Any]:
        """Get variables for specific scope.

        Args:
            scope: Variable scope.

        Returns:
            Dict[str, Any]: Variables in scope.

        Raises:
            ValidationError: If scope is invalid.
        """
        if scope not in self.PRECEDENCE_ORDER:
            raise ValidationError(f"Invalid scope: {scope}")

        return self.variables[scope].copy()

    def delete(self, name: str, scope: str | None = None) -> bool:
        """Delete variable.

        Args:
            name: Variable name.
            scope: Specific scope to delete from (all if None).

        Returns:
            bool: True if deleted.
        """
        deleted = False

        if scope:
            if scope in self.variables and name in self.variables[scope]:
                del self.variables[scope][name]
                deleted = True
        else:
            for scope_dict in self.variables.values():
                if name in scope_dict:
                    del scope_dict[name]
                    deleted = True

        return deleted

    def clear_scope(self, scope: str) -> None:
        """Clear all variables in scope.

        Args:
            scope: Variable scope.

        Raises:
            ValidationError: If scope is invalid.
        """
        if scope not in self.PRECEDENCE_ORDER:
            raise ValidationError(f"Invalid scope: {scope}")

        self.variables[scope].clear()


class VariableLoader:
    """Loads variables from files and sources."""

    @staticmethod
    def load_yaml_vars(content: str) -> dict[str, Any]:
        """Load variables from YAML content.

        Args:
            content: YAML content.

        Returns:
            Dict[str, Any]: Parsed variables.

        Raises:
            ValidationError: If YAML is invalid.
        """
        try:
            import yaml

            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                raise ValidationError("YAML must be a dictionary")

            return data
        except ImportError:
            raise ValidationError("PyYAML not installed")
        except Exception as e:
            raise ValidationError(f"Failed to parse YAML: {e}")

    @staticmethod
    def load_json_vars(content: str) -> dict[str, Any]:
        """Load variables from JSON content.

        Args:
            content: JSON content.

        Returns:
            Dict[str, Any]: Parsed variables.

        Raises:
            ValidationError: If JSON is invalid.
        """
        import json

        try:
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValidationError("JSON must be an object")

            return data
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON: {e}")
