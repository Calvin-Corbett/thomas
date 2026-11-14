"""The GPT in-process loop's event translator, moved out of ``dispatch_agent_loop``.

``dispatch_agent_loop.py`` grew past the 800-line soft limit the push gate
holds new files to; the translator class and the two helpers only it uses
live here. Behaviour is unchanged: the same forge events, the same shared
reasoning gate as the claude stream path.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thomas.agent.loop_tool_protocol import _canonical_code_tool_name, tool_call_access

from .build_lead_tools import TOOL_NAMES as _LEAD_TOOL_NAMES
from .build_model_receipt import reported_model_events
from .dispatch_agent_summary import _acceptance_summary
from .forge_event_stream import (
    FORGE_EVENT_KEY,
    _StreamState,
    _summarize_tool_input,
    _thinking_to_events,
)

# The file tools whose events carry the file they touched (`path`), so the UI can say which file an agent is on
# without parsing the summary text; the writers also carry the lines they added and removed when that is known.
_FILE_READ_TOOLS = frozenset({"fs.read_file", "diff.preview"})
_FILE_WRITE_TOOLS = frozenset({"fs.write_file", "fs.write_protected_file", "diff.create"})
_REPLACED_LINES = re.compile(r"Replaced (\d+) line\(s\) with (\d+) line\(s\)")


def _summarize_agent_event_tool(name: str, args: Any) -> str:
    """Compact summary for an AgentLoop tool call (reuses the tool-input summarizer)."""
    summary = _summarize_tool_input(args if isinstance(args, dict) else {})
    return summary or str(name or "tool")


def _is_lead_tool(name: str) -> bool:
    """plan.update / ask.user, also under the provider-safe spelling (plan_update)."""
    return str(name or "") in _LEAD_TOOL_NAMES or str(name or "").replace("_", ".", 1) in _LEAD_TOOL_NAMES


def _project_path(raw: Any, root: str | Path | None) -> str:
    """``raw`` relative to the project, with forward slashes; a path outside it stays as given."""
    text = str(raw or "").strip()
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(Path(root or os.getcwd()).resolve()).as_posix()
        except (OSError, ValueError):
            return text.replace("\\", "/")
    rel = path.as_posix()
    return rel[2:] if rel.startswith("./") else rel


def _file_tool_path(name: str, args: Any, root: str | Path | None) -> str:
    """The project-relative file a read, write or edit tool call names, or ``""`` for any other call."""
    if _canonical_code_tool_name(name) not in _FILE_READ_TOOLS | _FILE_WRITE_TOOLS or not isinstance(args, dict):
        return ""
    for key in ("path", "file_path", "file", "filename"):
        if args.get(key):
            return _project_path(args[key], root)
    return ""


def _line_counts(name: str, args: Any, result: str, *, new_file: bool) -> dict[str, int]:
    """``added``/``removed`` for a successful write or edit, when cheaply known; ``{}`` when not.

    An edit reports its own line counts ("Replaced N line(s) with M line(s)"). A whole-file write is counted only
    when the file is new: over an existing file the true difference is unknown, and a guess would read as fact."""
    canonical = _canonical_code_tool_name(name)
    if canonical == "diff.create":
        match = _REPLACED_LINES.search(result or "")
        return {"removed": int(match.group(1)), "added": int(match.group(2))} if match else {}
    if canonical in {"fs.write_file", "fs.write_protected_file"} and new_file and isinstance(args, dict):
        return {"added": len(str(args.get("content") or "").splitlines()), "removed": 0}
    return {}


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


def _tool_result_display(data: dict[str, Any]) -> dict[str, Any]:
    """Keep invocation success separate from a check's verification verdict."""
    display: dict[str, Any] = {
        "text": str(data.get("result") or "")[:500],
        "is_error": not bool(data.get("ok", True)),
    }
    if data.get("tool_name") != "check.run" or display["is_error"]:
        return display
    # result is only the first 4,000 chars; result_text holds the full receipt.
    # Verification feedback may follow the JSON, so decode its first value.
    raw = str(data.get("result_text") or data.get("result") or "").lstrip()
    try:
        receipt, _end = json.JSONDecoder().raw_decode(raw)
    except ValueError:
        receipt = None
    if (
        isinstance(receipt, dict)
        and receipt.get("status") in ("queued", "running")
        and receipt.get("passed") is None
        and "exit_code" not in receipt
    ):
        # No verdict yet: the tests wait their turn in the line of test runs, or are still going (check_run._not_yet).
        # That is neither a failed check nor a passed one: the row says it is waiting, and nothing counts a failure.
        display.update(
            check=str(receipt.get("check") or ""),
            waiting=str(receipt["status"]),
            text=str(receipt.get("message") or display["text"])[:500],
        )
        return display
    if (
        not isinstance(receipt, dict)
        or type(receipt.get("exit_code")) is not int
        or type(receipt.get("passed")) is not bool
        or receipt["passed"] != (receipt["exit_code"] == 0)
    ):
        display.update(is_error=True, text=("Check verdict unavailable. " + display["text"])[:500])
        return display
    display.update(
        is_error=not receipt["passed"],
        check=str(receipt.get("check") or ""),
        exit_code=receipt["exit_code"],
        passed=receipt["passed"],
    )
    return display


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

    def __init__(self, emit: Callable[[dict[str, Any]], None], *, root: str | Path | None = None) -> None:
        from thomas.core.events import EventType

        self.yielded_for_reload = False
        self._emit = emit
        # How long the model takes to put its first words, thought or tool call on the stream after the loop began.
        # Recorded once, so a slow first reply can be told apart from a slow start (steps-YYYYMMDD.jsonl).
        self._begun = time.monotonic()
        self._first_output_seen = False
        # Called with (tokens in the prompt, the model's window) at every model call; the lead's run sets it so the
        # header can show how much of the context window is left. A helper's translator leaves it unset.
        self.context_sink: Callable[[Any, Any, Any], None] | None = None
        # Called once when a pass ends with (prompt, completion, total tokens, seconds the pass took), and once with the
        # seconds to the first output. The lead's run sets both so the home slideshow can show real speed and usage.
        self.usage_sink: Callable[[int, int, int, float], None] | None = None
        self.first_output_sink: Callable[[float], None] | None = None
        # Where this loop's file tools resolve paths: the project (the runner's cwd) for the lead, a builder's
        # private snapshot for a builder. Event paths are given relative to it.
        self._root = root
        # tool_id -> the call's parsed arguments, kept from its classification for the result line.
        self._call_args: dict[str, Any] = {}
        # tool_id -> True when a whole-file write began on a file that did not exist yet.
        self._new_file: dict[str, bool] = {}
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
        # tool_id -> tool name, from the call's start, for the ``tool_started`` line its end writes.
        self._call_names: dict[str, str] = {}
        # True once we've forwarded token-progressive ``say`` deltas for the current
        # prose run, so the boundary flush does NOT re-emit the same text as a block.
        self._streamed_say = False
        self.rc = 0
        self.final_text = ""
        # How the pass ended early, when it did (pass_endings): the engine turns it into a decision -- another pass,
        # a question for you, or an honest stop -- instead of ending the Build on "agent loop exited 1".
        self.ending: Any = None
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
            self._emit({FORGE_EVENT_KEY: "say", "text": text, "source": "model"})

    def _flush_think(self) -> None:
        # The reasoning accumulated since the last boundary is ONE block: distil its
        # insight (gated) and emit the collapsed reason via the SHARED helper. Flush
        # BEFORE a tool flips the observation gate so pre-observation reasoning stays
        # plan (no card) and post-observation reasoning is insight-eligible.
        text = "".join(self._think_buf).strip()
        self._think_buf.clear()
        for ev in _thinking_to_events(text, self._state):
            self._emit(ev)

    def _started(self, tool_id: str, arguments: Any = "") -> None:
        """Write which step is starting, so a long one is visible while it runs (2026-10-26: "you should be able to
        see every single thing he is doing at any moment"). Only the result line was written, so a 10-minute test run
        was silence until it ended. The arguments stay buffered for the result's classification; a provider that
        streams no argument deltas sends them whole with the call's end, which is what is shown then."""
        from thomas.agent.loop_tool_exec import parse_tool_args

        name = self._call_names.get(tool_id, "")
        raw = "".join(self._tool_args_buf.get(tool_id, [])) or arguments
        args, _parse_error = parse_tool_args(raw) if raw else (None, None)
        path = _file_tool_path(name, args, self._root)
        if path and _canonical_code_tool_name(name) != "diff.create":
            # Seen before the call runs: whether a whole-file write creates the file decides its line counts.
            self._new_file[tool_id] = not (Path(self._root or os.getcwd()) / path).exists()
        self._emit(
            {
                FORGE_EVENT_KEY: "tool_started",
                "name": name,
                "text": _summarize_agent_event_tool(name, args),
                **({"path": path} if path else {}),
            }
        )

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
            self._call_args[tool_id] = args
        if _is_lead_tool(tool_name):
            # plan.update and ask.user only talk to you; a run that used them changed nothing by doing so.
            return "read", "name"
        return tool_call_access(tool_name, args if isinstance(args, dict) else None)

    def feed(self, et: str, data: dict[str, Any] | None) -> None:
        """Translate one AgentLoop event, emitting forge events as a side effect."""
        ET = self._ET
        data = data or {}
        if not self._first_output_seen and et in (ET.TEXT_DELTA.value, ET.THINKING.value, ET.TOOL_CALL_START.value):
            self._first_output_seen = True
            from thomas.core import step_log

            step_log.record("run_first_output", seconds=time.monotonic() - self._begun, kind=str(et))
            if self.first_output_sink is not None:
                self.first_output_sink(time.monotonic() - self._begun)
        if et == ET.AGENT_ITERATION.value and self.context_sink is not None:
            self.context_sink(data.get("token_estimate"), data.get("context_window"), data.get("context_breakdown"))
        if et == ET.TEXT_DELTA.value:
            # Forward each token PROMPTLY as a progressive ``say`` delta (RAW — no
            # strip, so inter-token spaces survive). The accumulator is still kept
            # so the boundary flush knows prose was streamed (must not re-emit as block).
            piece = str(data.get("text") or "")
            if piece:
                self._say_buf.append(piece)
                self._streamed_say = True
                self._emit({FORGE_EVENT_KEY: "say", "text": piece, "delta": True, "source": "model"})
        elif et == ET.THINKING.value:
            # Accumulate reasoning deltas; they flush as one block at the next
            # boundary so the shared insight/reason rule sees a whole thought.
            self._think_buf.append(str(data.get("text") or ""))
        elif et == ET.TOOL_CALL_START.value:
            self._call_names[str(data.get("tool_id") or "")] = str(data.get("tool_name") or "")
        elif et == ET.TOOL_CALL_END.value:
            self._started(str(data.get("tool_id") or ""), data.get("arguments") or "")
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
            start_name = str(data.get("tool_name") or "")
            start_access, start_basis = (
                ("read", "name")
                if _is_lead_tool(start_name)
                else tool_call_access(start_name, start_args if isinstance(start_args, dict) else None)
            )
            start_path = _file_tool_path(start_name, start_args, self._root)
            self._emit(
                {
                    FORGE_EVENT_KEY: "tool",
                    "name": start_name or "tool",
                    "text": _summarize_agent_event_tool(data.get("tool_name"), data.get("args")),
                    "access": start_access,
                    "access_basis": start_basis,
                    **({"path": start_path} if start_path else {}),
                }
            )
            self._state.seen_observation = True
        elif et == ET.TOOL_RESULT.value:
            tool_id, tool_name = str(data.get("tool_id") or ""), str(data.get("tool_name") or "")
            access, access_basis = self._classify_call(tool_name, tool_id)
            command_excerpt = self._last_call_command.pop(tool_id, "")
            # The loop hands the executed call's arguments to its result; the streamed ones are the fallback.
            call_args = self._call_args.pop(tool_id, None)
            if isinstance(data.get("arguments"), dict):
                call_args = data["arguments"]
            new_file = self._new_file.pop(tool_id, False)
            path = _file_tool_path(tool_name, call_args, self._root)
            file_fields: dict[str, Any] = {"path": path} if path else {}
            if path and data.get("ok", True):
                file_fields.update(_line_counts(tool_name, call_args, str(data.get("result") or ""), new_file=new_file))
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
                    **_tool_result_display(data),
                    # How this call was judged for the read-only-run verdict,
                    # and on what evidence — recorded so the decision is
                    # visible in the persisted event stream instead of being
                    # re-derived (differently) by whoever reads it later.
                    "access": access,
                    "access_basis": access_basis,
                    **file_fields,
                }
            )
            # A tool RESULT is the clearest observation — following reasoning is
            # insight-eligible, mirroring the claude ``tool_result`` branch.
            self._state.seen_observation = True
        elif et == ET.MODEL_REPORTED.value:
            # The exact model the provider named (`response.model`), as the same
            # receipt a Claude Code run writes, so the turn records `model_used`
            # for GPT too. Once per distinct id, however many calls the run makes.
            found = [(str(data.get("model") or ""), "provider")]
            for ev in reported_model_events(found, self._state.engine_models):
                self._emit(ev)
        elif et == ET.STATUS.value:
            if data.get("message") == "Yielding unfinished Build run for landed-code reload.":
                self.yielded_for_reload = True
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
            if self.ending is None:
                from .pass_endings import classify_agent_error

                self.ending = classify_agent_error(data)
            self._emit({FORGE_EVENT_KEY: "error", "text": str(data.get("error") or "agent loop reported an error")})
        elif et == ET.AGENT_DONE.value:
            self._flush_think()
            self.final_text = str(data.get("text") or "")
            if self._say_buf:
                self._flush_say()
            if self.final_text:
                self._emit({FORGE_EVENT_KEY: "final", "text": self.final_text})
            report = data.get("token_report")
            if self.usage_sink is not None and isinstance(report, dict):
                self.usage_sink(
                    int(report.get("prompt_tokens") or 0),
                    int(report.get("completion_tokens") or 0),
                    int(report.get("total_tokens") or 0),
                    time.monotonic() - self._begun,
                )
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
