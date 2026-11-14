"""Keep Build subprocess channel setup out of the Code launch route."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from thomas.core.project_root import user_praxis_root
from thomas.server.app_keys import APP_PRAXIS_RUN_CHANNELS as APP_PRAXIS_RUN_CHANNELS
from thomas.server.app_keys import APP_PRAXIS_START_CODE_RUN as APP_PRAXIS_START_CODE_RUN
from thomas.server.app_keys import APP_PRAXIS_STOP_CODE_RUN as APP_PRAXIS_STOP_CODE_RUN
from thomas.server.app_keys import local_port as local_port

_START_GUARD: ContextVar[Callable[[], Awaitable[bool]] | None] = ContextVar("praxis_start_guard", default=None)
_GATE_GUARD: ContextVar[Callable[[], bool] | None] = ContextVar("praxis_gate_guard", default=None)


@contextmanager
def guarded_start(
    can_start: Callable[[], Awaitable[bool]] | None, gate_guard: Callable[[], bool] | None = None
) -> Iterator[None]:
    """Keep a recovery's admission checks local to its continuation task."""
    token = _START_GUARD.set(can_start)
    gate_token = _GATE_GUARD.set(gate_guard)
    try:
        yield
    finally:
        _GATE_GUARD.reset(gate_token)
        _START_GUARD.reset(token)


def build_claude_read_child_runner(*args: Any, **kwargs: Any):
    from thomas.server.praxis.claude_child import build_claude_read_child_runner as build

    return build(*args, **kwargs)


def PraxisRunJournal(*args: Any, **kwargs: Any):  # noqa: N802 -- stands in for the class, imported when first used
    from thomas.server.praxis.recovery import PraxisRunJournal as journal

    return journal(*args, **kwargs)


def build_read_child_runner(*args: Any, **kwargs: Any):
    from thomas.server.praxis.worker import build_read_child_runner as build

    return build(*args, **kwargs)


def build_dispatching_child_runner(app: Any, project: Path, settings: Any, run_id: str):
    """Keep each child's explicit provider choice, including across lead families."""
    saved_profile = str(getattr(settings, "praxis_reviewer_profile", "") or "")
    saved_model = str(getattr(settings, "praxis_reviewer_model", "") or "")
    if settings.family == "gpt":
        default_profile = saved_profile or "openai_codex"
        default_model = (
            saved_model if default_profile != "openai_codex" else (settings.reviewer_model or settings.model_id)
        )
    elif str(getattr(settings, "agent", "") or "") == "thomas":
        # Thomas's own loop on Claude reaches it by key, so its read children do
        # too — the `anthropic` profile, not the Claude CLI's sign-in.
        default_profile = saved_profile or "anthropic"
        default_model = saved_model or str(settings.dispatch_model).split(":", 1)[-1]
    else:
        default_profile = saved_profile or "claude_cli"
        default_model = saved_model or settings.dispatch_model

    async def run(
        child_id: str, kind: str, title: str, brief: str, model_choice: dict[str, str] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        choice = model_choice or {}
        if choice and not choice.get("profile"):
            yield {
                "type": "error",
                "error": "Explicit Build child model choice needs a provider profile",
                "retryable": False,
            }
            return
        profile = choice.get("profile") or default_profile
        model = choice.get("model_id") or (default_model if profile == default_profile else "")
        if profile == "claude_cli":
            cli = build_claude_read_child_runner(project, model_id=model or settings.dispatch_model)
            async for event in cli(child_id, kind, title, brief):
                yield event
            return
        worker = build_read_child_runner(app, project, model_id=model, run_id=run_id, profile=profile)
        async for event in worker(child_id, kind, title, brief, choice if choice else None):
            yield event

    return run


def recovery_start_allowed(*, consume: bool = True) -> bool:
    """Check recovery admission, consuming the guard before follow-ups inherit it."""
    guard = _GATE_GUARD.get()
    if consume:
        _GATE_GUARD.set(None)
    return guard is None or guard()


def bind_internal_start(app: Any, start: Any, lock: asyncio.Lock, *, stop: Any = None) -> None:
    """Expose the same guarded Build start to Chat without a loopback HTTP shortcut."""

    async def begin(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        message = str(body.get("message") or "").strip()
        if not message:
            raise ValueError("Build message is empty")
        async with lock:
            can_start = _START_GUARD.get()
            if can_start is not None and not await can_start():
                return 503, {"code": "recovery_start_deferred"}
            with guarded_start(None, _GATE_GUARD.get()):
                response = await start(body, message, local_port=port)
        return response.status, json.loads(response.text)

    app[APP_PRAXIS_START_CODE_RUN] = begin

    async def stop_run(run_id: str) -> bool:
        return False if stop is None else await stop(app, run_id)

    app[APP_PRAXIS_STOP_CODE_RUN] = stop_run


def prepare_launch(
    app: Any,
    settings: Any,
    project: Path,
    run_id: str,
    request_id: str,
    env: dict[str, str],
    port: int,
    instructions: str = "",
    conversation_id: str = "",
) -> tuple[str, Any]:
    start_token = secrets.token_urlsafe(24)
    env.update(
        {
            "THOMAS_CODE_START_GATE": "pipe",
            "THOMAS_CODE_START_TOKEN": start_token,
            "THOMAS_CODE_RUN_ID": run_id,
            "THOMAS_CODE_REQUEST_ID": request_id,
        }
    )
    registry = None
    if settings.family in {"gpt", "claude"} and port > 0:
        registry = app.get(APP_PRAXIS_RUN_CHANNELS)
        if registry is not None:
            runner = build_dispatching_child_runner(app, project, settings, run_id)
            journal = PraxisRunJournal(user_praxis_root() / "praxis" / "runs.sqlite3")
            journal.record_launch(
                run_id,
                {
                    "project_root": str(project.resolve()),
                    "family": str(settings.family),
                    "agent": str(getattr(settings, "agent", "") or ""),
                    "model_id": str(getattr(settings, "model_id", "") or ""),
                    "reviewer_model": str(getattr(settings, "reviewer_model", "") or ""),
                    "dispatch_model": str(getattr(settings, "dispatch_model", "") or ""),
                    "praxis_reviewer_profile": str(getattr(settings, "praxis_reviewer_profile", "") or ""),
                    "praxis_reviewer_model": str(getattr(settings, "praxis_reviewer_model", "") or ""),
                    "conversation_id": str(conversation_id or ""),
                },
            )
            channel = registry.open(
                run_id,
                runner,
                instructions=instructions,
                journal=journal,
                project_root=project,
            )
            env["THOMAS_RUN_CHANNEL_URL"] = f"http://127.0.0.1:{port}"
            env["THOMAS_RUN_CHANNEL_TOKEN"] = channel.token
    return start_token, registry


def attach_cleanup(
    app: Any, task: asyncio.Task[Any], run_id: str, proc: Any, *, session: dict[str, Any] | None = None
) -> None:
    from thomas.server.landed_code_runs import track_start

    if session is not None:
        track_start(app, session)
    registry = app.get(APP_PRAXIS_RUN_CHANNELS)
    if registry is not None:

        def cleanup(_done: asyncio.Task[Any]) -> None:
            explicit_stop = bool(str(getattr(proc, "thomas_stop_requested", "") or ""))
            action = registry.close if explicit_stop else registry.suspend
            asyncio.create_task(action(run_id))

        task.add_done_callback(cleanup)
