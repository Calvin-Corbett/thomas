"""Forge-event streaming: wire protocol, insight distillation, claude stream-json translation.

A forge event is a single JSON object printed on its own line to the dispatch process's
stdout, flushed the instant it is produced. Each is ``{"fc": <kind>, ...}`` where kind is:
  * ``say``         — the agent's natural-language message text
  * ``reason``      — the agent's private reasoning (rendered collapsed/optional)
  * ``insight``     — a MID-TASK INSIGHT: the model's salient interim observation,
                      surfaced LIVE from the SAME reasoning stream as ``reason``.
  * ``tool``        — a tool/edit CALL: ``{"name": str, "text": <summary>}``
  * ``tool_result`` — a tool RESULT: ``{"text": str, "is_error": bool}``
  * ``error``       — an error surfaced by the agent / CLI
  * ``meta``        — a MEANINGFUL build-status line from the engine itself
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

FORGE_EVENT_KEY = "fc"


def _default_emit(event: dict[str, Any]) -> None:
    """Print one forge event as a flushed JSON line to stdout (the wire).

    Written as explicit UTF-8 *bytes* to ``sys.stdout.buffer`` rather than as text
    via ``sys.stdout.write``. On Windows the text layer may default to cp1252, so a
    TEXT write of an em-dash encodes to the SINGLE cp1252 byte ``0x97`` — not UTF-8
    ``E2 80 94``. Writing to ``.buffer`` emits UTF-8 bytes regardless of the text
    layer's code page, so every glyph survives on every platform.
    """
    import sys

    line = json.dumps(event, ensure_ascii=False) + "\n"
    try:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write(line.encode("utf-8"))
            buffer.flush()
        else:
            sys.stdout.write(line)
            sys.stdout.flush()
    except (OSError, ValueError, RuntimeError, UnicodeError):
        pass


def _summarize_tool_input(inp: Any) -> str:
    """Compact, human-readable summary of a tool_use input (path/command/etc.)."""
    if not isinstance(inp, dict):
        return ""
    for key in ("file_path", "path", "notebook_path", "pattern", "command", "url", "query", "prompt"):
        val = inp.get(key)
        if val:
            return f"{key}: {str(val)[:200]}"
    try:
        return json.dumps(inp, ensure_ascii=False)[:200]
    except (TypeError, ValueError):
        return ""


def _flatten_tool_result(content: Any) -> str:
    """Flatten a tool_result content (str | list[block]) to a short string."""
    if isinstance(content, str):
        return content[:500]
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            if isinstance(c, dict):
                parts.append(str(c.get("text") or c.get("content") or ""))
            else:
                parts.append(str(c))
        return "\n".join(p for p in parts if p)[:500]
    return str(content or "")[:500]


# Sentence OPENERS that mark a clause as task-restatement or bare INTENT (a
# preamble) rather than a genuine observation. Used ONLY to SUPPRESS a weak
# first-insight candidate — never to select one. The model's own reactive
# observations still surface organically; this just drops the "The user wants…",
# "I'll…", "I need to…", "Let me…", "First I'll…" preambles so the FIRST insight
# card is something the model OBSERVED, not a restatement of the prompt. Matching
# is STRUCTURAL (sentence-opener only), never a content/sentiment gate, so it
# respects the no-keyword-UX law: any genuine reasoning can still surface and none
# is required to contain a magic word. Note "I'm noticing…", "I see…", "I found…",
# "Looking at…" are deliberately NOT here — those are reactions, not preambles.
_INSIGHT_PREAMBLE_RE = re.compile(
    r"^(?:"
    r"i['']ll\b|i will\b|i['']m going to\b|i am going to\b|"
    r"i['']m about to\b|i need to\b|i have to\b|i want to\b|i should\b|"
    r"i must\b|i['']d like to\b|i plan to\b|i intend to\b|"
    r"let me\b|let['']s\b|let us\b|"
    r"first[,\s]+i\b|next[,\s]+i\b|then[,\s]+i\b|"
    r"now i['']ll\b|now let me\b|now i need\b|now i will\b|"
    r"the user\b|the task\b|the goal\b|the request\b|the prompt\b|"
    r"my task\b|my goal\b|my job\b|"
    r"we need to\b|we should\b|we['']ll\b|we will\b|"
    r"i['']m asked\b|i was asked\b|i['']m being asked\b|"
    # Bare IMPERATIVE "go look here" openers — the model talking to itself about
    # WHERE to look before it has looked ("Examine `thomas/forge/anvil`",
    # "Check the imports", "Read the loader", "Look at the router"). This is the
    # same preamble as "I'll examine…", just shorn of the subject, so it is the
    # same task-restatement/intent and is suppressed identically. Base-form verbs
    # only, anchored by ``\b``, so the gerund REACTIONS that must survive
    # ("Looking at…", "Examining…", "Reading…") never match — they are not
    # imperatives and carry a real observation.
    r"examine\b|inspect\b|explore\b|investigate\b|review\b|analy[sz]e\b|"
    r"check\b|read\b|open\b|look\b|search\b|scan\b|find\b|locate\b|identify\b|"
    r"start by\b|begin by\b"
    r")",
    re.IGNORECASE,
)


def _is_intent_or_restatement(sentence: str) -> bool:
    """True iff ``sentence`` merely restates the task or states bare intent."""
    return bool(_INSIGHT_PREAMBLE_RE.match(sentence.strip()))


def _strip_list_artifacts(sentence: str) -> str:
    """Strip enumeration/list scaffolding off a candidate insight sentence.

    A distilled clause must never carry a bare LIST NUMBER — the model's plan is
    often an enumeration ("1. … 2. … 3. …") and when a list item bleeds into the
    insight it arrives with a dangling marker. The strip is WORD-BOUNDARY AWARE:
    a number only counts as enumeration when it is a STANDALONE token bounded by
    whitespace / start / end / clause punctuation. A digit run that is hyphen-glued
    to a word — "UTF-8", "cp1252", "base-64" — is part of an IDENTIFIER and is
    left intact.
    """
    s = sentence.strip()
    # Leading list marker at the very start of the clause: "3." / "2)" / "1 - ".
    s = re.sub(r"^\d+\s*[.)\]:]\s+", "", s)  # "3." / "2)" / "1]" / "4:"
    s = re.sub(r"^\d+\s*[-–]\s+", "", s)  # "1 - " (dash marker, requires trailing space)
    # Trailing dangling marker: a separate token preceded by WHITESPACE at end-of-string.
    # The leading \s+ is mandatory, so a hyphen-glued digit ("UTF-8") is never matched.
    s = re.sub(r"\s+[-–]?\s*\d+\s*[.)]?\s*$", "", s)  # trailing " 3." / " - 2)"
    return s.strip()


def _distill_insight(thinking: str) -> str:
    """Pick the model's salient interim OBSERVATION out of a ``thinking`` block.

    Deliberately ORGANIC, NOT a keyword scan: we do NOT require any trigger phrase
    ("I notice", "I think"), we never rank by sentiment words, and we never invent
    text. We segment the model's OWN reasoning into sentences and return the first
    that reads as a real observation.

    TUNED FOR GENUINE OBSERVATIONS (not prompt-restatement): preambles are SKIPPED
    via ``_is_intent_or_restatement`` so the surfaced insight reacts to what was
    actually observed/decided. Thin OR still-just-planning reasoning distils to
    ``""`` and NO insight card is fabricated.
    """
    text = " ".join(str(thinking or "").split())  # collapse newlines/runs of space
    if not text:
        return ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        s = _strip_list_artifacts(sentence.strip())
        # A salient observation is a real clause, not a throwaway fragment...
        if len(s) < 24 or len(s.split()) < 4:
            continue
        # ...and not a task-restatement / bare-intent preamble.
        if _is_intent_or_restatement(s):
            continue
        return s[:240]
    return ""


# Two distilled insights count as the SAME beat (a repeat) when their normalized
# word sets overlap this much or more (Jaccard).
_INSIGHT_DEDUP_THRESHOLD = 0.5


def _insight_word_set(text: str) -> frozenset[str]:
    """Normalize an insight to its set of word tokens for similarity comparison."""
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def _insights_similar(a: frozenset[str], b: frozenset[str]) -> bool:
    """True iff two normalized insight word-sets are near-identical (same beat)."""
    if not a or not b:
        return a == b
    inter = len(a & b)
    union = len(a | b)
    return union > 0 and (inter / union) >= _INSIGHT_DEDUP_THRESHOLD


@dataclass
class _StreamState:
    """Per-RUN state for structural insight gating, carried across every line.

    A genuine "I'm noticing…" insight can only exist AFTER the model has OBSERVED
    something. The FIRST reasoning block of a run is always the model's PLAN —
    produced before it has read a file or seen a tool result — so we suppress
    insights POSITIONALLY rather than by phrasing:

      * ``seen_observation`` flips True at the run's first tool_use / tool_result.
        Reasoning before that flip is the plan and yields NO insight (its full
        ``reason`` is still emitted); only reasoning that FOLLOWS an observation is
        insight-eligible.
      * ``insight_keys`` dedupes within the run: a distilled insight whose word-set
        is near-identical to one already surfaced is dropped.

    A fresh state is created per dispatch pass (each pass re-plans), so the gate
    resets cleanly between the initial edit and any fix passes.
    """

    seen_observation: bool = False
    insight_keys: list[frozenset[str]] = field(default_factory=list)
    # True once we've streamed token-progressive ``say`` deltas for the CURRENT
    # assistant text block. It lets us SUPPRESS the duplicate COMPLETE text block
    # that arrives right after — the deltas already carried that text live.
    pending_text_delta: bool = False

    def admit_insight(self, insight: str) -> bool:
        """True iff this distilled insight may surface NOW (post-observation, novel)."""
        if not self.seen_observation:
            return False  # pre-observation reasoning is the plan, never an insight
        key = _insight_word_set(insight)
        if any(_insights_similar(key, prior) for prior in self.insight_keys):
            return False  # same beat as an already-surfaced insight -> drop the repeat
        self.insight_keys.append(key)
        return True


def _thinking_to_events(thinking: str, state: _StreamState | None) -> list[dict[str, Any]]:
    """Translate ONE complete reasoning block into forge events — the SHARED
    thinking→(insight + reason) rule that BOTH first-class engines call.

    This is the single source of truth for the mid-task "I'm noticing…" trust beat,
    so the claude stream-json path and the GPT in-process ``AgentLoop`` path stay in
    lockstep forever: a change to the insight rules here updates BOTH engines at once.
    """
    events: list[dict[str, Any]] = []
    txt = str(thinking or "").strip()
    if not txt:
        return events
    insight = _distill_insight(txt)
    if insight and (state is None or state.admit_insight(insight)):
        events.append({FORGE_EVENT_KEY: "insight", "text": insight})
    events.append({FORGE_EVENT_KEY: "reason", "text": txt})
    return events


def translate_claude_event(line: str, state: _StreamState | None = None) -> list[dict[str, Any]]:
    """Translate one ``claude -p --output-format stream-json`` line into forge events.

    Defensive: a non-JSON / unexpected line degrades to a single ``say`` event so
    the stream keeps flowing rather than dying on one bad line.

    ``state`` carries per-run structural insight gating across lines. When provided
    (the live/dispatch path, via ``ClaudeStreamTranslator``) an insight is surfaced
    ONLY from reasoning that follows the run's first tool observation, and
    near-duplicate insights are deduped. When ``None`` (a one-off, single-line
    translation) there is no run to position within.
    """
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return [{FORGE_EVENT_KEY: "say", "text": line}]
    if not isinstance(obj, dict):
        return [{FORGE_EVENT_KEY: "say", "text": str(line)}]

    etype = obj.get("type")
    events: list[dict[str, Any]] = []
    if etype == "system":
        # Internal session/init/hook plumbing — noise to a human watching a build;
        # dropped entirely and produces no forge event.
        pass
    elif etype == "assistant":
        for block in (obj.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                if state is not None and state.pending_text_delta:
                    # The token-progressive deltas already carried this whole block
                    # live — re-emitting the complete text would double it.
                    state.pending_text_delta = False
                    continue
                txt = str(block.get("text") or "").strip()
                if txt:
                    events.append({FORGE_EVENT_KEY: "say", "text": txt})
            elif btype == "thinking":
                # SHARED with the GPT in-process path: one reasoning block ->
                # optional distilled insight (structurally gated) ABOVE the full
                # collapsed reason. Rules live in ONE place so both engines move together.
                events.extend(_thinking_to_events(block.get("thinking"), state))
            elif btype == "tool_use":
                events.append(
                    {
                        FORGE_EVENT_KEY: "tool",
                        "name": str(block.get("name") or "tool"),
                        "text": _summarize_tool_input(block.get("input")),
                    }
                )
                # The run has now OBSERVED (acted): reasoning after this point is
                # eligible to surface as an insight; reasoning before it was plan.
                if state is not None:
                    state.seen_observation = True
    elif etype == "stream_event":
        # TOKEN-PROGRESSIVE streaming (claude ``--include-partial-messages``): forward
        # each text_delta as a ``say`` DELTA (RAW — never ``.strip()``, which would
        # swallow the spaces between tokens) so the transcript fills live.
        inner = obj.get("event")
        if isinstance(inner, dict) and inner.get("type") == "content_block_delta":
            delta = inner.get("delta")
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                piece = str(delta.get("text") or "")
                if piece:
                    events.append({FORGE_EVENT_KEY: "say", "text": piece, "delta": True})
                    if state is not None:
                        state.pending_text_delta = True
    elif etype == "user":
        for block in (obj.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                events.append(
                    {
                        FORGE_EVENT_KEY: "tool_result",
                        "text": _flatten_tool_result(block.get("content")),
                        "is_error": bool(block.get("is_error")),
                    }
                )
                # A tool RESULT is the clearest observation of all — mark it.
                if state is not None:
                    state.seen_observation = True
    elif etype == "result":
        is_err = bool(obj.get("is_error"))
        txt = str(obj.get("result") or "").strip()
        if is_err:
            events.append({FORGE_EVENT_KEY: "error", "text": txt or "claude reported an error"})
        elif txt:
            events.append({FORGE_EVENT_KEY: "say", "text": txt})
    return events


class ClaudeStreamTranslator:
    """A STATEFUL, per-run line translator over the claude stream-json output.

    ``translate_claude_event`` is a pure per-line function; the structural insight
    gate needs to remember things ACROSS lines (has the run observed a tool yet,
    which insights already surfaced). This wraps the per-line translator with one
    ``_StreamState`` so the gate works over the whole run. One instance is created
    per dispatch pass so the gate resets between the initial edit and any fix passes.
    """

    def __init__(self) -> None:
        self._state = _StreamState()

    def __call__(self, line: str) -> list[dict[str, Any]]:
        return translate_claude_event(line, self._state)


class _HybridByteDecoder:
    """Incrementally decode a subprocess stdout *byte* stream to text, surviving
    BOTH UTF-8 AND cp1252 output from the child CLI.

    WHY THIS EXISTS: the claude CLI is the source of the build transcript, but on
    Windows it can emit certain punctuation (em-dash ``0x97``, curly quotes
    ``0x91``–``0x94``) as SINGLE cp1252 bytes rather than UTF-8. Reading the pipe
    in text mode with ``errors="replace"`` turns each such byte into ``�`` at the
    subprocess read — BEFORE storage or streaming — so the garbling can't be undone.

    THE FIX — try UTF-8 first, cp1252 per-byte for the stragglers:
      * a byte that begins a valid UTF-8 sequence is decoded as UTF-8;
      * a byte that is NOT a valid UTF-8 lead/sequence is decoded as that ONE cp1252
        byte: an em-dash sent as ``0x97`` ALSO decodes to ``—``.

    INCREMENTAL: a multibyte UTF-8 sequence split across two read chunks is HELD
    until the bytes that complete it arrive, so a char straddling a read boundary
    is never mangled.
    """

    def __init__(self) -> None:
        self._pending = b""

    def feed(self, chunk: bytes) -> str:
        if chunk:
            self._pending += chunk
        return self._drain(final=False)

    def flush(self) -> str:
        out = self._drain(final=True)
        self._pending = b""
        return out

    def _drain(self, *, final: bool) -> str:
        buf = self._pending
        n = len(buf)
        out: list[str] = []
        i = 0
        while i < n:
            b0 = buf[i]
            if b0 < 0x80:
                length = 1
            elif 0xC2 <= b0 <= 0xDF:
                length = 2
            elif 0xE0 <= b0 <= 0xEF:
                length = 3
            elif 0xF0 <= b0 <= 0xF4:
                length = 4
            else:
                # Not a valid UTF-8 lead byte (e.g. a lone cp1252 em-dash/curly
                # quote) -> decode this ONE byte as cp1252 so it renders correctly.
                out.append(buf[i : i + 1].decode("cp1252", errors="replace"))
                i += 1
                continue
            if i + length > n:
                # An incomplete trailing multibyte sequence: hold it for the next
                # chunk. At true end-of-stream best-effort decode the truncated tail.
                if not final:
                    break
                out.append(buf[i:].decode("cp1252", errors="replace"))
                i = n
                break
            seq = buf[i : i + length]
            try:
                out.append(seq.decode("utf-8"))
            except UnicodeDecodeError:
                # Valid lead byte but the continuation bytes are not UTF-8 -> the
                # lead byte was really cp1252; consume just it and re-examine the rest.
                out.append(buf[i : i + 1].decode("cp1252", errors="replace"))
                i += 1
                continue
            i += length
        self._pending = buf[i:]
        return "".join(out)


def _stream_cli(
    cmd: list[str],
    cwd: str,
    timeout: int,
    translate: Callable[[str], list[dict[str, Any]]],
    emit: Callable[[dict[str, Any]], None],
    stdin_text: str | None = None,
) -> tuple[int, str]:
    """Run ``cmd``, reading its stdout line-by-line and emitting forge events AS
    THEY ARRIVE (never buffering the whole run). A watchdog kills the process at
    ``timeout`` so a hung CLI cannot block forever. Returns (returncode, tail).

    stdout is read in BINARY and decoded through ``_HybridByteDecoder`` (UTF-8 first,
    cp1252 per-byte fallback) so multibyte glyphs survive end-to-end.
    """
    import contextlib
    import subprocess
    import threading

    # Belt: nudge the child toward UTF-8 output. Suspenders: the hybrid decoder
    # recovers the glyphs regardless.
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    # Mark this as a dispatched, edit-only build so the coordinator inbox PreToolUse
    # gate (workboard_inbox_hook) does not wedge the builder's Edit/Write when a crew
    # message arrives mid-build (the builder can't ack — it has no shell).
    env["THOMAS_DISPATCH_BUILD"] = "1"

    proc = subprocess.Popen(  # noqa: S603 - cmd is built from a fixed CLI + safe args
        cmd,
        cwd=cwd,
        stdin=(subprocess.PIPE if stdin_text is not None else None),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    if stdin_text is not None and proc.stdin is not None:
        # Feed the (possibly very large) prompt via STDIN on a background thread.
        # Passing the prompt on argv overflows the Windows command-line limit for
        # big (e.g. funnel-composed) prompts -> [WinError 206] "filename or
        # extension is too long". Threading the write avoids a pipe-buffer deadlock
        # against our own stdout reader when the prompt exceeds the OS pipe buffer.
        def _feed_stdin() -> None:
            with contextlib.suppress(Exception):
                proc.stdin.write(stdin_text.encode("utf-8"))
                proc.stdin.flush()
            with contextlib.suppress(Exception):
                proc.stdin.close()

        threading.Thread(target=_feed_stdin, daemon=True).start()
    timed_out = {"v": False}

    def _kill() -> None:
        timed_out["v"] = True
        with contextlib.suppress(Exception):
            proc.kill()

    timer = threading.Timer(max(1, int(timeout)), _kill)
    timer.start()
    tail: list[str] = []
    decoder = _HybridByteDecoder()
    text_buf = ""

    def _handle_line(line: str) -> None:
        line = line.rstrip("\r")  # binary read keeps CRLF on Windows; drop the CR
        if not line.strip():
            return
        tail.append(line)
        del tail[:-200]  # bound memory: keep only the last 200 lines
        try:
            for ev in translate(line):
                emit(ev)
        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
            emit({FORGE_EVENT_KEY: "say", "text": line})

    try:
        assert proc.stdout is not None
        # read1 returns whatever bytes are available in one underlying read (not a
        # full buffer), preserving the live, as-it-arrives streaming property.
        for chunk in iter(lambda: proc.stdout.read1(65536), b""):
            text_buf += decoder.feed(chunk)
            *lines, text_buf = text_buf.split("\n")
            for line in lines:
                _handle_line(line)
        text_buf += decoder.flush()
        for line in text_buf.split("\n"):
            _handle_line(line)
        proc.wait()
    finally:
        timer.cancel()
    rc = proc.returncode if proc.returncode is not None else 0
    if timed_out["v"]:
        emit({FORGE_EVENT_KEY: "error", "text": f"build timed out after {timeout}s — process killed"})
        rc = rc or 124
    return rc, "\n".join(tail)[-2000:]
