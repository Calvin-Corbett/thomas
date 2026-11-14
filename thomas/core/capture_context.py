"""Capture correlation and the model-visible capture hook.

Every message list handed to the LLM client passes through
``LLMClient.stream_chat`` -- the narrow waist all ~24 producers converge on,
since ``chat()`` drains ``stream_chat()``. This module owns everything the
hook needs on the far side of that waist:

- a contextvar a conversation-owning surface (AgentLoop) sets so its model
  calls correlate to the run it belongs to ("contextvar" correlation);
- one lazily-created, per-process, pinned "ambient-capture" run for calls
  that never set that contextvar ("ambient" correlation) -- honestly
  labeled, never silently folded into an unrelated run;
- the capture itself: snapshot the messages, append a model/request event,
  accumulate the stream, append model/response referencing the request's
  landed seq.

Snapshot fidelity: the payload builders in session_log_events.py hold a live
reference to whatever list they are given -- no copy at any level. History
compaction mutates the caller's messages list in place. To guarantee the
logged request reflects what the model actually saw, `begin_model_capture`
deep-copies `messages` before handing it to the builder, and the append that
serializes it into sqlite happens synchronously in the same call with no
`await` in between -- so no intervening mutation, in-process or via the
event loop, can reach the snapshot before it is durable.

Capture failure is never allowed to break a model call: only a fixed set of
named exceptions is caught here, and every catch is counted by the caller
(`LLMClient.capture_failures`) rather than vanishing silently.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from thomas.core.llm_shared import StreamEvent, TokenUsage
from thomas.marketplace.observability import run_store

# `imported_payload` is re-exported for chat-tier consumers
# (thomas/chat/session_store.py): chat may only depend on core, so the
# session-log vocabulary it needs is served from this capture waist.
# core->marketplace is the single tracked debt edge for that vocabulary (see
# _architecture.py known_cycles; the hoist into core is the TODO'd fix) --
# chat must not add a second, untracked edge of its own.
from thomas.marketplace.observability.session_log_events import (  # noqa: F401
    imported_payload,
    model_request_payload,
    model_response_payload,
)

log = logging.getLogger(__name__)

# Exceptions the capture path is allowed to swallow. Deliberately a fixed,
# named tuple -- never a bare `except Exception` -- so a capture failure is
# always something recognizable (a run_store misuse, a bad payload, sqlite
# unavailable), not an accidental catch-all that could hide a real bug.
CAPTURE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    OSError,
    sqlite3.Error,
    # A huge deep-copied snapshot or serialization running out of memory is
    # still a capture failure, not a model-call failure -- the
    # capture-never-breaks-the-call contract covers this letter and verse.
    MemoryError,
)

_CAPTURE_RUN: ContextVar[str | None] = ContextVar("thomas_capture_run", default=None)

_ambient_lock = threading.Lock()
_ambient_run_id: str | None = None
_ambient_store_path: object = None

_seq_lock = threading.Lock()
_next_seq_by_run: dict[str, int] = {}


def set_capture_run(run_id: str) -> Token[str | None]:
    """Tag model calls made in this async context with `run_id`."""
    return _CAPTURE_RUN.set(str(run_id))


_cross_context_resets = 0
_cross_context_lock = threading.Lock()


def cross_context_resets() -> int:
    """How many resets met a token from another Context. Counted, never silent."""
    return _cross_context_resets


def reset(token: Token[str | None]) -> None:
    """Clear the run tag. A stale token must never abort the run being observed.

    `ContextVar.reset` raises ValueError when the token was created in a
    different Context, and that happens legitimately here. The set/reset bracket
    in loop_execution.py (set at :558, reset in the `finally` at :672) spans
    `yield`s, and an async generator runs in its CALLER's context - so a
    background worker driving `__anext__()` from a different task resets a token
    it did not create.

    Measured 2026-09-19: the chat task card "PRAXIS-PROBE-001" died on exactly
    this, twice, and `chat_delegation_runner` logged only a bare
    "Background worker run raised ValueError" with no traceback. Minimal repro:
    drive an async generator's two steps from two `asyncio.create_task` calls,
    then `aclose()` it - "<Token ...> was created in a different Context".

    This module's stated rule is that capture failure never breaks the call and
    is counted rather than vanishing silently. `reset` was the one function not
    obeying it. The tag is observability; it does not get to kill the work it is
    observing. So: fall back to clearing the tag in the current context, and
    count the event so it stays visible via `cross_context_resets()`.
    """
    global _cross_context_resets
    try:
        _CAPTURE_RUN.reset(token)
    except ValueError:
        with _cross_context_lock:
            _cross_context_resets += 1
        _CAPTURE_RUN.set(None)
        log.debug("capture run tag reset across contexts; cleared in the current context instead")


def current() -> str | None:
    return _CAPTURE_RUN.get()


def ambient_run_id(create: bool = True) -> str | None:
    """The one pinned, per-process run for calls with no correlated run_id.

    Honestly labeled (mode="ambient-capture", model_id carries the pid) so
    uncorrelated calls are never silently folded into an unrelated run.
    Lazily created once per process and cached; safe under concurrent
    first-callers via `_ambient_lock`.
    """
    global _ambient_run_id, _ambient_store_path
    with _ambient_lock:
        store_path = getattr(run_store, "_DB_PATH", None)
        if _ambient_run_id is not None and _ambient_store_path == store_path:
            return _ambient_run_id
        # The id belongs to the run store it was created in. If the store was pointed
        # at another database, writing to the old id would make that database invent
        # a bare run row that never ends and shows as a worker that is running.
        _ambient_run_id = None
        if not create:
            return None
        _ambient_store_path = store_path
        _ambient_run_id = run_store.create_run(
            {
                "pinned": True,
                "mode": "ambient-capture",
                "model_id": f"pid:{os.getpid()}",
            }
        )
        return _ambient_run_id


def _next_seq(run_id: str) -> int:
    with _seq_lock:
        seq = _next_seq_by_run.get(run_id, 0)
        _next_seq_by_run[run_id] = seq + 1
        return seq


_run_t0_ms: dict[str, int] = {}


def _now_ms(run_id: str | None = None) -> int:
    """Milliseconds since this module first wrote to `run_id`.

    The run store's own writer records `t_ms` as the offset from the run's start
    and every reader (Mission Control, replay) adds it to `started_at`. Epoch
    milliseconds here put the ambient run's last activity in the year 2083.
    """
    now = int(time.time() * 1000)
    if run_id is None:
        return now
    with _seq_lock:
        return now - _run_t0_ms.setdefault(run_id, now)


def append_capture_event(run_id: str, payload: dict[str, Any]) -> int:
    """Public alias for `_append_capture_event` -- new call sites use this name.

    Task 4 (the shadow-diff soak in derive_messages.py) is the first caller
    outside this module, so it gets the public name. Migrating this
    module's own in-module callers to the alias is a tracked follow-up (see
    status.md), not part of this change.
    """
    return _append_capture_event(run_id, payload)


def _append_capture_event(run_id: str, payload: dict[str, Any]) -> int:
    """Append one capture event to `run_id`'s spine; return its landed seq.

    Production wiring can already have an in-process `ThreadedRunWriter`
    registered for this exact `run_id` (e.g. the chat route's per-turn
    streaming writer, correlated to the same run this capture is tagged
    with). `events` has no `(run_id, seq)` uniqueness constraint, so two
    independent seq counters on one run_id silently collide. When a writer
    is registered, this defers to it entirely -- peek `writer.seq` (the
    value `record()` is about to assign) before calling `record()`, so both
    the seq and the durable write come from the SAME sequence source as
    everything else on this run. Only falls back to this module's own
    per-run counter (`_next_seq`) when no writer is registered for `run_id`
    (the ambient run, CLI paths, and any other run with no live writer).
    """
    writer = run_store.get_active_writer(run_id)
    if writer is not None:
        seq = writer.seq
        writer.record(payload)
        return seq
    seq = _next_seq(run_id)
    run_store.append_event(run_id, payload["type"], payload, _now_ms(run_id), seq)
    return seq


def _tools_digest(tools: list[dict[str, Any]] | None) -> str | None:
    if not tools:
        return None
    try:
        blob = json.dumps(tools, sort_keys=True, default=str)
    except CAPTURE_EXCEPTIONS:
        return None
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _count(usage: Any, name: str) -> int:
    """One token count from a TokenUsage or a usage dict; 0 when it is missing or not a number."""
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, 0)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _usage_to_dict(usage: Any) -> dict[str, Any]:
    if isinstance(usage, TokenUsage):
        return {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }
    if isinstance(usage, dict):
        return usage
    return {}


@dataclass
class CaptureState:
    """Everything one `stream_chat` call's capture needs to carry along."""

    run_id: str | None
    correlation: str
    request_seq: int | None = None
    active: bool = False
    failed: bool = False
    text_parts: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    # The provider's cache reads and writes for this call. Kept beside `usage`, not in it, so the captured
    # model/response payload stays exactly as it was; the step log and the spend ledger carry them.
    cached_prompt_tokens: int = 0
    cache_write_prompt_tokens: int = 0
    started: float = field(default_factory=time.monotonic)  # for the step log's seconds per model call


