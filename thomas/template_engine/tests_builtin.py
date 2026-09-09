"""Built-in test functions for templates."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def test_callable(value: Any) -> bool:
    """Test if value is callable."""
    return callable(value)


def test_defined(value: Any) -> bool:
    """Test if value is defined (not None)."""
    return value is not None


def test_undefined(value: Any) -> bool:
    """Test if value is undefined (None)."""
    return value is None


def test_none(value: Any) -> bool:
    """Test if value is None."""
    return value is None


def test_boolean(value: Any) -> bool:
    """Test if value is boolean."""
    return isinstance(value, bool)


def test_integer(value: Any) -> bool:
    """Test if value is integer."""
    return isinstance(value, int) and not isinstance(value, bool)


def test_float(value: Any) -> bool:
    """Test if value is float."""
    return isinstance(value, float)


def test_string(value: Any) -> bool:
    """Test if value is string."""
    return isinstance(value, str)


def test_mapping(value: Any) -> bool:
    """Test if value is mapping (dict-like)."""
    return isinstance(value, dict) or hasattr(value, "__getitem__")


def test_iterable(value: Any) -> bool:
    """Test if value is iterable."""
    try:
        iter(value)
        return True
    except TypeError:
        return False


def test_sequence(value: Any) -> bool:
    """Test if value is sequence (list-like, but not string)."""
    return isinstance(value, (list, tuple)) or (
        hasattr(value, "__getitem__") and hasattr(value, "__len__") and not isinstance(value, str)
    )


def test_number(value: Any) -> bool:
    """Test if value is number."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def test_odd(value: Any) -> bool:
    """Test if value is odd number."""
    try:
        return int(value) % 2 == 1
    except (ValueError, TypeError):
        return False


def test_even(value: Any) -> bool:
    """Test if value is even number."""
    try:
        return int(value) % 2 == 0
    except (ValueError, TypeError):
        return False


def test_divisibleby(value: Any, num: int) -> bool:
    """Test if value is divisible by num."""
    try:
        return int(value) % int(num) == 0
    except (ValueError, TypeError, ZeroDivisionError):
        return False


def test_sameas(value: Any, other: Any) -> bool:
    """Test if value is same object as other."""
    return value is other


def test_lower(value: str) -> bool:
    """Test if string is lowercase."""
    return isinstance(value, str) and value.islower()


def test_upper(value: str) -> bool:
    """Test if string is uppercase."""
    return isinstance(value, str) and value.isupper()


def test_escaped(value: Any) -> bool:
    """Test if value is HTML escaped."""
    if not isinstance(value, str):
        return False
    return "&lt;" in value or "&gt;" in value or "&amp;" in value or "&#" in value


def test_in(value: Any, container: Any) -> bool:
    """Test if value is in container."""
    try:
        return value in container
    except TypeError:
        return False


# Test function registry
BUILTIN_TESTS: dict[str, Callable[[Any, ...], bool]] = {
    "callable": test_callable,
    "defined": test_defined,
    "undefined": test_undefined,
    "none": test_none,
    "boolean": test_boolean,
    "integer": test_integer,
    "float": test_float,
    "string": test_string,
    "mapping": test_mapping,
    "iterable": test_iterable,
    "sequence": test_sequence,
    "number": test_number,
    "odd": test_odd,
    "even": test_even,
    "divisibleby": test_divisibleby,
    "sameas": test_sameas,
    "lower": test_lower,
    "upper": test_upper,
    "escaped": test_escaped,
    "in": test_in,
}
