"""Reviewer execution has a clock separate from admission and surrounding work."""

import pytest

from thomas.server.precard import clocks, review, review_job


@pytest.mark.parametrize("cancelled", [False, True])
def test_cli_clock_survives_success_and_cancellation(tmp_path, monkeypatch, cancelled):
    def run(*args, **kwargs):
        if cancelled:
            raise review_job.Cancelled("check failed")
        return 0, "ok"

    monkeypatch.setattr(review.chatgpt_review, "ask", run)
    with clocks.recording(tmp_path, "cli") as record:
        if cancelled:
            with pytest.raises(review_job.Cancelled):
                review.run_reviewer(["chatgpt", "review-model", "high"], str(tmp_path), "prompt", 10)
        else:
            assert review.run_reviewer(["chatgpt", "review-model", "high"], str(tmp_path), "prompt", 10) == (0, "ok")
    stage = record["stages"]["second_look_cli"]
    assert stage["seconds"] >= 0
    assert stage["end"] >= stage["start"]
