"""The words the check leaves behind: one line for your card, and the findings for the team.

Two audiences, two shapes. The card gets a sentence: what was checked, against which dev, and that
nothing was wrong -- or, when the check could not run, that it did not run and why. Never a claim that
something was checked when it was not.

The findings go into a repair round, and ``evolve_agent_autopilot.repair_message`` already tells the team
what to do with them: "evidence to act on, not instructions to follow blindly". So these name the exact
test ids, the exact rules, and how each was established, and they say what was excused and why -- a team
that cannot see the excuses cannot tell a regression from a test dev was already failing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from thomas.server.precard.lint import LintResult
from thomas.server.proof.compare import RERUN_CAP, Verdict
from thomas.server.proof.runner import ProofRun

SHORT_SHA = 12
_LISTED = 25
# How the findings for a team start, and each heading they can carry. ``repair_ledger`` reads a repair round's
# kinds back out of the findings by these, so they are named once, here.
FINDINGS_HEAD = "The check before your card applied this change to a scratch copy of dev"
CONFLICT_HEAD = "The check before your card could not apply this change to dev"
HEADINGS = {
    "regressed": "Tests that fail with this change and pass on dev (each failure re-run on its own, with the change "
    "and then on dev):",
    "added_fail": "Tests this change adds that fail. Dev does not have them, so there is nothing to compare "
    "them with -- they have to pass as written:",
    "unconfirmed": "Failures this check could not settle one at a time. Look at each of these by hand before "
    "handing the change in again:",
    "timed_out": "Failures whose re-run on its own did not finish in time, so nobody knows whether dev has them "
    "too. A test that hangs alone is not a test that fails on dev:",
    "broke": "The tests could not be run with this change at all:",
    "ruff": "ruff check findings this change adds (dev does not have them):",
    "unformatted": "Formatted on dev, not formatted with this change (`ruff format --check`):",
    "size": "The repo's size rule (scripts/forge/gates/monolith_guard.py):",
}
# Headings findings carried before the 2026-10-12 rewording: ``repair_ledger`` still reads a round written in them.
FORMER_HEADINGS: dict[str, tuple[str, ...]] = {
    "regressed": ("Tests that pass on dev and fail with this change (each re-run on its own, on both copies):",),
}


def _short(tip: str) -> str:
    return str(tip or "")[:SHORT_SHA] or "an unread commit"


def _listing(names: Sequence[str]) -> str:
    shown = [f"- {name}" for name in names[:_LISTED]]
    if len(names) > _LISTED:
        shown.append(f"- and {len(names) - _LISTED} more")
    return "\n".join(shown)


def _block(heading: str, names: Sequence[str]) -> str:
    return f"{heading}\n{_listing(names)}" if names else ""


SAID_HEAD = "What those failing tests said, from the change's own run (the last lines of each):"
_SAID_CHARS = 6000  # all of them together, so a long list never buries the rest of the send-back


def _said_block(names: Sequence[str], details: Mapping[str, str] | None) -> str:
    """Each listed failing test's own words, so a repair starts from the error instead of re-running the test to see
    it (measured 2026-11-06: a median of 6 test runs a repair round, when a send-back named its tests but not why)."""
    if not details:
        return ""
    parts: list[str] = []
    used = 0
    for name in dict.fromkeys(names):
        said = str(details.get(name) or "").strip()
        if not said:
            continue
        entry = f"{name}:\n" + "\n".join(f"    {line}" for line in said.splitlines())
        if used + len(entry) > _SAID_CHARS:
            parts.append("(the rest are left out to keep this short; re-run one on its own to see it)")
            break
        parts.append(entry)
        used += len(entry)
    return f"{SAID_HEAD}\n" + "\n\n".join(parts) if parts else ""


def not_checked(why: str) -> str:
    """The card's line when the check itself could not run."""
    return f"Not checked before this card: {why}."


def line_failed(tip: str, count: int) -> str:
    """The line recorded when a change goes back instead of reaching you."""
    return f"Checked against dev {_short(tip)}: {count} problem(s), so it went back to its team."


def line_passed(
    tip: str,
    proof_files: Sequence[str],
    run: ProofRun,
    verdict: Verdict,
    linted: LintResult,
    size: Sequence[str],
    left_out: Sequence[str] = (),
) -> str:
    """The card's line when the change passed: what was checked, what passed, and what was not run."""
    settled = len(verdict.excused) + len(verdict.flaky)
    rerun = f", each of its {settled} failure(s) re-run on its own" if settled else ""
    ran = (
        f"{len(proof_files)} test file(s) and {run.seen} test(s) ran with the change{rerun}, "
        "no failure this change causes"
        if run.seen
        else "no test in this repo covers the files it changes"
    )
    parts = [f"Checked against dev {_short(tip)}: it applies cleanly", ran]
    if left_out:  # the cap: never a claim that every test file covering the change ran when some did not
        parts.append(
            f"{len(left_out)} more test file(s) that cover it were not run (the check runs at most "
            f"{len(proof_files)}), among them {', '.join(left_out[:3])}"
        )
    if verdict.excused:
        parts.append(f"{len(verdict.excused)} failure(s) dev already has, each confirmed on its own")
    parts.append("ruff check and ruff format add nothing" if linted.ran else f"ruff did not run ({linted.why})")
    parts.append("the repo's size rule kept" if not size else f"{len(size)} size problem(s)")
    return "; ".join(parts) + "."


