"""A task that is only waiting must not get a permanent "Task failed" card.

One decision -- "is this run over, and did it fail" -- is spelled out in two
places in the classic shell's runtime, and they disagreed about ``blocked``:

    013_actions_interactions_02.js  _delegationIsTerminalState
        completed | verified | failed | abandoned | cancelled | canceled | done
        -> blocked is NOT terminal.  Correct.

    006_easy_setup_onboarding_04.js appendTerminalDelegationActivityResults
        gated on chatTaskIsTerminal (003_easy_setup_onboarding_01.js), whose list
        DOES include blocked, then computed
            failed = state === 'failed' || state === 'blocked' || ...

So the Mission-Control poll fallback wrote a permanent "Task failed" into the
chat transcript for a task that was merely waiting on an approval gate, while
the live SSE stream and the supervisor both still considered it running.

The state machine settles it, not taste: ``task_bot_runtime.ALLOWED_TRANSITIONS``
lets ``blocked`` go back to ``queued`` / ``claimed`` / ``executing``, and
``blocked`` is absent from ``TERMINAL_STATES``.

These files are live code, not a dead bundle: ``index.html`` loads
``app_runtime_loader.js``, which pulls every module from ``/static/js/runtime/``,
and that shell "still hosts every workspace and is served at /classic"
(app_middleware_helpers.py). The near-identical copy in
``js/app_runtime_primary.mjs`` has no importer anywhere and is deliberately left
alone.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
FALLBACK = RUNTIME / "006_easy_setup_onboarding_04.js"
STREAM = RUNTIME / "013_actions_interactions_02.js"


def _code(path: Path) -> str:
    """Source minus comments -- the change is documented above itself and the
    prose quotes the very expression under test."""

    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def _failed_expression() -> str:
    code = _code(FALLBACK)
    match = re.search(r"const failed = ([^;]+);", code)
    assert match, "the fallback no longer computes a `failed` flag"
    return match.group(1)


def test_the_live_path_still_does_not_treat_blocked_as_terminal() -> None:
    """The reference spelling. If this changes, the premise changes with it."""

    match = re.search(
        r"function _delegationIsTerminalState\(state\)\s*\{(.*?)\n {8}\}",
        _code(STREAM),
        re.S,
    )
    assert match, "_delegationIsTerminalState is gone"
    assert "'blocked'" not in match.group(1), (
        "the live SSE path now calls `blocked` terminal, which would make a "
        "waiting task look finished on the stream too"
    )


def test_a_blocked_task_is_not_written_into_the_transcript_at_all() -> None:
    code = _code(FALLBACK)
    match = re.search(r"if \(!chatTaskIsTerminal\(state\)([^)]*)\) return;", code)
    assert match, "the terminal gate in the fallback is gone"
    assert "blocked" in match.group(1), (
        "the fallback still admits `blocked` as an ending. chatTaskIsTerminal "
        "includes it, so a task merely waiting on an approval gate gets a "
        "permanent card written into the chat transcript."
    )


def test_a_blocked_task_is_never_called_failed() -> None:
    assert "'blocked'" not in _failed_expression(), (
        "a blocked task is still reported as failed. ALLOWED_TRANSITIONS lets "
        "`blocked` return to queued/claimed/executing, and it is not in "
        f"TERMINAL_STATES. Got: {_failed_expression()!r}"
    )


def test_a_genuine_failure_is_still_called_failed() -> None:
    """The opposite failure: reporting nothing as a failure."""

    expression = _failed_expression()
    for state in ("failed", "dead"):
        assert f"'{state}'" in expression, (
            f"{state!r} is no longer reported as a failure: {expression!r}"
        )


def test_the_cancelled_question_is_recorded_rather_than_silently_settled() -> None:
    """It is still called a failure, and that is a known, documented choice.

    The card is binary, so saying it truthfully needs a third result type.
    Calling a run you stopped "failed" is wrong; "completed" is also wrong.
    If someone adds that third type, this test should be deleted along with the
    comment -- it exists so the compromise cannot go quiet.
    """

    source = FALLBACK.read_text(encoding="utf-8")
    assert "cancelled" in _failed_expression(), (
        "cancelled is no longer grouped with failures -- if that was deliberate, "
        "update this test and the comment beside it"
    )
    assert "KNOWN, NOT FIXED HERE" in source, (
        "the note explaining why `cancelled` is still called a failure is gone, "
        "leaving an undocumented falsehood in the transcript"
    )
