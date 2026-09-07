"""A build that finished must not be filed as a crash by trailing output.

``_terminal_engine_verdict`` read only the last twelve transcript lines and
returned at the first forge event it met scanning backwards. Two ordinary things
therefore turned a successful build into a recorded crash:

* one more progress event emitted after the terminal marker — the backward scan
  hit that first and returned "no verdict";
* more than twelve trailing lines of any kind (interpreter shutdown chatter,
  ``Task was destroyed``, warnings) — the marker fell outside the window.

Measured before the fix, against the live function: marker alone -> SUCCESS;
marker + 5 noise lines -> SUCCESS; marker + 13 noise lines -> no verdict, filed
as a crash; marker + ONE later progress event -> no verdict, filed as a crash.
The second is the likely one in practice.

The fail-closed property the original was protecting is kept and pinned below:
an error AFTER the terminal marker still loses the run. Its docstring cites the
day a design doc was presented as a finished game, and that must not come back.
"""

from __future__ import annotations

import json

import pytest

from thomas.server.routes.evolve_agent_runtime import _terminal_engine_verdict

TERMINAL = json.dumps({"fc": "meta", "terminal": True, "is_error": False, "text": "run finished"})
PROGRESS = json.dumps({"fc": "meta", "is_error": False, "text": "cleanup done"})
NOISE = "Exception ignored in: <function _x>"


def _error(text: str) -> str:
    return json.dumps({"fc": "error", "is_error": True, "text": text})


@pytest.mark.parametrize(
    ("label", "transcript"),
    [
        ("marker alone", TERMINAL),
        ("marker then one progress event", f"{TERMINAL}\n{PROGRESS}"),
        ("marker then five noise lines", TERMINAL + "\n" + "\n".join([NOISE] * 5)),
        ("marker then thirteen noise lines", TERMINAL + "\n" + "\n".join([NOISE] * 13)),
        ("marker then forty noise lines", TERMINAL + "\n" + "\n".join([NOISE] * 40)),
        ("marker buried by later progress", f"{TERMINAL}\n" + "\n".join([PROGRESS] * 20)),
    ],
)
def test_a_finished_run_stays_finished_whatever_trails_it(label: str, transcript: str) -> None:
    ok, cause = _terminal_engine_verdict(transcript)

    assert ok is True, f"{label}: a finished build was not recognised as finished"
    assert cause == ""


def test_an_error_after_the_marker_still_loses_the_run() -> None:
    """The fail-closed half. A crash after the finish line is still a crash."""
    transcript = f"{TERMINAL}\n{_error('engine died writing output')}"

    ok, cause = _terminal_engine_verdict(transcript)

    assert ok is False
    assert "engine died" in cause


def test_the_oldest_error_in_a_cluster_names_the_cause() -> None:
    """A loop exit is the symptom; the first failure is the reason."""
    transcript = "\n".join([_error("no route to model"), _error("agent loop exited")])

    ok, cause = _terminal_engine_verdict(transcript)

    assert ok is False
    assert cause == "no route to model"


def test_a_run_with_no_verdict_at_all_is_still_unknown() -> None:
    """Absence of evidence must not become evidence of success."""
    ok, cause = _terminal_engine_verdict("\n".join([PROGRESS, NOISE, PROGRESS]))

    assert ok is None
    assert cause == ""


def test_an_empty_transcript_is_unknown_not_successful() -> None:
    assert _terminal_engine_verdict("") == (None, "")


TOOL_FAILURE = json.dumps(
    {
        "fc": "tool_result",
        "name": "fs.read_file",
        "is_error": True,
        "text": '{"ok": false, "error": "Directory not found: tests"}',
    }
)
SAY = json.dumps({"fc": "say", "text": "Checking the tests folder."})


def test_a_missing_file_is_not_a_dead_engine() -> None:
    """The symptom Calvin hit: "continue" ending the turn on every missing path.

    A build that looked for a tests/ directory that does not exist got the whole
    turn filed as "the run crashed before finishing — {"ok": false, "error":
    "Directory not found: tests"}". A tool reporting a missing path is an
    ordinary result the agent reads and works around, not the engine dying.
    """
    ok, cause = _terminal_engine_verdict("\n".join([SAY, TOOL_FAILURE, SAY]))

    assert ok is not False, f"a failed tool call was read as a crashed engine: {cause}"
    assert "Directory not found" not in cause


def test_a_tool_failure_does_not_outvote_a_finished_run() -> None:
    ok, _ = _terminal_engine_verdict("\n".join([SAY, TOOL_FAILURE, TERMINAL]))

    assert ok is True


def test_a_real_engine_error_after_a_tool_failure_still_fails() -> None:
    """Excluding tool frames must not blind the verdict to an actual death."""
    transcript = "\n".join([SAY, TOOL_FAILURE, _error("engine died")])

    ok, cause = _terminal_engine_verdict(transcript)

    assert ok is False
    assert "engine died" in cause