def begin_model_capture(
    messages: list[dict[str, Any]],
    *,
    model: str,
    provider: str,
    tools: list[dict[str, Any]] | None,
) -> CaptureState:
    """Snapshot `messages` and append the model/request event.

    Never raises: a capture failure is recorded on the returned state
    (`state.failed`) and the caller is expected to keep going regardless.
    Ambient-run creation (its own run_store call) is inside the same try as
    the append -- a run_store that was never initialized must fail exactly
    like any other capture failure, not take the model call down with it.
    """
    state = CaptureState(run_id=None, correlation="ambient")
    try:
        run_id = current()
        correlation = "contextvar"
        if run_id is None:
            run_id = ambient_run_id()
            correlation = "ambient"
        state.run_id = run_id
        state.correlation = correlation
        if run_id is None:
            return state
        snapshot = copy.deepcopy(messages)
        payload = model_request_payload(
            snapshot,
            model=model,
            provider=provider,
            tools_digest=_tools_digest(tools),
            correlation=correlation,
        )
        state.request_seq = _append_capture_event(run_id, payload)
        state.active = True
    except CAPTURE_EXCEPTIONS as e:
        log.debug("Capture: model/request append failed (%s): %s", type(e).__name__, e)
        state.failed = True
    return state


def record_stream_event(state: CaptureState, event: StreamEvent) -> None:
    """Accumulate one provider StreamEvent into `state` for the response payload."""
    if event.type == "usage":  # the step log and the spend ledger count tokens even when the capture is off
        raw = event.data.get("usage")
        if not state.active:
            state.usage = _usage_to_dict(raw)
        state.cached_prompt_tokens = _count(raw, "cached_prompt_tokens")
        state.cache_write_prompt_tokens = _count(raw, "cache_write_prompt_tokens")
    if not state.active:
        return
    try:
        if event.type == "token":
            state.text_parts.append(str(event.data.get("text", "")))
        elif event.type == "tool_call_end":
            state.tool_calls.append(
                {
                    "id": event.data.get("id", ""),
                    "name": event.data.get("name", ""),
                    "arguments": event.data.get("arguments", ""),
                }
            )
        elif event.type == "usage":
            state.usage = _usage_to_dict(event.data.get("usage"))
    except CAPTURE_EXCEPTIONS as e:
        log.debug("Capture: accumulating stream event failed (%s): %s", type(e).__name__, e)
        state.failed = True


