"""A candidate that needs a model: a Build team repairs it in its own green, then the ratchet proves it again.

The spec's first idea, resuming the session that wrote the candidate, has nothing
to resume: no commit on any ref carries a Build or Thomas-project conversation id
(measured 2026-09-24). A repair is a new Thomas project (``thomas_project``) in
the candidate's green, started with ``hold_settle``: Autopilot's done check ends
the team's work, and the ratchet -- not Autopilot -- proves it and settles it with
its own summary. The goal carries every constraint and every failure so far.

Hours pass in a repair and dev moves about 46 times a day, so work finished on an
old tip is carried to a fresh green at the new tip (``apply_patch``) and proven
there before anything is submitted.

Hours also outlast a restart. A run that ends mid-repair leaves ``repairing`` in
the ledger and the team's work in a kept green; the next run takes it up in that
same green (:meth:`Repairer.resume`), because proving the candidate again would
call ``fresh_green`` on the same execution id and discard it.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.core.kernel import late, seams
from thomas.server import green_checkout, thomas_project, thomas_project_held
from thomas.server.precard import ChangeFailedCheck, ReviewUnavailable
from thomas.server.ratchet.attempt import (
    HELD,
    Attempt,
    Context,
    DevMoved,
    discard,
    execution_id,
    fresh_green,
    prove_green,
    restore_left_out,
    settle_attempt,
)
from thomas.server.ratchet.candidates import Candidate
from thomas.server.ratchet.proof import Verdict
from thomas.server.ratchet.screen import screen

REPAIR_TIMEOUT_S = 8 * 3600.0
REPAIR_POLL_S = 30.0
CARRY_LIMIT = 2


def repair_settings() -> dict[str, Any]:
    """Autopilot, your saved Build team, your file-access level. Without your grant Build runs a lower level,
    which the ratchet records; the ratchet's own proof decides either way."""
    return late.call(
        seams.BUILD_SETTINGS, autonomy_level=5, file_access=None, model_id=None, reasoning_effort=None, guardrails=None
    )


@dataclass
class RepairHooks:
    start: Callable[..., Awaitable[dict[str, Any]]] = thomas_project.start_thomas_project
    phase: Callable[[Path, Path, str], tuple[str, str]] = thomas_project.project_phase
    outcome: Callable[[Path, Path, str], dict[str, Any] | None] = thomas_project_held.held_outcome
    settle_held: Callable[..., Path | None] = thomas_project.settle_if_finished
    retire: Callable[[Path, Path, str], None] = thomas_project_held.retire_held
    record_retirement: Callable[..., None] = thomas_project_held.record_retirement
    stop: Callable[[Path, str], None] = thomas_project.request_stop
    catalog_root: Callable[[], Path] = thomas_project_held.project_catalog_root
    settings: Callable[[], dict[str, Any]] = repair_settings
    timeout_s: float = REPAIR_TIMEOUT_S
    poll_s: float = REPAIR_POLL_S


def repair_goal(att: Attempt, verdict: Verdict | None) -> str:
    cand, found = att.candidate, att.screen
    lines = [
        f"Land {cand.ref} ({cand.sha[:12]}) onto dev ({att.dev_sha[:12]}).",
        "",
        "This copy already has the candidate merged into dev without a commit. Keep both sides' intent: what the "
        "candidate was for, and everything dev has done since. Finish when the merge is whole and its tests pass; "
        "the ratchet proves it again before anything lands.",
    ]
    if found.conflicts:
        lines += ["", "Files in conflict:", *(f"- {c.path}: {c.advice}" for c in found.conflicts)]
    if found.resurrected:
        lines += ["", "Files dev deleted that this merge brings back; keep them deleted:"]
        lines += [f"- {p}" for p in found.resurrected]
    if found.duplicate_tests:
        lines += ["", "Tests the candidate adds that dev already has; do not add them twice:"]
        lines += [f"- {t}" for t in found.duplicate_tests[:40]]
    if found.flags:
        lines += ["", "Lines that must not land:", *(f"- {f}" for f in found.flags)]
    if verdict is not None and (verdict.new_failures or verdict.missing):
        lines += ["", f"The proof with the candidate: {verdict.reason}"]
        lines += [f"- {n}" for n in (*verdict.new_failures, *verdict.missing)[:20]]
    if verdict is not None and verdict.flaky:
        lines += [
            "",
            "These fail beside other tests and pass when run alone: find what one test leaves behind for "
            "another, and fix that, not the assertion:",
        ]
        lines += [f"- {n}" for n in verdict.flaky[:20]]
    lines += ["", "Do not edit plans/thomas/WORKBOARD.md or any task PLAN.md, and do not commit to dev."]
    return "\n".join(lines)


