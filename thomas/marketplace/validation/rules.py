"""
Built-in validation rules.
"""

import re
from collections.abc import Callable
from datetime import datetime
from re import Pattern
from typing import Any

from thomas.marketplace.validation._types import FieldRule, Severity


def required(message: str = "This field is required") -> FieldRule:
    """Rule: Value is required (not None, not empty string)."""
    return FieldRule(
        name="required",
        validator=lambda x: x is not None and x != "",
        message=message,
        severity=Severity.ERROR,
    )


def type_check(expected_type: type, message: str = "") -> FieldRule:
    """Rule: Value must be of specified type."""
    type_name = expected_type.__name__
    return FieldRule(
        name="type_check",
        validator=lambda x: isinstance(x, expected_type),
        message=message or f"Must be of type {type_name}",
        context={"expected_type": type_name},
    )


def min_value(min_val: int | float, message: str = "") -> FieldRule:
    """Rule: Numeric value must be >= min_val."""
    return FieldRule(
        name="min_value",
        validator=lambda x: isinstance(x, (int, float)) and x >= min_val,
        message=message or f"Must be >= {min_val}",
        context={"min": min_val},
    )


def max_value(max_val: int | float, message: str = "") -> FieldRule:
    """Rule: Numeric value must be <= max_val."""
    return FieldRule(
        name="max_value",
        validator=lambda x: isinstance(x, (int, float)) and x <= max_val,
        message=message or f"Must be <= {max_val}",
        context={"max": max_val},
    )


def min_length(min_len: int, message: str = "") -> FieldRule:
    """Rule: String/list length must be >= min_len."""
    return FieldRule(
        name="min_length",
        validator=lambda x: hasattr(x, "__len__") and len(x) >= min_len,
        message=message or f"Must be at least {min_len} characters/items",
        context={"min_length": min_len},
    )


def max_length(max_len: int, message: str = "") -> FieldRule:
    """Rule: String/list length must be <= max_len."""
    return FieldRule(
        name="max_length",
        validator=lambda x: hasattr(x, "__len__") and len(x) <= max_len,
        message=message or f"Must be at most {max_len} characters/items",
        context={"max_length": max_len},
    )


def pattern(regex: str | Pattern, message: str = "") -> FieldRule:
    """Rule: String must match regex pattern.

    Args:
        regex: Pattern string or compiled regex.
        message: Custom error message.

    Returns:
        FieldRule for pattern validation.
    """
    compiled = re.compile(regex) if isinstance(regex, str) else regex
    pattern_str = regex if isinstance(regex, str) else regex.pattern

    def validator(x: Any) -> bool:
        if not isinstance(x, str):
            return False
        return compiled.match(x) is not None

    return FieldRule(
        name="pattern",
        validator=validator,
        message=message or f"Must match pattern: {pattern_str}",
        context={"pattern": pattern_str},
    )


def enum_rule(allowed_values: list[Any], message: str = "") -> FieldRule:
    """Rule: Value must be in list of allowed values."""
    return FieldRule(
        name="enum",
        validator=lambda x: x in allowed_values,
        message=message or f"Must be one of: {', '.join(str(v) for v in allowed_values)}",
        context={"allowed": allowed_values},
    )


def email(message: str = "Must be a valid email address") -> FieldRule:
    """Rule: String must be valid email address."""
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    def validator(x: Any) -> bool:
        if not isinstance(x, str):
            return False
        return re.match(email_pattern, x) is not None

    return FieldRule(
        name="email",
        validator=validator,
        message=message,
        context={"pattern": email_pattern},
    )


def url(message: str = "Must be a valid URL") -> FieldRule:
    """Rule: String must be valid URL."""
    url_pattern = r"^https?://[^\s/$.?#].[^\s]*$"

    def validator(x: Any) -> bool:
        if not isinstance(x, str):
            return False
        return re.match(url_pattern, x, re.IGNORECASE) is not None

    return FieldRule(
        name="url",
        validator=validator,
        message=message,
        context={"pattern": url_pattern},
    )


