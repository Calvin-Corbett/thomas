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

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

log = logging.getLogger(__name__)

_CURRENT: ContextVar[str] = ContextVar("thomas_session_id", default="")


def active_session_id() -> str:
    """The session bound around the running tool call, or "" outside one."""
    return _CURRENT.get()


_RUN: ContextVar[str] = ContextVar("thomas_tool_run_id", default="")
_TOOL_STATE: ContextVar[dict[object, object] | None] = ContextVar("thomas_tool_run_state", default=None)
_RUN_BINDINGS: ContextVar[tuple[tuple[str, object | None, dict[object, object]], ...]] = ContextVar(
    "thomas_tool_run_bindings", default=()
)


def active_tool_state() -> dict[object, object] | None:
    """Return runner-owned state shared by tool calls in the current run."""
    return _TOOL_STATE.get()


def active_run_id() -> str:
    """Return the runner-bound run id, or empty outside the agent runner."""
    return _RUN.get()


@contextmanager
def bind_session(session_id: str, *, run_id: str = "", run_owner: object | None = None) -> Iterator[None]:
    run_id = str(run_id or "").strip()
    bindings = _RUN_BINDINGS.get()
    tool_state = _TOOL_STATE.get()
    owner_state = getattr(run_owner, "_tool_run_state", None) if run_owner is not None else None
    restore_owner = run_owner is not None and any(owner is run_owner for _, owner, _ in bindings)
    next_bindings = bindings
    if run_id:
        tool_state = next(
            (state for run, owner, state in reversed(bindings) if run == run_id and owner is run_owner), None
        )
        if tool_state is None and owner_state is not None and owner_state[0] == run_id:
            tool_state = owner_state[1]
        if tool_state is None:
            tool_state = {}
        if run_owner is not None:
            run_owner._tool_run_state = (run_id, tool_state)
        next_bindings = (*bindings, (run_id, run_owner, tool_state))
    else:
        run_id = _RUN.get()
    token = _CURRENT.set(str(session_id or "").strip())
    run_token = _RUN.set(run_id)
    state_token = _TOOL_STATE.set(tool_state)
    bindings_token = _RUN_BINDINGS.set(next_bindings)
    try:
        yield
    finally:
        if restore_owner:
            run_owner._tool_run_state = owner_state
        _RUN_BINDINGS.reset(bindings_token)
        _TOOL_STATE.reset(state_token)
        _RUN.reset(run_token)
        _CURRENT.reset(token)


# The chat a piece of work belongs to, which is not always the session a tool
# call runs under. A background worker binds its own per-attempt id
# ("exec-<id>-attempt-1") for budget scoping, so a card filed under that id
# belongs to a chat nobody is looking at: the page asks for its own chat's
# cards and sees none. The worker sets this to the chat that started the work.
_CHAT: ContextVar[str] = ContextVar("thomas_chat_session_id", default="")


def set_chat(session_id: str) -> None:
    """Name the chat this work belongs to, for the rest of this context."""
    _CHAT.set(str(session_id or "").strip())


def active_chat_id() -> str:
    """The chat to show a card in: the owning chat, else the bound session."""
    return _CHAT.get() or _CURRENT.get()


def set_chat_from_execution(execution_id: str) -> None:
    """Bind the chat that started a background run, read from its own record.

    A worker knows its execution id; the record knows which chat asked for the
    work. Quiet on failure: a card that cannot find its chat still shows in the
    session the run is bound to, which is better than taking the run down.
    """
    if not str(execution_id or "").strip():
        return
    try:
        from thomas.core import task_bot_runtime
        from thomas.core.project_root import coordination_root

        for workspace in ("project", "isolated"):
            row = task_bot_runtime.get_execution(str(execution_id), coordination_root(None, workspace)) or {}
            # The record names the chat "conversation_id"; a background execution
            # carries no "session_id" at all. Reading only that name found nothing,
            # so cards were filed under the run's own per-attempt id, where no page
            # looks (observed live 2026-09-22: a card waited ten minutes unseen).
            chat = next(
                (
                    str(row.get(key) or "").strip()
                    for key in ("session_id", "conversation_id", "thread_id")
                    if str(row.get(key) or "").strip()
                ),
                "",
            )
            if chat:
                set_chat(chat)
                return
    except (ImportError, OSError, RuntimeError, TypeError, ValueError, KeyError):
        log.debug("could not resolve the chat for execution %s", execution_id, exc_info=True)


__all__ = [
    "active_chat_id",
    "active_run_id",
    "active_session_id",
    "active_tool_state",
    "bind_session",
    "set_chat",
    "set_chat_from_execution",
]