def resumable(ctx: Context, row: Mapping[str, Any]) -> tuple[Attempt, str] | None:
    """The attempt a ``repairing`` ledger line describes, in the green it is still in; None when that green is gone.

    The line keeps what this needs: the candidate's commit and refs, the dev tip the
    team is working on, the green's execution id, the conversation, and the landed
    commit a stacked candidate's own change sits on. The merge itself is measured
    again rather than stored -- it is a read of git, and it is what says which files
    the proof must run.
    """
    execution = str(row.get("execution_id") or "")
    sha, dev_sha = str(row.get("candidate_sha") or ""), str(row.get("dev_sha") or "")
    green = green_checkout.find_green(execution) if execution and sha and dev_sha else None
    if green is None or green.base != dev_sha:
        return None
    refs = tuple(str(ref) for ref in (row.get("refs") or [row.get("candidate_ref") or ""]) if ref)
    cand = Candidate(sha, refs or (f"refs/unknown/{sha[:12]}",), 0, (), 0)
    onto = str(row.get("onto") or "")
    found = screen(ctx.repo, dev_sha, cand, onto=onto)
    return Attempt(cand, dev_sha, found, green, onto=onto, repaired=True), str(row.get("conversation_id") or "")


class Repairer:
    """Starts, watches and lands a repair; ``Context.repairs`` when this server can start Build runs."""

    def __init__(self, app: Any, port: int, hooks: RepairHooks | None = None) -> None:
        self.app, self.port, self.hooks = app, port, hooks or RepairHooks()

    async def repair(self, ctx: Context, att: Attempt, *, verdict: Verdict | None) -> str:
        cand, green, hooks = att.candidate, att.green, self.hooks
        note = functools.partial(ctx.ledger.record, candidate=cand, dev_sha=att.dev_sha)
        green_checkout.mark_kept(green, f"ratchet repair of {cand.sha[:12]}")  # the 24h sweeps leave it alone
        catalog = hooks.catalog_root()
        att.repaired = True
        ratchet = {"sha": cand.sha, "ref": cand.ref, "dev_sha": att.dev_sha}
        meta: dict[str, Any] = {"hold_settle": True, "ratchet": ratchet}
        if ctx.chat:
            meta["chat_session_id"] = ctx.chat
        try:
            started = await hooks.start(
                self.app,
                request=repair_goal(att, verdict),
                settings=hooks.settings(),
                port=self.port,
                green=green,
                meta=meta,
            )
        except thomas_project.ThomasProjectError as exc:
            note(state="reported", reason=f"the repair run could not start: {exc}")
            return "reported"
        cid = str(started.get("conversation_id") or "")
        note(
            state="repairing",
            reason="a Build team is repairing it",
            conversation_id=cid,
            execution_id=green.execution_id,
            onto=att.onto,  # what a resume needs to measure the same merge again
        )
        return await self._watch(ctx, att, catalog, cid)

    async def resume(self, ctx: Context, att: Attempt, cid: str) -> str:
        """Take up a repair a restart left behind, in the green it is still in."""
        green_checkout.mark_kept(att.green, f"ratchet repair of {att.candidate.sha[:12]}")
        ctx.ledger.record(
            candidate=att.candidate,
            dev_sha=att.dev_sha,
            state="repairing",
            reason="a repair cut short by a restart was taken up again",
            conversation_id=cid,
            execution_id=att.green.execution_id,
            onto=att.onto,
        )
        return await self._watch(ctx, att, self.hooks.catalog_root(), cid)

    async def _watch(self, ctx: Context, att: Attempt, catalog: Path, cid: str) -> str:
        """Wait for the team to end, then prove what it made and hand it over, or report why not."""
        hooks = self.hooks
        green = att.green
        phase = await self._wait(ctx, green.work, catalog, cid)
        ended = await asyncio.to_thread(hooks.outcome, green.work, catalog, cid) or {}
        extra = {"conversation_id": cid, "autonomy": ended.get("autonomy_level")}
        if phase == "timeout":
            why = f"the repair did not end within {hooks.timeout_s / 3600:g} hours, so it was stopped"
            return self._report(ctx, att, catalog, cid, att.dev_sha, why, extra)
        if not ended.get("ok"):
            why = f"the repair team did not finish: {ended.get('reason') or phase}"
            return self._report(ctx, att, catalog, cid, att.dev_sha, why, extra)
        return await self._land(ctx, att, catalog, cid, extra)

    async def _wait(self, ctx: Context, root: Path, catalog: Path, cid: str) -> str:
        waited = 0.0
        while waited < self.hooks.timeout_s:
            phase, _why = await asyncio.to_thread(self.hooks.phase, root, catalog, cid)
            if phase in ("ended", "settled"):
                return phase
            await ctx.hooks.sleep(self.hooks.poll_s)
            waited += max(self.hooks.poll_s, 1.0)
        await asyncio.to_thread(self.hooks.stop, root, cid)
        return "timeout"

    async def _land(self, ctx: Context, held: Attempt, catalog: Path, cid: str, extra: dict[str, Any]) -> str:
        """Prove the team's work on dev as it is now -- carried to a fresh green if dev moved -- and hand it over."""
        for _round in range(CARRY_LIMIT + 1):
            att: Attempt | None = held
            try:
                tip = await asyncio.to_thread(ctx.repo.sha, "refs/heads/dev")
                if tip != held.dev_sha:
                    att = await self._carry(ctx, held, tip)
                    if att is None:
                        why = "the repair no longer applies to dev as it is now"
                        return self._report(ctx, held, catalog, cid, tip, why, extra)
                verdict = await prove_green(ctx, att)
                if not verdict.ok:
                    why = f"after the repair: {verdict.reason}"
                    spent = {**extra, "proof": verdict.as_dict()}
                    return self._report(ctx, held, catalog, cid, att.dev_sha, why, spent)
                if att is held:
                    settle = functools.partial(self._settle_held, held, catalog, cid)
                else:
                    settle = functools.partial(self._settle_carried, ctx, att, held, catalog, cid)
                try:  # settle_if_finished gives a held repair its own second look; a carried one gets it here
                    return await settle_attempt(ctx, att, verdict, settle=settle, looked=att is held, **extra)
                except ReviewUnavailable as why:
                    return self._hold(ctx, held, cid, why)
                except (thomas_project.ThomasProjectError, ChangeFailedCheck) as refused:
                    # The size rule, the check before your card or its second look refused it. Unrecorded, its
                    # ``settling`` line read as a crash to the next run, which started a new team on it every day
                    # (2026-09-28).
                    why = f"Thomas refused the repaired change at hand-in: {refused}"
                    return self._report(ctx, held, catalog, cid, att.dev_sha, why, extra)
            except DevMoved:
                continue
            finally:
                if att is not None and att is not held:
                    await asyncio.to_thread(discard, att.green, ctx.hooks)
        return self._report(ctx, held, catalog, cid, held.dev_sha, "dev kept moving while the repair was proven", extra)

    async def _carry(self, ctx: Context, held: Attempt, tip: str) -> Attempt | None:
        """The team's work, without the board or task-plan edits it made, applied three-way in a green at *tip*."""
        await asyncio.to_thread(restore_left_out, held.green)
        patch = await asyncio.to_thread(green_checkout.green_patch, held.green)
        green = await asyncio.to_thread(fresh_green, ctx, execution_id("fwd", held.candidate.sha, tip))
        if green.base != tip:
            await asyncio.to_thread(discard, green, ctx.hooks)
            raise DevMoved()
        try:
            conflicts = await asyncio.to_thread(green_checkout.apply_patch, green, patch)
        except green_checkout.GreenUnavailable:
            conflicts = ["the whole patch"]
        if conflicts:
            await asyncio.to_thread(discard, green, ctx.hooks)
            return None
        return Attempt(held.candidate, tip, held.screen, green, onto=held.onto, repaired=True)

    def _settle_held(self, held: Attempt, catalog: Path, cid: str, summary: str, _chat: str) -> Path | None:
        return self.hooks.settle_held(held.green.work, catalog, cid, summary=summary)

    def _settle_carried(
        self, ctx: Context, att: Attempt, held: Attempt, catalog: Path, cid: str, summary: str, chat: str
    ) -> Path | None:
        submission = ctx.hooks.settle(att.green.execution_id, promote=True, summary=summary, chat=chat)
        if submission is not None:
            self.hooks.retire(held.green.work, catalog, cid)
            self.hooks.record_retirement(catalog, cid, outcome="carried", submission=submission.name)
        return submission

    def _hold(self, ctx: Context, held: Attempt, cid: str, why: Exception) -> str:
        """Its second look could not run: the team's work stays in its green, and the next run takes it up there.

        Reported instead, hours of a team's work were thrown away over a usage limit, and the report counted
        towards giving the candidate up.
        """
        ctx.ledger.record(
            candidate=held.candidate,
            dev_sha=held.dev_sha,
            state="repairing",
            reason=f"held: {why}; the team's work is kept for the next run",
            conversation_id=cid,
            execution_id=held.green.execution_id,
            onto=held.onto,
        )
        return HELD

    def _report(
        self, ctx: Context, held: Attempt, catalog: Path, cid: str, dev_sha: str, reason: str, extra: dict[str, Any]
    ) -> str:
        self.hooks.retire(held.green.work, catalog, cid)
        self.hooks.record_retirement(catalog, cid, outcome="reported", reason=reason)
        ctx.ledger.record(candidate=held.candidate, dev_sha=dev_sha, state="reported", reason=reason, **extra)
        return "reported"


__all__ = [
    "CARRY_LIMIT",
    "REPAIR_POLL_S",
    "REPAIR_TIMEOUT_S",
    "Repairer",
    "RepairHooks",
    "repair_goal",
    "repair_settings",
    "resumable",
]
