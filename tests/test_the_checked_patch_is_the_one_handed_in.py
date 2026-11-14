"""The patch handed in is the patch that was checked, checks run one at a time, and never on a full disk.

Findings 1 and 3 of 2026-09-25. ``check_before_card`` and ``settle`` each read the green's patch, and
nothing tied the two reads together: with one write into the green between them, ``toctou_drive.py``
handed in a ``change.patch`` that broke ``tests/test_adder.py::test_add_makes_a_sum`` under a ``checked``
line that said "no failure this change causes". Every hand-in that finished at the same moment also
started its own two scratch copies and pytest processes, on a drive that was 97% full.

Real here, as in ``tests/test_a_change_is_checked_before_your_card.py`` whose fixture this uses: git,
greens, scratch copies, ``git apply --3way`` and pytest. The write into the green stands in for a process
the team left running.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_a_change_is_checked_before_your_card import (  # noqa: F401 -- world is the fixture
    BROKEN_ADDER,
    CLEAN_ADDER,
    CLEAN_TEST,
    EXECUTION,
    _change,
    _finished,
    _scratch_left,
    _submissions,
    base_repo,  # the fixture world takes since da23f510
    world,
)
from thomas.server import green_checkout, green_handoff, precard, thomas_project
from thomas.server.precard import check, handover, pool, scratch, slot

CLEAN = {"pkg/adder.py": CLEAN_ADDER, "tests/test_adder.py": CLEAN_TEST}


def _written_after_the_check(monkeypatch: pytest.MonkeyPatch, work: Path) -> list[str]:
    """After the check has read and tested the change, something still running writes into the green."""
    real, seen = check._against_dev, []

    def against_dev(*args: Any) -> check.Checked:
        checked = real(*args)
        seen.append(checked.state)
        seen.append(precard.patch_sha256(args[2]))  # (green, tip, patch, ...): the bytes it tested
        (work / "pkg" / "adder.py").write_text(BROKEN_ADDER, encoding="utf-8")
        return checked

    monkeypatch.setattr(check, "_against_dev", against_dev)
    return seen


def test_a_change_that_moves_while_it_is_checked_is_refused_and_never_handed_in(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _finished(world, _change(world, CLEAN))
    seen = _written_after_the_check(monkeypatch, world.green.work)

    with pytest.raises(precard.ChangeFailedCheck) as refused:
        thomas_project.settle_if_finished(world.green.work, world.catalog, cid)

    assert seen[0] == precard.PASSED, "the bytes the check read were fine: only the swap makes this a finding"
    assert _submissions(world) == [], "the swapped patch never reached the promoter's inbox"
    assert "changed while it was being checked" in str(refused.value)
    assert seen[1] in str(refused.value), "the findings name the patch that was checked"
    assert thomas_project.settled_record(world.catalog, cid) is None
    assert _scratch_left(world) == []


def test_the_check_for_a_hand_in_names_both_hashes_and_its_card_line(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _change(world, CLEAN)
    _written_after_the_check(monkeypatch, world.green.work)

    checked = precard.check_for_hand_in(EXECUTION)

    now = precard.patch_sha256(green_checkout.green_patch(world.green))
    assert checked.state == precard.FAILED and checked.line == handover.MOVED_LINE
    assert checked.patch_sha256 in checked.findings and now in checked.findings and checked.patch_sha256 != now


def test_a_clean_change_hands_in_exactly_the_bytes_that_were_checked(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _finished(world, _change(world, CLEAN))
    results: list[check.Checked] = []
    real = precard.check_for_hand_in
    monkeypatch.setattr(precard, "check_for_hand_in", lambda eid: results.append(real(eid)) or results[-1])
    fresh_reads: list[str] = []
    real_patch = green_checkout.green_patch
    monkeypatch.setattr(green_checkout, "green_patch", lambda g: fresh_reads.append(g.execution_id) or real_patch(g))

    submission = thomas_project.settle_if_finished(world.green.work, world.catalog, cid)

    assert submission is not None and len(results) == 1 and results[0].state == precard.PASSED
    handed_in = (submission / "change.patch").read_bytes()
    assert hashlib.sha256(handed_in).hexdigest() == results[0].patch_sha256
    manifest = json.loads((submission / "submission.json").read_text(encoding="utf-8"))
    assert manifest["checked"].startswith(results[0].line)
    assert "A second model read the change" in manifest["checked"]
    assert fresh_reads.count(EXECUTION) == 3, "freeze the review patch, read for the check, then confirm before hand-in"


def test_with_parallel_off_two_hand_ins_at_once_are_checked_one_after_the_other(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(pool.PARALLEL_ENV, "off")
    second = green_checkout.create_green(blue=world.blue, execution_id="thomas-checked2")
    for green in (world.green, second):
        for rel, text in CLEAN.items():
            (green.work / rel).write_text(text, encoding="utf-8")
    spans: dict[str, tuple[float, float]] = {}
    real = check._against_dev

    def timed(green: green_checkout.Green, *args: Any) -> check.Checked:
        start = time.monotonic()
        try:
            return real(green, *args)
        finally:
            spans[green.execution_id] = (start, time.monotonic())

    monkeypatch.setattr(check, "_against_dev", timed)
    results: dict[str, check.Checked] = {}
    threads = [
        threading.Thread(target=lambda eid=eid: results.__setitem__(eid, precard.check_before_card(eid)))
        for eid in (EXECUTION, second.execution_id)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(300)

    assert {eid: r.state for eid, r in results.items()} == {EXECUTION: "passed", second.execution_id: "passed"}
    (a_start, a_end), (b_start, b_end) = sorted(spans.values())
    assert a_end <= b_start, f"the second check started before the first finished: {spans}"
    assert not slot._lock.locked() and _scratch_left(world) == []


def test_a_check_refuses_to_start_on_a_full_disk_and_no_card_is_sent(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(slot, "disk_floor", lambda _total: 1 << 60)
    made: list[str] = []
    real = scratch.copy_of_dev
    monkeypatch.setattr(scratch, "copy_of_dev", lambda *a: made.append(a[3]) or real(*a))
    cid = _finished(world, _change(world, CLEAN))

    with pytest.raises(precard.CheckUnavailable, match="drive"):
        thomas_project.settle_if_finished(world.green.work, world.catalog, cid)

    assert not (tmp_inbox := green_handoff.inbox_dir()).exists() or not list(tmp_inbox.glob("self-*"))
    assert thomas_project.settled_record(world.catalog, cid) is None
    assert made == [] and _scratch_left(world) == [], "not one scratch copy was made"


def test_what_a_check_that_died_left_behind_is_cleared_and_a_fresh_copy_is_not(world: SimpleNamespace) -> None:
    tip = green_handoff.dev_tip(EXECUTION)
    old = scratch.copy_of_dev(world.blue, tip, EXECUTION, scratch.BASE)
    fresh = scratch.copy_of_dev(world.blue, tip, EXECUTION, scratch.WITH_CHANGE)
    try:
        long_ago = time.time() - 3 * precard.CHECK_DEADLINE_S
        os.utime(world.greens / "git" / old.execution_id, (long_ago, long_ago))

        removed = slot.clear_leftovers(2 * precard.CHECK_DEADLINE_S)

        assert removed == [old.execution_id] and _scratch_left(world) == [fresh.execution_id]
    finally:
        scratch.discard(fresh)
    assert _scratch_left(world) == []
