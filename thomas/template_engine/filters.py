"""Built-in template filters."""

from __future__ import annotations

import html
import math
import random
import re
import textwrap
import urllib.parse
from collections.abc import Callable
from typing import Any


def abs_filter(value: int | float) -> int | float:
    """Return absolute value."""
    return abs(value)


def batch(value: list[Any], size: int, fill_with: Any = None) -> list[list[Any]]:
    """Batch items into lists of size."""
    result = []
    for i in range(0, len(value), size):
        batch_list = list(value[i : i + size])
        if fill_with is not None and len(batch_list) < size:
            batch_list.extend([fill_with] * (size - len(batch_list)))
        result.append(batch_list)
    return result


def capitalize(value: str) -> str:
    """Capitalize first letter."""
    return value.capitalize() if value else ""


def center(value: str, width: int, fillchar: str = " ") -> str:
    """Center string in field of given width."""
    return value.center(width, fillchar)


def default(value: Any, default_value: Any = "", boolean: bool = False) -> Any:
    """Return value or default if undefined/false."""
    if boolean:
        return value if value else default_value
    return value if value is not None and value != "" else default_value


def dictsort(value: dict[str, Any], case_sensitive: bool = False, by: str = "key") -> list[tuple[str, Any]]:
    """Sort dict by keys or values."""
    if by == "value":
        return sorted(
            value.items(),
            key=lambda x: x[1],
            reverse=False,
        )
    reverse = case_sensitive
    return sorted(value.items(), key=lambda x: x[0] if case_sensitive else x[0].lower())


def escape(value: str) -> str:
    """HTML escape string."""
    return html.escape(value)


def filesizeformat(value: int | float, binary: bool = False) -> str:
    """Format value as file size."""
    units = ["B", "KB", "MB", "GB", "TB"]
    if binary:
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        divisor = 1024
    else:
        divisor = 1000

    abs_value = abs(value)
    for unit in units:
        if abs_value < divisor:
            return f"{value:.1f}{unit}"
        value /= divisor

    return f"{value:.1f}PB"


def first(value: str | list[Any]) -> Any:
    """Return first element."""
    try:
        return value[0] if value else None
    except (IndexError, TypeError):
        return None


def float_filter(value: Any) -> float:
    """Convert to float."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def forceescape(value: str) -> str:
    """Force HTML escape."""
    return html.escape(str(value))


def format_str(value: str, *args: Any, **kwargs: Any) -> str:
    """Format string using arguments."""
    try:
        return value.format(*args, **kwargs)
    except (IndexError, KeyError):
        return value


def groupby(value: list[Any], attribute: str) -> dict[str, list[Any]]:
    """Group items by attribute."""
    result: dict[str, list[Any]] = {}
    for item in value:
        if isinstance(item, dict):
            key = item.get(attribute)
        else:
            key = getattr(item, attribute, None)

        if key not in result:
            result[key] = []
        result[key].append(item)

    return result


def indent(value: str, width: int = 4, first: bool = False) -> str:
    """Indent string."""
    indent_str = " " * width
    lines = value.split("\n")
    start = 0 if first else 1
    for i in range(start, len(lines)):
        lines[i] = indent_str + lines[i]
    return "\n".join(lines)


def int_filter(value: Any) -> int:
    """Convert to integer."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def join(value: list[Any], sep: str = "", attribute: str | None = None) -> str:
    """Join list into string."""
    if attribute:
        items = []
        for item in value:
            if isinstance(item, dict):
                items.append(str(item.get(attribute, "")))
            else:
                items.append(str(getattr(item, attribute, "")))
        return sep.join(items)
    return sep.join(str(item) for item in value)


def last(value: str | list[Any]) -> Any:
    """Return last element."""
    try:
        return value[-1] if value else None
    except (IndexError, TypeError):
        return None


def length(value: Any) -> int:
    """Return length of value."""
    try:
        return len(value)
    except TypeError:
        return 0


