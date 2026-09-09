"""Worker event-stream helpers for the delegation runner, split out so the runner
stays under the size limit: user-facing tool phrases, per-tool outcome recording,
supervisor timeouts and the async event-stream plumbing."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from thomas.server.chat_delegation_deliverable import _WorkerRetry

log = logging.getLogger(__name__)


def _runner_setting(name: str) -> float:
    """Timeouts stay defined (and monkeypatched by tests) on the runner module; read
    them there at call time so this module never imports the runner at import time."""

    import importlib

    return float(getattr(importlib.import_module("thomas.server.chat_delegation_runner"), name))



# Progress lines are USER-FACING (the activity card under "Handed off to ...").
# Raw tool telemetry ("Finished fs.read_file; continuing.") reads like a stack
# trace to the owner; phrase every step like a teammate's status update.
_TOOL_PHRASES = {
    "fs.read_file": ("Reading files", "Read what I needed"),
    "fs.write_file": ("Writing the file", "Saved the file"),
    "fs.list_dir": ("Looking through the workspace", "Scanned the workspace"),
    "fs.search": ("Searching the workspace", "Searched the workspace"),
    "web.search": ("Searching the web", "Found some sources"),
    "web.fetch": ("Reading a web page", "Read the page"),
    "shell.exec": ("Running a command", "Command finished"),
    "ssh.exec": ("Running a remote command", "Remote command finished"),
}


def _tool_phrase(tool_name: str, *, done: bool = False, failed: bool = False) -> str:
    active, finished = _TOOL_PHRASES.get(str(tool_name or "tool"), ("Working on the next step", "Step finished"))
    if failed:
        return f"{active} hit a snag — trying another way."
    return f"{finished} — moving on." if done else f"{active}…"


_MAX_EFFORT_IDLE_EVENT_TIMEOUT_S = 360.0
# A worker that fails the same step this many times IN A ROW stops spinning
# "hit a snag" and hands control to the recovery machinery instead.
_MAX_CONSECUTIVE_SNAGS = 6


def _record_tool_outcome(
    tool_name: str,
    *,
    ok: bool,
    succeeded_tools: list[str],
    failed_tools: list[str],
) -> None:
    """Keep every failed action visible; a later same-named call is not proof of recovery."""
    target = succeeded_tools if ok else failed_tools
    if tool_name not in target:
        target.append(tool_name)


def _supervisor_worker_timeout_s(worker_kwargs: dict[str, Any], *, has_progress: bool) -> float:
    """Return a bounded watchdog window appropriate to the active worker tier."""

    base = _runner_setting("_WORKER_IDLE_EVENT_TIMEOUT_S") if has_progress else _runner_setting("_WORKER_FIRST_EVENT_TIMEOUT_S")
    effort = str(worker_kwargs.get("effort") or "").strip().lower()
    if has_progress and effort in {"max", "exhaustive"}:
        return max(base, _MAX_EFFORT_IDLE_EVENT_TIMEOUT_S)
    return base


async def _next_worker_event(stream: Any, *, saw_event: bool, timeout_s: float | None = None) -> dict[str, Any] | None:
    """Wait for the worker's next event, cancelling the stream if it never comes.

    `timeout_s` exists because this watchdog and `_supervisor_worker_timeout_s`
    were two spellings of one decision and they disagreed. The supervisor reads the
    effort dial and grants 360s for "max"/"exhaustive" -- Thorough in the UI -- while
    this function took no effort argument and always used the 120s idle constant.
    The stricter one wins, so choosing Thorough changed nothing and a worker that
    thought for over two minutes was cut off mid-step.

    Worth knowing what the cut costs: the timeout path cancels the pending
    `__anext__()`, which destroys the generator. After that StopAsyncIteration reads
    downstream as "the worker said nothing" rather than "we stopped listening", so
    the run is reported as silent rather than interrupted.
    """

    if timeout_s is None:
        timeout_s = _runner_setting("_WORKER_IDLE_EVENT_TIMEOUT_S") if saw_event else _runner_setting("_WORKER_FIRST_EVENT_TIMEOUT_S")
    next_task = asyncio.create_task(stream.__anext__())
    done, _pending = await asyncio.wait({next_task}, timeout=max(0.001, float(timeout_s)))
    if done:
        try:
            return next_task.result()
        except StopAsyncIteration:
            return None

    def _consume_background_result(task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        except (RuntimeError, OSError, ValueError, TypeError):
            log.debug("worker event stream background cleanup failed", exc_info=True)

    next_task.cancel()
    cancelled, _pending = await asyncio.wait({next_task}, timeout=_runner_setting("_WORKER_STREAM_CLOSE_TIMEOUT_S"))
    if cancelled:
        _consume_background_result(next_task)
    else:
        next_task.add_done_callback(_consume_background_result)
    await _close_worker_event_stream(stream, consume_result=_consume_background_result)
    phase = "first event" if not saw_event else "next event"
    raise _WorkerRetry(f"provider-native worker produced no {phase} within {timeout_s:g}s")


async def _close_worker_event_stream(
    stream: Any,
    *,
    consume_result: Callable[[asyncio.Task[Any]], None] | None = None,
) -> None:
    close = getattr(stream, "aclose", None)
    if callable(close):
        try:
            close_task = asyncio.ensure_future(close())
            closed, _pending = await asyncio.wait({close_task}, timeout=_runner_setting("_WORKER_STREAM_CLOSE_TIMEOUT_S"))
            if closed:
                if consume_result is not None:
                    consume_result(close_task)
                else:
                    close_task.result()
            else:
                close_task.cancel()
                if consume_result is not None:
                    close_task.add_done_callback(consume_result)
        except (RuntimeError, OSError, ValueError, TypeError):
            log.debug("worker event stream close failed", exc_info=True)


def _run_worker_thread_entry(runner: Callable[..., Awaitable[None]], app: Any, kwargs: dict[str, Any]) -> None:
    asyncio.run(runner(app, **kwargs))
