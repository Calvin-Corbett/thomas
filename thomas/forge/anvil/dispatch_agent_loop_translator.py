"""The GPT in-process loop's event translator, moved out of ``dispatch_agent_loop``.

``dispatch_agent_loop.py`` grew past the 800-line soft limit the push gate
holds new files to; the translator class and the two helpers only it uses
live here. Behaviour is unchanged: the same forge events, the same shared
reasoning gate as the claude stream path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from thomas.agent.loop_tool_protocol import tool_call_access

from .dispatch_agent_summary import _acceptance_summary
from .forge_event_stream import (
    FORGE_EVENT_KEY,
    _StreamState,
    _summarize_tool_input,
    _thinking_to_events,
)


def _summarize_agent_event_tool(name: str, args: Any) -> str:
    """Compact summary for an AgentLoop tool call (reuses the tool-input summarizer)."""
    summary = _summarize_tool_input(args if isinstance(args, dict) else {})
    return summary or str(name or "tool")


def _acceptance_event(acceptance: dict[str, Any] | None) -> dict[str, Any] | None:
    """The settlement as one forge event: the verdict and every item's outcome."""
    if not isinstance(acceptance, dict) or not acceptance.get("active"):
        return None
    verdict = acceptance.get("verdict")
    if not isinstance(verdict, dict):
        return None
    items = []
    for row in acceptance.get("items") or []:
        if not isinstance(row, dict):
            continue
        items.append(
            {
                "item_id": str(row.get("item_id") or ""),
                "kind": str(row.get("kind") or ""),
                "description": str(row.get("description") or "")[:300],
                "checked": bool(row.get("checked")),
                "satisfied": bool(row.get("satisfied")),
                "detail": str(row.get("detail") or "")[:400],
            }
        )
    return {
        FORGE_EVENT_KEY: "acceptance",
        "verdict": {
            "met": bool(verdict.get("met")),
            "unmet": [str(x) for x in verdict.get("unmet") or []],
            "unchecked": [str(x) for x in verdict.get("unchecked") or []],
        },
        "items": items,
    }