def uuid_rule(message: str = "Must be a valid UUID") -> FieldRule:
    """Rule: String must be valid UUID."""
    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

    def validator(x: Any) -> bool:
        if not isinstance(x, str):
            return False
        return re.match(uuid_pattern, x, re.IGNORECASE) is not None

    return FieldRule(
        name="uuid",
        validator=validator,
        message=message,
        context={"pattern": uuid_pattern},
    )


def ip_address(version: str = "4", message: str = "") -> FieldRule:
    """Rule: String must be valid IP address.

    Args:
        version: "4" for IPv4, "6" for IPv6, "both" for either.
        message: Custom error message.

    Returns:
        FieldRule for IP validation.
    """
    ipv4_pattern = r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
    ipv6_pattern = r"^(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$"

    patterns = {
        "4": (ipv4_pattern, "IPv4"),
        "6": (ipv6_pattern, "IPv6"),
        "both": (None, "IPv4 or IPv6"),
    }

    if version not in patterns:
        raise ValueError(f"IP version must be 4, 6, or both, got {version}")

    pattern_str, version_str = patterns[version]

    def validator(x: Any) -> bool:
        if not isinstance(x, str):
            return False
        if version == "both":
            return re.match(ipv4_pattern, x) is not None or re.match(ipv6_pattern, x) is not None
        return re.match(pattern_str, x) is not None

    return FieldRule(
        name="ip_address",
        validator=validator,
        message=message or f"Must be a valid {version_str} address",
        context={"ip_version": version},
    )


def date_format(format_str: str = "%Y-%m-%d", message: str = "") -> FieldRule:
    """Rule: String must be valid date in specified format.

    Args:
        format_str: Date format string (Python strptime format).
        message: Custom error message.

    Returns:
        FieldRule for date validation.
    """

    def validator(x: Any) -> bool:
        if not isinstance(x, str):
            return False
        try:
            datetime.strptime(x, format_str)
            return True
        except ValueError:
            return False

    return FieldRule(
        name="date_format",
        validator=validator,
        message=message or f"Must be valid date in format {format_str}",
        context={"format": format_str},
    )


def range_rule(
    min_val: int | float,
    max_val: int | float,
    message: str = "",
) -> FieldRule:
    """Rule: Numeric value must be in range [min_val, max_val]."""
    return FieldRule(
        name="range",
        validator=lambda x: isinstance(x, (int, float)) and min_val <= x <= max_val,
        message=message or f"Must be between {min_val} and {max_val}",
        context={"min": min_val, "max": max_val},
    )


def one_of(rules: list[FieldRule], message: str = "") -> FieldRule:
    """Rule: Value must match at least one of the provided rules.

    Args:
        rules: List of FieldRule objects.
        message: Custom error message.

    Returns:
        Composite FieldRule.
    """

    def validator(x: Any) -> bool:
        return any(rule.validator(x) for rule in rules)

    rule_names = ", ".join(r.name for r in rules)
    return FieldRule(
        name="one_of",
        validator=validator,
        message=message or f"Must match one of: {rule_names}",
        context={"rules": [r.name for r in rules]},
    )


def all_of(rules: list[FieldRule], message: str = "") -> FieldRule:
    """Rule: Value must match all of the provided rules.

    Args:
        rules: List of FieldRule objects.
        message: Custom error message.

    Returns:
        Composite FieldRule.
    """

    def validator(x: Any) -> bool:
        return all(rule.validator(x) for rule in rules)

    rule_names = ", ".join(r.name for r in rules)
    return FieldRule(
        name="all_of",
        validator=validator,
        message=message or f"Must match all of: {rule_names}",
        context={"rules": [r.name for r in rules]},
    )


def custom_predicate(
    predicate: Callable[[Any], bool],
    name: str = "custom",
    message: str = "",
) -> FieldRule:
    """Rule: Custom validation function.

    Args:
        predicate: Function that returns True if valid.
        name: Rule name for error messages.
        message: Error message.

    Returns:
        FieldRule for custom validation.
    """
    return FieldRule(
        name=name,
        validator=predicate,
        message=message or f"Custom validation '{name}' failed",
    )
