"""A successful second look releases descendants as well as its launcher."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from thomas.server.precard import review, review_job


def test_successful_posix_review_stops_its_group(monkeypatch):
    stopped = []

    class Exited:
        pid = 12345
        returncode = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def communicate(self, timeout=None):
            return None, None

    monkeypatch.setattr(review_job, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(review_job.subprocess, "Popen", lambda *args, **kwargs: Exited())
    monkeypatch.setattr(review_job, "_stop", lambda process: stopped.append(process.pid))
    with review_job.cancellable():
        done = review_job.run(subprocess.run, ["reviewer"], timeout=10)
    assert done.returncode == 0
    assert stopped == [12345]


@pytest.mark.parametrize("held", [False, True])
@pytest.mark.parametrize("timed_out", [False, True])
def test_serial_or_held_second_look_owns_its_job(tmp_path, monkeypatch, held, timed_out):
    monkeypatch.setattr(review, "turned_off", lambda: False)
    monkeypatch.setattr(review, "_held", {})
    checked = SimpleNamespace(status="passed", patch="frozen patch")
    seen = []
    if held:
        review.remember_unavailable("serial", checked)
        checked = review._held["serial"]

    def verdict(*args):
        seen.append(review_job._cancel.get())
        if timed_out:
            raise review.ReviewUnavailable("reviewer timed out")
        return review.Verdict(True)

    monkeypatch.setattr(review, "review_verdict", verdict)
    monkeypatch.setattr(review, "apply_verdict", lambda *args: checked)
    if timed_out:
        with pytest.raises(review.ReviewUnavailable, match="timed out"):
            review.second_look("serial", "request", checked)
    else:
        assert review.second_look("serial", "request", checked) is checked
    assert len(seen) == 1 and seen[0] is not None
    assert seen[0].is_set()
    assert review_job._cancel.get() is None


def test_nested_job_keeps_outer_cancellation():
    with review_job.cancellable() as outer:
        with review_job.cancellable() as inner:
            assert inner is outer
            assert not outer.is_set()
        assert not outer.is_set()
        outer.set()
        with review_job.cancellable(), pytest.raises(review_job.Cancelled):
            review_job.check_cancelled()
    assert review_job._cancel.get() is None
