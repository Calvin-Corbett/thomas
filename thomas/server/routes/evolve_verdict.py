"""How a finished build is told apart from a crashed one.

Lifted out of ``evolve_agent_runtime.py`` when that routes module passed the
800-line soft limit its own monolith guard enforces — the first change that gate
caught after it was repaired to scan the repository instead of its own folder.

The verdict rule, in one place so it can be read and tested on its own: find the
runner's terminal marker wherever it appears in the transcript, then let anything
that failed after it win. A crash that wrote some files first is still a crash.
"""

from __future__ import annotations

import json


def _terminal_engine_verdict(transcript_text: str) -> tuple[bool | None, str]:
    """Return the runner's explicit terminal verdict and failure cause.

    ``True`` means the marked runner verdict says success, ``False`` means it
    says failure, and ``None`` means the process died before it emitted one.
    A marked Claude success can outvote its unreliable exit 1; exit 1 plus a
    traceback and partial files must fail closed.
    Changed files must not outrank THIS signal — a crash that wrote some
    files first is still a crash, and filing it "completed" is how a design
    doc got presented as a finished game (2026-08-10, twice in one task).
    """
    # Find the verdict wherever it is, then let anything that failed AFTER it win.
    #
    # This used to read the last twelve lines and return at the first forge event
    # it met scanning backwards, which made two ordinary things fatal: one more
    # progress event after the terminal marker (the scan hit that first and gave
    # up), or thirteen trailing lines of interpreter-shutdown chatter (the marker
    # fell outside the window). Both filed a finished build as a crash. Measured
    # 2026-08-14: marker + 1 progress event -> no verdict; marker + 13 noise
    # lines -> no verdict; marker alone -> success.
    #
    # The fail-closed rule the old shape was protecting is unchanged and now
    # explicit: an error after the marker still loses the run, because a crash
    # that wrote some files first is still a crash.
    events: list[tuple[int, dict]] = []
    for index, raw_line in enumerate(transcript_text.strip().splitlines()):
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and "fc" in event:
            events.append((index, event))

    def _is_error_event(event: dict) -> bool:
        # A failed TOOL call is not a dead engine. `tool_result` frames carry
        # is_error whenever the tool itself reported a problem — a missing file,
        # an absent directory — which the agent reads and works around. Counting
        # those as engine deaths ended the whole turn and told the owner "the run
        # crashed before finishing — {"ok": false, "error": "Directory not found:
        # tests"}", so typing "continue" produced the same ending on the next
        # missing path. Observed on a real build, 2026-08-14.
        #
        # _confirmed_conversation_reply in evolve_agent_runtime already draws
        # this line, tracking tool failures as their own signal rather than as a
        # crash. Draw it the same way here.
        if str(event.get("fc") or "") in ("tool", "tool_result"):
            return False
        return event.get("fc") == "error" or event.get("is_error") is True

    def _is_terminal_success(event: dict) -> bool:
        if _is_error_event(event):
            return False
        if event.get("terminal") is True:
            return True
        text = str(event.get("text") or "").strip()
        if event.get("fc") == "final" and text:
            return True  # Claude protocol success, before runner markers
        return (
            event.get("fc") == "meta"
            and event.get("is_error") is False
            and text.startswith("dispatched via claude CLI (")
        )  # legacy pre-marker runner transcript

    terminal_index = -1
    for index, event in events:
        if _is_terminal_success(event):
            terminal_index = index  # keep the last one; a rerun may mark twice

    # The oldest error in the deciding cluster names the root cause (the dead
    # LLM route); the newest is the generic loop exit.
    def _causes_after(threshold: int) -> list[str]:
        return [
            str(event.get("text") or "").strip()
            for index, event in events
            if index > threshold and _is_error_event(event) and str(event.get("text") or "").strip()
        ]

    if terminal_index >= 0:
        later_failures = _causes_after(terminal_index)
        if later_failures:
            return False, later_failures[0][:220]
        return True, ""

    all_failures = _causes_after(-1)
    if all_failures:
        return False, all_failures[0][:220]
    return None, ""


def _unstructured_engine_error(transcript_text: str) -> str:
    """Return the final exception line when a runner died with a traceback."""

    marker = "Traceback (most recent call last):"
    if marker not in transcript_text:
        return ""
    traceback_tail = transcript_text.rsplit(marker, 1)[-1]
    for line in reversed(traceback_tail.splitlines()):
        text = line.strip()
        if text and not text.startswith("File "):
            return text[:220]
    return "unhandled Python traceback"
