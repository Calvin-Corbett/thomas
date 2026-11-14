"""Undo one landed change: the checker passes the undo first, then you approve it on its own card (spec 8.5, 8.6).

The undo is the reverse of the landed commit, derived on today's dev the way every hand-in is (never run, every
refusal a card landing has), then checked by the checker against today's dev with the tests of the undone files and of
every later change that touched them. Only an undo that applies and passes is asked about: ``undo_change`` when you
asked for it, ``revert_change`` when the check after a landing found the landing broke something. Nothing
lands until you approve; Cancel undoes nothing. An undo that does not apply, or fails, is stopped with the later
changes that depend on it named, and you choose what to undo next (newest first). A forward commit, never a rewind:
dev's history keeps both.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from scripts.cage import checker_completion as cc
from scripts.cage import checker_jobs as cj
from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp
from scripts.cage.window_cards import ask_card
from scripts.cage.window_record import Record

from thomas.tools import trusted_card

log = logging.getLogger("thomas.self_change_promoter")
KINDS = ("undo_change", "revert_change")
MAX_ROUNDS = 3
RETRY_S = 600.0
Ask = Callable[[sp.Promoter, str, dict[str, object], str, str], tuple[str, str]]


@dataclass
class Undo:
    sid: str
    commit: str  # the landing it undoes
    kind: str
    failed: tuple[str, ...] = ()
    batch: tuple[str, ...] = ()
    parent: str = ""  # the dev the undo was derived and checked on
    tree: str = ""
    changes: list[tuple[str, str]] = field(default_factory=list)
    job: cj.Job | None = None
    check: cj.Result | None = None
    rounds: int = 0
    retry_at: float = 0.0


def find_landing(repo: Path, branch: str, sid: str) -> str:
    """The promoter's own commit that landed *sid* on *branch* (exactly its two trailers), or ""."""
    found = checks.run_git(repo, "log", f"refs/heads/{branch}", "--format=%H", f"--grep=^Thomas-Submission-Id: {sid}$")
    keys = "%(trailers:key=Thomas-Submission-Id,valueonly)%x00%(trailers:key=Thomas-Committed-By,valueonly)"
    for commit in found.stdout.split():
        said = checks.run_git(repo, "show", "-s", f"--format={keys}", commit).stdout.split("\0")
        if [value.strip() for value in said] == [sid, "self-change-promoter"]:
            return commit
    return ""


def later_changes(repo: Path, branch: str, commit: str, files: Iterable[str]) -> list[str]:
    """Every later commit on *branch* that touched *files*, newest first, as "<subject> (<short id>)"."""
    paths = list(files)
    if not paths:
        return []
    listed = checks.run_git_paths(repo, "log", "--format=%h %s", f"{commit}..refs/heads/{branch}", paths=paths)
    rows = [line.split(" ", 1) + [""] for line in listed.stdout.splitlines() if line.strip()]
    return [f"{row[1][:80]} ({row[0]})" for row in rows]


def reverse_patch(repo: Path, commit: str) -> bytes:
    """The landed commit's diff, backwards, as the bytes git would apply."""
    done = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "diff", "--binary", "--full-index", "--no-renames", commit, f"{commit}^"],
        cwd=str(repo),
        capture_output=True,
        check=False,
        creationflags=checks.NO_WINDOW,
    )
    if done.returncode:
        raise checks.Refused(
            f"the landed change could not be read back: {done.stderr.decode('utf-8', 'replace')[:200]}"
        )
    return done.stdout


