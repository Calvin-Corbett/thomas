"""A finished Code run must report the same status whether you watched it or not.

Two readings of one dict. The server builds the outcome of a finished run ONCE,
in ``evolve_agent_runtime._record_run_outcome``, and ships that same dict down
both routes -- ``{"type": "done", **persistence}`` on the SSE stream, and
``{**response, **persistence, "run_state": ...}`` when ``/send`` replays an
idempotency receipt for a run that had already finished. The client read it two
different ways::

    unified_code_mode.js  terminalRunStatus()   persistence_confirmed / noop / ok
    unified_code_mode.js  acceptStartedRun()    persistence_confirmed ? outcome : 'failed'

They agree on ``completed``, ``noop``, ``failed`` and ``persistence_failed``, and
split on exactly one value: ``outcome: "conversation"`` -- the run where Thomas
ANSWERS a question instead of editing anything (``ok: true``, no changed files,
``reason: "Thomas replied without changing files"``). That is not an edge case;
it is what the shipped starter "Look at the project I have selected, tell me what
it does" asks for.

Measured by driving one payload down both routes (the harness beside this file)::

    before  outcome=completed     watched status=completed    bar "Completed"
                                  finished status=completed   bar "Completed"
    before  outcome=conversation  watched status=completed    bar "Completed"
                                  finished status=conversation bar "Ready"
                                  class "tc-mode-status is-conversation"
    after   outcome=conversation  watched status=completed    bar "Completed"
                                  finished status=completed   bar "Completed"

``conversation`` is not a word the label table knows, so ``labels[status] ||
'Ready'`` fell through and the activity bar said **Ready** about a run that had
just answered, wearing an ``is-conversation`` class no stylesheet defines.
Live-vs-finished is the axis that hid it: the run you watch was always right.

``completed`` is carried through as the control. It agreed before the fix and
agrees after, so a green result here means the two routes match -- not that the
comparison is incapable of matching.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_JS = REPO_ROOT / "thomas" / "server" / "web" / "js"
CODE_JS = WEB_JS / "unified_code_mode.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "code_run_terminal_status.mjs"
# chat.html loads these ahead of the adapter; the harness has to as well, because
# the adapter configures them at load time.
SIBLINGS = (
    WEB_JS / "unified_code_lifecycle.js",
    WEB_JS / "unified_code_results.js",
    WEB_JS / "unified_code_projects.js",
    WEB_JS / "unified_code_events.js",
)


def _sources() -> str:
    """Both halves of the adapter.

    terminalRunStatus() stayed in unified_code_mode.js; the rendering it feeds
    moved to unified_code_events.js. This contract spans the pair.
    """

    return chr(10).join(
        path.read_text(encoding="utf-8")
        for path in (CODE_JS, WEB_JS / "unified_code_events.js")
    )


def _drive() -> dict[str, dict[str, dict[str, str]]]:
    result = subprocess.run(
        ["node", str(HARNESS), str(CODE_JS), *[str(path) for path in SIBLINGS]],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_an_answered_question_does_not_finish_as_ready() -> None:
    """The divergent input, and a control that could have passed.

    ``outcome: "conversation"`` used to read status ``conversation`` / bar
    ``"Ready"`` on the replayed route while the watched route read ``completed``
    / ``"Completed"``. ``outcome: "completed"`` agreed on both routes before the
    fix and still does, which is what makes the disagreement above a real
    finding rather than a check that only ever fails.
    """

    report = _drive()

    for outcome, seen in report.items():
        assert seen["watched"] == seen["finished"], (
            f"a {outcome!r} run reads {seen['watched']} while you watch it and "
            f"{seen['finished']} once it is handed back finished"
        )

    # The words, not just the agreement: an empty vocabulary on both sides would
    # agree too. A run that answered a question is a run that finished.
    assert report["conversation"]["finished"]["label"] == "Completed"
    assert report["conversation"]["finished"]["status"] == "completed"
    assert report["completed"]["finished"]["label"] == "Completed"


def test_the_run_status_vocabulary_is_never_taken_from_the_server_wording() -> None:
    """No status may be assigned from a raw server ``outcome`` word.

    The bug was not a wrong branch, it was two of them. Pinning the shared
    predicate -- and forbidding a second site from reading ``outcome`` into
    ``state.runStatus`` -- is what stops a third caller from drifting again, the
    same way ``eventFailed`` pins the icon and the heading.
    """

    code = "\n".join(
        line
        for line in _sources().splitlines()
        # This change is documented directly above itself and quotes the old
        # expression verbatim, so a scan that read its own comment would pass on
        # the strength of prose rather than behaviour.
        if not line.strip().startswith(("//", "*", "/*"))
    )

    assert "function terminalRunStatus(" in code, (
        "the shared terminal-status predicate is gone; the watched route and the "
        "finished route are free to disagree again"
    )

    assignments = [line.strip() for line in code.splitlines() if re.search(r"\bstate\.runStatus\s*=", line)]
    assert assignments, "no run-status assignments found; this scan has stopped measuring anything"

    leaking = [line for line in assignments if "outcome" in line]
    assert not leaking, (
        "a run status is being assigned from the server's outcome word, which is a "
        f"larger vocabulary than the label table: {leaking}"
    )

    # Both terminal sites must route through the one predicate: the SSE `done`
    # handler and the already-finished `/send` reply.
    assert code.count("terminalRunStatus(") == 3, (
        "expected one definition and exactly two callers of terminalRunStatus "
        "(the streamed `done` frame and the already-finished send reply)"
    )
