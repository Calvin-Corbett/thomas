"""Which waiting self-fixes can share one Windows sign-in, each checked on top of the one before.

Your decision, 2026-10-08: "Yes, batch cards". When two or more reviewed self-fixes are waiting, up to five of them go
on one card (scripts/cage/shared_card.py asks it). This module forms that card's chain and asks nothing:

- The oldest decides. When it cannot share, no shared card forms on this pass and it is asked alone first, so nothing
  newer goes ahead of it.
- Each next one joins when it passes every check a single card runs (self_change_promoter._derive_checked), derived on
  the tree the one before it leaves, and when the card can still name every file of it that must be named. The
  running copy holds ``dev``, not the trees in between, so its check is against ``dev``.
- Never on a shared card: a change with a file that guards Thomas (policy C keeps its own cards), a change with no chat
  (no chat card to match the code against), a change you were already asked about on its own (remembered by its
  patch bytes), and a change whose must-name files do not fit.
- A change that fails only on top of another waits for a later card, with no verdict: it must not be refused for
  someone else's change, which you may yet decline. Judged by itself on ``dev``, a change that fails is refused in the
  words it would get alone, and anything else that goes wrong with it is its own ``error``.

At most ``1 + CANDIDATES`` hand-ins are looked at in one pass, so a full inbox costs a bounded pass.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp

SHARED = "promote_several"
CANDIDATES = 10  # hand-ins looked at beyond the oldest, so at most 11 in one pass
# One change's line, as the catalogue takes it: {"files": [[path, A|M|D, added, deleted], ...]}.
Row = dict[str, list[list[object]]]


@dataclass
class Member:
    """One waiting hand-in, read once, and where it sits on a chain."""

    sub_dir: Path
    meta: dict[str, str] = field(default_factory=dict)
    patch: bytes = b""  # read once: these bytes are what is checked and applied
    digest: str = ""  # sha256 of patch: what "asked alone from now on" remembers
    cards: list[dict[str, object]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    base: str = ""  # what it was derived on: dev's commit for the first, the tree before it for the rest
    tree: str = ""
    changes: list[tuple[str, str]] = field(default_factory=list)
    row: Row = field(default_factory=dict)
    place: dict[str, object] = field(default_factory=dict)  # pairing_code, position, of: once it is asked

    @property
    def sid(self) -> str:
        return self.meta.get("id") or self.sub_dir.name

    @property
    def files(self) -> list[str]:
        return [path for _, path in self.changes]


def enter(p: sp.Promoter, m: Member) -> None:
    """Point the state the promoter's own steps read (_ask, _write, _finish, _withdrawn, _message, _landed_before,
    _no_longer_applies) at *m*. Call it again after rebinding ``m.meta``."""
    p._sub_dir, p._meta, p._cards, p._conflicts = m.sub_dir, m.meta, m.cards, m.conflicts


def settle(p: sp.Promoter, m: Member, result: sp.Outcome | BaseException) -> sp.Outcome:
    """*m*'s verdict, written before its folder leaves the inbox; or its withdrawal, which writes none."""
    enter(p, m)
    outcome = result if isinstance(result, sp.Outcome) else p._outcome_of(result)
    if outcome.status != "withdrawn":
        p._finish(m.sub_dir, outcome)
        p._carry.pop(m.sub_dir.name, None)
    return outcome


def open_members(p: sp.Promoter, subs: list[Path], done: list[sp.Outcome]) -> list[Member]:
    """The oldest waiting hand-ins, each read once and its patch checked as text. One that cannot be read or is unsafe
    to apply gets its own verdict in *done*, exactly as it would alone."""
    members: list[Member] = []
    for sub in subs[: 1 + CANDIDATES]:
        m = Member(Path(sub), cards=list(p._carry.get(Path(sub).name, [])))
        enter(p, m)
        try:
            m.meta, m.patch = checks.read_submission(m.sub_dir)
            enter(p, m)
            m.digest = hashlib.sha256(m.patch).hexdigest()
            unsafe = checks.write_safety_refusal(m.patch.decode("utf-8", errors="replace"), p.repo)
            if unsafe:
                raise checks.Refused(unsafe)
        except (checks.Refused, *sp._HAND_IN_FAULTS) as exc:
            done.append(settle(p, m, exc))
            continue
        members.append(m)
    return members


