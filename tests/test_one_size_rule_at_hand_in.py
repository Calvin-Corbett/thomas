"""The repo's two size registers are read as one rule, and the hand-in check reads it.

WHAT WENT WRONG, IN THIS REPO'S OWN NUMBERS

``thomas/agent/loop_execution.py`` is listed in ``docs/monolith_guard_baseline.json`` under
``allowed_large_files`` with ``max_lines`` 1100 and ``max_growth_lines`` 130. It is NOT recorded in the
``agent`` module's ``debt`` note in ``thomas/_architecture.py``, which names ``swarm.py`` and nothing else.
``tests/test_architecture.py::test_debt_trending`` fails any ``.py`` file under ``thomas/`` over
``RULES["max_new_file_lines"]`` (800) that no debt note records, and it walks the whole tree rather than the
changed files -- so it fails for everyone, on every commit, not only for the change that caused it.

A change taking that file to 900 lines therefore passed its hand-in size check (``green_handoff.size_problems``,
which read only the baseline) and then broke every later commit's architecture check until the file was split.
Same limit, 800, in both registers; two different exemption lists; one of them checked at hand-in.

AND THE SAME GAP, THE OTHER WAY ROUND

``tests/test_architecture.py::test_health_annotations`` reads those same debt notes backwards: a note that
names a file which does not exist fails, and a note whose text says "exceeds" fails for any file it names that
is 800 lines or fewer. So trimming ``thomas/server/routes/work.py`` from 805 lines to 799 -- the split the
team notes ask for -- also passed the hand-in check and then failed every later commit. Both directions are
checked here.

These tests read the REAL registers in this checkout, so they keep speaking about the repo as it actually is,
and one drives the whole hand-in path against a real git green.

SINCE THE SIZES WERE PINNED (Step 25)

The baseline grants no headroom any more: every entry is frozen at its file's size with ``max_growth_lines`` 0,
and ``loop_execution.py``, under 800 lines when the sizes were pinned, has no entry at all. So the 900-line case
cannot pass the baseline half in this repo now. The tests that replay it put that one old waiver back on top of
the real registers (``OLD_WAIVER``); everything else is still read from this checkout as it is.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from thomas.server import green_checkout, green_handoff, green_size_rule

ROOT = Path(__file__).resolve().parents[1]
WAIVED = "thomas/agent/loop_execution.py"  # baselined to 1100 until the pins, absent from the agent debt note
RECORDED = "thomas/server/routes/work.py"  # the other way round: a debt note calls it oversized
# The waiver loop_execution.py carried until the sizes were pinned: the one the 900-line case slipped through.
OLD_WAIVER = {"owner": "thomas-core", "max_lines": 1100, "max_growth_lines": 130, "reason": "before the pins"}


def _with_the_old_waiver(rule: green_size_rule.SizeRule) -> green_size_rule.SizeRule:
    return dataclasses.replace(rule, allowed={**rule.allowed, WAIVED: OLD_WAIVER})


@pytest.fixture
def rule() -> green_size_rule.SizeRule:
    return green_size_rule.read_rule(ROOT)


def test_both_registers_are_actually_read_out_of_this_checkout(rule: green_size_rule.SizeRule) -> None:
    """Neither half may quietly fall back to a default: the numbers must come from the files."""
    assert rule.soft == 800 and rule.architecture_limit == 800  # the same number, written in two places
    # The baseline half, read: since the sizes were pinned, the file the 900-line case grew has no entry at all,
    # which is why the tests below put its old waiver back to replay that case.
    assert WAIVED not in rule.allowed
    # The architecture half, read: a file the debt notes DO record, and one they do not.
    assert "thomas/server/routes/work.py" in rule.debt_recorded
    assert WAIVED not in rule.debt_recorded
    # And the names that test skips, taken from where it takes them rather than copied.
    assert {"repl.py", "_architecture.py"} <= set(rule.architecture_skip)


def test_the_waiver_that_passed_is_still_a_waiver_and_the_debt_register_still_refuses(
    rule: green_size_rule.SizeRule,
) -> None:
    """The exact 900-line case, judged by each half and then by the rule."""
    problems = green_size_rule.file_problems(_with_the_old_waiver(rule), WAIVED, 900, before=796)
    baseline_half = [p for p in problems if green_size_rule.ARCHITECTURE not in p]
    assert baseline_half == [], f"the baseline waiver was meant to pass 900 lines: {baseline_half}"
    assert len(problems) == 1 and "_architecture.py" in problems[0]
    assert "test_architecture.py" in problems[0] and "800" in problems[0]
    assert "for every commit after this one" in problems[0]  # the team is told whose problem it becomes
    # With the registers as they are now the baseline half refuses it as well: nothing grants that headroom.
    assert len(green_size_rule.file_problems(rule, WAIVED, 900, before=796)) == 2


def test_a_file_the_debt_notes_record_is_not_refused_by_the_architecture_half(
    rule: green_size_rule.SizeRule,
) -> None:
    """The rule adds a register, it does not add a second 800-line ceiling to everything."""
    recorded = "thomas/server/routes/work.py"  # 'routes/work.py exceeds 800 lines', and baselined to 806
    assert green_size_rule.file_problems(rule, recorded, 806, before=806) == []
    # Under the limit, neither register has anything to say about any file.
    assert green_size_rule.file_problems(rule, WAIVED, 796, before=796) == []


def test_only_files_the_architecture_test_measures_are_judged_by_it(rule: green_size_rule.SizeRule) -> None:
    """test_debt_trending walks .py under thomas/ and skips its own forbidden/legacy names.

    Outside thomas/ the baseline half still speaks -- it is the gate that covers scripts/ and tests/ -- so
    what is asserted there is that the architecture half stays silent, not that nothing is wrong.

    The architecture half is told apart by the full ``thomas/_architecture.py`` its message names: the bare
    tail of that path is a substring of ``tests/test_architecture.py``, which is one of the paths here.
    """
    for rel in ("scripts/forge/gates/workboard_claims.py", "tests/test_architecture.py"):
        problems = green_size_rule.file_problems(rule, rel, 900, before=900)
        assert not any(green_size_rule.ARCHITECTURE in p for p in problems), rel
        assert any("allowed_large_files" in p for p in problems), rel  # the baseline half does judge it
    # repl.py is skipped by name (a legacy pattern); since the sizes were pinned it has no baseline entry, so only
    # the baseline half may speak about a 1400-line repl.py.
    repl = green_size_rule.file_problems(rule, "thomas/cli/repl.py", 1400, before=1400)
    assert repl and not any(green_size_rule.ARCHITECTURE in p for p in repl)
    pinned = int(rule.allowed["thomas/_architecture.py"]["max_lines"])  # frozen at its size, skipped by name
    assert green_size_rule.file_problems(rule, "thomas/_architecture.py", pinned, before=pinned) == []
    # A .py under thomas/ with no waiver anywhere is refused by BOTH halves, and hears both reasons.
    fresh = green_size_rule.file_problems(rule, "thomas/server/brand_new_module.py", 1400, before=0)
    assert len(fresh) == 2 and any("allowed_large_files" in p for p in fresh)


def test_the_register_is_read_the_other_way_round_too(rule: green_size_rule.SizeRule) -> None:
    """A debt note that stops being true breaks the same architecture check, from the other side.

    ``test_health_annotations`` fails a note that names a file that does not exist, or that calls a file
    oversized when it is no longer over 800 lines. Trimming a recorded file under the limit -- the move the
    team notes ask for -- used to pass the hand-in check and fail every commit after it.
    """
    assert RECORDED in rule.debt_named and RECORDED in rule.debt_oversize  # 'routes/work.py exceeds 800 lines'

    trimmed = green_size_rule.stale_debt_problems(rule, RECORDED, 799)
    assert len(trimmed) == 1 and "calls it oversized" in trimmed[0]
    assert "test_health_annotations" in trimmed[0] and "for every commit after this one" in trimmed[0]
    assert green_size_rule.stale_debt_problems(rule, RECORDED, 805) == []  # still over: the note is still true

    gone = green_size_rule.stale_debt_problems(rule, RECORDED, None)
    assert len(gone) == 1 and "not in this change's tree any more" in gone[0]
    # A file no note names is not this check's business, at any size, present or deleted.
    for lines in (10, None):
        assert green_size_rule.stale_debt_problems(rule, WAIVED, lines) == []


def test_a_note_that_says_exceeds_once_claims_it_for_every_file_it_names(rule: green_size_rule.SizeRule) -> None:
    """Why the claim is read per NOTE: that is how ``test_health_annotations`` reads it.

    The ``forge`` note names three files in one note. Splitting any one of them fails the check, so the
    hand-in warning has to reach all three, not only the one whose own phrase says "exceeds".
    """
    forge = ("evolve_verification.py", "native_orchestration.py", "run_report.py")
    for rel in (f"thomas/forge/anvil/{name}" for name in forge):
        assert rel in rule.debt_oversize, rel
        assert green_size_rule.stale_debt_problems(rule, rel, 700)


def _git(cwd: Path, *args: str) -> None:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    subprocess.run(command, cwd=cwd, check=True, capture_output=True)


def test_the_hand_in_check_refuses_the_green_that_would_have_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: a real green whose change keeps the baseline waiver and breaks the debt register.

    ``green_handoff.size_problems`` is what ``thomas_project.settle_if_finished`` calls before handing a
    project to your sign-in card, and a problem there raises ``ChangeTooLarge`` -- the project goes back to
    its team for a repair round instead of landing.
    """
    blue = tmp_path / "blue"
    (blue / "thomas" / "agent").mkdir(parents=True)
    (blue / "thomas" / "server" / "routes").mkdir(parents=True)
    (blue / "docs").mkdir()
    # Both registers copied from this checkout, so the green is judged by the repo's real numbers, with the one
    # old waiver put back that the case below grew through (see the module docstring).
    baseline = json.loads((ROOT / green_size_rule.BASELINE).read_text(encoding="utf-8"))
    baseline["allowed_large_files"][WAIVED] = OLD_WAIVER
    (blue / green_size_rule.BASELINE).write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    (blue / green_size_rule.ARCHITECTURE).write_text(
        (ROOT / green_size_rule.ARCHITECTURE).read_text(encoding="utf-8"), encoding="utf-8"
    )
    (blue / WAIVED).write_text("x = 1\n" * 796, encoding="utf-8")
    (blue / RECORDED).write_text("x = 1\n" * 805, encoding="utf-8")  # as its debt note says: over 800
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(blue, *args)

    greens = tmp_path / "green"
    (greens / "work").mkdir(parents=True)
    (greens / "git").mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    green = green_checkout.create_green(blue=blue, execution_id="exec-size-rule")

    (green.work / WAIVED).write_text("x = 1\n" * 900, encoding="utf-8")  # +104: inside max_growth_lines 130
    problems = green_handoff.size_problems("exec-size-rule")
    assert len(problems) == 1, problems
    assert WAIVED in problems[0] and "900 lines" in problems[0] and "_architecture.py" in problems[0]

    (green.work / WAIVED).write_text("x = 1\n" * 799, encoding="utf-8")  # split back under the one limit
    assert green_handoff.size_problems("exec-size-rule") == []

    # And the other direction, through the same hand-in check: the debt note stops being true about a file
    # this change trimmed. Neither the baseline (baselined to 806) nor the first direction has anything to say
    # about 799 lines, which is exactly why this used to land and then fail every commit after it.
    (green.work / RECORDED).write_text("x = 1\n" * 799, encoding="utf-8")
    trimmed = green_handoff.size_problems("exec-size-rule")
    assert len(trimmed) == 1, trimmed
    assert RECORDED in trimmed[0] and "calls it oversized" in trimmed[0]

    # What that refusal tells the team to do -- take the file out of its debt note in the same change -- must
    # then pass: the rule is read from this change's own checkout. On 2026-09-25 it was read from the running
    # copy, and the performance project that did exactly this was refused until its repair rounds ran out.
    architecture = green.work / green_size_rule.ARCHITECTURE
    noted = architecture.read_text(encoding="utf-8")
    clause = (
        "routes/work.py exceeds 800 lines (the Work lane proposal routes tipped a file that sat exactly on the cap); "
    )
    assert noted.count(clause) == 1
    architecture.write_text(noted.replace(clause, ""), encoding="utf-8")  # the clause out, the rest of the note kept
    assert green_handoff.size_problems("exec-size-rule") == []
    architecture.write_text(noted, encoding="utf-8")

    (green.work / RECORDED).unlink()  # deleting it instead leaves the same note describing nothing
    deleted = green_handoff.size_problems("exec-size-rule")
    assert len(deleted) == 1 and "not in this change's tree any more" in deleted[0], deleted
