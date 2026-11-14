"""The covering tests run once, with the change; dev is run in full only when dev may be the problem.

Spec 2026-10-12 Part 1 items 2-4. The full dev run was 49% of the check's pytest seconds. Now the tests run with the
change, sharded across the pool, and each failure is re-run on its own with the change and on dev. Only when the
change's run does not finish, has more than RERUN_CAP (40) failures, or leaves failures no re-run on its own could
settle, do the same tests run on dev: if dev fails the same way, the check is held as dev-side instead of sending dev's
own trouble back to the team. Up to 40 failures that dev also has, each confirmed alone there, never hold a change.
"""

from __future__ import annotations

import dataclasses
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.server.precard import check, report
from thomas.server.precard.lint import LintResult
from thomas.server.proof import ProofRun, Selection, runner

TEST = "tests/test_x.py::test_one"


class Copies:
    """Stands in for the proof step; records which copy (the change's or dev's) each run and re-run used."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.base, self.change = SimpleNamespace(work=tmp / "base"), SimpleNamespace(work=tmp / "change")
        self.change_run = ProofRun(True, "", (), 5, 1)
        self.dev_run = ProofRun(True, "", (), 5, 1)
        self.alone_change: dict[str, str] = {}
        self.alone_dev: dict[str, str] = {}
        self.dev_later: dict[str, str] = {}  # a test's answer on dev from its second re-run there on (the alone one)
        self.runs: list[str] = []
        self.alone: list[tuple[str, str]] = []
        self.folders: list[tuple[str, str]] = []  # (test, the data folder its re-run used)
        self.lock = threading.Lock()

    def _side(self, work: Path) -> str:
        return "change" if Path(work) == self.change.work else "base"

    def run_tests(self, work: Path, files: tuple, **kwargs: object) -> ProofRun:
        side = self._side(work)
        self.runs.append(side)
        return self.change_run if side == "change" else self.dev_run

    def run_one(self, work: Path, test: str, **kwargs: object) -> str:
        side = self._side(work)
        with self.lock:
            again = (side, test) in self.alone
            self.alone.append((side, test))
            self.folders.append((test, Path(str(kwargs["data_dir"])).name))
        if side == "base" and again and test in self.dev_later:
            return self.dev_later[test]
        return (self.alone_change if side == "change" else self.alone_dev).get(test, runner.UNKNOWN)

    def check(self) -> check.Checked:
        green, deadline = SimpleNamespace(execution_id="example"), check.proofs.Deadline(60)
        return check._steps(green, "abc123456789", "patch", ["pkg/x.py"], sys.executable, self.base, self.change,
                            self.tmp / "data", deadline)  # fmt: skip


def _copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Copies:
    """The proof step stood in for, and every other step of the check quiet; also used by a sibling file."""
    found = Copies(tmp_path)
    monkeypatch.setattr(check.scratch, "apply_change", lambda *_a: "")
    monkeypatch.setattr(check.green_handoff, "size_problems", lambda *_a: [])
    monkeypatch.setattr(check.proofs, "select", lambda *_a, **_k: Selection(("tests/test_x.py",), ()))
    monkeypatch.setattr(check.lint, "ruff_findings", lambda *_a, **_k: LintResult(True, "", (), ()))
    monkeypatch.setattr(check.machine_capacity, "check_shard_mb", lambda *_a: 100)  # never the saved profile
    monkeypatch.setattr(check.proofs, "run_tests", found.run_tests)
    monkeypatch.setattr(check.proofs, "run_one", found.run_one)
    return found


@pytest.fixture
def copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Copies:
    return _copies(tmp_path, monkeypatch)


def _many(count: int) -> tuple[str, ...]:
    return tuple(f"tests/test_x.py::test_{n}" for n in range(count))


def test_a_clean_change_is_run_once_and_dev_is_never_run(copies: Copies) -> None:
    assert copies.check().state == check.PASSED
    assert copies.runs == ["change"]


def test_a_failure_that_fails_alone_on_dev_passes_without_any_dev_run(copies: Copies) -> None:
    copies.change_run = ProofRun(True, "", (TEST,), 5, 1)
    copies.alone_change[TEST] = copies.alone_dev[TEST] = runner.FAILED

    checked = copies.check()

    assert checked.state == check.PASSED and copies.runs == ["change"]
    assert "1 failure(s) dev already has, each confirmed on its own" in checked.line


def test_a_failure_that_passes_alone_on_dev_goes_back_to_its_team(copies: Copies) -> None:
    copies.change_run = ProofRun(True, "", (TEST,), 5, 1)
    copies.alone_change[TEST], copies.alone_dev[TEST] = runner.FAILED, runner.PASSED

    checked = copies.check()

    assert checked.state == check.FAILED and report.HEADINGS["regressed"] in checked.findings
    assert TEST in checked.findings


def test_a_run_that_does_not_finish_on_the_change_or_on_dev_is_held_dev_side(copies: Copies) -> None:
    copies.change_run = copies.dev_run = ProofRun(False, "pytest exited 3", (), 0, 1)

    checked = copies.check()

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, "dev-side", False)
    assert not checked.failed and checked.line.startswith("Not checked before this card")
    assert copies.runs == ["change", "base"]


def test_a_run_that_does_not_finish_only_with_the_change_goes_back_as_broken(copies: Copies) -> None:
    copies.change_run = ProofRun(False, "pytest exited 3", (), 0, 1)

    checked = copies.check()

    assert checked.state == check.FAILED and report.HEADINGS["broke"] in checked.findings


def test_more_failures_than_the_rerun_cap_that_dev_also_has_are_held_dev_side(copies: Copies) -> None:
    copies.change_run = copies.dev_run = ProofRun(True, "", _many(41), 41, 1)

    checked = copies.check()

    assert (checked.state, checked.cause) == (check.UNAVAILABLE, "dev-side") and copies.alone == []


def test_at_the_rerun_cap_dev_is_not_run(copies: Copies, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "_width", lambda *_a: 1)  # one re-run at a time: each dev re-run is already alone
    copies.change_run = ProofRun(True, "", _many(40), 40, 1)
    for test in _many(40):
        copies.alone_change[test] = copies.alone_dev[test] = runner.FAILED

    assert copies.check().state == check.PASSED and copies.runs == ["change"]


def test_an_excuse_from_a_dev_re_run_beside_others_is_settled_alone_and_blocks_when_dev_passes(
    copies: Copies, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check, "_width", lambda *_a: 4)
    first, second = "tests/test_x.py::test_a", "tests/test_x.py::test_b"
    copies.change_run = ProofRun(True, "", (first, second), 5, 1)
    for test in (first, second):
        copies.alone_change[test] = copies.alone_dev[test] = runner.FAILED
    copies.dev_later[first] = runner.PASSED  # beside the other re-run dev failed it; alone, dev passes it

    checked = copies.check()

    assert checked.state == check.FAILED and first in checked.findings
    assert copies.alone.count(("base", first)) == 2 and copies.runs == ["change"]
    assert [folder for test, folder in copies.folders if test == first] == ["one-change", "one-base", "one-base-again"]


@pytest.mark.parametrize("count", [25, 40])
def test_up_to_forty_failures_dev_also_has_pass_at_full_width_without_a_dev_run(
    copies: Copies, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    monkeypatch.setattr(check, "_width", lambda *_a: 4)
    copies.change_run = ProofRun(True, "", _many(count), count, 1)
    copies.dev_run = ProofRun(True, "", _many(count), count, 1)
    for test in _many(count):
        copies.alone_change[test] = copies.alone_dev[test] = runner.FAILED

    checked = copies.check()

    assert checked.state == check.PASSED and copies.runs == ["change"], "dev-side is only for more than 40"
    assert sum(1 for side, _test in copies.alone if side == "base") == 2 * count, "each excuse settled once more"


def test_a_run_the_change_broke_goes_back_as_broken_even_when_dev_has_its_failures(
    copies: Copies, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check, "_width", lambda *_a: 4)
    copies.change_run = ProofRun(False, "shard 2 of 3 crashed", _many(45), 30, 3)
    copies.dev_run = ProofRun(True, "", _many(45), 45, 3)
    for test in _many(45):
        copies.alone_change[test] = copies.alone_dev[test] = runner.FAILED

    checked = copies.check()

    assert checked.state == check.FAILED and report.HEADINGS["broke"] in checked.findings
    assert copies.runs == ["change", "base"], "dev ran to the end: the change broke its own run"


def test_past_the_cap_failures_dev_does_not_share_are_confirmed_first(
    copies: Copies, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _many(40)
    copies.change_run = ProofRun(True, "", ("tests/test_x.py::test_new", *old), 41, 1)
    copies.dev_run = ProofRun(True, "", old, 41, 1)
    for test in old:
        copies.alone_change[test] = copies.alone_dev[test] = runner.FAILED
    copies.alone_change["tests/test_x.py::test_new"] = runner.FAILED
    copies.alone_dev["tests/test_x.py::test_new"] = runner.PASSED
    real, given = check.proofs.confirm, {}

    def spy(*args: object, **kwargs: object) -> object:
        given.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(check.proofs, "confirm", spy)

    checked = copies.check()

    assert set(given["known_on_dev"]) == set(old)
    assert checked.state == check.FAILED and "tests/test_x.py::test_new" in checked.findings


def test_past_the_cap_leftovers_dev_also_fails_are_held_dev_side_not_sent_back(copies: Copies) -> None:
    old = _many(40)
    copies.change_run = ProofRun(True, "", ("tests/test_x.py::test_flaky", *old), 41, 1)
    copies.dev_run = ProofRun(True, "", old, 41, 1)
    copies.alone_change["tests/test_x.py::test_flaky"] = runner.PASSED
    for test in old:
        copies.alone_change[test] = copies.alone_dev[test] = runner.FAILED

    checked = copies.check()

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, "dev-side", False)


def test_a_dev_run_cut_by_the_deadline_is_unavailable_for_time(copies: Copies) -> None:
    copies.change_run = ProofRun(False, "pytest exited 3", (), 0, 1)
    copies.dev_run = ProofRun(False, "it ran out of time", (), 0, 1, out_of_time=True)

    assert copies.check().cause == "deadline"


def test_the_second_look_is_told_what_the_check_ran() -> None:
    """Ratchet cards share this prompt and their line says "on dev with and without it": the prompt claims neither."""
    from thomas.server.precard import review

    words = review.prompt("request", check.Checked(check.PASSED, "line"))

    assert "on dev with and without it" not in words and "re-ran each failure" not in words
    assert "the line below says what it ran" in words


def test_a_held_check_of_an_older_format_is_never_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server import green_checkout
    from thomas.server.precard import review

    monkeypatch.setattr(green_checkout, "find_green", lambda _eid: object())
    monkeypatch.setattr(green_checkout, "green_patch", lambda _green: "patch")
    monkeypatch.setattr(review.green_handoff, "dev_tip", lambda _eid: "dev-1")
    kept = check.Checked(
        check.PASSED, "passed", patch="patch", patch_sha256=check.patch_sha256("patch"), dev_tip="dev-1"
    )
    older = {f"format {n}": dataclasses.replace(kept, format=n) for n in (1, 2, 3)}
    monkeypatch.setattr(review, "_held", {"now": kept, **older})

    assert all(review.held_check(name) is None for name in older)
    assert review.held_check("now") == kept
    # 4: the cap again, with the covering files past it named on the card (2026-10-27).
    assert kept.format == check.CHECK_FORMAT == 4
