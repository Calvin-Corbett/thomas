"""The checker's answer and the second look's verdict for one hand-in the window may land (spec 8.2, conditions 1-3).

For the change as derived now (its base, tree and change digest, in a ``Prep``), the checker is asked once, with a
commit of exactly that tree on that base, and the second look once, on a thread of its own so a long read never holds
the window's loop. A failed check or a NOT SAFE second look is a refusal with the findings; anything that could not run
is tried again after ten minutes; only PASSED and SAFE together let the lane land it. A second look's verdict counts
only for the change digest it read: one of an older derivation, still running or finished, is never read for the new
one (2026-10-14 review: a look of C1 once landed C2).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from scripts.cage import checker_completion as cc
from scripts.cage import checker_jobs as cj
from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp
from scripts.cage import window_review as wrev

RETRY_S = 600.0
_NO_BLOB = "0" * 40


def change_digest(repo: Path, parent: str, tree: str, changes: list[tuple[str, str]]) -> str:
    """sha256 of every changed path's status, mode and blob in *tree*, in path order: what a second look's verdict is
    bound to. Base-independent: the same change derived on another dev gives the same digest unless what it lands
    differs."""
    lines: list[str] = []
    for status, path in sorted(changes, key=lambda change: change[1]):
        listed = checks.run_git(repo, "ls-tree", tree, "--", path).stdout.strip()
        meta = listed.split("\t", 1)[0].split() if listed else []
        mode, blob = (meta[0], meta[2]) if len(meta) == 3 else ("000000", _NO_BLOB)
        lines.append(f"{status}\0{path}\0{mode}\0{blob}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


@dataclass
class Prep:
    """What the lane knows of one hand-in, from the bytes it read; dropped when those bytes change."""

    sid: str
    patch_sha: str
    parent: str = ""
    tree: str = ""
    changes: list[tuple[str, str]] = field(default_factory=list)
    change: str = ""
    job: cj.Job | None = None
    check: cj.Result | None = None
    review: wrev.Review | None = None
    reviewing: Future[wrev.Review] | None = None
    retry_at: float = 0.0
    retry_why: str = ""
    wait: str = ""


class Evidence:
    def __init__(self, *, link: object, reviewer: object, clock: Callable[[], float] = time.time) -> None:
        self.link = link  # scripts/cage/window_checker.CheckerLink, or a test's stand-in
        self.reviewer = reviewer  # scripts/cage/window_review.Reviewer, or a test's stand-in
        self.clock = clock
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="window-second-look")

    def gather(self, p: sp.Promoter, prep: Prep) -> bool | sp.Outcome:
        """True when the checker PASSED this exact change on this dev and the second look found it SAFE; a refused
        outcome when either found a problem; False while either is running or will be tried again."""
        now = self.clock()
        if prep.job is None and now >= prep.retry_at:
            commit = checks.make_commit(p.repo, prep.tree, prep.parent, f"window check of {prep.sid}", [])
            changed = [path for status, path in prep.changes if status != "D"]
            prep.job = self.link.post(cj.CHECK, base=prep.parent, commit=commit, tree=prep.tree, changed=changed)
        if prep.review is None and prep.reviewing is None and prep.job is not None and now >= prep.retry_at:
            diff = checks.card_diff(p.repo, prep.parent, prep.tree)
            prep.reviewing = self._pool.submit(
                self.reviewer.review,
                change=prep.change,
                commit=prep.job.commit,
                summary=p._meta.get("summary", ""),
                diff=diff,
            )
        if prep.reviewing is not None and prep.reviewing.done():
            prep.review, prep.reviewing = prep.reviewing.result(), None
        if prep.review is not None and prep.review.change != prep.change:  # never another change's (review, WS-R1)
            prep.review = wrev.Review(prep.change, wrev.UNAVAILABLE, why="it read another change than this one")
        self.refresh(prep)
        if prep.review is not None and prep.review.verdict == wrev.NOT_SAFE:
            found = "\n".join(f"- {item}" for item in prep.review.findings)
            return sp.Outcome(
                "refused", f"A second look read the change in a fresh copy before a window landed it:\n{found}"
            )
        if prep.check is not None and prep.check.verdict == cj.FAILED:
            failed = "\n".join(f"- {test}" for test in prep.check.findings[:40])
            return sp.Outcome(
                "refused", f"The checker ran the tests that cover this change: {prep.check.why}\n{failed}"
            )
        waits: list[str] = []
        if prep.review is not None and prep.review.verdict == wrev.UNAVAILABLE:
            waits.append(f"the second look gave no verdict ({prep.review.why})")
            prep.review, prep.retry_at = None, now + RETRY_S
        if prep.check is not None and prep.check.verdict == cj.UNAVAILABLE:
            waits.append(f"the checker could not check it ({prep.check.why})")
            self.forget(prep)
            prep.retry_at = now + RETRY_S
        if waits:
            prep.retry_why = "; ".join(waits)
        if prep.check is None or prep.review is None:
            if now < prep.retry_at:
                prep.wait = f"{prep.retry_why}; tried again in {max(1, int((prep.retry_at - now) // 60))} minute(s)"
            else:
                prep.wait = "the checker and the second look are reading it"
            return False
        return prep.check.verdict == cj.PASSED and prep.review.safe

    def refresh(self, prep: Prep) -> bool:
        """Read the checker's answer, and read an accepted one again: a changed or vanished answer is UNAVAILABLE,
        never a PASSED kept from the first read (review B2). True when it is a PASSED that saw tests (review B3)."""
        if prep.job is not None:
            prep.check = (
                self.link.result(prep.job)
                if prep.check is None
                else cc.unchanged(prep.job, prep.check, self.link.result, clock=self.clock)
            )
        if prep.check is not None and prep.check.verdict == cj.PASSED and not prep.check.seen:  # review B3
            prep.check = replace(prep.check, verdict=cj.UNAVAILABLE, why="it passed with no test run")
        return prep.check is not None and prep.check.verdict == cj.PASSED

    def forget(self, prep: Prep) -> None:
        """The checker's job for *prep* is no longer wanted: dev moved, or the hand-in is done."""
        if prep.job is not None:
            self.link.forget(prep.job)
        prep.job, prep.check = None, None

    def unreview(self, prep: Prep) -> None:
        """What the second look said, or will say, is not for *prep*'s change now. A look already running cannot be
        stopped (its one worker stays busy until it ends); its answer is never read."""
        if prep.reviewing is not None:
            prep.reviewing.cancel()
        prep.review, prep.reviewing = None, None

    def drop(self, prep: Prep) -> None:
        self.forget(prep)
        self.unreview(prep)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


__all__ = ["RETRY_S", "Evidence", "Prep", "change_digest"]
