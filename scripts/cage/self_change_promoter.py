"""The only way a self-fix reaches the running Thomas: your approval, on a pinned card.

A self-fix is made in green and handed to the commit-master inbox as a
``self_change`` submission (thomas/server/green_handoff.py). This promoter runs
as you, in your session -- it has to, to show the Windows sign-in -- and takes
the inbox in the order it first saw each hand-in, and those it first saw
together in the order they were handed in. For each one it:

1. reads the patch once -- those bytes are what is checked, applied and asked
   about, since the caged account can rewrite the file -- checks it is safe to
   apply at all, and that nobody unexpected can write Thomas's code (refusing
   before any prompt if not);
2. re-derives the change on the current ``dev`` without executing any of it, and
   judges the tree git built as well as the patch text
   (scripts/cage/self_change_checks.py);
3. asks you: one card for each file that guards Thomas (policy C, and you can
   leave any of them out), then one card for the whole change -- worded by the
   pinned catalogue, with a pairing code bound to the exact tree, and the same
   card written to the outbox so the chat that asked can show it;
4. right after your answer, asks again about the new tree if ``dev`` moved
   while the card was up; else checks the running copy again, then moves
   ``dev`` only if it has not moved since, and then the running copy's changed
   files.

While the approval cards do not match their pin, every hand-in waits: nothing is
asked, refused or landed (a re-pin refused self-thomas-eb0e79c9d549 on
2026-10-08). A sign-in Windows does not accept is never your answer: the same
card is asked again, and after three in a row it is put away for two minutes,
never declined. Only Cancel declines. Anything else that goes wrong with one
hand-in is that hand-in's ``error`` verdict: it never stays first in the inbox,
holding up every hand-in behind it.

When two or more are waiting, up to five share one card (your decision,
2026-10-08: "Yes, batch cards"): scripts/cage/card_chain.py forms the chain,
each change checked on top of the one before, scripts/cage/shared_card.py asks
it, and scripts/cage/shared_landing.py lands each change as its own commit, or
none. Cancel there declines nothing: each change is then asked on its own
single card. One waiting hand-in, and a change with a guarded file, with no
chat, or that you were asked about on its own, always get the cards above.

Spec: docs/superpowers/specs/2026-09-22-trusted-self-change-design.md, section 7.

A change that no longer applies to ``dev`` is refused with every file that stops
it named, in the verdict's ``conflicts`` and in its words. Measured 2026-09-24,
the refusal kept only git's first 300 characters and ended mid-word ("error:
tests/web_node/conftest.py: does not mat"), so the team sent to repair it could
not see what to merge.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType

from scripts.cage import self_change_checks as checks

from thomas.tools import trusted_card

log = logging.getLogger("thomas.self_change_promoter")

REPO_ROOT = Path(__file__).resolve().parents[2]
# The prompt's answer: "approved", "cancelled" or "failed" (an older asker, or a test, answers True or False).
Ask = Callable[[str, str], bool | str]
Audit = Callable[[Path], list[str]]

# Sign-ins Windows did not accept, in a row, before a card is put away; and how long every hand-in then waits, so a
# prompt that cannot show never spins and a mistyped PIN never declines anything.
_TRIES = 3
_QUIET_S = 120.0
# Named, not "except Exception": the families a hand-in or the prompt can raise. A hand-in that raises one of these
# gets its own "error" verdict instead of stopping every hand-in behind it; a prompt that raises one is not an answer.
_HAND_IN_FAULTS = (
    OSError,
    ValueError,
    LookupError,
    TypeError,
    AttributeError,
    ArithmeticError,
    RuntimeError,  # RecursionError included: Python or a manifest nested past what the parser reads
    ImportError,
    AssertionError,
    EOFError,
    subprocess.SubprocessError,
)
_PROMPT_FAULTS = (OSError, RuntimeError, ValueError, TypeError, AttributeError, ImportError, LookupError)
_NOT_ACCEPTED = (
    "the sign-in did not go through three times in a row (not accepted, or the prompt did not show); the card is "
    "asked again shortly"
)


@dataclass
class Outcome:
    status: str  # landed | declined | refused | error | withdrawn | held
    detail: str = ""
    commit_sha: str = ""
    files: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)  # every file that stops the change applying to dev
    card: dict[str, object] = field(default_factory=dict)  # the shared card it landed on: pairing_code, position, of
    window: dict[str, object] = field(default_factory=dict)  # the window it landed in: window_id, opened_at, code


# How self_change_checks.derive_tree begins the refusal, and how git names each file that will not apply.
_NO_LONGER_APPLIES = "the change no longer applies to "
_MAX_CONFLICTS = 200
_CONFLICT_LINES = (
    re.compile(r"^Applied patch to '(.+)' with conflicts\.$"),
    re.compile(r"^error: patch failed: (.+):\d+$"),
    re.compile(r"^error: (.+?): (?:does not exist in index|does not match index|already exists in index)$"),
    re.compile(r"^error: (.+?): (?:patch does not apply|No such file or directory)$"),
    re.compile(r"^U (.+)$"),
)


def _conflicting_files(repo: Path, parent: str, patch: Path | bytes, exclude: list[str]) -> list[str]:
    """Every file git names when the patch will not apply to *parent*: the same apply ``derive_tree`` ran, whole."""
    with tempfile.TemporaryDirectory() as tmp:
        patch_path = checks.patch_file(patch, tmp)
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if checks.run_git(repo, "read-tree", parent, env=env).returncode:
            return []
        skip = checks.exclude_args(exclude)
        apply = checks.apply_apart(repo, tmp)  # never in the running copy: git's --3way can write there
        three_way = (*apply, "--cached", "--3way", "--whitespace=nowarn", *skip, str(patch_path))
        output = checks.run_git(repo, *three_way, env=env).stderr
    names: list[str] = []
    for line in output.splitlines():
        match = next((found for found in (p.match(line.strip()) for p in _CONFLICT_LINES) if found), None)
        if match:
            names.append(match.group(1))
    return list(dict.fromkeys(names))


def _clip(diff: str, max_lines: int = 80) -> str:
    lines = diff.splitlines()
    shown = "\n".join(lines[:max_lines])
    return shown + (f"\n... {len(lines) - max_lines} more line(s)" if len(lines) > max_lines else "")


def _answer(value: object) -> str:
    """approved, cancelled or failed. True and False are an older asker's sign-in and Cancel; anything else is a
    prompt that did not answer, never a no from you."""
    if value is True:
        return "approved"
    if value is False:
        return "cancelled"
    return str(value) if value in ("approved", "cancelled", "failed") else "failed"


def _windows_sign_in(action: str, reason: str) -> str:
    from thomas.tools.windows_auth import sign_in_answer

    return sign_in_answer(action, reason)


def _real_audit(repo: Path) -> list[str]:
    from scripts.cage.writer_audit import unexpected_writers

    return unexpected_writers(repo)


def _handed_in_at(sub: Path) -> float:
    """When the server handed *sub* in, from its manifest; infinity when that cannot be read (promote() says why)."""
    try:
        when = json.loads((sub / "submission.json").read_text(encoding="utf-8")).get("submitted_at")
    except (OSError, ValueError, RecursionError, AttributeError, TypeError):  # unreadable, not an object, too deep
        return math.inf
    return float(when) if isinstance(when, (int, float)) and math.isfinite(when) else math.inf


def _enforced(catalogue: ModuleType, repo: Path) -> frozenset[str]:
    try:
        return catalogue.load_enforcement_paths(repo)
    except OSError:
        return frozenset()


class Withdrawn(Exception):  # noqa: N818 - reads as what happened
    """The hand-in left the inbox while it was being promoted: it was moved aside to be checked first.

    On 2026-09-27 a hand-in was moved to ``withdrawn`` a minute after the promoter had picked it up; the promoter
    kept going from what it had read, asked twice, and landed a change its check had just found not safe.
    """


class Held(Exception):  # noqa: N818 - reads as what happened
    """Nothing asked, nothing landed, nothing refused: the hand-in stays in the inbox and is taken up again later."""


class Promoter:
    def __init__(
        self,
        *,
        repo: Path = REPO_ROOT,
        cage_root: Path,
        ask: Ask | None = None,
        pin_root: Path | None = None,
        audit: Audit | None = None,
        branch: str = "dev",
        max_rounds: int = 3,
        clock: Callable[[], float] = time.monotonic,
        skip: Callable[[], frozenset[str]] | None = None,
    ) -> None:
        self.repo = Path(repo)
        self.cage_root = Path(cage_root)
        self.ask = ask or _windows_sign_in
        self.pin_root = pin_root
        self.audit = audit or _real_audit
        self.branch = branch
        self.max_rounds = max_rounds
        self.clock = clock
        self._seen: dict[str, int] = {}  # each hand-in's place, in the order this promoter first saw it
        self._next_place = 0
        self._quiet_until = 0.0
        self._said = ""
        # Several hand-ins on one card (scripts/cage/card_chain.py, shared_card.py). Memory only: a restart forgets
        # them, and at worst a change set aside is a line on a shared card again, where Cancel declines nothing.
        self._alone: set[str] = set()  # patch digests asked about one at a time from now on
        self._queue: list[str] = []  # hand-ins to ask alone first, in their card's order
        self._carry: dict[str, list[dict[str, object]]] = {}  # a set-aside shared card's record, kept before its own
        self._swept: set[str] = set()  # hand-ins whose stale "asking" records were marked interrupted, each once
        # Part 4: the hand-ins the window's loop owns now (scripts/cage/window_loop.py), which this one leaves alone;
        # and the hand-ins this one's current pass took up, which the window's loop leaves alone in turn. Both are
        # decided under *taking*, so a hand-in is never taken up by both loops at once.
        self.skip: Callable[[], frozenset[str]] = skip or frozenset
        self.busy: frozenset[str] = frozenset()
        self.taking = threading.Lock()

    def pending(self) -> list[Path]:
        """The inbox in the order this promoter first saw each hand-in.

        Hand-ins first seen together -- those waiting when it started, and every one that arrived while a card was up,
        which is most of them (overnight 2026-10-07, four arrived during one card) -- go in the order they were handed
        in (``submitted_at``, green_handoff.py), then by name. The caged account writes both, so it can reorder only
        hand-ins first seen together, as names always let it; never ahead of one seen before."""
        inbox = self.cage_root / "inbox"
        found = [p for p in inbox.glob("self-*") if p.is_dir()] if inbox.is_dir() else []
        names = {p.name for p in found}
        self._seen = {name: place for name, place in self._seen.items() if name in names}
        for sub in sorted((p for p in found if p.name not in self._seen), key=lambda p: (_handed_in_at(p), p.name)):
            self._seen[sub.name] = self._next_place
            self._next_place += 1
        ordered = sorted(found, key=lambda sub: self._seen[sub.name])
        skip = self.skip()
        return [sub for sub in ordered if sub.name not in skip] if skip else ordered

    def run_once(self) -> Outcome | None:
        with self.taking:  # the window's lane takes hand-ins under the same lock (scripts/cage/window_lane.py)
            subs = self.pending()
            self.busy = frozenset(sub.name for sub in subs)
        if not subs:
            return None
        try:
            return self._run_once(subs)
        finally:
            self.busy = frozenset()

    def _run_once(self, subs: list[Path]) -> Outcome | None:
        from scripts.cage import shared_card  # here, not at the top: shared_card imports this module

        shared_card.sweep_interrupted(self, subs)
        why = self._hold_reason()
        if why:
            return self._hold(why)
        self._said = ""
        queued = shared_card.ask_queued(self, subs)  # set aside from a shared card: asked alone, first
        if queued is not None:
            return queued
        if len(subs) >= 2:  # one waiting: today's single card, untouched
            outcome = shared_card.promote_together(self, subs)
            if outcome is not None:
                return outcome
            subs = self.pending()
            if not subs:
                return None
        return self.promote(subs[0])  # the oldest, alone

    def _hold_reason(self) -> str:
        """Why every hand-in waits now, or "": a pause after sign-ins Windows did not accept, or approval cards that
        do not match their pin -- a re-pin under way, or cards changed on disk since this promoter loaded them."""
        if self.clock() < self._quiet_until:
            return _NOT_ACCEPTED
        status = trusted_card.catalogue_status(pin_root=self.pin_root)
        if status != trusted_card.STATUS_OK:
            return f"the approval cards are {status}: nothing is asked and nothing lands until they match their pin"
        try:
            trusted_card.require_trusted_catalogue(pin_root=self.pin_root)
        except trusted_card.CatalogueTampered as exc:
            return f"{exc}; restart the promoter"
        return ""

    def _hold(self, why: str) -> Outcome:
        if why != self._said:
            log.warning("holding every hand-in: %s", why)
            self._said = why
        return Outcome("held", why)

    def promote(self, sub_dir: Path) -> Outcome:
        name = Path(sub_dir).name
        # A shared card it was on and that was set aside stays first in its record, before its own card.
        self._cards: list[dict[str, object]] = list(self._carry.get(name, []))
        self._meta: dict[str, str] = {}
        self._conflicts: list[str] = []
        self._digest = ""
        self._sub_dir = Path(sub_dir)
        try:
            outcome = self._promote(Path(sub_dir))
        except Held as exc:
            return self._hold(str(exc))
        except (Withdrawn, checks.Refused, *_HAND_IN_FAULTS) as exc:
            outcome = self._outcome_of(exc)
        self._carry.pop(name, None)
        if outcome.status == "withdrawn":
            return outcome
        if outcome.status == "declined" and self._digest:
            self._alone.add(self._digest)  # declined on its own card: never put on a shared card again
        self._finish(Path(sub_dir), outcome)
        return outcome

    def _outcome_of(self, exc: BaseException) -> Outcome:
        """What one hand-in's failure is: a withdrawal (no verdict), a refusal in its own words, or its own error --
        never every hand-in's wait. A pass that raised used to leave the hand-in first in the inbox, and the next pass
        took it again: a manifest nested past what json reads, or Python past what the parser nests, stopped every
        hand-in."""
        if isinstance(exc, Withdrawn):
            return self._withdrawn(str(exc))
        if not self._sub_dir.is_dir():  # the patch went with it: a withdrawal, not a refusal
            return self._withdrawn("it was taken out of the inbox before its card")
        if isinstance(exc, checks.Refused):
            return Outcome("refused", str(exc), conflicts=list(self._conflicts))
        if not isinstance(exc, (OSError, ValueError)):
            log.error("%s: promotion failed", self._sub_dir.name, exc_info=exc)
        return Outcome("error", f"{type(exc).__name__}: {str(exc)[:300]}")

    def _still_in_inbox(self) -> None:
        if not self._sub_dir.is_dir():
            raise Withdrawn("it was taken out of the inbox before it landed")

    def _withdrawn(self, why: str) -> Outcome:
        """No verdict and no card left asking: put back in the inbox, it is taken up again from the start."""
        sid = self._meta.get("id") or self._sub_dir.name
        (self.cage_root / "outbox" / f"{sid}.pending.json").unlink(missing_ok=True)
        log.info("%s: withdrawn, %s; nothing landed", sid, why)
        return Outcome("withdrawn", why)

    # -- the flow ---------------------------------------------------------- #
    def _promote(self, sub_dir: Path) -> Outcome:
        # Read once: the caged account can rewrite change.patch at any moment, and the writer audit below takes up to
        # two minutes. These bytes are what is checked, applied and asked about.
        self._meta, patch = checks.read_submission(sub_dir)
        self._digest = hashlib.sha256(patch).hexdigest()  # what "asked about on its own" remembers (card_chain.py)
        unsafe = checks.write_safety_refusal(patch.decode("utf-8", errors="replace"), self.repo)
        if unsafe:
            raise checks.Refused(unsafe)
        why = self._hold_reason()
        if why:
            raise Held(why)
        writers = self.audit(self.repo)
        if writers:
            raise checks.Refused("unexpected writers on Thomas's code: " + ", ".join(writers))
        catalogue = trusted_card.load_catalogue()
        enforced = _enforced(catalogue, self.repo)

        excluded: list[str] = []
        decided: dict[tuple[str, str], bool] = {}
        moved = 0
        last: tuple[str, frozenset[str]] = ("", frozenset())  # the dev asked about, and the files changed on it
        while True:
            parent = self._dev()
            try:
                tree, changes = self._derive_checked(patch, parent, excluded)
            except checks.Refused:
                # Once landed, a file the change adds is already there and one it deletes is gone, so it no longer
                # applies: look for its own commit first (nearly every self-fix adds a changelog.d file).
                landed = None if excluded else self._landed_before(parent)
                if landed:
                    return landed
                raise
            last = self._left_out_exactly(parent, changes, excluded, last)
            if not changes:
                if excluded:
                    return Outcome("declined", "you left out every file in this change")
                landed = self._landed_before(parent)
                if landed:
                    return landed
                raise checks.Refused(f"the change is already on {self.branch}")
            refusal, already = checks.running_copy_refusal(self.repo, parent, tree, changes)
            if refusal:
                raise checks.Refused(refusal)

            left_out = False
            for status_code, path in changes:
                diff = checks.file_diff(self.repo, parent, tree, path)
                danger = catalogue.danger_class(path, added_diff=diff, enforcement_paths=enforced)
                if not danger:
                    continue
                key = (path, checks.blob(self.repo, tree, path))
                if key not in decided:
                    before = checks.text_at(self.repo, parent, path) or None
                    after = "" if status_code == "D" else checks.text_at(self.repo, tree, path)
                    details = {"category": danger, "path": path, "diffstat": catalogue.diffstat(before, after)}
                    decided[key] = self._ask("promote_dangerous", details, key[1] or tree, parent, danger, diff)
                if not decided[key]:
                    excluded.append(path)
                    left_out = True
            if left_out:
                continue

            files = [path for _, path in changes]
            # Every file with its size, as many as the card holds, never a name cut: "Apply 1 change: x.py" hid a
            # 102-line deletion, and a 200-character cap hid two of six files without saying so (2026-10-08).
            shown = catalogue.name_files(
                self._listed(parent, tree, changes), catalogue.KINDS["promote_batch"].cap("files")
            )
            whole = checks.card_diff(self.repo, parent, tree)
            if not self._ask("promote_batch", {"count": len(files), "files": shown}, tree, parent, None, whole):
                return Outcome("declined", "you declined the change", files=files)
            # Again, right after your answer: the prompt has no timeout, and work can appear in the running copy
            # while it is up. Nothing has landed yet, and the server hands the change in again once the work is in.
            refusal, already = checks.running_copy_refusal(self.repo, parent, tree, changes)
            if self._dev() != parent:
                # dev moved while the card was up. A commit made in the running copy is no one's uncommitted work,
                # though its files differ from the old dev: ask again about the new tree, as land() would.
                moved = self._moved(moved)
                continue
            if refusal:
                raise checks.Refused(refusal)
            commit = checks.make_commit(self.repo, tree, parent, *self._message(files))
            try:
                note = checks.land(self.repo, self.branch, commit, parent, changes, already)
            except checks.Moved:
                moved = self._moved(moved)
                continue
            return Outcome("landed", note or f"on {self.branch} and in the running copy", commit, files)

    def _moved(self, moved: int) -> int:
        """One more approval that dev moved under: the new tree is asked about, up to max_rounds times."""
        moved += 1
        if moved >= self.max_rounds:
            raise checks.Refused(f"{self.branch} kept moving; asked {moved} times and landed nothing")
        return moved

    def _left_out_exactly(
        self, parent: str, changes: list[tuple[str, str]], excluded: list[str], last: tuple[str, frozenset[str]]
    ) -> tuple[str, frozenset[str]]:
        """Leaving files out left out exactly those files, or the change is refused: git once kept a cancelled file
        named with "[" and dropped another it matched, and asked nothing more, forever."""
        paths = frozenset(path for _, path in changes)
        kept = sorted(paths.intersection(excluded))
        if kept:
            raise checks.Refused(f"git did not leave out {', '.join(kept[:6])} as you asked; nothing landed")
        if last[0] == parent and paths != last[1].difference(excluded):
            raise checks.Refused("leaving out the files you cancelled changed which other files this change has")
        return parent, paths

    def _dev(self) -> str:
        return checks.run_git(self.repo, "rev-parse", "--verify", f"refs/heads/{self.branch}").stdout.strip()

    def _derive_checked(self, patch: bytes, on: str, excluded: list[str]) -> tuple[str, list[tuple[str, str]]]:
        """The tree *on* becomes with *patch*, and every refusal of that tree, before anything is asked."""
        try:
            tree = checks.derive_tree(self.repo, on, patch, excluded)
        except checks.Refused as exc:
            raise self._no_longer_applies(exc, on, patch, excluded) from None
        changes = checks.tree_changes(self.repo, on, tree)
        if changes:
            for refusal_of in (
                lambda: checks.tree_safety_refusal(self.repo, on, tree, self.repo),
                lambda: checks.integrity_refusal(self.repo, on, tree),
                lambda: checks.compile_refusal(self.repo, tree, changes),
                lambda: checks.import_break_refusal(self.repo, on, tree, changes),
            ):
                refusal = refusal_of()
                if refusal:
                    raise checks.Refused(refusal)
        return tree, changes

    def _listed(self, on: str, tree: str, changes: list[tuple[str, str]]) -> list[list[object]]:
        """Each changed file as a card names it: [path, A|M|D, added, deleted], None for a binary file's counts."""
        sizes = checks.numstat(self.repo, on, tree)
        listed: list[list[object]] = []
        for status, path in changes:
            size = sizes.get(path, "binary")
            added, deleted = (None, None) if size == "binary" else (int(n[1:]) for n in size.split())
            listed.append([path, status[0], added, deleted])
        return listed

    def _landed_before(self, tip: str) -> Outcome | None:
        """This hand-in's change landed and its verdict was never written: the promoter stopped in between.

        ``dev`` itself is the record: the newest commit carrying exactly this hand-in's ``Thomas-Submission-Id`` and
        ``Thomas-Committed-By: self-change-promoter`` (a later commit that only names it, by hand or by
        ``cherry-pick -x``, is passed over). No verdict may exist yet, and the running copy must hold what ``dev``
        holds -- else the verdict says what is missing, and nothing more is done."""
        sid = self._meta.get("id", "")
        if not sid or (self.cage_root / "outbox" / f"{sid}.verdict.json").exists():
            return None
        found = checks.run_git(self.repo, "log", "--format=%H", f"--grep=^Thomas-Submission-Id: {sid}$", tip)
        if found.returncode:
            return None
        keys = "%(trailers:key=Thomas-Submission-Id,valueonly)%x00%(trailers:key=Thomas-Committed-By,valueonly)"
        for commit in found.stdout.split():  # newest first, past any later commit that only names this hand-in
            said = checks.run_git(self.repo, "show", "-s", f"--format={keys}", commit).stdout.split("\0")
            if [value.strip() for value in said] == [sid, "self-change-promoter"]:
                break
        else:
            return None
        changes = checks.tree_changes(self.repo, f"{commit}^", commit)
        files = [path for _, path in changes]
        have = checks.already_in_running_copy(self.repo, f"{commit}^", tip, changes)
        if set(files) <= have:
            return Outcome("landed", "landed before the promoter stopped; its verdict is written now", commit, files)
        missing = ", ".join(path for path in files if path not in have)
        return Outcome(
            "error",
            f"{self.branch} holds this change as {commit[:12]}, but the running copy does not have all of it "
            f"({missing}); nothing more was done",
            commit,
            files,
        )

    def _no_longer_applies(
        self, refused: checks.Refused, parent: str, patch: bytes, excluded: list[str]
    ) -> checks.Refused:
        """The refusal for a change dev moved on under, naming every file that stops it (capped, never mid-word)."""
        if not str(refused).startswith(_NO_LONGER_APPLIES):
            return refused
        found = _conflicting_files(self.repo, parent, patch, excluded)
        if not found:
            return refused
        self._conflicts[:] = found[:_MAX_CONFLICTS]  # in place: a shared card's member holds this same list
        more = f", and {len(found) - _MAX_CONFLICTS} more" if len(found) > _MAX_CONFLICTS else ""
        return checks.Refused(
            f"{_NO_LONGER_APPLIES}{self.branch}: {len(found)} file(s) will not apply: {', '.join(self._conflicts)}{more}"
        )

    def _ask(
        self, kind: str, details: dict[str, object], digest: str, parent: str, danger: str | None, excerpt: str = ""
    ) -> bool:
        # The writer audit alone can take two minutes: cards re-pinned or changed since the pass began hold it too.
        why = self._hold_reason()
        if why:
            raise Held(why)
        catalogue = trusted_card.load_catalogue()
        title, body = catalogue.render(kind, details)
        nonce = f"{self._meta.get('id', '')}:{parent[:12]}"
        code = catalogue.pairing_code(kind, details, digest, nonce)
        card = trusted_card.TrustedCard(
            kind=kind,
            details={k: str(v) for k, v in details.items()},
            content_hash=digest,
            nonce=nonce,
            code=code,
            title=title,
            body=body,
            danger=danger,
        )
        action, reason = card.dialog()
        # Windows shows at most DIALOG_LIMIT characters of the message and drops the rest without a word, the pairing
        # code last: a card that would not fit, its retry line included, is never shown.
        size = len(action) + 2 + len(catalogue.RETRY_NOTE) + 2 + len(reason)
        if size > catalogue.DIALOG_LIMIT:
            raise ValueError(f"this card would not fit the Windows prompt ({size} characters), so it is not shown")
        # The diff goes to the chat card only: the Windows prompt stays the
        # catalogue's own short wording.
        record = {"kind": kind, "title": title, "body": body, "pairing_code": code, "state": "asking"}
        record["excerpt"] = _clip(excerpt)
        self._still_in_inbox()  # never ask about a hand-in taken aside to be checked
        self._cards.append(record)
        self._write("pending", {"round": parent, "cards": self._cards})

        # Only completed prompt calls count; a failed sign-in may never have appeared.
        def observed(start: float, end: float) -> None:
            self._write("pending", {"round": parent, "cards": self._cards, "card_prompt": {"start": start, "end": end}})

        answer = self._sign_in(action, reason, catalogue.RETRY_NOTE, observed=observed)
        self._still_in_inbox()  # taken aside while its card was up: an approval lands nothing
        record["state"] = {"approved": "approved", "cancelled": "declined", "failed": "held"}[answer]
        self._write("pending", {"round": parent, "cards": self._cards})
        if answer == "failed":
            raise Held(_NOT_ACCEPTED)
        return answer == "approved"

    def _sign_in(
        self,
        action: str,
        reason: str,
        retry_note: str,
        still: Callable[[], None] | None = None,
        observed: Callable[[float, float], None] | None = None,
    ) -> str:
        """Your answer to one card: approved or cancelled. A sign-in Windows did not accept, or a prompt that did not
        show, shows the same card again with *retry_note* above its pairing code, while the hand-in is still in the
        inbox (*still* raises Withdrawn when not; a shared card checks every change on it); after _TRIES of them in a
        row it is "failed", and every hand-in waits _QUIET_S before it is asked again."""
        sid = self._meta.get("id") or self._sub_dir.name
        for attempt in range(_TRIES):
            if attempt:
                (still or self._still_in_inbox)()  # taken aside to be checked meanwhile: never shown again
            said = reason if attempt == 0 else f"{retry_note}\n\n{reason}"
            try:
                started = time.time()
                answer = _answer(self.ask(action, said))
            except _PROMPT_FAULTS:  # a prompt that broke is never your answer
                log.error("%s: the sign-in prompt failed", sid, exc_info=True)
                answer = "failed"
            if answer != "failed":
                if observed is not None:
                    observed(self._turn_started(started), time.time())
                return answer
            # "failed" is also a prompt that never showed (thomas/tools/windows_auth.sign_in_answer says which).
            log.warning("%s: the sign-in did not go through (%d of %d)", sid, attempt + 1, _TRIES)
        self._quiet_until = self.clock() + _QUIET_S
        return "failed"

    def _turn_started(self, called: float) -> float:
        """When the prompt just answered got its turn. The card loop and the window's loop share one asker
        (scripts/cage/window_loop.py, OnePrompt), so a card can wait behind a window card; that wait is not this card's
        prompt. *called* (just before the asker was called) when the asker keeps no such time."""
        turn = getattr(self.ask, "turn_started", None)
        began = turn() if callable(turn) else None
        usable = isinstance(began, (int, float)) and not isinstance(began, bool)
        return float(began) if usable and began >= called else called

    def _message(
        self, files: list[str], place: dict[str, object] | None = None, window: dict[str, object] | None = None
    ) -> tuple[str, list[tuple[str, str]]]:
        from scripts.crew.brief import commit_integrity

        summary = (self._meta.get("summary") or "").strip().splitlines()
        body = f"self-fix: {summary[0][:120]}" if summary else f"self-fix: {', '.join(files[:3])}"
        try:
            commit_integrity.validate_caller_message(body)
        except commit_integrity.CommitIntegrityError:
            body = f"self-fix: {', '.join(files[:3])}"
        if window:  # Part 4: it had no card of its own, and its message never says it had one
            body += (
                f"\n\nMade in green (execution {self._meta.get('execution_id', '?')}), re-derived by the"
                f" self-change promoter without running any of it, passed by the checker and a second look,"
                f" and landed inside the window you opened at the Windows sign-in at"
                f" {window.get('opened_at')} (window {window.get('window_id')}, pairing code"
                f" {window.get('pairing_code')}), with no card of its own."
            )
            return body, self._trailers("owner-window/windows-sign-in")
        # Only the cards you approved: a shared card you cancelled stays first in the record (2026-10-09 review).
        approved = sum(1 for card in self._cards if card.get("state") == "approved")
        body += (
            f"\n\nMade in green (execution {self._meta.get('execution_id', '?')}), re-derived by the"
            f" self-change promoter without running any of it, and approved by you at the Windows"
            f" sign-in on {approved} card(s)"
        )
        if place:  # a shared card: still one commit per change, each with its own Thomas-Submission-Id below
            body += (
                f", one of them a single card for {place.get('of')} changes (pairing code"
                f" {place.get('pairing_code')}) on which this was number {place.get('position')}"
            )
        body += "."
        return body, self._trailers("owner-approved/windows-sign-in")

    def _trailers(self, gated: str) -> list[tuple[str, str]]:
        """The reserved trailers of every promoter commit; _landed_before finds a landing by the middle two."""
        return [
            ("Thomas-Submitted-By", "thomas"),
            ("Thomas-Committed-By", "self-change-promoter"),
            ("Thomas-Submission-Id", self._meta.get("id", "")),
            ("Thomas-Gated", gated),
        ]

    # -- records ----------------------------------------------------------- #
    def _write(self, kind: str, payload: dict[str, object]) -> None:
        sid = self._meta.get("id") or "unknown"
        outbox = self.cage_root / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        record = {"id": sid, "chat": self._meta.get("chat", ""), "execution_id": self._meta.get("execution_id", "")}
        record.update(payload)
        if kind == "pending":
            previous = outbox / f"{sid}.pending.json"
            try:
                saved = json.loads(previous.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
            prompts = saved.get("card_prompts", []) if isinstance(saved, dict) else []
            prompts = prompts if isinstance(prompts, list) else []
            prompt = record.pop("card_prompt", None)
            if isinstance(prompt, dict):
                prompts = [*prompts, prompt]
            if prompts:
                record["card_prompts"] = prompts
        tmp = outbox / f".{sid}.{kind}.tmp"
        tmp.write_bytes(json.dumps(record, indent=2).encode("utf-8"))
        os.replace(tmp, outbox / f"{sid}.{kind}.json")

    def _finish(self, sub_dir: Path, outcome: Outcome) -> None:
        self._meta.setdefault("id", sub_dir.name)
        verdict = {"submission_id": sub_dir.name, **asdict(outcome), "ts": time.time()}
        try:
            path = self.cage_root / "outbox" / f"{sub_dir.name}.pending.json"
            pending = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pending = {}
        if isinstance(pending, dict) and isinstance(pending.get("card_prompts"), list):
            verdict["card_prompts"] = pending["card_prompts"]
        self._write("verdict", verdict)
        log.info("%s: %s %s", sub_dir.name, outcome.status, outcome.detail)
        processed = self.cage_root / "processed" / sub_dir.name
        if processed.exists():
            shutil.rmtree(processed, ignore_errors=True)
        processed.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(sub_dir), str(processed))
        except OSError:
            log.warning("could not move %s out of the inbox", sub_dir.name, exc_info=True)
