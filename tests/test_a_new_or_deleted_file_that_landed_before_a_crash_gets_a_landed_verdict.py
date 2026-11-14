"""A self-fix that added or deleted a file, and landed just before the promoter stopped, gets its "landed" verdict.

The promoter moves ``dev`` and the running copy, then writes each verdict. Stopped in between, it finds the hand-in still
in the inbox on its next pass and derives the change again on ``dev``. A change that only edits files comes out empty
there, and its own commit gives it "landed" (tests/test_a_change_that_landed_before_a_crash_gets_a_landed_verdict.py).
But a file the change adds is already on ``dev`` and a file it deletes is already gone, so the patch no longer applied,
and a change that had landed was refused: "the change no longer applies to dev: 1 file(s) will not apply: ..." --
its team sent to repair work that was done. Nearly every self-fix adds a changelog.d file.

Now a change that no longer applies is first looked for on ``dev`` by its own commit, on a single card and on a shared
one. A change that never landed, with a file in its way, is refused as before.
"""

from __future__ import annotations

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
from thomas.server import green_checkout, green_handoff
from thomas.tools import trusted_card

SHARED = trusted_card.load_catalogue().LIST_KINDS["promote_several"].title


class _Stopped(BaseException):
    """The promoter process ending, between moving dev and writing the verdicts."""


def _stop(_self: sp.Promoter, _sub: Path, _outcome: sp.Outcome) -> None:
    raise _Stopped


def _hand_ins(blue: Path, kind: str, names: list[str]) -> list[Path]:
    """One self-fix per name: each adds ``thomas/<name>.py``, or deletes it from dev."""
    if kind == "delete":
        for name in names:
            (blue / "thomas" / f"{name}.py").write_text(f"{name.upper()} = 0\n", encoding="utf-8")
        git(blue, "add", "-A")
        git(blue, "commit", "-qm", "files a self-fix deletes")
    subs = []
    for name in names:
        green = green_checkout.create_green(blue, f"exec-{kind}-{name}")
        path = green.work / "thomas" / f"{name}.py"
        if kind == "delete":
            path.unlink()
        else:
            path.write_text(f"{name.upper()} = 1\n", encoding="utf-8")
        sub = green_handoff.settle(f"exec-{kind}-{name}", promote=True, summary="Fixed it.", chat="chat-1")
        assert sub is not None
        subs.append(sub)
    return subs


@pytest.mark.parametrize("kind", ["add", "delete"])
def test_a_change_that_landed_alone_before_a_crash_gets_a_landed_verdict(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    (sub,) = _hand_ins(blue, kind, ["new"])
    with monkeypatch.context() as patched:
        patched.setattr(sp.Promoter, "_finish", _stop)
        with pytest.raises(_Stopped):
            _promoter(blue, pins, Asker(True)).promote(sub)
    landed = git(blue, "rev-parse", "dev")
    assert (blue / "thomas" / "new.py").exists() is (kind == "add"), "it landed in the running copy"
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert outcome.commit_sha == landed and outcome.files == ["thomas/new.py"]
    assert "before the promoter stopped" in outcome.detail and outcome.conflicts == []
    assert ask.asked == [], "nothing is asked twice"
    verdict = _outbox(sub.name, "verdict")
    assert verdict["status"] == "landed" and verdict["commit_sha"] == landed
    assert not sub.exists(), "moved out of the inbox"


@pytest.mark.parametrize("kind", ["add", "delete"])
def test_changes_that_landed_on_one_card_before_a_crash_get_landed_verdicts(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    first, second = _hand_ins(blue, kind, ["a", "b"])
    ask = Asker(True)
    with monkeypatch.context() as patched:
        patched.setattr(sp.Promoter, "_finish", _stop)
        with pytest.raises(_Stopped):
            _promoter(blue, pins, ask).run_once()
    assert [action.split("\n", 1)[0] for action, _ in ask.asked] == [SHARED], "both landed on one shared card"
    tip = git(blue, "rev-parse", "dev")
    ask = Asker()
    fresh = _promoter(blue, pins, ask)

    outcome = fresh.run_once()

    assert outcome is not None and outcome.status == "landed", outcome
    assert fresh.run_once() is None, "both verdicts written in one pass"
    assert ask.asked == [], "nothing is asked twice"
    for sub, commit, path in ((first, git(blue, "rev-parse", "dev^"), "thomas/a.py"), (second, tip, "thomas/b.py")):
        verdict = _outbox(sub.name, "verdict")
        assert verdict["status"] == "landed" and verdict["commit_sha"] == commit, verdict
        assert verdict["files"] == [path] and "before the promoter stopped" in verdict["detail"]
        assert not sub.exists()


@pytest.mark.parametrize("by", ["by hand", "by another hand-in whose id starts the same"])
def test_a_new_file_that_never_landed_is_still_refused_when_dev_has_one_in_its_way(
    blue: Path, pins: Path, by: str
) -> None:
    if by == "by hand":
        sub = _submit(blue, "exec-never", {"thomas/new.py": "NEW = 1\n"})
        (blue / "thomas" / "new.py").write_text("NEW = 2\n", encoding="utf-8")
        git(blue, "add", "-A")
        git(blue, "commit", "-qm", "another thomas/new.py")
    else:  # landed as self-exec-same: a commit of the promoter's own, but not this hand-in's
        other = _submit(blue, "exec-same", {"thomas/new.py": "NEW = 3\n"})
        sub = _submit(blue, "exec-sam", {"thomas/new.py": "NEW = 1\n"})
        assert _promoter(blue, pins, Asker(True)).promote(other).status == "landed"
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused", outcome
    assert outcome.detail == "the change no longer applies to dev: 1 file(s) will not apply: thomas/new.py"
    assert outcome.conflicts == ["thomas/new.py"] and outcome.commit_sha == ""
    assert ask.asked == []


def test_on_a_shared_card_a_new_file_that_never_landed_is_still_refused(blue: Path, pins: Path) -> None:
    first = _submit(blue, "exec-never-a", {"thomas/a.py": "A = 1\n"})
    second = _submit(blue, "exec-never-b", {"thomas/b.py": "B = 1\n"})
    (blue / "thomas" / "a.py").write_text("A = 2\n", encoding="utf-8")
    git(blue, "add", "-A")
    git(blue, "commit", "-qm", "another thomas/a.py")
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).run_once()

    assert outcome is not None and outcome.status == "refused", outcome
    assert outcome.conflicts == ["thomas/a.py"] and "will not apply: thomas/a.py" in outcome.detail
    assert _outbox(first.name, "verdict")["status"] == "refused"
    assert ask.asked == [] and second.is_dir(), "the other waits for its own card"
