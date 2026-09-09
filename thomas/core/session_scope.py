"""The chat session a tool call runs for, bound by the runner, never by the model.

``ask_user`` and ``todo.write`` file their rows under this id so the page can
show one chat's questions and checklist and no other's. The first version
read ``_session_id`` from the model's arguments: forgeable, and never sent,
so every row was unscoped and every panel saw all of them (codex, 2026-09-05).

The tool runner wraps each tool execution in ``bind_session(session_id)``;
tools call ``active_session_id()``. A headless run binds nothing and its rows
stay session-less, which the console answerer handles on purpose.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_CURRENT: ContextVar[str] = ContextVar("thomas_session_id", default="")


def active_session_id() -> str:
    """The session bound around the running tool call, or "" outside one."""
    return _CURRENT.get()


@contextmanager
def bind_session(session_id: str) -> Iterator[None]:
    token = _CURRENT.set(str(session_id or "").strip())
    try:
        yield
    finally:
        _CURRENT.reset(token)


__all__ = ["active_session_id", "bind_session"]
