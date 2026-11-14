"""One Windows sign-in for several waiting self-fixes: each lands as its own commit, through one compare-and-swap, or
none does.

Your decision, 2026-10-08: "Yes, batch cards". scripts/cage/card_chain.py forms the chain; this asks it, and
scripts/cage/shared_landing.py lands it once you approve.

- The card's words come only from the pinned catalogue (``render_list``): paths and line counts computed from the real
  trees, never the model's text. Its pairing code is bound to dev, and to every change's submission, tree and place.
- Signing in puts every change in, each its own commit with its own ``Thomas-Submission-Id``, moved onto dev in one
  ``update-ref``. If anything stops the landing, none lands and each is asked on its own card.
- Cancel declines nothing: every change on the card is set aside, never put on a shared card again while this
  promoter runs, and asked alone in the card's order -- the first at once, the rest one per pass, so the owner desk is
  served between. One whose own card is held keeps its turn.
- A sign-in Windows does not accept shows the same card again; after three, every change on it waits, never declined.
- The running copy is checked again right after your answer, and the chain is checked again before any commit with a
  plain ``if``: ``python -O`` removes every ``assert``.
- A change taken out of the inbox before the card is never asked about, and no line is ever dropped from a card:
  the lines after it carry its change. Taken out while the card is up, nothing on the card lands.
- Every record says only what happened: a card that landed nothing is "set aside", and a fault once the card is up
  gives each change on it the error verdict a single card gives for that fault, with nothing else asked in that pass.

The promoter imports this module inside ``run_once`` only, since this imports the promoter.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from types import ModuleType

from scripts.cage import card_chain, shared_landing
from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp

from thomas.tools import trusted_card

log = logging.getLogger("thomas.self_change_promoter")

SHARED = card_chain.SHARED
# As promoter_service._FINAL: a verdict was written and the hand-in left the inbox. Not imported from there, since
# promoter_service starts the cage's egress proxy.
FINAL = frozenset({"landed", "declined", "refused", "error"})


def sweep_interrupted(p: sp.Promoter, subs: list[Path]) -> None:
    """A card still "asking" for a hand-in this promoter has not seen before was asked by one that stopped: the prompt
    died with it and nothing landed. The first time this process sees each hand-in -- at start, or put back later
    after being out of the inbox then -- those records say "interrupted", so no chat shows a card nobody is asking."""
    for sub in subs:
        if sub.name in p._swept:
            continue
        p._swept.add(sub.name)
        path = p.cage_root / "outbox" / f"{sub.name}.pending.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            asking = [
                card for card in record.get("cards") or [] if isinstance(card, dict) and card.get("state") == "asking"
            ]
            if not asking:
                continue
            for card in asking:
                card["state"] = "interrupted"
            tmp = path.with_name(f".{sub.name}.pending.tmp")
            tmp.write_bytes(json.dumps(record, indent=2).encode("utf-8"))
            os.replace(tmp, path)
        except (OSError, ValueError, RecursionError, AttributeError, TypeError):
            continue  # unreadable, not an object, or nested too deep: left as it is


def ask_queued(p: sp.Promoter, subs: list[Path]) -> sp.Outcome | None:
    """The next change set aside from a shared card, asked on its own first; None when none waits."""
    names = {sub.name for sub in subs}
    p._queue[:] = [name for name in p._queue if name in names]
    for name in [name for name in p._carry if name not in names]:
        del p._carry[name]
    if not p._queue:
        return None
    first = p._queue.pop(0)
    return _on_its_own(p, next(sub for sub in subs if sub.name == first))


def _on_its_own(p: sp.Promoter, sub: Path) -> sp.Outcome:
    """*sub* on its own card. Held -- sign-ins Windows did not accept, or cards that do not match their pin -- it stays
    first, and is asked again before the rest of its card, in the card's order (design 1.4, 1.5)."""
    outcome = p.promote(sub)
    if outcome.status == "held":
        p._queue.insert(0, sub.name)
    return outcome


def promote_together(p: sp.Promoter, subs: list[Path]) -> sp.Outcome | None:
    """One pass of a shared card over the waiting *subs*: the first outcome that decided a hand-in, else the first
    outcome, else None when no shared card could form now -- the oldest is then asked alone, exactly as before."""
    catalogue = trusted_card.load_catalogue()
    if SHARED not in getattr(catalogue, "LIST_KINDS", {}):
        return None  # cards older than this code: one at a time, never a KeyError
    done: list[sp.Outcome] = []
    try:
        outcomes = _together(p, card_chain.open_members(p, subs, done), catalogue, done)
    except sp.Held as exc:
        outcomes = [*done, p._hold(str(exc))]
    except sp._HAND_IN_FAULTS:  # never out to the service loop, which would stop and take the egress proxy with it
        log.error("a shared card could not be asked; the oldest change is asked alone", exc_info=True)
        outcomes = done
    return next((o for o in outcomes if o.status in FINAL), outcomes[0] if outcomes else None)