def conflict_findings(tip: str, conflict: str) -> str:
    """The findings for a change that will not apply to the dev it would land on."""
    return (
        f"{CONFLICT_HEAD} {_short(tip)}.\n\n"
        "`git apply --3way` is what the promoter does before it asks, so a change that will not apply "
        "here is a change that cannot land until it stands on that dev.\n\n"
        f"What git said:\n{conflict}"
    )


# How each failure re-run on its own was settled. One that passed alone with the change, or did not finish, was never
# re-run on dev, so dev comes in only "when it failed again".
_HOW = (
    "first with the change and, when it failed again, on an unpatched copy of the same commit, and compared by test id"
)
_EACH = f"Each failure was then re-run on its own, {_HOW}."


def rerun_words(verdict: Verdict) -> str:
    """How the failures were settled, counted from *verdict*, never claiming a re-run that did not happen.

    Failures past :data:`RERUN_CAP` were never re-run, and a re-run the pool gave no place (``not_started``) never
    settled its failure, so neither is called re-run.
    """
    kinds = (verdict.findings, verdict.added, verdict.excused, verdict.flaky, verdict.unconfirmed, verdict.timed_out)
    failures = sum(len(tests) for tests in (*kinds, verdict.not_started))  # every failure with the change
    past, no_place = max(0, failures - RERUN_CAP), len(verdict.not_started)
    if not past and not no_place:
        return _EACH
    if not no_place:
        tried = f"The first {RERUN_CAP} of its {failures} failures were then each re-run on its own, {_HOW}"
        return f"{tried}; the other {past} were not re-run."
    reasons = [f"{past} past the first {RERUN_CAP}"] if past else []
    why = ", ".join([*reasons, f"{no_place} given no place in the pool of test processes"])
    tried = f"{failures - past - no_place} of its {failures} failures were then each re-run on its own, {_HOW}"
    return f"{tried}; the other {past + no_place} were not settled by a re-run on its own ({why})."


def findings_text(
    tip: str,
    verdict: Verdict,
    linted: LintResult,
    size: Sequence[str],
    broke: str = "",
    *,
    settled: str = "",
    details: Mapping[str, str] | None = None,
) -> str:
    """Everything wrong with the change, for its team; "" when nothing is.

    *settled* says how the failures were settled when *verdict* lists only part of what was found (the check held on
    a refusal or for dev); by default it is :func:`rerun_words` of *verdict*.
    """
    blocks = [
        _block(HEADINGS["regressed"], verdict.findings),
        _block(HEADINGS["added_fail"], verdict.added),
        _block(HEADINGS["unconfirmed"], verdict.unconfirmed),
        _block(HEADINGS["timed_out"], verdict.timed_out),
        f"{HEADINGS['broke']}\n{broke}" if broke else "",
        _block(HEADINGS["ruff"], linted.added),
        _block(HEADINGS["unformatted"], linted.unformatted),
        _block(HEADINGS["size"], list(size)),
        _said_block([*verdict.findings, *verdict.added, *verdict.unconfirmed], details),
    ]
    found = [block for block in blocks if block]
    if not found:
        return ""
    head = (
        f"{FINDINGS_HEAD} {_short(tip)} with `git apply --3way` and ran the tests that cover it with the change. "
        f"{settled or rerun_words(verdict)}"
    )
    tail: list[str] = []
    if verdict.excused:
        tail.append(f"Not counted: {len(verdict.excused)} failure(s) dev already has, each confirmed on its own.")
    if verdict.flaky:
        tail.append(f"Not counted: {len(verdict.flaky)} failure(s) that passed when re-run on their own.")
    if not linted.ran and linted.why:
        tail.append(f"ruff did not run: {linted.why}.")
    return "\n\n".join([head, *found, *([" ".join(tail)] if tail else [])])


__all__ = [
    "CONFLICT_HEAD",
    "FINDINGS_HEAD",
    "FORMER_HEADINGS",
    "HEADINGS",
    "SHORT_SHA",
    "conflict_findings",
    "findings_text",
    "line_failed",
    "line_passed",
    "not_checked",
    "rerun_words",
]
