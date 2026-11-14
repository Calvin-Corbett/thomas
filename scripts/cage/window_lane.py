"""One checked hand-in, landed inside your window with no card (spec 2026-10-12, sections 8.2 and 8.4).

While a window is open, the lane takes up every hand-in in the inbox that the card loop has not already taken
(``take``, under the card loop's own lock, so no hand-in is ever held by both loops). When the window ends, or the
window's loop cannot rely on its checker or record, every hand-in it took goes back to the cards, exactly as today. No
one outside Thomas looks at a change first: Thomas's own gates decide. For each one, oldest first, from the bytes it
read once:

1. every check a card landing runs, except the prompt: the patch's write safety, the catalogue's pin, the change
   re-derived on dev without running any of it (``_derive_checked``: tree safety, gate files, compiling, removed
   imports), the writer audit and the running copy's uncommitted work (spec 8.2 condition 5);
2. no file on the never-in-a-window list (scripts/cage/window_rules.py; condition 4). A change with one leaves the lane
   and gets its cards from the card loop;
3. the checker's answer for that exact base, commit and tree is PASSED, from tests that ran as thomas-runner and an
   answer only thomas-checker could write (conditions 1 and 2);
4. the window's own second look, on a fresh copy, found that same change SAFE (condition 3).

Then, and only while the window says a landing may start: the write-ahead record, the commit naming the window, and
the same compare-and-swap landing a card uses. A failed check or a NOT SAFE second look refuses the hand-in with the
findings, so it goes back to its team; anything that could not run waits and is tried again.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp
from scripts.cage import window_review as wrev
from scripts.cage.window_evidence import Evidence, Prep, change_digest
from scripts.cage.window_record import Record
from scripts.cage.window_rules import Rules
from scripts.cage.window_state import Window

from thomas.tools import trusted_card

log = logging.getLogger("thomas.self_change_promoter")


def decided(cage_root: Path, sid: str) -> bool:
    """Whether *sid* already has a verdict (in the outbox, or its folder in processed): it never lands again."""
    root = Path(cage_root)
    return os.path.lexists(root / "outbox" / f"{sid}.verdict.json") or os.path.lexists(root / "processed" / sid)


class Lane:
    def __init__(
        self,
        p: sp.Promoter,
        *,
        link: object,
        reviewer: object,
        rules: Rules,
        record: Record,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.p = p
        # The checker's answer and the second look's verdict (scripts/cage/window_evidence.py).
        self.evidence = Evidence(link=link, reviewer=reviewer, clock=clock)
        self.rules = rules
        self.record = record
        self.last_landed: tuple[str, str, str, list[str]] | None = None  # sid, commit, parent, files
        self._preps: dict[str, Prep] = {}
        # The card loop's thread reads this (``owned``): it is replaced whole, never changed in place.
        self._taken: frozenset[str] = frozenset()
        self._released: set[str] = set()  # sent to their cards (a never-in-a-window file): never taken again

    def owned(self) -> frozenset[str]:
        """Hand-ins the card loop leaves alone: every one this lane took up for the open window."""
        return self._taken

    def takeable(self, card_busy: frozenset[str]) -> list[str]:
        """The hand-ins a window opened now would take up: in the inbox, on no card, never sent to one by this lane, and
        with no verdict yet."""
        names = (sub.name for sub in self.p.pending())
        return [
            sid
            for sid in names
            if sid not in card_busy and sid not in self._released and not decided(self.p.cage_root, sid)
        ]

    def take(self, window: Window, *, card_busy: frozenset[str], reliable: bool) -> None:
        """While a window is open and its checker and record can be relied on, own every takeable hand-in; otherwise
        hand every one back to the cards (spec 8.3: outside a window, today's cards; 8.8). Run under the card loop's
        lock (``Promoter.taking``): the card loop never picks one this owns, and this never owns one it picked."""
        taken = frozenset(self.takeable(card_busy)) if window.opened is not None and reliable else frozenset()
        self._released &= {sub.name for sub in self.p.pending()}
        for sid in self._taken - taken:  # back to the cards, or out of the inbox: nothing gathered for it counts
            self._drop(sid)
        self._taken = taken

    def waiting(self) -> list[dict[str, object]]:
        return [
            {
                "sid": prep.sid,
                "wait": prep.wait,
                "check": prep.check.verdict if prep.check else "",
                "second_look": prep.review.verdict if prep.review else "",
            }
            for prep in self._preps.values()
        ]

    def close(self) -> None:
        self.evidence.close()

    def step(self, window: Window, *, card_busy: frozenset[str], landing_allowed: bool) -> sp.Outcome | None:
        """Prepare every hand-in taken, oldest first, and land at most one. The first verdict ends the pass."""
        held = self.p._hold_reason()
        present: set[str] = set()
        taken = self._taken
        for sub in self.p.pending():
            present.add(sub.name)
            if held or sub.name not in taken or sub.name in card_busy:
                continue
            if decided(self.p.cage_root, sub.name):  # a verdict already ended it (2026-10-14 review, PR-R8)
                self._end(sub.name)
                continue
            outcome = self._one(sub, window, landing_allowed)
            if outcome is not None:
                return outcome
        for sid in [sid for sid in self._preps if sid not in present]:  # taken out of the inbox meanwhile
            self._end(sid)
        return None

    # -- one hand-in --------------------------------------------------------- #
    def _one(self, sub: Path, window: Window, landing_allowed: bool) -> sp.Outcome | None:
        p = self.p
        p._sub_dir, p._meta, p._cards, p._conflicts, p._digest = sub, {}, [], [], ""
        try:
            p._meta, patch = checks.read_submission(sub)
            digest = hashlib.sha256(patch).hexdigest()
            prep = self._preps.get(sub.name)
            if prep is None or prep.patch_sha != digest:  # new bytes are a new change: nothing gathered counts
                self._drop(sub.name)
                prep = self._preps[sub.name] = Prep(sub.name, digest)
            return self._advance(sub, prep, patch, window, landing_allowed)
        except sp.Withdrawn:
            self._end(sub.name)
            return None
        except (checks.Refused, *sp._HAND_IN_FAULTS) as exc:
            return self._final(sub, p._outcome_of(exc))

    def _advance(self, sub: Path, prep: Prep, patch: bytes, window: Window, landing_allowed: bool) -> sp.Outcome | None:
        p = self.p
        unsafe = checks.write_safety_refusal(patch.decode("utf-8", errors="replace"), p.repo)
        if unsafe:
            raise checks.Refused(unsafe)
        dev = p._dev()
        if prep.parent != dev:
            landed = self._derive(prep, patch, dev)
            if landed is not None:
                return self._final(sub, landed)
        catalogue = trusted_card.load_catalogue()
        enforced = sp._enforced(catalogue, p.repo)
        excluded = self.rules.excluded(prep.parent, prep.tree, prep.changes, catalogue=catalogue, enforced=enforced)
        if excluded:
            self._release(prep.sid)
            prep.wait = "needs its own card: " + "; ".join(f"{path} ({why})" for path, why in excluded[:4])
            log.info("%s: leaves the window lane: %s", prep.sid, prep.wait)
            return None
        found = self.evidence.gather(p, prep)
        if isinstance(found, sp.Outcome):
            return self._final(sub, found)
        if prep.review is not None and prep.review.verdict == wrev.TOO_LARGE:  # judged whole, or by you (2026-10-26)
            why = prep.review.why
            self._release(prep.sid)
            prep.wait = "needs its own card: " + why
            log.info("%s: leaves the window lane: %s", prep.sid, prep.wait)
            return None
        if not found:
            return None
        if not landing_allowed:
            prep.wait = "ready: waiting for the check after the last landing"
            return None
        why = window.why_not()
        if why:
            prep.wait = f"ready: waiting for your window ({why})"
            return None
        return self._land(sub, prep, window)

    def _derive(self, prep: Prep, patch: bytes, dev: str) -> sp.Outcome | None:
        """Derive the change on *dev* again; a landed verdict when dev already holds it."""
        p = self.p
        try:
            tree, changes = p._derive_checked(patch, dev, [])
        except checks.Refused:
            landed = p._landed_before(dev)
            if landed:
                return landed
            raise
        if not changes:
            landed = p._landed_before(dev)
            if landed:
                return landed
            raise checks.Refused(f"the change is already on {p.branch}")
        change = change_digest(p.repo, dev, tree, changes)
        self.evidence.forget(prep)
        prep.parent, prep.tree, prep.changes, prep.check = dev, tree, changes, None
        if prep.change != change:  # a look of the old change, finished or running, never counts for this one
            self.evidence.unreview(prep)
            prep.change = change
        return None

    def _land(self, sub: Path, prep: Prep, window: Window) -> sp.Outcome | None:
        p = self.p
        p._still_in_inbox()
        writers = p.audit(p.repo)
        if writers:
            raise checks.Refused("unexpected writers on Thomas's code: " + ", ".join(writers))
        refusal, already = checks.running_copy_refusal(p.repo, prep.parent, prep.tree, prep.changes)
        if p._dev() != prep.parent:  # a card landed meanwhile: derive again, as the card path does (review D6)
            prep.parent, prep.wait = "", "dev moved: derived and checked again"
            return None
        if refusal:
            raise checks.Refused(refusal)
        why, opened = window.why_not(), window.opened
        if why or opened is None:
            prep.wait = f"ready: waiting for your window ({why})"
            return None
        review = prep.review
        if review is None or not review.safe or review.change != prep.change:  # 2026-10-14 review, WS-R1
            self.evidence.unreview(prep)
            prep.wait = "its second look was not of this change: it is read again"
            return None
        if not self.evidence.refresh(prep):  # the answer read again at the landing itself (review B2)
            prep.wait = "its completed checker answer no longer passes: it is checked again"
            return None
        files = [path for _, path in prep.changes]
        commit = checks.make_commit(p.repo, prep.tree, prep.parent, *p._message(files, window=opened.trailer()))
        evidence = {"window_id": opened.window_id, "sid": prep.sid, "commit": commit, "parent": prep.parent}
        try:
            self.record.event("landing_intent", **evidence, tree=prep.tree)  # written before dev moves
        except OSError as exc:
            prep.wait = f"the window's record could not be written ({exc}); nothing landed"
            return None
        try:
            note = checks.land(p.repo, p.branch, commit, prep.parent, prep.changes, already)
        except checks.Moved:
            self._quietly("landing_moved", **evidence, reason="dev moved")
            prep.parent, prep.wait = "", "dev moved: derived and checked again"
            return None
        except checks.Refused as exc:
            self._quietly("landing_moved", **evidence, reason=str(exc)[:300])
            raise
        window.landed()
        self._quietly(
            "landed",
            **evidence,
            tree=prep.tree,
            files=files,
            change=prep.change,
            check_job=prep.job.id if prep.job else "",
            check_verdict=prep.check.verdict if prep.check else "",
            check_tree=prep.check.tree if prep.check else "",
            second_look=review.verdict,
            second_look_change=review.change,  # what the audit proves the landing by (2026-10-14 review, A5)
        )
        self.last_landed = (prep.sid, commit, prep.parent, files)
        words = note or f"on {p.branch} and in the running copy, inside your window"
        return self._final(sub, sp.Outcome("landed", words, commit, files, window=opened.trailer()))

    # -- bookkeeping --------------------------------------------------------- #
    def _final(self, sub: Path, outcome: sp.Outcome) -> sp.Outcome:
        """The hand-in's verdict, as the card loop writes it; it leaves the lane."""
        self._end(sub.name)
        if outcome.status == "withdrawn":
            return outcome
        self.p._finish(sub, outcome)
        if outcome.status != "landed":
            self._quietly("refused", sid=sub.name, status=outcome.status, detail=outcome.detail[:500])
        return outcome

    def _drop(self, sid: str) -> None:
        prep = self._preps.pop(sid, None)
        if prep is not None:
            self.evidence.drop(prep)

    def _end(self, sid: str) -> None:
        """*sid* left the lane (2026-10-14 review, RH-R7): what was gathered for it ends, and it is no longer taken."""
        self._drop(sid)
        self._taken = self._taken - {sid}

    def _release(self, sid: str) -> None:
        """*sid* goes to its cards, and is never taken again while it waits for them. Its wait stays shown."""
        prep = self._preps.get(sid)
        if prep is not None:
            self.evidence.drop(prep)
        self._released.add(sid)
        self._taken = self._taken - {sid}

    def _quietly(self, name: str, **fields: object) -> None:
        try:
            self.record.event(name, **fields)
        except OSError:
            log.warning("the window's record could not take %s for %s", name, fields.get("sid"), exc_info=True)


__all__ = ["Lane", "decided"]