def may_share(p: sp.Promoter, m: Member) -> bool:
    """A chat to show its card in, and never asked about on its own before."""
    return bool(str(m.meta.get("chat") or "").strip()) and m.digest not in p._alone


def form(
    p: sp.Promoter,
    members: list[Member],
    base: str,
    catalogue: ModuleType,
    enforced: frozenset[str],
    done: list[sp.Outcome],
) -> list[Member]:
    """The chain for one shared card, from *base* (``dev``), oldest first: [] when the oldest cannot share. Each member
    on it has its ``base``, ``tree``, ``changes`` and ``row`` set. Members refused alone get their verdict in *done*."""
    chain: list[Member] = []
    rows: list[Row] = []
    prev = base
    most = catalogue.LIST_KINDS[SHARED].max_rows
    for m in members:
        head = not chain
        joined = link(p, m, prev, base, catalogue, enforced, done) if may_share(p, m) else "alone"
        if joined == "settled":  # refused or landed by itself, its verdict written: the next one is the oldest
            continue
        if isinstance(joined, str) or not fits(catalogue, rows, joined[2]):
            if head:  # it is asked alone first, nothing ahead of it
                return []
            continue  # "alone" or "wait": no verdict, it stays in the inbox
        m.base, (m.tree, m.changes, m.row) = prev, joined
        chain.append(m)
        rows.append(m.row)
        prev = m.tree
        if len(chain) == most:
            break
    return chain


def fits(catalogue: ModuleType, rows: list[Row], row: Row) -> bool:
    """Whether *row* fits the card after *rows*, every file it must name named in full."""
    try:
        return catalogue.fit_rows(SHARED, [*rows, row]) == len(rows) + 1
    except ValueError:  # a file the card cannot name: asked alone
        return False


def link(
    p: sp.Promoter,
    m: Member,
    prev: str,
    base: str,
    catalogue: ModuleType,
    enforced: frozenset[str],
    done: list[sp.Outcome],
) -> tuple[str, list[tuple[str, str]], Row] | str:
    """*m* on top of *prev*: (tree, changes, row) when it can ride the card; else "alone" (a guarded file), "wait"
    (it fails only on top of the changes ahead of it) or "settled" (judged by itself on dev, its verdict written)."""
    enter(p, m)
    try:
        tree, changes = p._derive_checked(m.patch, prev, [])
        if not changes:
            raise checks.Refused("nothing left to apply on top of the changes ahead of it")
        refusal, _already = checks.running_copy_refusal(p.repo, base, tree, changes)  # the running copy holds base
        if refusal:
            raise checks.Refused(refusal)
        for _status, path in changes:
            diff = checks.file_diff(p.repo, prev, tree, path)
            if catalogue.danger_class(path, added_diff=diff, enforcement_paths=enforced):
                return "alone"
        row: Row = {"files": p._listed(prev, tree, changes)}
    except (checks.Refused, *sp._HAND_IN_FAULTS):
        own = alone_refusal(p, m, base)
        if own is None:
            return "wait"
        done.append(settle(p, m, own))
        return "settled"
    return tree, changes, row


def alone_refusal(p: sp.Promoter, m: Member, base: str) -> sp.Outcome | BaseException | None:
    """*m* judged by itself on dev, as a single card would judge it: its refusal or fault (returned, not raised), the
    landed verdict of a change that landed before the promoter stopped, or None when it passes alone."""
    enter(p, m)
    m.conflicts.clear()
    try:
        tree, changes = p._derive_checked(m.patch, base, [])
        if not changes:
            return p._landed_before(base) or checks.Refused(f"the change is already on {p.branch}")
        refusal, _already = checks.running_copy_refusal(p.repo, base, tree, changes)
    except checks.Refused as exc:  # once landed, a file it adds or deletes no longer applies: its own commit first
        return p._landed_before(base) or exc
    except sp._HAND_IN_FAULTS as exc:
        return exc
    return checks.Refused(refusal) if refusal else None


def chain_digest(base: str, chain: list[Member]) -> str:
    """What the shared card's pairing code is bound to: dev, and every member's sid, base and tree, in order."""
    bound = [["dev", base], *([m.sid, m.base, m.tree] for m in chain)]
    return hashlib.sha256(json.dumps(bound, separators=(",", ":")).encode("ascii")).hexdigest()
