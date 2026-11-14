"""The card says exactly what ran, and the findings say how each failure was settled (spec 2026-10-12 Part 1 item 9).

The tests run once with the change and each failure is re-run on its own, with the change and then on dev. The card
line, the findings head and the regressed heading say so; the "dev's own run also had" words are gone with that
excuse; and repair_ledger still reads a repair round written in the words used before.
"""

from __future__ import annotations

from itertools import permutations

from thomas.server import repair_ledger
from thomas.server.precard import report
from thomas.server.precard.lint import LintResult
from thomas.server.proof.compare import RERUN_CAP, Verdict
from thomas.server.proof.runner import ProofRun

CLEAN = LintResult(True, "", (), ())
OLD = (
    "The check before your card applied this change to a scratch copy of dev 0123456789ab with `git apply --3way`, "
    "ran the tests that cover it on that copy and on an unpatched copy of the same commit, and compared the two by "
    "test id.\n\nTests that pass on dev and fail with this change (each re-run on its own, on both copies):\n"
    "- tests/test_x.py::test_a\n\nTests this change adds that fail. Dev does not have them, so there is nothing to "
    "compare them with -- they have to pass as written:\n- tests/test_x.py::test_b\n\nNot counted: 2 failure(s) "
    "dev's own run also had, not settled by a re-run on its own."
)


def test_the_cards_line_says_the_tests_ran_with_the_change_and_each_failure_was_re_run_alone() -> None:
    verdict = Verdict((), (), ("t::a",), ("t::b",), ())
    run = ProofRun(True, "", ("t::a", "t::b"), 40, 1)

    line = report.line_passed("abc123456789", ["tests/test_x.py"], run, verdict, CLEAN, [], ("tests/test_y.py",))

    assert (
        "1 test file(s) and 40 test(s) ran with the change, each of its 2 failure(s) re-run on its own, "
        "no failure this change causes" in line
    )
    assert "ran on dev" not in line and "own run also had" not in line
    assert "1 failure(s) dev already has, each confirmed on its own" in line
    assert "1 more test file(s) that cover it were not run" in line


def test_a_clean_run_claims_no_re_run() -> None:
    line = report.line_passed("abc123456789", ["tests/test_x.py"], ProofRun(True, "", (), 3, 1),
                              Verdict((), (), (), (), ()), CLEAN, [])  # fmt: skip

    assert "ran with the change, no failure this change causes" in line and "re-run" not in line


def test_the_findings_head_says_the_tests_ran_with_the_change_and_each_failure_alone() -> None:
    findings = report.findings_text("0123456789abcdef", Verdict(("t::a",), (), (), (), ()), CLEAN, [])

    assert findings.startswith(report.FINDINGS_HEAD + " 0123456789ab")
    assert "ran the tests that cover it with the change" in findings
    assert "re-run on its own, first with the change and, when it failed again, on an unpatched copy" in findings
    assert "then on an unpatched copy" not in findings, "a failure that passed alone was never re-run on dev"
    assert "on that copy and on an unpatched copy" not in findings and "compared the two by test id" not in findings
    assert report.HEADINGS["regressed"] in findings and report.FORMER_HEADINGS["regressed"][0] not in findings


def test_past_the_rerun_cap_the_findings_head_never_says_each_failure_was_re_run() -> None:
    """Failures past RERUN_CAP are never re-run, so the head names how many were and how many were not."""
    tried = tuple(f"t::{n}" for n in range(RERUN_CAP))
    past = tuple(f"t::late_{n}" for n in range(5))
    at_cap = report.findings_text("0123456789abcdef", Verdict(tried[:1], (), tried[1:], (), ()), CLEAN, [])
    over = report.findings_text("0123456789abcdef", Verdict(tried[:1], (), tried[1:], (), past), CLEAN, [])

    same_words = (
        "Each failure was then re-run on its own, first with the change and, when it failed again, on an unpatched "
        "copy of the same commit, and compared by test id."
    )
    assert same_words in at_cap, "at the cap every failure was re-run, and the words stay as they were"
    assert same_words not in over and "Each failure" not in over
    assert (
        f"The first {RERUN_CAP} of its {RERUN_CAP + 5} failures were then each re-run on its own, first with the "
        "change and, when it failed again, on an unpatched copy of the same commit, and compared by test id; the "
        "other 5 were not re-run." in over
    )


def test_findings_in_the_words_used_before_the_rewording_are_still_read_by_their_kinds() -> None:
    assert [kind["kind"] for kind in repair_ledger.kinds("sent_back", OLD)] == ["regressed", "added_fail"]


def test_new_findings_land_as_the_same_kinds() -> None:
    findings = report.findings_text("0123456789abcdef", Verdict(("t::a",), (), (), (), ()), CLEAN, [])

    assert repair_ledger.kinds("sent_back", findings) == [{"kind": "regressed"}]


def test_no_heading_is_found_inside_another() -> None:
    every = [*report.HEADINGS.values(), *(old for olds in report.FORMER_HEADINGS.values() for old in olds)]

    for one, other in permutations(every, 2):
        assert one not in other, (one, other)
