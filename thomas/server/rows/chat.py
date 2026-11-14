"""The Chat routes, as a row that is required: Chat itself, the sessions it keeps, its side routes and deliverables.

Chat is part of how Thomas works, so this row has no off switch. It loads whatever was saved, and every way of turning it
off is refused. What the row does is bring Chat's routes up in the same order the server always did: the session routes,
the plan and slash command routes, the routes for the questions and checklist the model puts to you (a password or
protected file card is answered through the questions route), the deliverable routes, and last the Chat V2 turn routes
with their state.

A part other than Chat V2 that cannot load is logged and left out, and the rest carries on, as it always has. Chat V2 is
the one that must load. When it does not, this row raises and reads ``failed`` with the reason, the server goes on
running, and ``app_routes_init`` puts the 503 answer in the place of ``POST /api/chat`` and marks chat degraded in the
health report. Pressing Try again on the Plugins page runs this again, and its routes then come first. The state Chat V2
makes for itself, and the routes of the parts that did load, are taken back with a failed row, so nothing half made stays.

On shutdown the row stops with the rest: the language model clients Chat kept for its sessions are closed.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)


def _ledger_update_for(app: Any) -> Any:
    """What the session routes call to record a goal: the ledger's ``update``, else its older ``update_session_goal``."""
    from thomas.server.app_keys import APP_TASK_LEDGER

    def record(session_id: str, goal: Any = None, status: Any = None, **kwargs: Any) -> None:
        try:
            ledger = app.get(APP_TASK_LEDGER)
            if not ledger:
                return
            if hasattr(ledger, "update"):
                ledger.update(
                    session_id,
                    active_goal=kwargs.get("active_goal", goal),
                    status=status,
                    missing_inputs=kwargs.get("missing_inputs"),
                    last_progress=kwargs.get("last_progress"),
                    source=str(kwargs.get("source") or ""),
                    force_event=bool(kwargs.get("force_event", False)),
                )
                return
            if hasattr(ledger, "update_session_goal"):
                ledger.update_session_goal(session_id, goal or "", status or "in_progress")
        except (AttributeError, KeyError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            log.debug("Task ledger update failed: %s", exc)

    def compat(
        session_id: str,
        *,
        active_goal: Any = None,
        status: Any = None,
        missing_inputs: Any = None,
        last_progress: Any = None,
        source: str = "",
        force_event: bool = False,
    ) -> None:
        try:
            ledger = app.get(APP_TASK_LEDGER)
            if ledger and hasattr(ledger, "update"):
                ledger.update(
                    session_id,
                    active_goal=active_goal,
                    status=status,
                    missing_inputs=missing_inputs,
                    last_progress=last_progress,
                    source=source,
                    force_event=force_event,
                )
                return
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            # Named, not broad: ledger compat is best-effort bookkeeping.
            log.debug("Task ledger compat update failed: %s", exc)
        record(session_id, active_goal, status or "in_progress")

    return compat


def _register_sessions_and_side_routes(service: Any, view: Any) -> None:
    """The session lifecycle, the plan and slash command routes, then the questions and checklist the model puts to you.

    Each part may be missing without the others.
    """
    if not all(callable(dep) for dep in (service.require_api_access, service.read_json)):
        log.warning("Chat/session route registration skipped: missing runtime dependencies")
        return
    try:
        from thomas.server.routes.sessions_aiohttp import register_sessions_routes

        register_sessions_routes(
            view,
            require_api_access=service.require_api_access,
            read_json=service.read_json,
            task_ledger_update=_ledger_update_for(service.app),
        )
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
        log.warning("Session routes unavailable: %s", exc)

    # Session lifecycle is a core dependency for Chat, Work onboarding, and several automation surfaces. Keep it
    # registered even when an optional chat helper (for example CLI slash-command presentation) is unavailable.
    try:
        from thomas.server.routes.chat_auxiliary import register_chat_auxiliary_routes

        register_chat_auxiliary_routes(view, require_api_access=service.require_api_access)
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
        log.warning("Chat auxiliary routes unavailable: %s", exc)

    # Questions the model asks the person mid-run (the ask_user tool): the page lists what is waiting and posts the answer.
    try:
        from thomas.server.routes.user_questions_routes import setup_user_question_routes

        setup_user_question_routes(view, require_api_access=service.require_api_access)
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
        log.warning("User question routes unavailable: %s", exc)

    try:
        from thomas.server.routes.todo_routes import setup_todo_routes

        setup_todo_routes(view, require_api_access=service.require_api_access)
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError) as exc:
        log.warning("Todo routes unavailable: %s", exc)