def list_filter(value: Any) -> list[Any]:
    """Convert to list."""
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, str):
        return list(value)
    try:
        return list(value)
    except TypeError:
        return [value]


def lower(value: str) -> str:
    """Convert to lowercase."""
    return value.lower()


def map_filter(value: list[Any], name: str, *args: Any) -> list[Any]:
    """Map function over items."""
    # Simplified implementation
    result = []
    for item in value:
        if isinstance(item, dict):
            result.append(item.get(name))
        else:
            result.append(getattr(item, name, None))
    return result


def max_filter(value: list[Any] | str) -> Any:
    """Return maximum value."""
    try:
        return max(value)
    except (ValueError, TypeError):
        return None


def min_filter(value: list[Any] | str) -> Any:
    """Return minimum value."""
    try:
        return min(value)
    except (ValueError, TypeError):
        return None


def pprint(value: Any, verbose: bool = False) -> str:
    """Pretty print value."""
    import pprint as pp

    return pp.pformat(value)


def random_filter(value: list[Any]) -> Any:
    """Return random item from list."""
    return random.choice(value) if value else None


def reject(value: list[Any], test: str, *args: Any) -> list[Any]:
    """Filter items failing test."""
    # Simplified - would need test function reference
    return value


def rejectattr(value: list[Any], attribute: str, test: Any = None) -> list[Any]:
    """Filter items where attribute fails test."""
    result = []
    for item in value:
        if isinstance(item, dict):
            attr_val = item.get(attribute)
        else:
            attr_val = getattr(item, attribute, None)

        if test is None:
            if not attr_val:
                result.append(item)
        elif attr_val != test:
            result.append(item)

    return result


def replace(value: str, old: str, new: str, count: int | None = None) -> str:
    """Replace substring."""
    if count is None:
        return value.replace(old, new)
    return value.replace(old, new, count)


def reverse(value: str | list[Any]) -> str | list[Any]:
    """Reverse value."""
    if isinstance(value, str):
        return value[::-1]
    return list(reversed(value))


def round_filter(value: int | float, precision: int = 0, method: str = "common") -> int | float:
    """Round number."""
    if method == "ceil":
        return math.ceil(value * (10**precision)) / (10**precision)
    elif method == "floor":
        return math.floor(value * (10**precision)) / (10**precision)
    return round(value, precision)


def safe(value: str) -> str:
    """Mark string as safe (no escaping)."""
    safe_str = value
    safe_str._safe = True  # type: ignore
    return safe_str


def select(value: list[Any], test: str, *args: Any) -> list[Any]:
    """Filter items passing test."""
    # Simplified - would need test function reference
    return value


def selectattr(value: list[Any], attribute: str, test: Any = None) -> list[Any]:
    """Filter items where attribute passes test."""
    result = []
    for item in value:
        if isinstance(item, dict):
            attr_val = item.get(attribute)
        else:
            attr_val = getattr(item, attribute, None)

        if test is None:
            if attr_val:
                result.append(item)
        elif attr_val == test:
            result.append(item)

    return result


def slice_filter(value: list[Any], slices: int, fill_with: Any = None) -> list[list[Any]]:
    """Slice list into n slices."""
    result = []
    slice_size = (len(value) + slices - 1) // slices
    for i in range(slices):
        start = i * slice_size
        end = min(start + slice_size, len(value))
        slice_items = list(value[start:end])
        if fill_with is not None and len(slice_items) < slice_size:
            slice_items.extend([fill_with] * (slice_size - len(slice_items)))
        result.append(slice_items)
    return result


def sort(value: list[Any], reverse: bool = False, attribute: str | None = None) -> list[Any]:
    """Sort list."""
    if attribute:
        return sorted(
            value,
            reverse=reverse,
            key=lambda x: getattr(x, attribute, None) if not isinstance(x, dict) else x.get(attribute),
        )
    return sorted(value, reverse=reverse)


