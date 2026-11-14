"""Unusable checks release their reviewer before scratch removal starts."""

import pytest

from tests.test_lazy_baseline_failures_are_held_and_cleaned import pipeline  # noqa: F401
from thomas.server.precard import check, review_job


@pytest.mark.parametrize("state", [check.FAILED, check.UNAVAILABLE, check.PASSED])
def test_review_cancelled_before_copy_removal(pipeline, monkeypatch, state):
    monkeypatch.setattr(check, "_steps", lambda *args: check.Checked(state, "result"))
    observed = []
    discard = check.scratch.discard_all
    with review_job.cancellable() as cancellation:

        def remove(*copies):
            observed.append(cancellation.is_set())
            discard(*copies)

        monkeypatch.setattr(check.scratch, "discard_all", remove)
        result = check._against_dev(pipeline.green, "tip", "patch", ["pkg/changed.py"], "python", shared=True)
        assert result.state == state
        assert observed == [state != check.PASSED]
        assert not pipeline.change.work.exists()


def test_unexpected_fault_cancels_review_before_copy_removal(pipeline, monkeypatch):
    def broken(*args):
        raise IndexError("broken result")

    monkeypatch.setattr(check, "_steps", broken)
    observed = []
    discard = check.scratch.discard_all
    with review_job.cancellable() as cancellation:

        def remove(*copies):
            observed.append(cancellation.is_set())
            discard(*copies)

        monkeypatch.setattr(check.scratch, "discard_all", remove)
        result = check._against_dev(pipeline.green, "tip", "patch", ["pkg/changed.py"], "python", shared=True)
        assert result.state == check.UNAVAILABLE
        assert observed == [True]
        assert not pipeline.change.work.exists()