def _register_deliverables(service: Any, view: Any) -> None:
    """Serve worker-built deliverables (generated games and apps) for one-click Play."""
    if not callable(service.require_api_access):
        log.warning("Deliverable routes unavailable: missing API access guard")
        return
    try:
        from thomas.server.routes.deliverable_aiohttp import register_deliverable_routes

        register_deliverable_routes(view, require_api_access=service.require_api_access)
    except (ImportError, ModuleNotFoundError, RuntimeError) as exc:
        log.warning("Deliverable routes unavailable: %s", exc)


class _TurnPathsRouter:
    """The view's router for the Chat V2 registrar when the server's 503 answer already holds the two turn paths."""

    def __init__(self, view: Any) -> None:
        self._view = view

    def add_post(self, path: str, handler: Any, **kwargs: Any) -> Any:
        if path in _TURN_PATHS:
            from thomas.server.app_keys import APP_CHAT_TURN_HANDLER

            self._view[APP_CHAT_TURN_HANDLER] = handler
            return None
        return self._view.router.add_post(path, handler, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._view.router, name)


class _HandsOverTheTurnPaths:
    """The view as that registrar sees it. A row may not claim a path the server answers, so on Try again the turn handler
    goes on the app, and the 503 answer hands every request to it. Everything else goes through to the view."""

    def __init__(self, view: Any) -> None:
        self._view = view
        self.router = _TurnPathsRouter(view)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._view, name)

    def __getitem__(self, key: Any) -> Any:
        return self._view[key]

    def __setitem__(self, key: Any, value: Any) -> None:
        self._view[key] = value

    def get(self, key: Any, default: Any = None) -> Any:
        return self._view.get(key, default)


_TURN_PATHS = ("/api/chat", "/api/v2/chat")


def _register_chat_v2(service: Any, view: Any) -> None:
    """The unified V2 chat routes, which the server cannot do without: a failure here is the row's failure."""
    from thomas.server.app_keys import APP_DIAGNOSTICS, APP_MEMORY, APP_TOOLS

    if not callable(service.require_api_access):
        raise RuntimeError("missing API access guard")
    from thomas.server.routes.chat_v2 import register_chat_v2_routes

    held = any(
        route.method == "POST" and route.resource is not None and route.resource.canonical in _TURN_PATHS
        for route in service.app.router.server_routes()
    )
    register_chat_v2_routes(
        _HandsOverTheTurnPaths(view) if held else view,
        config=service.config,
        llm=None,
        memory=service.app.get(APP_MEMORY),
        tools=service.app.get(APP_TOOLS),
        chat_store_dir=service.config.memory.root_path / ".thomas" / "sessions_v2",
        require_api_access=service.require_api_access,
    )
    diagnostics = service.app.get(APP_DIAGNOSTICS)
    if isinstance(diagnostics, dict):
        diagnostics["chat"] = True


class _Chat:
    name = "chat"
    inject = ("web",)
    imports = (
        "thomas.server.routes.chat_v2",
        "thomas.server.routes.sessions_aiohttp",
        "thomas.server.routes.chat_auxiliary",
        "thomas.server.routes.deliverable_aiohttp",
        "thomas.server.routes.user_questions_routes",
        "thomas.server.routes.todo_routes",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        view = service.view(ctx)
        _register_sessions_and_side_routes(service, view)
        _register_deliverables(service, view)
        _register_chat_v2(service, view)


plugin = _Chat()
