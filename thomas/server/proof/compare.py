"""Which failures the change is responsible for: one run with the change, each failure confirmed alone.

The rule you set on 2026-09-25: "count only failures that pass on dev and fail with the patch, each re-run alone to
rule out flakiness". Spec 2026-10-12 Part 1 item 2 made it the only rule: a failure blocks unless it passes when re-run
alone with the change (noise) or fails alone on dev (already broken there). Nothing else excuses it: not dev's own full
run, which the check no longer makes unless it has to (``precard/check.py``).

Every candidate is a test that failed in the run with the change. It is re-run on its own there first: a test that
passes alone was noise from its neighbours, not a finding. It is then re-run on its own on dev: failing there excuses
it, passing there convicts the change, and a dev copy that does not have the test at all means the change brought a
failing test with it, which is its own finding, named separately so nobody reads it as a regression.

Only a re-run that finished can confirm anything. A re-run that timed out, on either copy, is
:attr:`Verdict.timed_out`, and it blocks. Candidates past :data:`RERUN_CAP`, and any a re-run could not settle, are
:attr:`Verdict.unconfirmed`, and they block too. ``known_on_dev`` only orders the work: failures already known on dev
are confirmed last. A re-run the pool gave no place never started (:attr:`Verdict.not_started`): it proved nothing, so
it neither blocks nor passes, and the check holds the change for another try.

Re-runs may go side by side (``workers``), each in its own report and sandbox (``runner.run_one``). A failure excused
by a dev re-run that ran beside others is re-run once more on dev, one at a time within this check after the
side-by-side pass, in a sandbox of its own (``again_on_base``, required with ``workers``). :data:`RERUN_CAP` counts
only the failures tried: the second dev re-runs are at most one for each of them, and the check's deadline ends them
like any other re-run, so one cut short is :attr:`Verdict.timed_out`, never an excuse.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from thomas.server.proof.runner import FAILED, MISSING, NO_PLACE, PASSED, TIMEOUT

# How many failures are settled by re-runs on their own (one with the change and one on dev each): the real cost of a
# noisy proof. An excuse settled once more on dev is not counted again; past this many failures the check runs dev in
# full instead (spec 2026-10-12 Part 1 item 3).
RERUN_CAP = 40
_ON_DEV = {FAILED: "excused", MISSING: "added", PASSED: "findings", TIMEOUT: "timed_out", NO_PLACE: "not_started"}
_KINDS = ("findings", "added", "excused", "flaky", "unconfirmed", "timed_out", "not_started")


@dataclass(frozen=True)
class Verdict:
    """Every failure with the change, sorted into what it means."""

    findings: tuple[str, ...]
    added: tuple[str, ...]
    excused: tuple[str, ...]  # dev fails it too, confirmed by a re-run on its own there
    flaky: tuple[str, ...]
    unconfirmed: tuple[str, ...]
    timed_out: tuple[str, ...] = ()  # its re-run on its own did not finish, so nothing is known about it
    not_started: tuple[str, ...] = ()  # the pool gave its re-run on its own no place: never blocking, never a pass

    @property
    def blocking(self) -> tuple[str, ...]:
        return self.findings + self.added + self.unconfirmed + self.timed_out


def _on_dev(answer: str) -> str:
    return _ON_DEV.get(answer, "unconfirmed")


def confirm(
    with_change: Sequence[str],
    *,
    rerun_with_change: Callable[[str], str],
    rerun_on_base: Callable[[str], str],
    cap: int = RERUN_CAP,
    known_on_dev: Collection[str] = (),
    workers: int = 1,
    again_on_base: Callable[[str], str] | None = None,
) -> Verdict:
    """Sort the failures *with_change* by what a re-run of each, on its own, on both copies, shows.

    With *workers* above 1 the re-runs go side by side; each excuse a dev re-run gave there is then settled once more
    by *again_on_base*, one at a time. It is required then: falling back to *rerun_on_base* would settle the excuse in
    the first dev re-run's own sandbox, which that re-run wrote in and nothing clears.
    """
    if workers > 1 and again_on_base is None:
        raise ValueError("re-runs side by side need again_on_base: a sandbox of its own for the second dev re-run")
    known = set(known_on_dev)
    unique = list(dict.fromkeys(with_change))
    candidates = [test for test in unique if test not in known] + [test for test in unique if test in known]
    tried = candidates[: max(0, cap)]

    def settle(test: str) -> str:
        again = rerun_with_change(test)
        if again == PASSED:
            return "flaky"
        if again == TIMEOUT:
            return "timed_out"
        if again == NO_PLACE:
            return "not_started"  # the pool gave it no place: it never ran, which settles nothing either way
        if again != FAILED:
            return "unconfirmed"  # it could not be re-run on its own at all; nobody can say
        return _on_dev(rerun_on_base(test))

    if workers > 1 and len(tried) > 1 and again_on_base is not None:  # it is never None here: refused above
        with ThreadPoolExecutor(max_workers=min(workers, len(tried))) as side_by_side:
            buckets = list(side_by_side.map(settle, tried))  # in order: failures known on dev start last
        # A dev re-run beside others may have failed for its neighbours: each excuse it gave is settled once more on
        # dev, one at a time, before it counts. At most one more re-run per failure tried; the deadline ends them.
        again = again_on_base
        buckets = [_on_dev(again(test)) if bucket == "excused" else bucket for test, bucket in zip(tried, buckets)]
    else:
        buckets = [settle(test) for test in tried]
    found: dict[str, list[str]] = {name: [] for name in _KINDS}
    for test, bucket in zip(tried, buckets):
        found[bucket].append(test)
    found["unconfirmed"].extend(candidates[len(tried) :])
    return Verdict(**{name: tuple(tests) for name, tests in found.items()})


__all__ = ["RERUN_CAP", "Verdict", "confirm"]
