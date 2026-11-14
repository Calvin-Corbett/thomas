"""Ordinary checker faults hold the card, including faults outside scratch work."""

import pytest

from thomas.server.precard import check


@pytest.mark.parametrize("error", [IndexError("bad result"), AssertionError("bad invariant")])
def test_outer_hand_in_boundary_holds_unexpected_checker_fault(monkeypatch, error):
    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(check, "turned_off", lambda: False)
    monkeypatch.setattr(check, "_decide", broken)
    monkeypatch.setattr(check.pool, "parallel", lambda: True)
    result = check.check_before_card("fault")
    assert result.state == check.UNAVAILABLE
    assert result.cause == "unexpected"
    assert result.costly


# The fixture exercises the real changed-copy and lazy baseline path.
from tests.test_lazy_baseline_failures_are_held_and_cleaned import pipeline, run  # noqa: E402,F401


@pytest.mark.parametrize("error", [IndexError("bad report"), AssertionError("bad invariant")])
def test_inner_boundary_holds_unexpected_fault_and_removes_copy(pipeline, monkeypatch, error):
    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(check.proofs, "run_tests", broken)
    result = run(pipeline)
    assert result.state == check.UNAVAILABLE
    assert result.cause == "unexpected"
    assert result.costly
    assert pipeline.removed == [pipeline.change]
    assert not pipeline.change.work.exists()