class _AgentLoopForgeTranslator:
    """Map Thomas's own ``AgentEvent`` stream (the GPT in-process loop) onto the
    SAME forge events the claude stream-json path emits — including the mid-task
    insight + collapsed reasoning beat, via the SAME shared gate.

    This is the GPT twin of ``ClaudeStreamTranslator``. Both engines carry a
    per-run ``_StreamState`` and funnel reasoning through ``_thinking_to_events``,
    so a user who picks GPT sees the IDENTICAL genuine post-observation insight
    cards (deduped, enumeration-stripped, honest) a claude run shows — never zero.

    Two stream-shape differences from the claude path are absorbed here:

      * ``THINKING`` arrives as token DELTAS, not whole blocks, so reasoning is
        ACCUMULATED in ``_think_buf`` and flushed as ONE block at the next
        boundary (a tool, an error, or done).
      * the flush happens BEFORE a tool flips ``seen_observation``: reasoning that
        precedes the run's first observation is the plan (gated to NO card, only
        its collapsed ``reason``); reasoning that follows an observation is
        insight-eligible — exactly the claude positional rule.

    ``rc`` is set to 1 on an agent error and ``final_text`` holds the loop's final
    message, so the async driver keeps returning the genuine ``(rc, final_text)``.
    """

    def __init__(self, emit: Callable[[dict[str, Any]], None]) -> None:
        from thomas.core.events import EventType

        self._emit = emit
        self._ET = EventType
        self._state = _StreamState()
        self._say_buf: list[str] = []
        self._think_buf: list[str] = []
        # Raw argument JSON per tool call, accumulated from the streaming
        # TOOL_CALL_ARGS_DELTA events. This is the ONLY place the arguments are
        # visible to this translator: the executed TOOL_RESULT event carries
        # tool_id/name/result but no args, so without this buffer a shell.exec
        # that ran "dir" is indistinguishable from one that ran "del x", and
        # every shell call was assumed to write — which filed correct
        # explain-only runs as failed edits with a fabricated exit 1.
        self._tool_args_buf: dict[str, list[str]] = {}
        # tool_id -> the shell command it ran (excerpt), so results are auditable.
        self._last_call_command: dict[str, str] = {}
        # True once we've forwarded token-progressive ``say`` deltas for the current
        # prose run, so the boundary flush does NOT re-emit the same text as a block.
        self._streamed_say = False
        self.rc = 0
        self.final_text = ""
        # The acceptance settlement the loop computed for this pass (the
        # ``acceptance_contract`` block of its token report). The engine reads
        # it after the pass: a settled-but-unmet contract is the reason for
        # another pass, and it used to be dropped here with the rest of the
        # report, which left "completed" as the only outcome a passing smoke
        # could reach.
        self.acceptance: dict[str, Any] | None = None

    def _flush_say(self) -> None:
        # If the prose was already streamed token-by-token (the live path), the
        # deltas ARE the message — just drop the accumulator and re-arm for the next
        # block. Only the non-streaming fallback emits the buffered text as one block.
        if self._streamed_say:
            self._say_buf.clear()
            self._streamed_say = False
            return
        text = "".join(self._say_buf).strip()
        self._say_buf.clear()
        if text:
            self._emit({FORGE_EVENT_KEY: "say", "text": text})

    def _flush_think(self) -> None:
        # The reasoning accumulated since the last boundary is ONE block: distil its
        # insight (gated) and emit the collapsed reason via the SHARED helper. Flush
        # BEFORE a tool flips the observation gate so pre-observation reasoning stays
        # plan (no card) and post-observation reasoning is insight-eligible.
        text = "".join(self._think_buf).strip()
        self._think_buf.clear()
        for ev in _thinking_to_events(text, self._state):
            self._emit(ev)

    def _classify_call(self, tool_name: str, tool_id: str) -> tuple[str, str]:
        """Classify one completed call as ``("read"|"write", basis)``.

        Uses the streamed argument JSON buffered for this ``tool_id`` so a
        shell command is judged by its content — the same repair-tolerant
        parse the executor itself uses (``parse_tool_args``), so the
        classification sees the same command the tool actually ran. When the
        stream never showed the arguments, ``tool_call_access`` fails toward
        "write": no positive evidence, no relaxation.
        """
        from thomas.agent.loop_tool_exec import parse_tool_args

        raw = "".join(self._tool_args_buf.pop(tool_id, []))
        args, _parse_error = parse_tool_args(raw) if raw else (None, None)
        # Remember the shell command so the RESULT event can carry it. Without
        # this the durable record holds only stdout -- a passing check was
        # unauditable after the fact, because nothing could say WHAT ran.
        if isinstance(args, dict):
            self._last_call_command[tool_id] = str(args.get("command") or "")[:300]
        return tool_call_access(tool_name, args if isinstance(args, dict) else None)

    def feed(self, et: str, data: dict[str, Any] | None) -> None:
        """Translate one AgentLoop event, emitting forge events as a side effect."""
        ET = self._ET
        data = data or {}
        if et == ET.TEXT_DELTA.value:
            # Forward each token PROMPTLY as a progressive ``say`` delta (RAW — no
            # strip, so inter-token spaces survive). The accumulator is still kept
            # so the boundary flush knows prose was streamed (must not re-emit as block).
            piece = str(data.get("text") or "")
            if piece:
                self._say_buf.append(piece)
                self._streamed_say = True
                self._emit({FORGE_EVENT_KEY: "say", "text": piece, "delta": True})
        elif et == ET.THINKING.value:
            # Accumulate reasoning deltas; they flush as one block at the next
            # boundary so the shared insight/reason rule sees a whole thought.
            self._think_buf.append(str(data.get("text") or ""))
        elif et == ET.TOOL_CALL_ARGS_DELTA.value:
            # Buffer the streamed argument JSON per call. The command a
            # shell.exec ran only ever crosses this stream here, and the
            # read-only-run verdict needs it (see _classify_call).
            tool_id = str(data.get("tool_id") or "")
            delta = str(data.get("delta") or "")
            if tool_id and delta:
                self._tool_args_buf.setdefault(tool_id, []).append(delta)
        elif et == ET.TOOL_START.value:
            # Reasoning BEFORE the tool is flushed (and gated) FIRST, then the tool
            # marks the run as having OBSERVED so later reasoning can surface.
            self._flush_think()
            self._flush_say()
            start_args = data.get("args")
            start_access, start_basis = tool_call_access(
                str(data.get("tool_name") or ""),
                start_args if isinstance(start_args, dict) else None,
            )
            self._emit(
                {
                    FORGE_EVENT_KEY: "tool",
                    "name": str(data.get("tool_name") or "tool"),
                    "text": _summarize_agent_event_tool(data.get("tool_name"), data.get("args")),
                    "access": start_access,
                    "access_basis": start_basis,
                }
            )
            self._state.seen_observation = True
        elif et == ET.TOOL_RESULT.value:
            access, access_basis = self._classify_call(str(data.get("tool_name") or ""), str(data.get("tool_id") or ""))
            command_excerpt = self._last_call_command.pop(str(data.get("tool_id") or ""), "")
            self._emit(
                {
                    FORGE_EVENT_KEY: "tool_result",
                    # The command the tool ran (excerpt), when the stream showed
                    # one -- so a passing check is auditable after the fact
                    # instead of being stdout with no provenance.
                    **({"command": command_excerpt} if command_excerpt else {}),
                    # Carry the tool's name. TOOL_START is never emitted by the
                    # agent loop -- Events.tool_start has no callers anywhere --
                    # so this is the ONLY place a name reaches the forge stream.
                    # Without it, everything downstream that asks "did this run
                    # only read?" gets an unnamed event, cannot tell reading from
                    # writing, and falls back to treating every tool call as a
                    # failed edit. That is what reported correct read-only
                    # answers as no-ops.
                    "name": str(data.get("tool_name") or ""),
                    "text": str(data.get("result") or "")[:500],
                    "is_error": not bool(data.get("ok", True)),
                    # How this call was judged for the read-only-run verdict,
                    # and on what evidence — recorded so the decision is
                    # visible in the persisted event stream instead of being
                    # re-derived (differently) by whoever reads it later.
                    "access": access,
                    "access_basis": access_basis,
                }
            )
            # A tool RESULT is the clearest observation — following reasoning is
            # insight-eligible, mirroring the claude ``tool_result`` branch.
            self._state.seen_observation = True
        elif et == ET.STATUS.value:
            # The loop's hold rounds ("Reply checked against the acceptance
            # contract: not finished yet ...") were invisible: generation 7
            # replayed two races seven times and the record showed only replays.
            message = str(data.get("message") or "")
            if "acceptance contract" in message.lower():
                self._flush_think()
                self._flush_say()
                self._emit({FORGE_EVENT_KEY: "meta", "text": message[:1200]})
        elif et == ET.AGENT_ERROR.value:
            self._flush_think()
            self._flush_say()
            self.rc = 1
            self._emit({FORGE_EVENT_KEY: "error", "text": str(data.get("error") or "agent loop reported an error")})
        elif et == ET.AGENT_DONE.value:
            self._flush_think()
            self.final_text = str(data.get("text") or "")
            if self._say_buf:
                self._flush_say()
            if self.final_text:
                self._emit({FORGE_EVENT_KEY: "final", "text": self.final_text})
            report = data.get("token_report")
            acceptance = report.get("acceptance_contract") if isinstance(report, dict) else None
            self.acceptance = acceptance if isinstance(acceptance, dict) else None
            summary = _acceptance_summary(self.acceptance)
            if summary:
                self._emit({FORGE_EVENT_KEY: "meta", "text": summary})
            # The settlement itself, not only its one-line summary: the run
            # report is built from these events, and with only the summary to
            # read its rubric fell back to "no individual requirement was
            # extracted or checked" one line under "every item checked and
            # satisfied" (seen live on a kanban Build, 2026-09-06).
            event = _acceptance_event(self.acceptance)
            if event:
                self._emit(event)

    def close(self) -> None:
        """Drain any trailing reasoning/say buffered when the stream ends."""
        self._flush_think()
        self._flush_say()


__all__ = ["_AgentLoopForgeTranslator", "_acceptance_event", "_summarize_agent_event_tool"]
