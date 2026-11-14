"""Optional settings discovery supplied by the running settings plugin."""

from __future__ import annotations

from typing import Any

_provider: Any = None


def provider() -> Any:
    return _provider


def install(value: Any) -> None:
    global _provider
    _provider = value


def remove(value: Any) -> None:
    global _provider
    if _provider is value:
        _provider = None
