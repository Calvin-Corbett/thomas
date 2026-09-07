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

_seq_lock = threading.Lock()
_next_seq_by_run: dict[str, int] = {}


def set_capture_run(run_id: str) -> Token[str | None]:
    """Tag model calls made in this async context with `run_id`."""
    return _CAPTURE_RUN.set(str(run_id))


def reset(token: Token[str | None]) -> None:
    _CAPTURE_RUN.reset(token)


def current() -> str | None:
    return _CAPTURE_RUN.get()


def ambient_run_id(create: bool = True) -> str | None:
    """The one pinned, per-process run for calls with no correlated run_id.

    Honestly labeled (mode="ambient-capture", model_id carries the pid) so
    uncorrelated calls are never silently folded into an unrelated run.
    Lazily created once per process and cached; safe under concurrent
    first-callers via `_ambient_lock`.
    """
    global _ambient_run_id
    with _ambient_lock:
        if _ambient_run_id is not None:
            return _ambient_run_id
        if not create:
            return None
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


def _now_ms() -> int:
    return int(time.time() * 1000)


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
    run_store.append_event(run_id, payload["type"], payload, _now_ms(), seq)
    return seq


def _tools_digest(tools: list[dict[str, Any]] | None) -> str | None:
    if not tools:
        return None
    try:
        blob = json.dumps(tools, sort_keys=True, default=str)
    except CAPTURE_EXCEPTIONS:
        return None
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


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
