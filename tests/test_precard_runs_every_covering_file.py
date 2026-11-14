"""The check runs the selector's capped files and the card names the covering files it did not run (2026-10-27).

From 2026-10-26 the check ran every covering file past the cap as well. A change that reached a module most tests
import chose 1,892 to 1,961 files, close to the whole suite; none of those checks finished inside its limit, and on
2026-10-27 no hand-in reached your card all day. You chose: "Restore the 360 cap". The files past it are named on the
card, never claimed as run.
"""

from tests.test_lazy_baseline_failures_are_held_and_cleaned import pipeline, run  # noqa: F401
from thomas.server.precard import check
from thomas.server.proof import Selection, runner
from thomas.server.proof.deadline import Deadline


def test_files_past_the_cap_are_not_run_and_the_card_names_them(pipeline, monkeypatch):
    selected = ("tests/test_architecture.py", "tests/test_direct.py")
    overflow = ("tests/test_overflow.py", "tests/test_last.py")
    monkeypatch.setattr(check.proofs, "select", lambda *a, **k: Selection(selected, overflow))
    monkeypatch.setattr(check.proofs, "Deadline", Deadline)
    observed = []

    def tests(work, files, **kwargs):
        observed.extend(files)
        return runner.ProofRun(True, "", (), len(files), 1)

    monkeypatch.setattr(check.proofs, "run_tests", tests)
    result = run(pipeline)
    assert result.state == check.PASSED, result
    assert observed == list(selected)
    assert "2 more test file(s) that cover it were not run" in result.line
    assert "tests/test_overflow.py" in result.line
    assert result.format == check.CHECK_FORMAT == 4
    assert pipeline.calls == [check.scratch.WITH_CHANGE]
    assert pipeline.removed == [pipeline.change]
