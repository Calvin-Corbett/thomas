"""A lending slot and damage exception that readers can import without loading the journal.

No journals are lent by default. :func:`lend` installs a caller-supplied object and returns a callback that takes
back only that particular loan, without clearing a newer loan. :class:`JournalDamaged` lives here so a reader can
catch it without importing the journal implementation. Plugin-row and hand-in integration are separate work.

Spec: docs/superpowers/specs/2026-11-04-durable-thomas-design.md section 1.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class JournalDamaged(OSError):
    """A complete journal record is unreadable or exceeds the record size limit."""


_lent: tuple[Any] | None = None


def lend(journals: Any) -> Callable[[], None]:
    """Make *journals* what every reader gets from :func:`lent`, until the returned call is made."""
    global _lent
    mine = (journals,)
    _lent = mine

    def take_back() -> None:
        global _lent
        if _lent is mine:
            _lent = None

    return take_back


def lent() -> Any | None:
    """The journals the row lent, or None while it is off."""
    held = _lent
    return held[0] if held is not None else None


__all__ = ["JournalDamaged", "lend", "lent"]