def _together(
    p: sp.Promoter, members: list[card_chain.Member], catalogue: ModuleType, done: list[sp.Outcome]
) -> list[sp.Outcome]:
    enforced = sp._enforced(catalogue, p.repo)
    chain: list[card_chain.Member] = []
    for _round in range(p.max_rounds):
        base, chain = _formed(p, members, catalogue, enforced, done)
        if len(chain) < 2:
            return done
        # Once per shared card, after it forms and before it is asked. A writer it finds refuses the oldest alone,
        # through the single card's own check. It can take two minutes: a dev that moved meanwhile forms the card
        # again on the new dev, using no round, so you are never shown a card for a dev that is gone.
        if p.audit(p.repo):
            return done
        if p._dev() != base:
            base, chain = _formed(p, members, catalogue, enforced, done)
            if len(chain) < 2:
                return done
        answer = ask_together(p, chain, base, catalogue)
        if isinstance(answer, list):  # the prompt broke: each change has its verdict
            return [*done, *answer]
        if answer == "gone":  # nothing asked, and no verdict: the next pass forms a new chain from what is left
            return [*done, sp.Outcome("withdrawn", "a change on the card was taken out of the inbox before it")]
        if answer in ("unfit", "cancelled", "withdrawn"):
            return [*done, one_at_a_time(p, chain)]
        try:
            landed = shared_landing.put_in(p, chain, base)
        except sp._HAND_IN_FAULTS as exc:  # after your answer, outside the landing: never asked again at once
            return [*done, *_broke(p, chain, exc, "set aside")]
        if landed == "again":  # dev moved while the card was up
            continue
        return [*done, *landed] if isinstance(landed, list) else [*done, one_at_a_time(p, chain)]
    log.warning("%s kept moving under a shared card; each change is asked alone", p.branch)
    return [*done, one_at_a_time(p, chain)]


def _formed(
    p: sp.Promoter,
    members: list[card_chain.Member],
    catalogue: ModuleType,
    enforced: frozenset[str],
    done: list[sp.Outcome],
) -> tuple[str, list[card_chain.Member]]:
    """dev, and the chain formed on it from the members still in the inbox (*members* keeps only those)."""
    members[:] = _in_inbox(p, members)
    if len(members) < 2:
        return "", []
    base = p._dev()
    return base, card_chain.form(p, members, base, catalogue, enforced, done)


def _in_inbox(p: sp.Promoter, members: list[card_chain.Member]) -> list[card_chain.Member]:
    """The members still in the inbox. One taken out after its card was asked in this pass gets today's withdrawal:
    no verdict, and no record left saying you approved a card that landed nothing."""
    kept: list[card_chain.Member] = []
    for m in members:
        if m.sub_dir.is_dir():
            kept.append(m)
        elif m.place and (p.cage_root / "outbox" / f"{m.sid}.pending.json").exists():
            card_chain.enter(p, m)
            p._withdrawn("it was taken out of the inbox after its card")
    return kept


