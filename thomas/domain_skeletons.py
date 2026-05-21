"""Shared helpers for intentionally scoped but incomplete domain modules.

These helpers allow domain packages to remain importable during staged
implementation without causing import-time crashes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _make_placeholder_exception(name: str, module_name: str) -> type[Exception]:
    cls = type(name, (Exception,), {})
    cls.__module__ = module_name
    cls.__doc__ = f"SKELETON: `{module_name}.{name}` is a planned domain exception and is not fully implemented yet."
    return cls


def _make_placeholder_class(name: str, module_name: str) -> type[Any]:
    def _init(self: Any, *args: Any, **kwargs: Any) -> None:
        if args:
            self._args = args
        for key, value in kwargs.items():
            setattr(self, key, value)

    cls = type(name, (object,), {"__init__": _init})
    cls.__module__ = module_name
    cls.__doc__ = f"SKELETON: `{module_name}.{name}` is a planned domain type and is not fully implemented yet."
    return cls


def _make_placeholder_function(name: str, module_name: str) -> Callable[..., Any]:
    def _placeholder(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(f"SKELETON: `{module_name}.{name}` is planned but not implemented yet.")

    _placeholder.__name__ = name
    _placeholder.__module__ = module_name
    _placeholder.__doc__ = f"SKELETON: `{module_name}.{name}` is a planned callable and is not fully implemented yet."
    return _placeholder


def make_module_getattr(module_name: str) -> Callable[[str], Any]:
    """Return a ``__getattr__`` implementation for skeleton modules.

    Rules:
    - `*Error` / `*Exception` names become Exception subclasses.
    - lowercase names become placeholder callables.
    - all other names become lightweight placeholder classes.
    """

    cache: dict[str, Any] = {}

    def _resolve(name: str) -> Any:
        if name in cache:
            return cache[name]

        if name.endswith("Error") or name.endswith("Exception"):
            value = _make_placeholder_exception(name, module_name)
        elif name and name[0].islower():
            value = _make_placeholder_function(name, module_name)
        else:
            value = _make_placeholder_class(name, module_name)

        cache[name] = value
        return value

    return _resolve
