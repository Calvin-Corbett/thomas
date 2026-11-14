"""A check before your card that could not run says why, and whether that counts against it.

thomas/server/precard/check.py marks every unavailable answer with a ``cause`` and ``costly``: low disk and an
intentional skip never count as a strike in the hold (thomas/server/hand_in_hold.py); a check that could not run
because of its own machinery (the change's copy, an interpreter, the dev tip or a scratch copy of dev it could not
get), past its deadline or unexpectedly does. ``dev-side`` is only a change whose tests ran while dev itself is the
problem, and it is never a strike. A kept check is reused only when it passed, on the same dev, for the same patch
(precard/review.held_check).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from thomas.server import capacity_ledger, green_checkout, precard
from thomas.server.precard import check

PATCH = "diff --git a/example.py b/example.py\n+changed\n"


@pytest.fixture
def green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> green_checkout.Green:
    """A change everything is ready for, up to the scratch copies of dev."""
    blue = tmp_path / "blue"
    (blue / "tests").mkdir(parents=True)
    found = green_checkout.Green("green-1", tmp_path / "work", tmp_path / "git", "base", blue)
    monkeypatch.setenv(check.CHECK_ENV, "on")
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))  # never the real catalog's ledger
    roomy = capacity_ledger.Room(100 * 1024**3, None, None)  # admission never depends on this machine's free disk
    monkeypatch.setattr(capacity_ledger, "measure", lambda _where: roomy)
    monkeypatch.setattr(green_checkout, "find_green", lambda _eid: found)
    monkeypatch.setattr(green_checkout, "green_patch", lambda _green: PATCH)
    monkeypatch.setattr(green_checkout, "changed_paths", lambda _green: ["example.py"])
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path / "greens")
    monkeypatch.setattr(check.proofs, "interpreter", lambda _blue: sys.executable)
    monkeypatch.setattr(check.green_handoff, "dev_tip", lambda _eid: "dev-1")
    monkeypatch.setattr(check.slot, "clear_leftovers", lambda _age: None)
    monkeypatch.setattr(check.slot, "too_little_room", lambda _root, **_kw: "")
    return found


def _raise(exc: Exception) -> Any:
    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return boom


BREAKS: dict[str, tuple[str, Any, str, bool]] = {
    "copy gone": ("green_checkout.find_green", lambda _eid: None, "incomplete", True),
    "empty": ("green_checkout.green_patch", lambda _green: "", "empty", False),
    "no interpreter": ("check.proofs.interpreter", lambda _blue: "", "incomplete", True),
    "dev tip unread": ("check.green_handoff.dev_tip", lambda _eid: "", "incomplete", True),
    "low disk": ("check.slot.too_little_room", lambda _root, **_kw: "the drive has 1.0 GB free", "low-disk", False),
    "scratch copy": (
        "check.scratch.copy_of_dev",
        _raise(green_checkout.GreenUnavailable("no copy")),
        "incomplete",
        True,
    ),
    "unexpected": ("check.scratch.copy_of_dev", _raise(RuntimeError("surprise")), "unexpected", True),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_each_unavailable_check_names_its_cause(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    where, replacement, cause, costly = BREAKS[name]
    owner, attribute = where.rsplit(".", 1)
    target = {"green_checkout": green_checkout, "check.proofs": check.proofs, "check.green_handoff": check.green_handoff,
              "check.slot": check.slot, "check.scratch": check.scratch}[owner]  # fmt: skip
    monkeypatch.setattr(target, attribute, replacement)
    checked = check.check_before_card("green-1")
    assert checked.state == precard.UNAVAILABLE and not checked.failed
    assert (checked.cause, checked.costly) == (cause, costly)
    assert checked.line.startswith("Not checked before this card")


def test_a_turned_off_check_hands_in_the_bytes_it_read(green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(check.CHECK_ENV, "off")
    checked = check.check_before_card("green-1")
    assert (checked.state, checked.cause, checked.costly) == (precard.UNAVAILABLE, "off", False)
    assert checked.patch == PATCH and checked.patch_sha256 == check.patch_sha256(PATCH)
    assert "turned off" in checked.line


def test_only_a_passed_check_with_the_same_patch_on_the_same_dev_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    review = precard.review
    current = [PATCH]
    monkeypatch.setattr(green_checkout, "find_green", lambda _eid: object())
    monkeypatch.setattr(green_checkout, "green_patch", lambda _green: current[0])
    monkeypatch.setattr(review.green_handoff, "dev_tip", lambda _eid: "dev-1")
    monkeypatch.setattr(review, "_held", {})
    passed = precard.Checked(
        precard.PASSED, "passed", patch=PATCH, patch_sha256=precard.patch_sha256(PATCH), dev_tip="dev-1"
    )
    with review._held_lock:
        review._held["green-1"] = precard.Checked(precard.FAILED, "failed")
    assert review.held_check("green-1") is None
    with review._held_lock:
        review._held["green-1"] = passed
    assert review.held_check("green-1") == passed
    monkeypatch.setattr(review.green_handoff, "dev_tip", lambda _eid: "dev-2")
    assert review.held_check("green-1") is None
    with review._held_lock:
        review._held["green-1"] = passed
    monkeypatch.setattr(review.green_handoff, "dev_tip", lambda _eid: "dev-1")
    current[0] = PATCH + "new bytes\n"
    assert review.held_check("green-1") is None and "green-1" not in review._held
    with review._held_lock:
        review._held["green-1"] = passed
    current[0] = ""
    assert review.held_check("green-1") is None


def test_empty_patch_does_not_reuse_a_passed_check(monkeypatch: pytest.MonkeyPatch) -> None:
    review = precard.review
    monkeypatch.setattr(green_checkout, "find_green", lambda _eid: object())
    monkeypatch.setattr(green_checkout, "green_patch", lambda _green: "")
    kept = precard.Checked(precard.PASSED, "passed", patch="", patch_sha256=precard.patch_sha256(""))
    monkeypatch.setattr(review, "_held", {"green-1": kept})
    assert review.held_check("green-1") is None and "green-1" not in review._held


@pytest.mark.parametrize("verdict", ["unavailable", "unsafe", "safe"])
def test_second_look_keeps_only_an_unavailable_passed_check(monkeypatch: pytest.MonkeyPatch, verdict: str) -> None:
    review = precard.review
    monkeypatch.setattr(review, "_held", {})
    checked = precard.Checked(precard.PASSED, "tests passed", patch="patch")

    def decide(*_args: Any) -> Any:
        if verdict == "unavailable":
            raise precard.ReviewUnavailable("no reader")
        return review.Verdict(verdict == "safe", "specific finding")

    monkeypatch.setattr(review, "turned_off", lambda: False)
    monkeypatch.setattr(review, "review_hand_in", decide)
    if verdict == "unavailable":
        with pytest.raises(precard.ReviewUnavailable, match="no reader"):
            review.second_look("green-1", "request", checked)
        assert review._held["green-1"] == checked
    elif verdict == "unsafe":
        with pytest.raises(precard.ChangeFailedCheck, match="specific finding"):
            review.second_look("green-1", "request", checked)
        assert "green-1" not in review._held
    else:
        assert review.SAFE_LINE in review.second_look("green-1", "request", checked).line
        assert "green-1" not in review._held


def test_a_turned_off_second_look_says_so_on_the_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(precard.review, "turned_off", lambda: True)
    checked = precard.review.second_look("green-1", "request", precard.Checked(precard.PASSED, "tests passed"))
    assert checked.line == f"tests passed The second look was turned off ({precard.review.REVIEW_ENV})."
