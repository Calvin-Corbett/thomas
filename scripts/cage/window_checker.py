"""The promoter's side of the checker: post a job, and take only an answer that is for exactly that job.

The jobs folder is yours to write and the checker's to read; the results folder is the checker's to write and yours to
read (scripts/cage/enable_window.ps1 sets both, and gives thomas-agent neither). An answer counts only when it names the
job's id, kind, base, commit and tree (spec 2026-10-12, section 8.2 conditions 1 and 2). An answer that cannot be read,
that is for something else, or that passed with no test seen, is UNAVAILABLE: never a pass.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from scripts.cage import checker_completion as cc
from scripts.cage import checker_jobs as cj

FRESH_S = 90.0  # the checker beats every 10 s; three missed minutes and a half is not there


class CheckerLink:
    def __init__(
        self, root: Path = cj.CHECK_ROOT, *, clock: Callable[[], float] = time.time, fresh_s: float = FRESH_S
    ) -> None:
        self.root = Path(root)
        self.clock = clock
        self.fresh_s = fresh_s

    def answering(self) -> str:
        """Why the checker cannot be relied on now, or "" when it is beating and fenced off the network."""
        state = self.root / cj.STATE
        try:
            beat = float((state / cj.HEARTBEAT).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return "the checker is not running (no heartbeat)"
        if self.clock() - beat > self.fresh_s:
            return f"the checker has not beaten for {int(self.clock() - beat)} s"
        try:
            fence = cj.read_json(state / cj.FENCE)
        except (OSError, ValueError, RecursionError):
            fence = None
        if not isinstance(fence, dict) or fence.get("fenced") is not True:
            return "the checker has not shown that it is fenced off the network"
        return ""

    def post(
        self, kind: str, *, base: str, commit: str, tree: str, changed: Iterable[str], tests: Iterable[str] = ()
    ) -> cj.Job:
        """Write a new job and return it. Its id is new every time, so an old answer can never be taken for it."""
        job = cj.Job(
            secrets.token_hex(12), kind, base, commit, tree, tuple(changed), tuple(tests), posted_at=self.clock()
        )
        cj.Job.parse(job.to_json())  # what the checker will read back, refused here first
        folder = self.root / cj.JOBS
        folder.mkdir(parents=True, exist_ok=True)
        cj.write_json(folder / f"{job.id}.json", job.to_json())
        return job

    def result(self, job: cj.Job) -> cj.Result | None:
        """The checker's completed answer to *job*: None while there is none, or while its completion receipt is not
        yet published (scripts/cage/checker_completion.py; an answer file alone is never taken, review B2);
        UNAVAILABLE when it cannot be read, is for another job, or does not match its receipt."""
        try:
            answer = cc.read(self.root, job)
        except (OSError, ValueError, RecursionError) as exc:
            return self._unavailable(job, f"the checker's answer could not be taken: {exc}")
        if answer is None:
            return None
        if answer.verdict == cj.PASSED and not answer.seen:  # a pass that tested nothing (2026-10-14 review, B3)
            return self._unavailable(job, "the checker passed it with no test run")
        return answer

    def forget(self, job: cj.Job) -> None:
        """Remove *job* once its answer is taken. Answers stay: only the checker can remove them."""
        (self.root / cj.JOBS / f"{job.id}.json").unlink(missing_ok=True)

    def _unavailable(self, job: cj.Job, why: str) -> cj.Result:
        return cj.Result(
            job.id, job.kind, job.base, job.commit, job.tree, cj.UNAVAILABLE, why, finished_at=self.clock()
        )


__all__ = ["FRESH_S", "CheckerLink"]
