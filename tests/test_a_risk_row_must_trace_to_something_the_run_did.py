"""An open risk must trace to something the run actually did.

Measured on the 2026-08-05 audit: an explain-only run — outcome
``conversation``, a confirmed final reply, zero changed files — carried a
build-verification card whose only two "open risks" were manufactured by the
harness's own bookkeeping, not by anything the run did:

* the Claude CLI exits 1 even on runs whose answer landed (the runtime route
  already calls the exit code "the weakest evidence there is" and outranks it
  with git truth and the confirmed reply), yet ``_build_open_risks`` still
  turned that same exit code back into "run exited non-zero (1)";
* the CLI's empty ``result`` error was translated into the harness's own
  stand-in sentence ("claude reported an error" — forge_event_stream falls back
  to it when the error event carried NO text at all), and that stand-in became
  "error surfaced during the run".

Neither row describes the run. Both rows describe the harness. The same shape
applies to a ``stopped`` run: the kill signal's exit code is the person's
decision, and the route records it in those words — the risk list must not
re-file the person's stop as the run's error.

Real negatives stay. An error event that carries the run's own words is still a
risk, and a completed run's non-zero exit is still a risk — the controls below
prove both survive, so this is removing fabricated rows, not softening honest
ones.

The report also now carries ``outcome`` so the card can tell what KIND of run
it is grading (an answer is not a build; a stop is not a failure).
"""

from __future__ import annotations

from typing import Any

from thomas.forge.anvil.run_report import build_run_report

# A minimal explain-only stream: the model answered, no tools mutated anything,
# and the CLI's empty is_error result became the harness's fallback sentence.
_ANSWER_EVENTS: list[dict[str, Any]] = [
    {"fc": "say", "text": "This project is a Vite app with three routes."},
    {"fc": "final", "text": "This project is a Vite app with three routes."},
    {"fc": "error", "text": "claude reported an error"},
]


def _risk_names(report: dict[str, Any]) -> list[str]:
    return [str(risk.get("risk") or "") for risk in report["open_risks"]]


def _conversation_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    return build_run_report(
        goal="what does this project do?",
        events=events,
        changed_files=[],
        returncode=1,
        ok=True,
        outcome="conversation",
        reason="Thomas replied without changing files",
    )


def test_the_report_carries_the_run_outcome() -> None:
    """The card cannot pick answer/stop/build wording without knowing which
    kind of run it is grading, and the sections alone do not say."""
    report = _conversation_report(_ANSWER_EVENTS)
    assert report["outcome"] == "conversation"


def test_an_answer_run_grows_no_risks_from_the_harness_exit_code() -> None:
    """The two manufactured rows from the audit, gone together: the CLI's
    lying exit 1 and the fallback sentence standing in for an empty error."""
    report = _conversation_report(_ANSWER_EVENTS)
    names = _risk_names(report)
    assert "run exited non-zero (1)" not in names
    assert "error surfaced during the run" not in names
    assert report["open_risks"] == []


def test_a_stopped_run_is_not_charged_with_its_own_kill_signal() -> None:
    """Stopping a run is the person's decision. The route records it in those
    words; the risk list must not re-file it as the run's error."""
    report = build_run_report(
        goal="build me a ledger",
        events=[{"fc": "say", "text": "Starting on the ledger."}],
        changed_files=[],
        returncode=-15,
        ok=False,
        outcome="stopped",
        reason="stopped by you",
    )
    assert "run exited non-zero (-15)" not in _risk_names(report)


def test_a_completed_run_keeps_its_non_zero_exit_risk() -> None:
    """The control. On a build, a dirty exit is real information and stays."""
    report = build_run_report(
        goal="build me a ledger",
        events=[{"fc": "say", "text": "Edited the ledger."}],
        changed_files=["ledger.html"],
        returncode=1,
        ok=True,
        outcome="completed",
        reason="1 file(s) changed (build process exited 1)",
    )
    assert "run exited non-zero (1)" in _risk_names(report)


def test_an_error_in_the_runs_own_words_is_still_a_risk() -> None:
    """The other control. Only the harness's stand-in sentences are dropped —
    an error event carrying what actually went wrong stays a risk row."""
    report = _conversation_report(
        [
            {"fc": "say", "text": "Answering."},
            {"fc": "final", "text": "Done."},
            {"fc": "error", "text": "TypeError: cannot read properties of null"},
        ]
    )
    names = _risk_names(report)
    assert "error surfaced during the run" in names


def test_the_agent_loop_fallback_sentence_is_also_not_a_risk() -> None:
    """dispatch_agent_loop has the same empty-error stand-in; same rule."""
    report = _conversation_report(
        [
            {"fc": "final", "text": "Done."},
            {"fc": "error", "text": "agent loop reported an error"},
        ]
    )
    assert "error surfaced during the run" not in _risk_names(report)
