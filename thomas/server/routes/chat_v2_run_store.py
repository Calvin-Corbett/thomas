"""Best-effort Mission Control run persistence for Chat V2."""

from __future__ import annotations

import asyncio
import logging
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from thomas import __version__ as THOMAS_VERSION
from thomas.server.app_keys import APP_RUN_STORE_ENABLED, APP_RUN_STORE_MODULE

log = logging.getLogger(__name__)

_RUN_STORE_ERRORS = (AttributeError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError)
_PERSISTENCE_START_ERROR = "chat run persistence failed to start"
_PERSISTENCE_EVENT_ERROR = "chat run event persistence failed"


@dataclass(slots=True)
class ChatV2RunRecorder:
    """Own one run-store writer without making persistence a chat dependency."""

    run_id: str
    module: Any = None
    writer: Any = None
    persistence_failed: bool = False
    writer_closed: bool = False
    finished: bool = False

    def record(self, event: dict[str, Any]) -> None:
        if self.writer is None or self.persistence_failed or self.writer_closed or self.finished:
            return
        try:
            self.writer.record(event)
        except _RUN_STORE_ERRORS as exc:
            self.persistence_failed = True
            log.warning("Chat V2 run event persistence failed: %s", exc)

    def finish(self, *, ok: bool, usage: dict[str, Any] | None = None) -> None:
        if self.module is None or self.finished:
            return
        persistence_ok = not self.persistence_failed
        if self.writer is not None and not self.writer_closed:
            try:
                self.writer.close()
            except _RUN_STORE_ERRORS as exc:
                persistence_ok = False
                self.persistence_failed = True
                log.warning("Chat V2 run writer close failed: %s", exc)
            finally:
                self.writer_closed = True
        final_ok = bool(ok and persistence_ok)
        error = None if final_ok else (_PERSISTENCE_EVENT_ERROR if not persistence_ok else "chat turn failed")
        try:
            self.module.finalize_run(
                self.run_id,
                ok=final_ok,
                error=error,
                iterations=None,
                tool_calls=None,
                usage=usage,
            )
        except _RUN_STORE_ERRORS as exc:
            log.warning("Chat V2 run finalization failed: %s", exc)
            return
        self.finished = True


@dataclass(slots=True)
class ChatV2RunLifecycle:
    """Finalize a Chat V2 run even when the request task is cancelled."""

    recorder: ChatV2RunRecorder
    usage: Callable[[], dict[str, Any] | None]
    launcher_task: asyncio.Task[Any] | None = None
    finished: bool = False

    def __post_init__(self) -> None:
        task = asyncio.current_task()
        if task is not None:
            task.add_done_callback(self._on_handler_done)

    def track_launcher(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        self.launcher_task = task
        return task

    def finish(self, *, ok: bool) -> None:
        if self.finished:
            return
        self.finished = True
        if not ok and self.launcher_task is not None and not self.launcher_task.done():
            self.launcher_task.cancel()
        self.recorder.finish(ok=ok, usage=self.usage())

    def _on_handler_done(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            self.finish(ok=False)


def start_chat_v2_run(
    app: Any,
    *,
    session_id: str,
    profile: str,
    model_id: str,
    mode: str,
    autonomy_level: int,
) -> ChatV2RunRecorder:
    """Start a run when the optional run store is available; otherwise no-op."""
    run_id = secrets.token_urlsafe(10)
    module = app.get(APP_RUN_STORE_MODULE)
    if not bool(app.get(APP_RUN_STORE_ENABLED, False)) or module is None:
        return ChatV2RunRecorder(run_id)
    created = False
    writer = None
    try:
        module.create_run(
            {
                "run_id": run_id,
                "session_id": session_id,
                "profile": profile,
                "model_id": model_id,
                "mode": mode,
                "autonomy_level": autonomy_level,
                "thomas_version": THOMAS_VERSION,
            }
        )
        created = True
        writer = module.ThreadedRunWriter(run_id)
        writer.start()
        return ChatV2RunRecorder(run_id, module, writer)
    except _RUN_STORE_ERRORS as exc:
        log.warning("Chat V2 run persistence could not start: %s", exc)
        if writer is not None:
            try:
                writer.close()
            except _RUN_STORE_ERRORS as close_exc:
                log.warning("Chat V2 failed run writer close failed: %s", close_exc)
        if created:
            try:
                module.finalize_run(
                    run_id,
                    ok=False,
                    error=_PERSISTENCE_START_ERROR,
                    iterations=None,
                    tool_calls=None,
                    usage=None,
                )
            except _RUN_STORE_ERRORS as finalize_exc:
                log.warning("Chat V2 failed run finalization failed: %s", finalize_exc)
        return ChatV2RunRecorder(run_id)
