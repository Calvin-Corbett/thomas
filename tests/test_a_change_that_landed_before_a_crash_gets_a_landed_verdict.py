"""A change that landed just before the promoter stopped gets a "landed" verdict, never "already on dev".

The promoter moves ``dev`` and the running copy, then writes the verdict and moves the hand-in out of the inbox. A
promoter stopped between the two left the hand-in in the inbox; on the next pass its change was empty on ``dev`` and it
was refused as "already on dev" -- a landed change reported as refused, its team sent to repair work that was done.

``dev`` itself records what landed: each commit carries its hand-in's ``Thomas-Submission-Id`` and
``Thomas-Committed-By: self-change-promoter``. The verdict is "landed" only when no verdict was written yet, that
commit is the promoter's own, and the running copy holds what ``dev`` holds; otherwise it says what is missing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.cage import self_change_promoter as sp

from tests.green_support import git
from tests.test_a_self_fix_lands_only_when_you_approve import (  # noqa: F401
    Asker,
    _outbox,
    _promoter,
    _submit,
    blue,
    pins,
)
from thomas.tools import cage_shell


class _Stopped(BaseException):
    """The promoter process ending, between moving dev and writing the verdict."""


def _land_then_stop(blue: Path, pins: Path, sub: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    def stop(_self: sp.Promoter, _sub: Path, _outcome: sp.Outcome) -> None:
        raise _Stopped

    with monkeypatch.context() as patched:
        patched.setattr(sp.Promoter, "_finish", stop)
        with pytest.raises(_Stopped):
            _promoter(blue, pins, Asker(True)).promote(sub)
    assert sub.is_dir(), "still in the inbox"
    assert not (cage_shell.cage_root() / "outbox" / f"{sub.name}.verdict.json").exists()
    return git(blue, "rev-parse", "dev")


def test_a_change_that_landed_before_the_promoter_stopped_gets_a_landed_verdict(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = _submit(blue, "exec-crash", {"thomas/fix_me.py": "VALUE = 2\n"})
    landed = _land_then_stop(blue, pins, sub, monkeypatch)
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert outcome.commit_sha == landed
    assert outcome.files == ["thomas/fix_me.py"]
    assert "before the promoter stopped" in outcome.detail
    assert ask.asked == [], "nothing is asked twice"
    verdict = _outbox(sub.name, "verdict")
    assert verdict["status"] == "landed" and verdict["commit_sha"] == landed
    assert not sub.exists(), "moved out of the inbox"


def test_a_running_copy_behind_dev_is_an_error_that_names_the_commit(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = _submit(blue, "exec-crash-behind", {"thomas/fix_me.py": "VALUE = 2\n"})
    landed = _land_then_stop(blue, pins, sub, monkeypatch)
    (blue / "thomas" / "fix_me.py").write_text("VALUE = 1\n", encoding="utf-8")  # its files were never written

    outcome = _promoter(blue, pins, Asker(True)).promote(sub)

    assert outcome.status == "error", outcome.detail
    assert landed[:12] in outcome.detail and "thomas/fix_me.py" in outcome.detail
    assert outcome.commit_sha == landed
    assert (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8") == "VALUE = 1\n", "nothing more was done"


def test_a_verdict_already_written_is_not_written_again_as_landed(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = _submit(blue, "exec-crash-said", {"thomas/fix_me.py": "VALUE = 2\n"})
    _land_then_stop(blue, pins, sub, monkeypatch)
    outbox = cage_shell.cage_root() / "outbox"
    (outbox / f"{sub.name}.verdict.json").write_text(json.dumps({"status": "landed"}), encoding="utf-8")

    outcome = _promoter(blue, pins, Asker(True)).promote(sub)

    assert outcome.status == "refused" and outcome.detail == "the change is already on dev"


def test_a_commit_that_only_names_the_hand_in_is_not_taken_for_its_landing(blue: Path, pins: Path) -> None:
    """Anyone can write a trailer into a message: only the promoter's own commit, with its own trailers, counts."""
    sub = _submit(blue, "exec-named-by-hand", {"thomas/fix_me.py": "VALUE = 2\n"})
    (blue / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(blue, "commit", "-qam", f"by hand\n\nThomas-Submission-Id: {sub.name}")

    outcome = _promoter(blue, pins, Asker(True)).promote(sub)

    assert outcome.status == "refused" and outcome.detail == "the change is already on dev"


def test_a_later_commit_that_names_the_hand_in_does_not_hide_its_landing(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit made after the promoter's own that also carries the hand-in's id (by hand, or `cherry-pick -x`) is
    passed over: the promoter's own commit is still found, and the verdict is "landed", never "already on dev"."""
    sub = _submit(blue, "exec-crash-named-later", {"thomas/fix_me.py": "VALUE = 2\n"})
    landed = _land_then_stop(blue, pins, sub, monkeypatch)
    (blue / "README.md").write_text("later\n", encoding="utf-8")
    git(blue, "commit", "-qam", f"by hand, later\n\nThomas-Submission-Id: {sub.name}")

    outcome = _promoter(blue, pins, Asker(True)).promote(sub)

    assert outcome.status == "landed" and outcome.commit_sha == landed, outcome
    assert "before the promoter stopped" in outcome.detail


def test_another_hand_ins_landing_is_not_this_ones(blue: Path, pins: Path) -> None:
    """self-exec-same lands; self-exec-sam, the same change under a sid that is the start of the other's, is already
    on dev -- its own commit is nowhere."""
    first = _submit(blue, "exec-same", {"thomas/fix_me.py": "VALUE = 2\n"})
    second = _submit(blue, "exec-sam", {"thomas/fix_me.py": "VALUE = 2\n"})
    assert _promoter(blue, pins, Asker(True)).promote(first).status == "landed"

    outcome = _promoter(blue, pins, Asker(True)).promote(second)

    assert outcome.status == "refused" and outcome.detail == "the change is already on dev"
