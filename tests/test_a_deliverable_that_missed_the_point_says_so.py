"""Thomas tells you when a deliverable shares no subject with your request.

The changelog promised this: "Thomas no longer calls a deliverable 'verified'
when it has nothing to do with what you asked ... A deliverable is now also
checked against the subject of the request, and fails when it shares nothing
with it."

That guarantee stopped existing on 2026-07-27. `6cc89af2` shipped
``chat_delegation_artifact_intent`` WITH a call site inside
``_hidden_completion_review_passes``, where a mismatch scored the review 0.0 and
failed the run. `87ae37e5` replaced that whole file with a branch version written
before the gate existed, and the call site went with it. The module has had no
production caller since.

**It is reconnected here as a REPORT, not as a gate**, and that distinction is
the point rather than a compromise. The measurement is a token overlap. A
verification probe that rejects a run on that basis grades the model instead of
reporting honestly, and restoring the original wiring flips a real recorded case
from pass to fail. So `verified_success` is untouched and the owner is simply
told, in the run summary, beside the executability warning that already works
exactly this way.

Measured, with the request "make me a graph of current technology adoption
trends" answered two ways::

    an arcade game     -> "⚠ This may not be what you asked for — game.html does
                           not appear to be about what was asked (matched 0 of
                           the requested subject: adoption, current, graph,
                           technology, trends)."
    a real trend page  -> silent

`artifact_intent_issues` returns [] whenever the question cannot be answered
honestly -- no request, no artifacts, a request too vague to have a subject,
unreadable files. Silence means "not checkable", never "checked and fine", and
the controls below pin that so the warning cannot quietly become unconditional.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from thomas.server import chat_delegation_runner
from thomas.server.chat_delegation_deliverable_postprocess import subject_mismatch_warning

_ASK = "make me a graph of current technology adoption trends"

_GAME = (
    "<html><body><h1>Zombie Arcade</h1>"
    "<p>Shoot the zombies before they reach the barricade. Press space to fire, "
    "arrow keys to move. Your high score is saved locally.</p>"
    "<canvas id=arcade></canvas><script>const zombies=[];</script></body></html>"
)
_TRENDS = (
    "<html><body><h1>Technology adoption trends</h1>"
    "<p>Current adoption of cloud, AI and edge technology over five years.</p>"
    "<table><tr><td>cloud</td><td>62%</td></tr></table></body></html>"
)


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "game.html").write_text(_GAME, encoding="utf-8")
    (tmp_path / "trends.html").write_text(_TRENDS, encoding="utf-8")
    return tmp_path


def test_an_arcade_game_answered_for_a_graph_request_is_flagged(tmp_path: Path) -> None:
    warning = subject_mismatch_warning(_ASK, _workspace(tmp_path), ["game.html"])
    assert warning, "a deliverable sharing no subject with the request produced no warning"
    assert "game.html" in warning
    assert "what you asked for" in warning


def test_the_deliverable_that_actually_answers_is_not_flagged(tmp_path: Path) -> None:
    """The control. Without this, the test above only proves the warning is loud."""

    assert subject_mismatch_warning(_ASK, _workspace(tmp_path), ["trends.html"]) == "", (
        "the genuine answer to the request was flagged as off-topic, which would "
        "train the reader to ignore this line"
    )


def test_it_stays_silent_when_the_question_cannot_be_answered(tmp_path: Path) -> None:
    """Silence means "not checkable", never "checked and fine"."""

    root = _workspace(tmp_path)
    assert subject_mismatch_warning("do it", root, ["game.html"]) == "", "a vague request has no subject to match"
    assert subject_mismatch_warning("", root, ["game.html"]) == "", "no request means nothing to compare against"
    assert subject_mismatch_warning(_ASK, root, []) == "", "no artifacts means nothing to check"
    assert subject_mismatch_warning(_ASK, None, ["game.html"]) == "", "no workspace means nothing to read"


def test_it_reports_and_never_gates() -> None:
    """`verified_success` must not be computed from this.

    A probe that rejects a run on a token overlap grades the model rather than
    reporting honestly, and reconnecting the original wiring flips a real
    recorded case from pass to fail. If someone later folds this into the
    verdict, that should be a deliberate decision that has to delete this test.
    """

    # The CALL, not the import-list entry. A bare `    subject_mismatch_warning,`
    # inside a multi-line `from ... import (` block contains neither the word
    # "import" nor a paren, and matching it made this test read the wrong line.
    source = inspect.getsource(chat_delegation_runner)
    call = next(
        (
            line
            for line in source.splitlines()
            if "subject_mismatch_warning" in line and "(" in line and "import" not in line
        ),
        "",
    )
    assert call, "the subject check is no longer called from the delegation runner"
    assert "verified_success" not in call, (
        f"the subject warning now feeds the verdict: {call.strip()!r}. It reports; "
        "it must not gate."
    )
    assert "_exec_warnings" in call or "result_summary" in call, (
        "the subject warning no longer reaches the run summary, so the owner is "
        "not actually told"
    )
