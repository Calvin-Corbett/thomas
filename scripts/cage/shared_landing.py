"""Landing a shared card after you approved it: one commit per change, one compare-and-swap, each change's verdict.

Your decision, 2026-10-08: "Yes, batch cards". scripts/cage/shared_card.py asks the card; this puts your approval in.

- Right after your answer, ``dev`` is checked for a move and the running copy is checked again.
- Each commit is made only after your answer, and only when the chain is exactly the one the card showed, checked with
  a plain ``if``: ``python -O`` removes every ``assert``.
- ``dev`` moves in one ``update-ref`` (self_change_checks.land), so it never holds part of a card. When landing raises
  after that move, ``dev`` itself says what landed (design 6.4): each change gets its own verdict at once, naming what
  happened, and nothing is asked again.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from scripts.cage import card_chain
from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp

log = logging.getLogger("thomas.self_change_promoter")

_BROKEN = "the changes on the card are not the ones it showed, so none of them landed"


def put_in(p: sp.Promoter, chain: list[card_chain.Member], base: str) -> list[sp.Outcome] | str:
    """After you approved: each change's verdict once it landed (or once landing raised after dev moved), "again"
    when dev moved under the card, or "alone" when nothing landed and each is to be asked on its own card. A fault
    outside the landing itself is raised."""
    if p._dev() != base:  # a commit made while the card was up is no one's uncommitted work: ask again
        return "again"
    tip = chain[-1].tree
    net = checks.tree_changes(p.repo, base, tip)
    refusal, already = checks.running_copy_refusal(p.repo, base, tip, net)  # again, right after your answer
    if refusal:
        log.warning("the running copy changed while a shared card was up (%s); each change is asked alone", refusal)
        return "alone"
    try:
        commits = commit_chain(p, chain, base)
        note = checks.land(p.repo, p.branch, commits[-1], base, net, already)
    except checks.Moved:
        return "again"
    except (checks.Refused, *sp._HAND_IN_FAULTS) as exc:  # dev never moved, land() put it back, or it raised after
        decided = _after_dev_moved(p, chain, exc) if p._dev() != base else []
        if decided:
            return decided
        log.warning("the changes on one card could not land together (%s); each is asked alone", exc)
        return "alone"
    return landed_together(p, chain, commits, note)


def _after_dev_moved(p: sp.Promoter, chain: list[card_chain.Member], exc: BaseException) -> list[sp.Outcome]:
    """Landing raised after update-ref moved dev onto the card. dev itself says what landed: each change's own commit,
    landed when the running copy has it too, else an error naming what it lacks. [] when dev does not hold the card:
    someone else moved it, and nothing landed."""
    tip = p._dev()
    found: list[sp.Outcome] = []
    for m in chain:
        card_chain.enter(p, m)
        own = p._landed_before(tip)
        if own is None:
            return []
        found.append(own)
    said = f"landing raised after {p.branch} moved ({type(exc).__name__}: {str(exc)[:200]})"
    log.error("%s; each change on the shared card gets the verdict %s supports", said, p.branch)
    verdicts: list[sp.Outcome] = []
    for m, o in zip(chain, found):
        words = f"{said}; {o.detail}" if o.status == "error" else f"on {p.branch} and in the running copy; {said}"
        verdicts.append(card_chain.settle(p, m, replace(o, detail=words, card=dict(m.place))))
    return verdicts


def commit_chain(p: sp.Promoter, chain: list[card_chain.Member], base: str) -> list[str]:
    """One commit per change, each on the one before, made only after your answer. Each is checked first to be exactly
    what its line showed, with a plain if: nothing lands when the chain is not the one on the card."""
    commits: list[str] = []
    parent = prev = base
    for m in chain:
        if m.base != prev or checks.tree_changes(p.repo, m.base, m.tree) != m.changes:
            raise checks.Refused(_BROKEN)
        card_chain.enter(p, m)
        parent = checks.make_commit(p.repo, m.tree, parent, *p._message(m.files, m.place))
        commits.append(parent)
        prev = m.tree
    return commits


def landed_together(p: sp.Promoter, chain: list[card_chain.Member], commits: list[str], note: str) -> list[sp.Outcome]:
    """Each change's own verdict, naming its own commit and the card it was on."""
    others = len(chain) - 1
    words = note or f"on {p.branch} and in the running copy, with the {others} other change(s) on the same card"
    return [
        card_chain.settle(p, m, sp.Outcome("landed", words, commit, m.files, card=dict(m.place)))
        for m, commit in zip(chain, commits)
    ]