def string(value: Any) -> str:
    """Convert to string."""
    return str(value)


def striptags(value: str) -> str:
    """Remove HTML tags."""
    return re.sub(r"<[^>]+>", "", value)


def sum_filter(value: list[int | float], start: int | float = 0) -> int | float:
    """Sum list items."""
    return sum(value, start)


def title(value: str) -> str:
    """Convert to title case."""
    return value.title()


def trim(value: str) -> str:
    """Strip whitespace."""
    return value.strip()


def truncate(value: str, length: int = 255, killwords: bool = False, end: str = "...") -> str:
    """Truncate string to length."""
    if len(value) <= length:
        return value

    if killwords:
        return value[:length] + end

    # Truncate at word boundary
    truncated = value[: length - len(end)]
    last_space = truncated.rfind(" ")
    if last_space > length // 2:
        truncated = truncated[:last_space]

    return truncated + end


def unique(value: list[Any], attribute: str | None = None) -> list[Any]:
    """Return unique items."""
    if attribute:
        seen = set()
        result = []
        for item in value:
            if isinstance(item, dict):
                key = item.get(attribute)
            else:
                key = getattr(item, attribute, None)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    seen = set()
    result = []
    for item in value:
        # Handle unhashable types
        try:
            if item not in seen:
                seen.add(item)
                result.append(item)
        except TypeError:
            if item not in result:
                result.append(item)
    return result


def upper(value: str) -> str:
    """Convert to uppercase."""
    return value.upper()


def urlencode(value: dict[str, Any]) -> str:
    """URL encode dict."""
    return urllib.parse.urlencode(value)


def urlize(value: str, target: str | None = None) -> str:
    """Convert URLs to links."""
    url_pattern = r"https?://[^\s]+"
    if target:
        replacement = f'<a href="\\g<0>" target="{target}">\\g<0></a>'
    else:
        replacement = '<a href="\\g<0>">\\g<0></a>'
    return re.sub(url_pattern, replacement, value)


def wordcount(value: str) -> int:
    """Count words."""
    return len(value.split())


def wordwrap(value: str, width: int = 79, break_long_words: bool = True, wrapstr: str = "\n") -> str:
    """Wrap text."""
    if break_long_words:
        return textwrap.fill(value, width=width)
    return textwrap.fill(value, width=width, break_long_words=False)


def xmlattr(value: dict[str, Any]) -> str:
    """Convert dict to XML attributes."""
    items = []
    for key, val in value.items():
        items.append(f'{key}="{html.escape(str(val))}"')
    return " ".join(items)


# Filter registry
BUILTIN_FILTERS: dict[str, Callable[..., Any]] = {
    "abs": abs_filter,
    "batch": batch,
    "capitalize": capitalize,
    "center": center,
    "default": default,
    "dictsort": dictsort,
    "escape": escape,
    "filesizeformat": filesizeformat,
    "first": first,
    "float": float_filter,
    "forceescape": forceescape,
    "format": format_str,
    "groupby": groupby,
    "indent": indent,
    "int": int_filter,
    "join": join,
    "last": last,
    "length": length,
    "list": list_filter,
    "lower": lower,
    "map": map_filter,
    "max": max_filter,
    "min": min_filter,
    "pprint": pprint,
    "random": random_filter,
    "reject": reject,
    "rejectattr": rejectattr,
    "replace": replace,
    "reverse": reverse,
    "round": round_filter,
    "safe": safe,
    "select": select,
    "selectattr": selectattr,
    "slice": slice_filter,
    "sort": sort,
    "string": string,
    "striptags": striptags,
    "sum": sum_filter,
    "title": title,
    "trim": trim,
    "truncate": truncate,
    "unique": unique,
    "upper": upper,
    "urlencode": urlencode,
    "urlize": urlize,
    "wordcount": wordcount,
    "wordwrap": wordwrap,
    "xmlattr": xmlattr,
}
