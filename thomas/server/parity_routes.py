"""Frontier-parity route registrations, kept out of app_core for the size guard.

Each block registers one surface built on 2026-09-05 and reports a boolean
into the boot diagnostics under its own key: questions the model asks the
person (ask_user), chat export, scheduled tasks with their executor, and
thumbs feedback on replies.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web


def register_parity_routes(
    app: web.Application,
    *,
    config: Any,
    require_api_access: Callable[[web.Request], Any],
    log: Any,
) -> dict[str, bool]:
    _diagnostics: dict[str, bool] = {}
    _require_api_access = require_api_access
    # Questions the model asks the person mid-run (the ask_user tool): the
    # page lists what is waiting and posts the answer here.
    _questions_ok = False
    try:
        from thomas.server.routes.user_questions_routes import setup_user_question_routes

        setup_user_question_routes(app, require_api_access=_require_api_access)
        _questions_ok = True
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
        log.warning("User question routes unavailable: %s", e)
    _diagnostics["user_questions"] = _questions_ok

    # A chat can leave Thomas as a Markdown or JSON file the person owns.
    _export_ok = False
    try:
        from thomas.server.routes.todo_routes import setup_todo_routes

        setup_todo_routes(app, require_api_access=_require_api_access)
        _diagnostics["todos"] = True
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError) as e:
        log.warning("Todo routes unavailable: %s", e)
        _diagnostics["todos"] = False

    try:
        from thomas.server.routes.chat_export_routes import setup_chat_export_routes

        setup_chat_export_routes(
            app,
            sessions_dir=Path(config.memory.root_path) / ".thomas" / "sessions_v2",
            require_api_access=_require_api_access,
        )
        _export_ok = True
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, AttributeError, TypeError) as e:
        log.warning("Chat export routes unavailable: %s", e)
    _diagnostics["chat_export"] = _export_ok

    # Resting model profiles (a 429 parks one for a while): the page shows a
    # countdown instead of a generic error with no end in sight.
    try:
        from thomas.server.routes.cooldown_routes import setup_cooldown_routes

        setup_cooldown_routes(app, require_api_access=_require_api_access)
        _diagnostics["cooldowns"] = True
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError) as e:
        log.warning("Cooldown routes unavailable: %s", e)
        _diagnostics["cooldowns"] = False

    # A chat can be branched into a new chat from the sidebar (ChatGPT and
    # Claude.ai branch from a message); the copy keeps the first N messages.
    try:
        from thomas.server.routes.chat_branch_routes import setup_chat_branch_routes

        setup_chat_branch_routes(
            app,
            sessions_dir=Path(config.memory.root_path) / ".thomas" / "sessions_v2",
            require_api_access=_require_api_access,
        )
        _diagnostics["chat_branch"] = True
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, AttributeError, TypeError) as e:
        log.warning("Chat branch routes unavailable: %s", e)
        _diagnostics["chat_branch"] = False

    # Scheduled tasks get a page, not only the `thomas cron` CLI, and an
    # executor: until 2026-09-05 nothing ever ran a saved schedule.
    _schedules_ok = False
    try:
        from thomas.core.schedule_executor import install_scheduler
        from thomas.server.routes.schedule_routes import setup_schedule_routes

        scheduler = install_scheduler(data_dir=Path(config.memory.root_path), auto_start=True, app=app)
        setup_schedule_routes(app, scheduler=scheduler, require_api_access=_require_api_access)
        _schedules_ok = True
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, AttributeError, TypeError) as e:
        log.warning("Schedule routes unavailable: %s", e)
    _diagnostics["schedules"] = _schedules_ok

    # Thumbs up or down on a reply, kept for self-review.
    _feedback_ok = False
    try:
        from thomas.server.routes.chat_feedback_routes import setup_chat_feedback_routes

        setup_chat_feedback_routes(
            app,
            store_path=Path(config.memory.root_path) / ".thomas" / "feedback.jsonl",
            require_api_access=_require_api_access,
        )
        _feedback_ok = True
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, AttributeError, TypeError) as e:
        log.warning("Chat feedback routes unavailable: %s", e)
    _diagnostics["chat_feedback"] = _feedback_ok

    # Image, video, and music creation run outside the request loop, publish their
    # output through the normal deliverable service, and therefore appear in Library.
    try:
        from thomas.server.routes.media_generation_routes import setup_media_generation_routes

        setup_media_generation_routes(
            app,
            data_root=Path(config.memory.root_path),
            require_api_access=_require_api_access,
        )
        _diagnostics["media_generation"] = True
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError) as e:
        log.warning("Media generation routes unavailable: %s", e)
        _diagnostics["media_generation"] = False

    # Settings' Export logs button has probed HEAD /api/logs/export since the settings
    # script was split; until now nothing served it (a 404 on every settings load).
    try:
        import os

        from thomas.server.routes.logs_export_routes import setup_logs_export_routes

        log_file = str(os.environ.get("THOMAS_LOG_FILE") or "").strip()
        logs_dir = Path(log_file).parent if log_file else Path(config.memory.root_path) / "logs"
        setup_logs_export_routes(app, logs_dir=logs_dir, require_api_access=_require_api_access)
        _diagnostics["logs_export"] = True
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError) as e:
        log.warning("Log export route unavailable: %s", e)
        _diagnostics["logs_export"] = False
    return _diagnostics


__all__ = ["register_parity_routes"]
