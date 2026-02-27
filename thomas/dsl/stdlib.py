"""Standard library functions for DSL."""

import math
import re
from collections.abc import Callable
from typing import Any


class DSLStdlib:
    """Standard library implementation."""

    # Math functions
    @staticmethod
    def sin(x: float) -> float:
        """Sine function."""
        return math.sin(float(x))

    @staticmethod
    def cos(x: float) -> float:
        """Cosine function."""
        return math.cos(float(x))

    @staticmethod
    def tan(x: float) -> float:
        """Tangent function."""
        return math.tan(float(x))

    @staticmethod
    def asin(x: float) -> float:
        """Arcsine function."""
        return math.asin(float(x))

    @staticmethod
    def acos(x: float) -> float:
        """Arccosine function."""
        return math.acos(float(x))

    @staticmethod
    def atan(x: float) -> float:
        """Arctangent function."""
        return math.atan(float(x))

    @staticmethod
    def atan2(y: float, x: float) -> float:
        """Two-argument arctangent."""
        return math.atan2(float(y), float(x))

    @staticmethod
    def sqrt(x: float) -> float:
        """Square root."""
        return math.sqrt(float(x))

    @staticmethod
    def pow(x: float, y: float) -> float:
        """Power function."""
        return pow(float(x), float(y))

    @staticmethod
    def exp(x: float) -> float:
        """Exponential function."""
        return math.exp(float(x))

    @staticmethod
    def log(x: float, base: float = math.e) -> float:
        """Logarithm."""
        return math.log(float(x), float(base))

    @staticmethod
    def log10(x: float) -> float:
        """Base-10 logarithm."""
        return math.log10(float(x))

    @staticmethod
    def log2(x: float) -> float:
        """Base-2 logarithm."""
        return math.log2(float(x))

    @staticmethod
    def abs(x: Any) -> Any:
        """Absolute value."""
        return abs(x)

    @staticmethod
    def floor(x: float) -> int:
        """Floor function."""
        return math.floor(float(x))

    @staticmethod
    def ceil(x: float) -> int:
        """Ceiling function."""
        return math.ceil(float(x))

    @staticmethod
    def round(x: float, ndigits: int = 0) -> float:
        """Round function."""
        return round(float(x), ndigits)

    @staticmethod
    def sign(x: float) -> int:
        """Sign of number (-1, 0, 1)."""
        x = float(x)
        if x > 0:
            return 1
        elif x < 0:
            return -1
        else:
            return 0

    # String functions
    @staticmethod
    def len(obj: Any) -> int:
        """Length of object."""
        return len(obj)

    @staticmethod
    def upper(s: str) -> str:
        """Convert to uppercase."""
        return str(s).upper()

    @staticmethod
    def lower(s: str) -> str:
        """Convert to lowercase."""
        return str(s).lower()

    @staticmethod
    def strip(s: str, chars: str | None = None) -> str:
        """Strip whitespace."""
        return str(s).strip(chars)

    @staticmethod
    def lstrip(s: str, chars: str | None = None) -> str:
        """Strip left whitespace."""
        return str(s).lstrip(chars)

    @staticmethod
    def rstrip(s: str, chars: str | None = None) -> str:
        """Strip right whitespace."""
        return str(s).rstrip(chars)

    @staticmethod
    def split(s: str, sep: str | None = None) -> list[str]:
        """Split string."""
        return str(s).split(sep)

    @staticmethod
    def join(iterable: list[str], sep: str = "") -> str:
        """Join strings."""
        return sep.join(str(item) for item in iterable)

    @staticmethod
    def replace(s: str, old: str, new: str) -> str:
        """Replace substring."""
        return str(s).replace(old, new)

    @staticmethod
    def contains(s: str, substr: str) -> bool:
        """Check if substring exists."""
        return substr in str(s)

    @staticmethod
    def startswith(s: str, prefix: str) -> bool:
        """Check if starts with prefix."""
        return str(s).startswith(prefix)

    @staticmethod
    def endswith(s: str, suffix: str) -> bool:
        """Check if ends with suffix."""
        return str(s).endswith(suffix)

    @staticmethod
    def find(s: str, substr: str, start: int = 0) -> int:
        """Find substring position."""
        return str(s).find(substr, start)

    @staticmethod
    def count(s: str, substr: str) -> int:
        """Count substring occurrences."""
        return str(s).count(substr)

    @staticmethod
    def reverse(s: str) -> str:
        """Reverse string."""
        return str(s)[::-1]

    @staticmethod
    def repeat(s: str, count: int) -> str:
        """Repeat string."""
        return str(s) * int(count)

    @staticmethod
    def matches(s: str, pattern: str) -> bool:
        """Check if regex matches."""
        return bool(re.search(pattern, str(s)))

    # List functions
    @staticmethod
    def append(lst: list[Any], item: Any) -> list[Any]:
        """Append item to list."""
        lst.append(item)
        return lst

    @staticmethod
    def extend(lst: list[Any], items: list[Any]) -> list[Any]:
        """Extend list."""
        lst.extend(items)
        return lst

    @staticmethod
    def insert(lst: list[Any], index: int, item: Any) -> list[Any]:
        """Insert item in list."""
        lst.insert(int(index), item)
        return lst

    @staticmethod
    def remove(lst: list[Any], item: Any) -> list[Any]:
        """Remove item from list."""
        lst.remove(item)
        return lst

    @staticmethod
    def pop(lst: list[Any], index: int = -1) -> Any:
        """Pop item from list."""
        return lst.pop(int(index))

    @staticmethod
    def clear(lst: list[Any]) -> list[Any]:
        """Clear list."""
        lst.clear()
        return lst

    @staticmethod
    def sort(lst: list[Any]) -> list[Any]:
        """Sort list."""
        lst.sort()
        return lst

    @staticmethod
    def reverse_list(lst: list[Any]) -> list[Any]:
        """Reverse list."""
        lst.reverse()
        return lst

    @staticmethod
    def index(lst: list[Any], item: Any, start: int = 0) -> int:
        """Find index of item."""
        return lst.index(item, int(start))

    @staticmethod
    def count_list(lst: list[Any], item: Any) -> int:
        """Count occurrences in list."""
        return lst.count(item)

    @staticmethod
    def sum(lst: list[Any], start: Any = 0) -> Any:
        """Sum list items."""
        return sum(lst, start)

    @staticmethod
    def min(lst: list[Any]) -> Any:
        """Minimum item."""
        return min(lst)

    @staticmethod
    def max(lst: list[Any]) -> Any:
        """Maximum item."""
        return max(lst)

    @staticmethod
    def all(lst: list[Any]) -> bool:
        """All items truthy."""
        return all(lst)

    @staticmethod
    def any(lst: list[Any]) -> bool:
        """Any item truthy."""
        return any(lst)

    # Type functions
    @staticmethod
    def type_name(obj: Any) -> str:
        """Get type name."""
        return type(obj).__name__

    @staticmethod
    def is_int(obj: Any) -> bool:
        """Check if integer."""
        return isinstance(obj, int)

    @staticmethod
    def is_float(obj: Any) -> bool:
        """Check if float."""
        return isinstance(obj, float)

    @staticmethod
    def is_str(obj: Any) -> bool:
        """Check if string."""
        return isinstance(obj, str)

    @staticmethod
    def is_bool(obj: Any) -> bool:
        """Check if boolean."""
        return isinstance(obj, bool)

    @staticmethod
    def is_list(obj: Any) -> bool:
        """Check if list."""
        return isinstance(obj, list)

    @staticmethod
    def is_dict(obj: Any) -> bool:
        """Check if dict."""
        return isinstance(obj, dict)

    @staticmethod
    def is_none(obj: Any) -> bool:
        """Check if None."""
        return obj is None

    # Conversion functions
    @staticmethod
    def to_int(obj: Any) -> int:
        """Convert to integer."""
        return int(obj)

    @staticmethod
    def to_float(obj: Any) -> float:
        """Convert to float."""
        return float(obj)

    @staticmethod
    def to_str(obj: Any) -> str:
        """Convert to string."""
        return str(obj)

    @staticmethod
    def to_bool(obj: Any) -> bool:
        """Convert to boolean."""
        if obj is None or obj is False:
            return False
        if obj == 0 or obj == "" or obj == [] or obj == {}:
            return False
        return True

    # IO functions
    @staticmethod
    def print(*args: Any) -> None:
        """Print function."""
        print(*args)

    @staticmethod
    def print_ln(*args: Any) -> None:
        """Print with newline."""
        print(*args)

    # Range and iteration
    @staticmethod
    def range_fn(start: int, stop: int | None = None, step: int = 1) -> list[int]:
        """Generate range."""
        if stop is None:
            return list(range(int(start)))
        return list(range(int(start), int(stop), int(step)))

    @staticmethod
    def enumerate_fn(lst: list[Any]) -> list[tuple]:
        """Enumerate list."""
        return list(enumerate(lst))

    @staticmethod
    def zip_fn(*lists: list[Any]) -> list[tuple]:
        """Zip lists."""
        return list(zip(*lists))

    # Functional operations
    @staticmethod
    def map_fn(func: Callable, lst: list[Any]) -> list[Any]:
        """Map function over list."""
        return [func(item) for item in lst]

    @staticmethod
    def filter_fn(func: Callable, lst: list[Any]) -> list[Any]:
        """Filter list."""
        return [item for item in lst if func(item)]

    @staticmethod
    def reduce_fn(func: Callable, lst: list[Any], initial: Any | None = None) -> Any:
        """Reduce list."""
        from functools import reduce

        if initial is None:
            return reduce(func, lst)
        return reduce(func, lst, initial)

    # Assertions and testing
    @staticmethod
    def assert_true(condition: bool, msg: str = "Assertion failed") -> None:
        """Assert condition is true."""
        if not condition:
            raise AssertionError(msg)

    @staticmethod
    def assert_false(condition: bool, msg: str = "Assertion failed") -> None:
        """Assert condition is false."""
        if condition:
            raise AssertionError(msg)

    @staticmethod
    def assert_equal(a: Any, b: Any, msg: str = "Assertion failed") -> None:
        """Assert values are equal."""
        if a != b:
            raise AssertionError(f"{msg}: {a} != {b}")

    @staticmethod
    def assert_not_equal(a: Any, b: Any, msg: str = "Assertion failed") -> None:
        """Assert values are not equal."""
        if a == b:
            raise AssertionError(f"{msg}: {a} == {b}")
