"""Whether a Code run answered, is still recording, or can be replayed.

Split out of ``evolve_agent_runtime.py`` (move-only, no logic changes) to bring
that file back under monolith_guard's unbaselined 800-line soft limit, following
the worker.py -> worker_pipeline.py/worker_dispatch.py precedent (commit
7f1006d7). Two related status questions live here: whether a transcript shows a
structured turn that answered without changing files
(``_confirmed_conversation_reply``, mirrored deliberately in
``dispatch_agent_loop``/``dispatch_claude_cli`` via a shared helper), and
where a run's background recorder currently stands
(``_recording_task``/``_recording_active``/``_run_replay_available``/
``_recording_status``/``_await_recording``). Self-contained -- nothing here
calls back into ``evolve_agent_runtime.py``.

``evolve_agent_runtime.py`` re-exports every name here under its original spot;
``evolve_agent_routes.py``, ``evolve_agent_watch_routes.py``,
``evolve_agent_run_state.py``, and ``dispatch_claude_cli.py`` import these from
``evolve_agent_runtime`` (directly, or via ``evolve_agent_runtime.<name>``
attribute access in tests) and needed no changes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from thomas.agent.tool_failures import ToolFailures


def _confirmed_conversation_reply(transcript: str, *, require_final: bool = False) -> bool:
    """Return true for a structured turn that answered without changing files.

    Reading is not a failed edit. A request to inspect and explain something
    must read files to answer it, and disqualifying any tool use meant those
    runs were recorded as "no change made" with the answer buried underneath.

    The same tool-result verdict used by both dispatchers judges recovered
    failures here; callers establish separately that no files changed.

    ``require_final`` narrows the evidence to ``final`` frames alone. The
    stream translator emits ``final`` only for a non-error CLI ``result``
    message, so it is protocol-level proof the answer arrived -- which is what
    lets a reply outvote a nonzero exit code. Streamed ``say`` text is not
    that proof: a run that crashed mid-narration has ``say`` frames too.
    """

    saw_reply = False
    tool_verdict = ToolFailures()
    for raw in str(transcript or "").splitlines():
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        kind = str(event.get("fc") or "")
        if kind in {"tool", "tool_result"}:
            tool_verdict.observe(event)
        elif kind in {"final", "say"} and str(event.get("text") or "").strip():
            if kind == "final" or not require_final:
                saw_reply = True
    return saw_reply and not tool_verdict.unresolved


def _recording_task(recording: Any) -> Any:
    return recording.get("task") if isinstance(recording, dict) else recording


def _recording_active(recording: Any) -> bool:
    task = _recording_task(recording)
    return bool(task is not None and not task.done())


def _run_replay_available(receipt: dict[str, Any], session: Any, running: bool, recording: Any) -> bool:
    state = receipt.get("state")
    if state in {"completed", "persistence_failed", "after_run_pending", "finished"}:
        return True
    if state not in {"launching", "running"}:
        return False
    response = receipt.get("response") if isinstance(receipt.get("response"), dict) else {}
    active_run = str((session or {}).get("run_id") or "")
    return active_run == str(response.get("run_id") or "") and (running or _recording_active(recording))


def _recording_status(recording: Any) -> dict[str, Any]:
    task = _recording_task(recording)
    if task is None:
        return {"recording": False, "persistence_confirmed": False, "persistence_state": "missing"}
    if not task.done():
        return {"recording": True, "persistence_confirmed": False, "persistence_state": "recording"}
    if task.cancelled():
        return {"recording": False, "persistence_confirmed": False, "persistence_state": "cancelled"}
    try:
        result = task.result()
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "recording": False,
            "persistence_confirmed": False,
            "persistence_state": "failed",
            "persistence_error": str(exc) or type(exc).__name__,
        }
    if not isinstance(result, dict) or result.get("persistence_confirmed") is not True:
        error = result.get("persistence_error") if isinstance(result, dict) else "invalid recorder result"
        return {
            **(result if isinstance(result, dict) else {}),
            "recording": False,
            "persistence_confirmed": False,
            "persistence_state": "failed",
            "persistence_error": error or "agent turn was not persisted",
        }
    return {**result, "recording": False, "persistence_state": "persisted"}


async def _await_recording(recording: Any) -> dict[str, Any]:
    task = _recording_task(recording)
    if task is None:
        return _recording_status(None)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        return {
            "recording": False,
            "persistence_confirmed": False,
            "persistence_state": "cancelled",
            "persistence_error": "recorder wait was cancelled",
        }
    return _recording_status(recording)
