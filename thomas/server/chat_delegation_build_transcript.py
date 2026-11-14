"""Record a chat-dispatched run into the Build session it is watched through.

Opening the session showed an empty pane. The session was real and the run was
real; they simply spoke different languages. The Activity panel renders a
conversation turn's ``transcript`` as one forge event per line
(``{"fc": <kind>, ...}``, see ``thomas/forge/anvil/forge_event_stream.py``),
while the chat worker emits ``progress``/``text``/``tool_start``/``tool_output``/
``error``. Nothing translated between them, so there was nothing to render.

The tee below wraps the worker's event stream, passes every event through
untouched, and keeps a forge line for the ones worth showing. When the run ends
the lines become an agent turn on the bound conversation, and Build has a run to
display.

Two rules this module holds to:

* **It never eats an event.** The tee is a mirror, not a filter; the caller's
  stream is unchanged whether or not a session exists.
* **It never takes the run down.** Losing the window into a run costs you the
  view; losing the run costs you the work. Every failure here is logged and
  swallowed, which is the one place that is the right answer.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from thomas.forge.anvil import forge_code_store

log = logging.getLogger(__name__)

# How often the in-progress run is written to its session. Every recordable
# event would rewrite the whole conversation file; once a second is well under
# what a person notices and keeps the cost flat on a long run.
_WRITE_EVERY_S = 1.0

# execution_id -> (project_root, conversation_id). In-process because the tee
# and the dispatcher that opened the session live in the same server process.
_SESSIONS: dict[str, tuple[str, str]] = {}


def remember_build_session(execution_id: str, project_root: str, conversation_id: str) -> None:
    """Bind an execution to the Build session the person was told to watch."""
    key = str(execution_id or "").strip()
    if key and project_root and conversation_id:
        _SESSIONS[key] = (str(project_root), str(conversation_id))


def build_session_for(execution_id: str) -> tuple[str, str] | None:
    return _SESSIONS.get(str(execution_id or "").strip())


# execution_id -> the forge lines recorded for that run so far. Shared, because
# a spawned agent writes into the SAME session the lead is watched through: two
# buffers would mean two turns and a panel that shows the run twice.
_LINES: dict[str, list[str]] = {}


def record_line(execution_id: str, line: str, *, flush: bool = True) -> None:
    """Add one forge line to a run's transcript and persist it.

    Used by the tee for the lead's own events and by a spawned agent for its
    child's. Both land in one buffer so the panel reads a single interleaved
    story rather than two competing ones.
    """
    key = str(execution_id or "").strip()
    if not key or not line:
        return
    _LINES.setdefault(key, []).append(line)
    if flush:
        flush_run(key)


def flush_run(execution_id: str, *, ok: bool = True) -> None:
    """Write what a run has produced so far onto its Build session."""
    key = str(execution_id or "").strip()
    session = build_session_for(key)
    lines = _LINES.get(key)
    if session and lines:
        _persist(session, lines, ok=ok, execution_id=key)


def forget_run(execution_id: str) -> None:
    """Drop a finished run's buffer so a long-lived server does not grow."""
    _LINES.pop(str(execution_id or "").strip(), None)


def forge_line(event: dict[str, Any]) -> str | None:
    """Translate one worker event into a forge event line, or ``None`` to drop it.

    ``text`` is the agent talking and becomes ``say``; ``progress`` is the engine
    reporting on itself and becomes ``meta``. Collapsing the two would put engine
    chatter into the narrative the person reads.
    """
    kind = str(event.get("type") or "").strip()

    if kind == "tool_start":
        name = str(event.get("name") or "").strip()
        return _line("tool", name=name, text=name) if name else None

    if kind == "tool_output":
        text = str(event.get("result_text") or event.get("text") or event.get("output") or "")
        error = str(event.get("error") or "")
        if error and error not in text:
            text = f"{text}\n{error}" if text else error
        return _line(
            "tool_result",
            name=str(event.get("name") or ""),
            text=text,
            is_error=bool(event.get("is_error") or event.get("ok") is False or error),
        )

    if kind == "error":
        text = str(event.get("error") or event.get("text") or "").strip()
        return _line("error", text=text) if text else None

    if kind in ("text", "progress"):
        text = str(event.get("text") or "").strip()
        return _line("say" if kind == "text" else "meta", text=text) if text else None

    # done, model_runtime and anything new are bookkeeping, not something to show.
    return None


def _line(kind: str, **fields: Any) -> str:
    payload: dict[str, Any] = {"fc": kind}
    payload.update({key: value for key, value in fields.items() if value not in ("", None)})
    return json.dumps(payload, ensure_ascii=False)


def tee_to_build_session(
    events_fn: Callable[..., AsyncIterator[dict[str, Any]]],
) -> Callable[..., AsyncIterator[dict[str, Any]]]:
    """Wrap a worker event stream so the run is recorded on its Build session."""

    async def _wrapped(app: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        execution_id = str(kwargs.get("execution_id") or "")
        session = build_session_for(execution_id)
        failed = False
        last_write = 0.0
        try:
            async for event in events_fn(app, **kwargs):
                if session:
                    try:
                        line = forge_line(event)
                    except (TypeError, ValueError) as exc:
                        log.warning("Could not record a worker event for %s: %s", execution_id, exc)
                        line = None
                    if line:
                        # Written as it happens, so opening the session mid-run
                        # shows the run. Throttled because each write rewrites
                        # the whole conversation file -- but a spawned agent's
                        # lines go in unthrottled, so a child never waits.
                        now = time.monotonic()
                        due = now - last_write >= _WRITE_EVERY_S
                        if due:
                            last_write = now
                        record_line(execution_id, line, flush=due)
                if str(event.get("type") or "") == "error":
                    failed = True
                yield event
        finally:
            # `finally`, so a cancelled or crashed run still leaves behind what
            # it managed to do rather than an empty session.
            flush_run(execution_id, ok=not failed)

    return _wrapped


def _persist(session: tuple[str, str], lines: list[str], *, ok: bool, execution_id: str) -> None:
    project_root, conversation_id = session
    try:
        forge_code_store.upsert_run_transcript(
            project_root,
            conversation_id,
            run_id=execution_id,
            transcript="\n".join(lines),
            ok=ok,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # REVIEWED: swallowed on purpose. This is the recorder; if it raised it
        # would take down the very run it exists to describe.
        log.warning("Could not record the run on its Build session (%s): %s", execution_id, exc)