class Undoer:
    """One undo at a time, moved on by the window's loop on every pass."""

    def __init__(
        self,
        p: sp.Promoter,
        *,
        link: object,
        record: Record,
        ask: Ask = ask_card,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.p, self.link, self.record, self.ask, self.clock = p, link, record, ask, clock
        self.current: Undo | None = None
        self.said = ""

    def start(
        self, sid: str, *, kind: str = "undo_change", failed: Iterable[str] = (), batch: Iterable[str] = ()
    ) -> str:
        """Begin undoing *sid*: "" when begun, else why not."""
        if kind not in KINDS:
            return f"no undo card {kind!r}"
        if self.current is not None:
            return f"the undo of {self.current.sid} is still under way"
        commit = find_landing(self.p.repo, self.p.branch, sid)
        if not commit:
            return f"{self.p.branch} holds no change the promoter landed as {sid}"
        self.current = Undo(sid, commit, kind, tuple(failed), tuple(batch))
        self.said = f"undoing {sid}: started"
        return ""

    def step(self) -> str:
        """Move the undo on by one step and say where it is ("" when there is none)."""
        undo = self.current
        if undo is None:
            return ""
        try:
            self.said = self._step(undo)
        except (checks.Refused, checks.Moved, OSError, ValueError) as exc:
            self.said = self._stop(undo, f"the undo stopped: {exc}")
        return self.said

    def _step(self, undo: Undo) -> str:
        p, dev = self.p, self.p._dev()
        if undo.parent != dev:
            if self.clock() < undo.retry_at:
                return f"undoing {undo.sid}: the checker could not check the undo; tried again soon"
            return self._prepare(undo, dev)
        if undo.check is None:
            undo.check = self.link.result(undo.job)
            if undo.check is None:
                return f"undoing {undo.sid}: the checker is checking the undo"
        if undo.check.verdict == cj.FAILED:
            later = later_changes(p.repo, p.branch, undo.commit, [path for _, path in undo.changes])
            return self._stop(undo, f"the undo fails the checker ({undo.check.why}); later changes to its files: "
                                    f"{', '.join(later) or 'none'}")  # fmt: skip
        if undo.check.verdict != cj.PASSED:
            self.link.forget(undo.job)
            undo.parent, undo.job, undo.check, undo.retry_at = "", None, None, self.clock() + RETRY_S
            return f"undoing {undo.sid}: the checker could not check the undo; tried again in 10 minutes"
        return self._ask_and_land(undo, dev)

    def _prepare(self, undo: Undo, dev: str) -> str:
        p = self.p
        undo.rounds += 1
        if undo.rounds > MAX_ROUNDS:
            return self._stop(undo, f"{p.branch} kept moving; the undo was checked {MAX_ROUNDS} times and asked none")
        p._sub_dir, p._meta, p._cards, p._conflicts = Path(f"undo-{undo.sid}"), {"id": f"undo-{undo.sid}"}, [], []
        try:
            tree, changes = p._derive_checked(reverse_patch(p.repo, undo.commit), dev, [])
        except checks.Refused as exc:
            later = later_changes(p.repo, p.branch, undo.commit, self._files(undo.commit))
            return self._stop(undo, f"the undo does not apply to today's {p.branch} ({exc}); later changes to its "
                                    f"files, newest first: {', '.join(later) or 'none'}")  # fmt: skip
        if not changes:
            return self._stop(undo, f"{p.branch} no longer holds this change")
        if undo.job is not None:
            self.link.forget(undo.job)
        later_files = {path for line in self._later_commits(undo.commit) for path in self._files(line)}
        changed = sorted({path for status, path in changes if status != "D"} | later_files)
        commit = checks.make_commit(p.repo, tree, dev, f"undo check of {undo.sid}", [])
        undo.parent, undo.tree, undo.changes, undo.check = dev, tree, changes, None
        undo.job = self.link.post(cj.CHECK, base=dev, commit=commit, tree=tree, changed=changed)
        return f"undoing {undo.sid}: the checker is checking the undo"

    def _ask_and_land(self, undo: Undo, dev: str) -> str:
        p = self.p
        catalogue = trusted_card.load_catalogue()
        enforced = sp._enforced(catalogue, p.repo)
        for _status, path in undo.changes:  # an undo never stands in for a protected change's own card (review D7)
            added = checks.file_diff(p.repo, dev, undo.tree, path)
            danger = catalogue.danger_class(path, added_diff=added, enforcement_paths=enforced)
            if danger:
                return self._stop(undo, f"{path} touches {danger}; use its own protected-change card, not an undo card")
        if undo.kind == "undo_change":
            listed = p._listed(dev, undo.tree, undo.changes)
            details: dict[str, object] = {
                "sid": undo.sid,
                "files": catalogue.name_files(listed, catalogue.KINDS["undo_change"].cap("files")),
            }
        else:
            details = {"sid": undo.sid, "failed": ", ".join(undo.failed) or "a test", "batch": ", ".join(undo.batch)}
        answer, code = self.ask(p, undo.kind, details, undo.tree, f"undo-{undo.sid}:{dev[:12]}")
        if answer == "failed":
            return f"undoing {undo.sid}: the sign-in did not go through; asked again shortly"
        if answer != "approved":
            return self._stop(undo, "you cancelled the undo; nothing changed")
        writers = p.audit(p.repo)  # the writer audit every landing runs, the card path's and the lane's (review D7)
        refusal, already = checks.running_copy_refusal(p.repo, dev, undo.tree, undo.changes)
        if p._dev() != dev:
            undo.parent = ""
            return f"undoing {undo.sid}: {p.branch} moved while the card was up; the undo is checked again"
        if writers:
            return self._stop(undo, "unexpected writers on Thomas's code: " + ", ".join(writers))
        if refusal:
            return self._stop(undo, refusal)
        undo.check = cc.unchanged(undo.job, undo.check, self.link.result, clock=self.clock)  # read again (review B2)
        if undo.check.verdict != cj.PASSED:
            self.link.forget(undo.job)
            undo.parent, undo.job, undo.check, undo.retry_at = "", None, None, self.clock() + RETRY_S
            return f"undoing {undo.sid}: the checker's answer changed while the card was up; tried again in 10 minutes"
        body = (
            f"undo: {undo.sid} ({undo.commit[:12]})\n\nUndoes {undo.commit}, approved by you at the Windows sign-in on "
            f"the {undo.kind} card (pairing code {code}), after the checker passed the undo on {dev[:12]}."
        )
        trailers = [
            ("Thomas-Submitted-By", "window-control"),
            ("Thomas-Committed-By", "self-change-promoter"),
            ("Thomas-Submission-Id", f"undo-{undo.sid}"),
            ("Thomas-Gated", "owner-approved/windows-sign-in"),
        ]
        commit = checks.make_commit(p.repo, undo.tree, dev, body, trailers)
        checks.land(p.repo, p.branch, commit, dev, undo.changes, already)
        self.link.forget(undo.job)
        self._quietly("undo_landed", sid=undo.sid, commit=commit, undoes=undo.commit, card=undo.kind, code=code)
        self.current = None
        return f"undone: {undo.sid} ({commit[:12]})"

    def _stop(self, undo: Undo, why: str) -> str:
        if undo.job is not None:
            self.link.forget(undo.job)
        self.current = None
        return f"undoing {undo.sid} stopped: {why}"

    def _files(self, commit: str) -> list[str]:
        shown = checks.run_git(self.p.repo, "diff-tree", "--no-commit-id", "-r", "--name-only", "--no-renames", commit)
        return [line for line in shown.stdout.splitlines() if line]

    def _later_commits(self, commit: str) -> list[str]:
        files = self._files(commit)
        if not files:
            return []
        listed = checks.run_git_paths(
            self.p.repo, "log", "--format=%H", f"{commit}..refs/heads/{self.p.branch}", paths=files
        )
        return listed.stdout.split()

    def _quietly(self, name: str, **fields: object) -> None:
        try:
            self.record.event(name, **fields)
        except OSError:  # the record is never authority; the undo is on dev, with its own trailers
            log.warning("the window's record could not take %s for %s", name, fields.get("sid"), exc_info=True)


__all__ = ["KINDS", "Undo", "Undoer", "find_landing", "later_changes", "reverse_patch"]