def _record_model_step(state: CaptureState, interrupted: bool, model: str, provider: str, attempts: int) -> None:
    """Every model call goes in the step log: seconds, the model that answered, its tokens (2026-10-25).

    That makes the step log Thomas's token log, in every process that makes a call (the server, each Build run,
    the CLI), summed at /api/metrics/steps. Since 2026-11-06, when you asked for a token log, each row also has the
    tokens the provider served from its cache and wrote into it, so whether caching works can be read, not guessed.
    The spend ledger behind /api/spend is the self-upgrade loop's and is not written here.
    """
    from thomas.core import step_log

    usage = state.usage or {}
    step_log.record(
        "model",
        seconds=time.monotonic() - state.started,
        run=state.run_id or "",
        model=model,
        provider=provider,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        cached_prompt_tokens=state.cached_prompt_tokens,  # 0 included: a row without it predates 2026-11-06
        cache_write_prompt_tokens=state.cache_write_prompt_tokens,
        tool_calls=len(state.tool_calls),
        interrupted=bool(interrupted),
        attempts=attempts,
    )


def end_model_capture(
    state: CaptureState,
    *,
    interrupted: bool,
    served_by_model: str,
    served_by_provider: str,
    provider_attempts: int,
    merged_partial_output: bool,
) -> bool:
    """Append the model/response event.

    Returns True only when THIS call newly failed -- never re-surfaces a
    failure `begin_model_capture` already reported and the caller already
    counted. Without that distinction, one real append failure at the
    request stage reads as `state.failed=True` here too on the early-return
    path below, and gets counted twice for a single attempted append.
    """
    _record_model_step(state, interrupted, served_by_model, served_by_provider, provider_attempts)
    if not state.active or state.run_id is None or state.request_seq is None:
        return False
    try:
        payload = model_response_payload(
            "".join(state.text_parts),
            state.tool_calls,
            state.usage,
            bool(interrupted),
            state.request_seq,
            served_by_model=served_by_model,
            served_by_provider=served_by_provider,
            provider_attempts=provider_attempts,
            merged_partial_output=merged_partial_output,
        )
        _append_capture_event(state.run_id, payload)
    except CAPTURE_EXCEPTIONS as e:
        log.debug("Capture: model/response append failed (%s): %s", type(e).__name__, e)
        state.failed = True
        return True
    return False