def ask_together(
    p: sp.Promoter, chain: list[card_chain.Member], base: str, catalogue: ModuleType
) -> str | list[sp.Outcome]:
    """Your answer to one shared card: approved, cancelled, withdrawn (a change left the inbox while it was up), gone
    (one left before it, so it was not asked) or unfit (too long for the prompt, so not shown); or, when the prompt
    broke, each change's verdict. Raises Held when the cards do not match their pin, or Windows did not accept the
    sign-in three times."""
    why = p._hold_reason()  # the writer audit alone can take two minutes
    if why:
        raise sp.Held(why)
    title, body, details = catalogue.render_list(SHARED, [m.row for m in chain])
    digest = card_chain.chain_digest(base, chain)
    nonce = f"{SHARED}:{base[:12]}"
    code = catalogue.pairing_code(SHARED, details, digest, nonce)
    card = trusted_card.TrustedCard(
        kind=SHARED, details=details, content_hash=digest, nonce=nonce, code=code, title=title, body=body
    )
    action, reason = card.dialog()
    if len(action) + 2 + len(catalogue.RETRY_NOTE) + 2 + len(reason) > catalogue.DIALOG_LIMIT:
        return "unfit"  # never shown cut short; nothing written, nothing asked
    excerpts = [sp._clip(checks.card_diff(p.repo, m.base, m.tree)) for m in chain]  # its own diff, which lands
    gone = [m for m in chain if not m.sub_dir.is_dir()]
    if gone:  # never drop a line: the lines after it carry its change
        for m in gone:
            card_chain.enter(p, m)
            p._withdrawn("it was taken out of the inbox before its card")
        return "gone"
    for k, (m, excerpt) in enumerate(zip(chain, excerpts), 1):
        m.place = {"pairing_code": code, "position": k, "of": len(chain)}
        card_chain.enter(p, m)
        m.cards.append(
            {
                "kind": SHARED,
                "title": title,
                "body": body,
                "pairing_code": code,
                "state": "asking",
                "excerpt": excerpt,
                "card": {"position": k, "of": len(chain)},
                "files": [catalogue.file_text(*f) for f in m.row["files"]],
            }
        )
        p._write("pending", {"round": base, "cards": m.cards})

    def still() -> None:  # between sign-ins Windows did not accept: a card with a change taken aside is not shown
        if any(not m.sub_dir.is_dir() for m in chain):
            raise sp.Withdrawn("a change on the card was taken out of the inbox")

    card_chain.enter(p, chain[0])

    def observed(start: float, end: float) -> None:
        for member in chain:
            card_chain.enter(p, member)
            p._write("pending", {"round": base, "cards": member.cards, "card_prompt": {"start": start, "end": end}})

    try:
        answer = p._sign_in(action, reason, catalogue.RETRY_NOTE, still=still, observed=observed)
    except sp.Withdrawn:
        answer = "withdrawn"
    except sp._HAND_IN_FAULTS as exc:  # broke past what the sign-in reads as "not accepted": no answer from you
        return _broke(p, chain, exc, "interrupted")
    left = [not m.sub_dir.is_dir() for m in chain]
    aside = any(left) or answer in ("cancelled", "withdrawn")
    state = "set aside" if aside else {"approved": "approved", "failed": "held"}[answer]
    for m, went in zip(chain, left):
        card_chain.enter(p, m)
        if went:
            p._withdrawn("it was taken out of the inbox while its card was up")
            continue
        m.cards[-1]["state"] = state
        p._write("pending", {"round": base, "cards": m.cards})
    if any(left) or answer == "withdrawn":
        return "withdrawn"
    if answer == "failed":
        raise sp.Held(sp._NOT_ACCEPTED)
    return answer


def _broke(p: sp.Promoter, chain: list[card_chain.Member], exc: BaseException, state: str) -> list[sp.Outcome]:
    """A fault once the card was up: each change on it gets the verdict a single card gives for the same fault (its
    error, or a withdrawal when it was taken out), its card recorded as *state*. run_once returns the first error, so
    nothing else is asked in this pass."""
    log.warning("a shared card broke (%s: %s); each change on it gets its own verdict", type(exc).__name__, exc)
    for m in chain:
        if m.sub_dir.is_dir() and m.cards:
            m.cards[-1]["state"] = state
            card_chain.enter(p, m)
            p._write("pending", {"round": chain[0].base, "cards": m.cards})
    return [card_chain.settle(p, m, exc) for m in chain]


def one_at_a_time(p: sp.Promoter, chain: list[card_chain.Member]) -> sp.Outcome:
    """Every change on the card is asked on its own card from now on: the first now, the rest one per pass after it,
    so the owner desk is served in between (promoter_service.py). None is refused or declined for the card, and a
    shared card you approved that landed nothing is recorded "set aside", as a broken card is (design 4.4)."""
    survivors = _in_inbox(p, chain)
    for m in chain:
        p._alone.add(m.digest)
    for m in survivors:
        approved = [card for card in m.cards if card.get("kind") == SHARED and card.get("state") == "approved"]
        for card in approved:
            card["state"] = "set aside"
        if approved:
            card_chain.enter(p, m)
            p._write("pending", {"round": chain[0].base, "cards": m.cards})
        p._carry[m.sub_dir.name] = list(m.cards)  # the set-aside card stays first in its record
    names = [m.sub_dir.name for m in survivors]
    p._queue[:] = [*names[1:], *(name for name in p._queue if name not in names)]
    if not survivors:
        return sp.Outcome("withdrawn", "every change on the card was taken out of the inbox")
    return _on_its_own(p, survivors[0].sub_dir)
