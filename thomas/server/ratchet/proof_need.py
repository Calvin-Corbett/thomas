"""The proof cap, checked on the merge before a repair Build is spent on a candidate.

The ratchet proves a candidate with the test files its change reaches, at most ``proof_set.MAX_FILES`` of them
(``proof_set.select``). That set was only chosen on the green, after any repair (``attempt.prove_green``), and a
set past the cap is refused there (``results.capped``). The unify candidate 2f730c5 spent 3 repair Builds, 5.1
hours, before that refusal reported it (measured 2026-10-07).

So before a repair Build starts, :func:`capped_before_a_repair` makes ``prove_green``'s selection, with its limit,
on the tree ``git merge-tree`` writes for the merge (into a temporary object store, ``Repo.scratch``, as
``screen.screen`` measures it). It starts no run and makes no green. It does not count what the screen tells the
repair to settle on dev's side (:func:`settled_on_devs_side`): a conflict where one side deleted the file ("keep
dev's file", "keep dev's deletion"), a file dev deleted coming back, a test file that copies tests dev already
has. Those may end up as dev's own version and reach no test, so they are left out of the count, and their test
files out of the tree.

A file both sides changed or added is counted: its repair is told to keep both sides' intent, so it stays changed.
A repair that kept only dev's side of one (dev had already done the same thing its own way) could have come in
under the cap, and such a candidate is still reported here (review 2026-10-07, R4). Nothing after a repair would
catch the difference: ``merge_integrity`` objects only to deletions and, before a repair, to extra paths. Leaving
those files out too would have let the case this check exists for through: for 2f730c5 on dev 8b879b0c the whole
merge leaves 1,418 test files out, this count 1,403, and a count without any conflicted file 0 (measured
2026-10-07: 10 conflicts both sides changed, 30 that dev deleted). A report fails closed: the candidate is checked
again when dev moves, until it has been reported ``MAX_REPORTS`` times.

A candidate that needs no repair is not counted here: it costs a green and no Build, and ``prove_green`` refuses
a set past the cap before dev's proof or its own runs.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from thomas.server.ratchet import proof_set
from thomas.server.ratchet.candidates import Candidate
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import MAX_REPORTS
from thomas.server.ratchet.proof_set import ProofSet
from thomas.server.ratchet.screen import Screen

FOUND_EARLY = (
    "Found on the merge, before a repair Build was spent on it. It is checked again each time dev moves, until it "
    f"has been reported {MAX_REPORTS} times"
)
_DEVS_SIDE = ("candidate_deleted", "dev_deleted")  # screen._ADVICE: keep dev's file; keep dev's deletion


def proof_need(
    repo: Repo, dev_sha: str, cand: Candidate, changed: Sequence[str], *, onto: str = "", without: Collection[str] = ()
) -> ProofSet:
    """The proof set the merge of *cand* onto dev at *dev_sha* gets: ``prove_green``'s selection and limit.

    *without* names files to count as absent from the merged tree. The limit is read when this runs
    (``select``'s default was bound when it was defined), so the check and the tests that lower the cap see the
    same number.
    """
    with repo.scratch() as s:
        args = ["merge-tree", "--write-tree", "--name-only", "--no-messages"]
        if onto:
            args.append(f"--merge-base={onto}")
        merged = s.run(*args, dev_sha, cand.sha, ok=(0, 1))
        tree = merged.stdout.split("\n", 1)[0].strip()
        return proof_set.select(s, tree, changed, base=dev_sha, limit=proof_set.MAX_FILES, without=without)


def settled_on_devs_side(found: Screen) -> set[str]:
    """Paths the screen tells a repair to settle on dev's side: a conflict where one side deleted the file, a file
    dev deleted coming back, a test file that copies tests dev already has."""
    paths = {conflict.path for conflict in found.conflicts if conflict.kind in _DEVS_SIDE}
    paths |= {path for _status, path in found.changes if any(e.startswith(f"{path} (") for e in found.resurrected)}
    paths |= {entry.split("::", 1)[0] for entry in found.duplicate_tests}
    return paths


def past_the_cap(need: ProofSet) -> str:
    """Why *need* cannot be proven ("" when it fits under the cap)."""
    if not need.left_out:
        return ""
    return (
        f"{need.left_out} test file(s) that prove it would not be run, not counting what its repair is told to "
        f"keep as dev has it: the proof set is capped at {proof_set.MAX_FILES}. {FOUND_EARLY}"
    )


def capped_before_a_repair(repo: Repo, dev_sha: str, cand: Candidate, found: Screen, *, onto: str = "") -> str:
    """Why *cand* would be refused for the cap after the repair it is about to get ("" when it may fit)."""
    drop = settled_on_devs_side(found)
    kept = [path for _status, path in found.changes if path not in drop]
    return past_the_cap(proof_need(repo, dev_sha, cand, kept, onto=onto, without=drop))


__all__ = ["FOUND_EARLY", "capped_before_a_repair", "past_the_cap", "proof_need", "settled_on_devs_side"]
