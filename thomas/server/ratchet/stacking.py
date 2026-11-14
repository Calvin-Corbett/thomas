"""A candidate stacked on another is proven as its own commits above the one that landed, never whole.

The census sees a stack while both commits have refs. On 2026-09-24 only the seven
refs/heads/praxis/* heads pointed at fcb5f06 (``git for-each-ref --points-at
fcb5f06``), and each salvage snapshot sat one commit above it. The archive only
copies a landed candidate's refs, so those heads stay and the census keeps seeing
the stack; the ledger, which records the landing, is asked too, for a lower commit
whose own refs someone has since removed. Merging a snapshot whole would bring
fcb5f06's own change back, its deletion of tests/test_chat_delegation.py included.
"""

from __future__ import annotations

from thomas.server.ratchet.candidates import Candidate
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import Ledger

LANDED = ("landed", "already_on_dev")


def landed_below(repo: Repo, ledger: Ledger, cand: Candidate, dev: str) -> str:
    """The nearest commit under *cand*, not on dev, whose landing the ledger records ("" when none)."""
    latest = ledger.latest()
    for sha in repo.out("rev-list", f"{dev}..{cand.sha}").split()[1:]:  # newest first; cand itself left out
        if str(latest.get(sha, {}).get("state") or "") in LANDED:
            return sha
    return ""


def onto_for(repo: Repo, ledger: Ledger, cand: Candidate, dev: str) -> tuple[str, str, str]:
    """(onto, state, why) for *cand* in this run.

    *onto* is the landed commit to prove it above ("" for a whole merge). When it is
    not proven this run, *state* says how that is recorded and *why* says why:
    ``queued`` while the work under it has not landed, ``reported`` when that work
    never will, or when *cand* sits more than one commit above it.
    """
    below = cand.stacked_on or landed_below(repo, ledger, cand, dev)
    if not below:
        return "", "", ""
    state = str(ledger.latest().get(below, {}).get("state") or "")
    if state not in LANDED:
        gave_up = ledger.gave_up(below)
        if gave_up:
            return "", "reported", f"it is stacked on {below[:12]}, which will not land: {gave_up}"
        return "", "queued", f"it waits on {below[:12]}, which it is stacked on ({state or 'not proven yet'})"
    above = repo.out("rev-list", "--count", f"{below}..{cand.sha}")
    if above != "1":
        why = f"it sits {above} commits above {below[:12]}; the ratchet brings in one commit at a time"
        return "", "reported", why
    return below, "", ""


def note_once(ledger: Ledger, cand: Candidate, dev: str, state: str, why: str) -> None:
    """Record why *cand* is not proven, once: a later run that finds the same reason adds no line."""
    last = ledger.latest().get(cand.sha, {})
    if (last.get("state"), last.get("reason")) != (state, why):
        ledger.record(candidate=cand, dev_sha=dev, state=state, reason=why)


__all__ = ["LANDED", "landed_below", "note_once", "onto_for"]
