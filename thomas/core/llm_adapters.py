"""Provider adapters: a table from a provider name to the function that streams its answer.

A leaf: it imports no Thomas code, so ``llm_transport_pool`` can read it without a cycle. Nothing reads the table yet;
``thomas.core.llm_slot.Models.adapter`` is how a row writes to it, and every write returns its own undo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

#: ``(owner, messages, tools, *, turn_user_content=None)`` -> events, as the built-in provider helpers are called.
ProviderStream = Callable[..., AsyncIterator[Any]]


class _Entry:
    """One registration, compared by identity, so the same function registered twice is two entries."""

    __slots__ = ("stream",)

    def __init__(self, stream: ProviderStream) -> None:
        self.stream = stream


_table: dict[str, list[_Entry]] = {}


def _key(provider: str) -> str:
    return str(provider or "").strip().lower().replace("-", "_")


def register(provider: str, stream: ProviderStream) -> Callable[[], None]:
    """Add *stream* for *provider*, and return the undo.

    The newest one still registered answers. Undoing any one takes only that one away, so an older undo run late never
    removes a newer adapter, and undoing the newest gives back the one before it.
    """
    key = _key(provider)
    if not key:
        raise ValueError("an adapter needs a provider name")
    if not callable(stream):
        raise TypeError("an adapter's stream must be callable")
    entry = _Entry(stream)
    _table.setdefault(key, []).append(entry)

    def undo() -> None:
        entries = _table.get(key, [])
        if entry in entries:
            entries.remove(entry)
        if not entries:
            _table.pop(key, None)

    return undo


def lookup(provider: str) -> ProviderStream | None:
    """The adapter for *provider*, or None when the built-in providers should answer."""
    entries = _table.get(_key(provider))
    return entries[-1].stream if entries else None
