"""The check after each landing, kept through a restart or a failed post (2026-10-14 review, D1).

Each AFTER job is recorded when posted (``after_posted``); landings stay blocked until every landing's check is recorded
(``after_check``). On a restart, ``recover`` rebuilds the queue from the record and dev: every landed or recovered-on-dev
commit with no later ``after_check`` is checked again, reusing its posted job when it still matches. From Codex's
lineage (work/part4, 2026-10-15). A failed check queues its revert durably (scripts/cage/window_reverts.py;
review D8).
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.cage import checker_completion as cc
from scripts.cage import checker_jobs as cj
from scripts.cage import self_change_checks as checks
from scripts.cage import window_record as wr
from scripts.cage.window_reverts import Reverts

AFTER_DEADLINE_S = 3600.0


@dataclass
class After:
    job: cj.Job | None
    sid: str
    commit: str
    parent: str
    posted: float
    files: tuple[str, ...] = ()
    window_id: str = ""
    batch: tuple[str, ...] = ()
    durable: bool = True


class AfterChecks:
    def __init__(self, loop: object) -> None:
        self.loop = loop
        self.queue: list[After] = []
        self.reverts = Reverts(loop)

    def _append(self, after: After) -> None:
        loop = self.loop
        if loop.after is None:
            loop.after = after
        elif all(item.commit != after.commit for item in [loop.after, *self.queue]):
            self.queue.append(after)

    def _post(self, after: After) -> None:
        loop = self.loop
        if after.job is None:
            tree = checks.run_git(loop.card.repo, "rev-parse", f"{after.commit}^{{tree}}").stdout.strip()
            after.job = loop.link.post(
                cj.AFTER, base=after.parent, commit=after.commit, tree=tree, changed=list(after.files)
            )
            after.posted = loop.clock()
        if not after.durable:
            loop.record.event(
                "after_posted",
                window_id=after.window_id,
                sid=after.sid,
                commit=after.commit,
                parent=after.parent,
                files=list(after.files),
                batch=list(after.batch),
                job=after.job.to_json(),
            )
            after.durable = True
        last = getattr(loop.lane, "last_landed", None)
        if last is not None and last[1] == after.commit:
            loop.lane.last_landed = None

    def landed(self) -> None:
        loop = self.loop
        sid, commit, parent, files = loop.lane.last_landed
        if sid not in loop.batch:
            loop.batch.append(sid)
        loop.landed_files = sorted({*loop.landed_files, *files})
        window_id = loop.window.opened.window_id if loop.window.opened else ""
        after = After(
            None,
            sid,
            commit,
            parent,
            loop.clock(),
            tuple(loop.landed_files),
            window_id,
            tuple(loop.batch),
            durable=False,
        )
        self._append(after)  # block before either a post or a record write can fail
        self._post(loop.after)

    def check(self) -> None:
        loop, after = self.loop, self.loop.after
        if after is None:
            return
        self._post(after)
        result = loop.link.result(after.job)
        if result is not None:
            result = cc.unchanged(after.job, result, loop.link.result, clock=loop.clock)
        if result is None and loop.clock() - after.posted <= AFTER_DEADLINE_S:
            return
        verdict = result.verdict if result else cj.UNAVAILABLE
        why = result.why if result else "the checker did not answer within an hour"
        findings = list(result.findings[:40]) if result else []
        batch = list(after.batch) or list(loop.batch)
        if verdict == cj.FAILED:
            self.reverts.add(after.sid, after.commit, findings[:5] or [why[:200]], batch)
        # Never clear blocking state until this completion is durable, even for a successful answer.
        loop.record.event(
            "after_check",
            sid=after.sid,
            commit=after.commit,
            verdict=verdict,
            why=why,
            findings=findings,
            check_job=after.job.id,
            window_id=after.window_id,
            batch=batch,
        )
        loop.link.forget(after.job)
        loop.after = self.queue.pop(0) if self.queue else None
        if verdict == cj.PASSED:
            loop._note(f"the check after {after.sid} landed passed")
            return
        loop.window.close(f"the check after {after.sid} landed found: {why}")
        loop._record_ended()
        if verdict == cj.FAILED:
            self.revert()

    def revert(self) -> None:
        self.reverts.step()

    def recover(self) -> None:
        loop = self.loop
        for intent in loop.record.unfinished():
            fields = {key: value for key, value in intent.items() if key not in {"seq", "prev", "hash", "name", "at"}}
            commit = str(fields.get("commit") or "")
            loop.record.event("recovered", **fields, on_dev=wr.landed_on(loop.card.repo, loop.card.branch, commit))
        events = loop.record.events()
        intents = {row.get("commit"): int(row.get("seq", 0)) for row in events if row.get("name") == "landing_intent"}
        landings = [
            row
            for row in events
            if row.get("name") == "landed" or (row.get("name") == "recovered" and row.get("on_dev"))
        ]
        landings.sort(key=lambda row: intents.get(row.get("commit"), int(row.get("seq", 0))))
        unions, batches, seen = {}, {}, set()
        for event in landings:
            commit = str(event.get("commit") or "")
            if commit in seen:
                continue
            seen.add(commit)
            wid, sid = str(event.get("window_id") or ""), str(event.get("sid") or "")
            files = (
                event.get("files")
                or checks.run_git(
                    loop.card.repo, "diff-tree", "--no-commit-id", "-r", "--name-only", commit
                ).stdout.splitlines()
            )
            unions[wid] = sorted({*unions.get(wid, []), *files})
            batches[wid] = [*batches.get(wid, []), sid]
            position = intents.get(commit, int(event.get("seq", 0)))
            later = [row for row in events if row.get("seq", 0) > position]
            if any(row.get("name") == "after_check" and row.get("commit") == commit for row in later):
                continue
            parent = str(
                event.get("parent") or checks.run_git(loop.card.repo, "rev-parse", f"{commit}^").stdout.strip()
            )
            after = After(None, sid, commit, parent, loop.clock(), tuple(unions[wid]), wid, tuple(batches[wid]), False)
            for row in reversed(later):
                if row.get("name") != "after_posted" or row.get("commit") != commit:
                    continue
                try:
                    job = cj.Job.parse(row.get("job"))
                    tree = checks.run_git(loop.card.repo, "rev-parse", f"{commit}^{{tree}}").stdout.strip()
                    matches = (job.kind, job.base, job.commit, job.tree, job.changed) == (
                        cj.AFTER,
                        parent,
                        commit,
                        tree,
                        after.files,
                    )
                    root = getattr(loop.link, "root", None)
                    present = root is None or cj.read_json(root / cj.JOBS / f"{job.id}.json") == job.to_json()
                    result = loop.link.result(job)
                    if matches and (present or (result is not None and result.verdict != cj.UNAVAILABLE)):
                        after.job, after.durable, after.posted = job, True, job.posted_at
                except (OSError, ValueError, RecursionError):
                    pass  # missing or damaged jobs are posted again; no unverified answer is adopted
                break
            self._append(after)
        closed = {row.get("window_id") for row in events if row.get("name") == "window_closed"}
        for opened in events:
            wid = opened.get("window_id")
            if opened.get("name") == "window_opened" and wid not in closed:
                rows = wr.window_summary(loop.card.repo, loop.card.branch, str(wid))
                loop.record.event("window_closed", window_id=wid, reason="the promoter restarted", landed=rows)
                closed.add(wid)
        self.reverts.recover()


__all__ = ["AFTER_DEADLINE_S", "After", "AfterChecks"]
