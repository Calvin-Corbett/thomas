"""
Type coercion engine.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class CoercionConfig:
    """Configuration for type coercion."""

    strict: bool = False
    """If True, no coercion attempted."""

    coerce_strings: bool = True
    """If True, coerce strings to other types."""

    coerce_numbers: bool = True
    """If True, coerce numbers between int/float."""

    coerce_to_bool: bool = True
    """If True, coerce to boolean (1/0, 'true'/'false', etc)."""

    coerce_to_list: bool = False
    """If True, wrap scalars in lists."""

    date_format: str = "%Y-%m-%d"
    """Format for parsing date strings."""

    datetime_format: str = "%Y-%m-%d %H:%M:%S"
    """Format for parsing datetime strings."""

    trim_strings: bool = True
    """If True, trim whitespace from strings."""

    handle_none: bool = False
    """If True, convert 'null'/'None' strings to None."""

    custom_coercers: dict[str, Callable[[Any], Any]] = field(default_factory=dict)
    """Custom coercion functions by type name."""

    log_coercions: bool = False
    """If True, log all coercion operations."""


class CoercionLog:
    """Track coercion operations."""

    def __init__(self) -> None:
        """Initialize log."""
        self.entries: dict[str, Any] = {}

    def log(self, field: str, original: Any, coerced: Any, rule: str) -> None:
        """Log a coercion.

        Args:
            field: Field name.
            original: Original value.
            coerced: Coerced value.
            rule: Coercion rule applied.
        """
        self.entries[field] = {
            "original": original,
            "coerced": coerced,
            "rule": rule,
        }

    def get_log(self) -> dict[str, Any]:
        """Get entire log."""
        return self.entries


class TypeCoercer:
    """Type coercion engine."""

    def __init__(self, config: CoercionConfig | None = None) -> None:
        """Initialize coercer.

        Args:
            config: CoercionConfig instance.
        """
        self.config = config or CoercionConfig()
        self.log = CoercionLog()

    def coerce(self, value: Any, target_type: str) -> Any:
        """Coerce value to target type.

        Args:
            value: Value to coerce.
            target_type: Target type name (int, str, bool, list, dict, etc).

        Returns:
            Coerced value or original if coercion fails/disabled.
        """
        if self.config.strict:
            return value

        if value is None:
            return None

        # Already correct type
        type_map = {
            "int": int,
            "integer": int,
            "float": float,
            "number": (int, float),
            "str": str,
            "string": str,
            "bool": bool,
            "boolean": bool,
            "list": list,
            "array": list,
            "dict": dict,
            "object": dict,
        }

        if target_type in type_map:
            expected = type_map[target_type]
            if isinstance(expected, tuple):
                if isinstance(value, expected):
                    return value
            else:
                if isinstance(value, expected):
                    return value

        # Custom coercer
        if target_type in self.config.custom_coercers:
            try:
                coerced = self.config.custom_coercers[target_type](value)
                if self.config.log_coercions:
                    self.log.log("", value, coerced, f"custom_{target_type}")
                return coerced
            except Exception:
                return value

        # Attempt coercion based on target type
        try:
            if target_type in ("int", "integer"):
                return self._coerce_to_int(value)
            elif target_type in ("float", "number"):
                return self._coerce_to_float(value)
            elif target_type in ("str", "string"):
                return self._coerce_to_str(value)
            elif target_type in ("bool", "boolean"):
                return self._coerce_to_bool(value)
            elif target_type in ("list", "array"):
                return self._coerce_to_list(value)
            elif target_type in ("dict", "object"):
                return self._coerce_to_dict(value)
            elif target_type == "date":
                return self._coerce_to_date(value)
            elif target_type == "datetime":
                return self._coerce_to_datetime(value)
            else:
                return value
        except Exception:
            return value

    def _coerce_to_int(self, value: Any) -> Any:
        """Coerce to integer."""
        if not self.config.coerce_numbers:
            return value

        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            if not self.config.coerce_strings:
                return value
            value = value.strip() if self.config.trim_strings else value
            try:
                return int(value)
            except ValueError:
                try:
                    return int(float(value))
                except ValueError:
                    return value
        return value

    def _coerce_to_float(self, value: Any) -> Any:
        """Coerce to float."""
        if not self.config.coerce_numbers:
            return value

        if isinstance(value, bool):
            return float(int(value))
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            if not self.config.coerce_strings:
                return value
            value = value.strip() if self.config.trim_strings else value
            try:
                return float(value)
            except ValueError:
                return value
        return value

    def _coerce_to_str(self, value: Any) -> Any:
        """Coerce to string."""
        if isinstance(value, str):
            return value.strip() if self.config.trim_strings else value
        if value is None:
            if self.config.handle_none:
                return "null"
            return value
        return str(value)

    def _coerce_to_bool(self, value: Any) -> Any:
        """Coerce to boolean."""
        if not self.config.coerce_to_bool:
            return value

        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            if not self.config.coerce_strings:
                return value
            lower = value.lower().strip()
            if lower in ("true", "1", "yes", "on"):
                return True
            if lower in ("false", "0", "no", "off", ""):
                return False
            return value
        if isinstance(value, (list, dict)):
            return bool(value)
        return value

    def _coerce_to_list(self, value: Any) -> Any:
        """Coerce to list."""
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            if not self.config.coerce_strings:
                return value
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
            if not self.config.coerce_to_list:
                return value
            return [value]
        if isinstance(value, (tuple, set)):
            return list(value)
        if self.config.coerce_to_list and value is not None:
            return [value]
        return value

    def _coerce_to_dict(self, value: Any) -> Any:
        """Coerce to dict."""
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            if not self.config.coerce_strings:
                return value
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return value

    def _coerce_to_date(self, value: Any) -> Any:
        """Coerce to date."""
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            if not self.config.coerce_strings:
                return value
            try:
                dt = datetime.strptime(value, self.config.date_format)
                return dt.date()
            except ValueError:
                return value
        return value

    def _coerce_to_datetime(self, value: Any) -> Any:
        """Coerce to datetime."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            if not self.config.coerce_strings:
                return value
            try:
                return datetime.strptime(value, self.config.datetime_format)
            except ValueError:
                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    return value
        return value

    def coerce_dict(
        self,
        data: dict[str, Any],
        type_map: dict[str, str],
    ) -> dict[str, Any]:
        """Coerce all values in dict to specified types.

        Args:
            data: Dictionary of values.
            type_map: Mapping of field name to target type.

        Returns:
            Dictionary with coerced values.
        """
        result = {}
        for field_name, value in data.items():
            if field_name in type_map:
                result[field_name] = self.coerce(value, type_map[field_name])
            else:
                result[field_name] = value
        return result

    def clear_log(self) -> None:
        """Clear coercion log."""
        self.log = CoercionLog()
