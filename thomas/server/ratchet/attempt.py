"""One candidate on today's dev: merged in a green, proven in the cage, handed to your card.

No model changes anything on this path. A candidate that needs one --
conflicts, a file dev deleted coming back, tests dev already has, a line that
must not land, new failures -- goes to ``ctx.repairs`` when this server can start
a repair, and waits in ``queued`` when it cannot. What a candidate waits on is
checked before any green is spent. The proof's file cap is checked on the merge
before a repair Build is started (``proof_need``), and on every green before a
test runs (``prove_green``).

The base is proven in a green of its own, never in the running copy (which holds
other sessions' uncommitted work) and never in the candidate's green. Both greens
are checked to start at the dev tip the attempt read, and dev is read again right
before the change is handed over (``DevMoved``). The tree the proof ran on is
recorded, and what is handed over must still be that tree.

What is handed over is also checked to *be* the candidate's change, twice: once
against the merge the screen measured, before a proof is spent on the green
(``merge_integrity.wrong_green``), and once on the finished change, right before the hand-off
(``merge_integrity.against_the_screen``). Without that, a green ``create_green`` made with a
tracked file already missing put a deletion the candidate never made on your card,
and the proof passed it (scratch run 9c, 2026-09-25).

A second model reads the proven change against what its own commits say it is
for, before your card (``precard.review``), as every other hand-in is read.
NOT SAFE is reported; a reader that cannot run holds it (``HELD``) for the next
run, and the green is checked again after the read, which can take minutes.
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thomas.server import green_checkout
from thomas.server.green_checkout import Green
from thomas.server.precard import PASSED, Checked, patch_sha256, review, workers
from thomas.server.ratchet import proof, proof_set
from thomas.server.ratchet.archive import archive_refs
from thomas.server.ratchet.candidates import Candidate
from thomas.server.ratchet.context import (
    Attempt,
    Context,
    DevMoved,
    Hooks,
    discard,
    end_processes,
    execution_id,
    fresh_green,
    green_repo,
    restore_left_out,
)
from thomas.server.ratchet.landing_summary import landing_summary
from thomas.server.ratchet.merge_integrity import against_the_screen, wrong_green
from thomas.server.ratchet.proof_need import capped_before_a_repair
from thomas.server.ratchet.proof_set import select
from thomas.server.ratchet.results import capped
from thomas.server.ratchet.screen import cage_checks, final_refusal, left_out, screen

HELD = "held"  # its second look could not run: recorded as queued, and the run stops
REQUEST_SHOWN = 6_000


def _waiting_on_blue(dirty: list[str]) -> str:
    return "waiting: the running copy has uncommitted work in " + ", ".join(dirty[:6])


async def side_at(
    ctx: Context,
    rev: str,
    files: list[str],
    *,
    label: str,
    execution: str,
    expect_base: str = "",
    confirm: bool = False,
) -> proof.SideResult:
    """Run *files* in a fresh green at *rev*: dev's tip itself (``expect_base``) or a commit already on dev.

    With *confirm*, each failure runs again by itself, and only one that fails again
    counts as this side's own (``SideResult.confirmed``).
    """
    green = await asyncio.to_thread(fresh_green, ctx, execution)
    try:
        if expect_base and green.base != expect_base:
            raise DevMoved()
        if green.base != rev:
            await asyncio.to_thread(green_checkout.checkout_detached, green, rev)
        why = await asyncio.to_thread(proof.boot_check, green, ctx.hooks.run_caged)
        if why:
            return proof.SideResult(tuple(files), unrunnable=(why,))
        result = await asyncio.to_thread(proof.run_side, green, files, label, ctx.hooks.run_caged)
        if confirm and result.failing and not result.unrunnable:
            nodes = list(result.failing)
            _alone, again = await asyncio.to_thread(proof.rerun_alone, green, nodes, ctx.hooks.run_caged)
            result = dataclasses.replace(result, confirmed=frozenset(again))
        return result
    finally:
        await asyncio.to_thread(discard, green, ctx.hooks)


async def base_result(ctx: Context, dev_sha: str, files: list[str]) -> proof.SideResult:
    """Dev's own result for *files*, from the cache when an earlier attempt already ran it."""
    path, known = proof.cached(ctx.ledger.path.parent / "base-proofs", dev_sha, files)
    if known is not None:
        return known
    execution = f"ratchet-base-{dev_sha[:7]}-{path.stem.rsplit('-', 1)[-1][:7]}"
    result = await side_at(ctx, dev_sha, files, label="base", execution=execution, expect_base=dev_sha, confirm=True)
    if not result.unrunnable:
        proof.remember(path, result)
    return result


def _touched(att: Attempt) -> str:
    """The files changed in green since its proof began ("" while green still holds the proven tree)."""
    if not att.tree:
        return "no proof recorded the tree it ran on"
    now = green_checkout.green_tree(att.green)
    if now == att.tree:
        return ""
    names = green_repo(att.green).out("diff-tree", "-r", "--name-only", att.tree, now).splitlines()
    return ", ".join(names[:6]) or "file modes only"


async def prove_green(ctx: Context, att: Attempt) -> proof.Verdict:
    """Prove what green holds now against dev: the same test files on both sides, on one recorded tree."""
    green = att.green
    restored = await asyncio.to_thread(restore_left_out, green)
    changed = await asyncio.to_thread(green_checkout.changed_paths, green, _staged=not restored)
    att.tree = await asyncio.to_thread(green_checkout.green_tree, green, _staged=True)
    limit = proof_set.MAX_FILES  # read now, as proof_need reads it: select's default was bound at import
    pset = await asyncio.to_thread(select, green_repo(green), att.tree, changed, base=att.dev_sha, limit=limit)
    att.proof_set = pset
    if pset.left_out:  # refused before dev's proof or its own is run: no run could make the set fit
        return proof.Verdict(False, capped(pset.left_out), files=len(pset.files), left_out=pset.left_out)
    on_dev = await asyncio.to_thread(lambda: [f for f in pset.files if ctx.repo.has_path(att.dev_sha, f)])
    base = await base_result(ctx, att.dev_sha, [*on_dev, *pset.gone])
    why = await asyncio.to_thread(proof.boot_check, green, ctx.hooks.run_caged)
    if why:
        return proof.compare(base, proof.SideResult(pset.files, unrunnable=(why,)), left_out=pset.left_out)
    cand = await asyncio.to_thread(proof.run_side, green, list(pset.files), "cand", ctx.hooks.run_caged)
    touched = await asyncio.to_thread(_touched, att)
    if touched:
        return proof.Verdict(False, "the proof changed files in the green: " + touched, files=len(pset.files))
    first = proof.compare(base, cand, changed=changed, left_out=pset.left_out)
    if first.ok or not first.new_failures:
        return first
    alone, _again = await asyncio.to_thread(proof.rerun_alone, green, first.new_failures, ctx.hooks.run_caged)
    touched = await asyncio.to_thread(_touched, att)
    if touched:
        why = "running a failure by itself changed files in the green: " + touched
        return proof.Verdict(False, why, files=len(pset.files))
    return proof.compare(base, cand, changed=changed, flaky=alone, left_out=pset.left_out)


async def prove_candidate(ctx: Context, cand: Candidate, *, onto: str = "") -> str:
    """Prove *cand* on dev's tip and hand it to your card when it holds. Returns the last state recorded."""
    dev_sha = await asyncio.to_thread(ctx.repo.sha, "refs/heads/dev")
    note = functools.partial(ctx.ledger.record, candidate=cand, dev_sha=dev_sha)
    note(state="proving", reason="proving it on dev" + (f", on top of {onto[:12]}" if onto else ""))
    found = await asyncio.to_thread(screen, ctx.repo, dev_sha, cand, onto=onto)
    if found.already_on_dev:
        archive = await asyncio.to_thread(archive_refs, ctx.repo, cand.refs, cand.sha)
        note(
            state="already_on_dev",
            reason="merging it onto dev changes nothing: its content is already there",
            archive=archive,
        )
        return "already_on_dev"
    if not found.changes and not found.conflicts:
        dropped = ", ".join(found.dropped[:6])
        note(state="not_for_ratchet", reason=f"it changes only coordination files the ratchet leaves out: {dropped}")
        return "not_for_ratchet"
    if found.refusal:
        note(state="reported", reason=f"the promoter would refuse it: {found.refusal}", screen=found.as_dict())
        return "reported"
    dirty = await asyncio.to_thread(cage_checks().blue_dirty, ctx.repo.path, dev_sha, list(found.changes))
    if dirty:  # checked before a green is spent, and again before the card
        note(state="queued", reason=_waiting_on_blue(dirty), screen=found.as_dict())
        return "queued"
    if not found.mechanical and ctx.repairs is None:
        why = f"it needs a repair run ({found.needs()}), and {ctx.no_repair_reason}"
        note(state="queued", reason=why, screen=found.as_dict())
        return "queued"
    if not found.mechanical:  # a repair Build is next: the proof's cap, read from the merge, comes first
        over = await asyncio.to_thread(capped_before_a_repair, ctx.repo, dev_sha, cand, found, onto=onto)
        if over:
            note(state="reported", reason=over, screen=found.as_dict())
            return "reported"
    attempt_id = execution_id("cand", cand.sha, dev_sha)
    withdrawn = ctx.ledger.withdrawals(cand.sha)
    if withdrawn:
        attempt_id += f"-w{withdrawn + 1}"
    green = await asyncio.to_thread(fresh_green, ctx, attempt_id)
    att = Attempt(cand, dev_sha, found, green, onto=onto)
    try:
        if green.base != dev_sha:
            raise DevMoved()
        conflicts = await asyncio.to_thread(green_checkout.apply_candidate, green, cand.sha, pick=bool(onto))
        # Restoring a left-out coordination file resolves its conflict with dev.
        coordination = sorted({*found.dropped, *(p for p in conflicts if left_out(p))})
        await asyncio.to_thread(green_checkout.restore_paths, green, coordination)
        conflicts = [p for p in conflicts if not left_out(p)]
        if conflicts or not found.mechanical:
            if ctx.repairs is None:
                why = f"it needs a repair run ({found.needs() or 'conflicts'}), and {ctx.no_repair_reason}"
                note(state="queued", reason=why, screen=found.as_dict())
                return "queued"
            return await ctx.repairs.repair(ctx, att, verdict=None)
        off = await asyncio.to_thread(wrong_green, ctx, att)
        if off:
            note(state="reported", reason=off, screen=found.as_dict())
            return "reported"
        verdict = await prove_green(ctx, att)
        if not verdict.ok:
            if ctx.repairs is not None and (verdict.new_failures or verdict.missing):
                return await ctx.repairs.repair(ctx, att, verdict=verdict)
            note(state="reported", reason=verdict.reason, proof=verdict.as_dict())
            return "reported"
        try:
            return await settle_attempt(ctx, att, verdict, settle=functools.partial(_settle_green, ctx, green))
        except review.ChangeFailedReview as found:
            note(state="reported", reason=str(found), proof=verdict.as_dict())
            return "reported"
        except review.ReviewUnavailable as why:
            note(state="queued", reason=f"held: its second look could not run ({why})", proof=verdict.as_dict())
            return HELD
    finally:
        if not _repair_still_in(ctx, cand, green):
            await asyncio.to_thread(discard, green, ctx.hooks)


def _repair_still_in(ctx: Context, cand: Candidate, green: Green) -> bool:
    """True when the ledger's last word on *cand* is a repair still in *green*: the next run takes it up there."""
    last = ctx.ledger.latest().get(cand.sha) or {}
    return last.get("state") == "repairing" and last.get("execution_id") == green.execution_id


def _settle_green(ctx: Context, green: Green, summary: str, chat: str) -> Path | None:
    return ctx.hooks.settle(green.execution_id, promote=True, summary=summary, chat=chat)


def _last_checks(ctx: Context, att: Attempt) -> tuple[str, str, list[str]]:
    """("", "", files) when green's change may go to your card, else (state, reason, files).

    What the proof left running in green is ended first, so nothing changes green
    between this check and the hand-off. ``green_handoff.settle`` writes green's
    staged tree as a patch against green's base, which is ``att.dev_sha``, so the
    tree checked here is exactly what the promoter receives -- which is why what is
    handed over is compared with the candidate's own change here
    (``merge_integrity.against_the_screen``) and not only when the green was made.
    """
    if ctx.repo.sha("refs/heads/dev") != att.dev_sha:
        raise DevMoved()
    end_processes(att.green, ctx.hooks)
    att.checked_patch = ""
    touched = _touched(att)  # stages afresh after proof, repairs, or a second look
    changes = green_checkout.changed_status(att.green, _staged=bool(att.tree))
    files = [path for _status, path in changes]
    if touched:
        return "reported", "green changed after its proof, so it is not what was proven: " + touched, files
    wrong, att.extra = against_the_screen(att, changes)
    if wrong:
        return "reported", "what would be handed over is not the candidate's change: " + wrong, files
    patch = green_checkout.green_patch(att.green, _staged=True)
    att.checked_patch = patch
    problem = final_refusal(ctx.repo, att.dev_sha, patch, files)
    if problem:
        return "reported", problem, files
    against_blue = [("M" if ctx.repo.has_path(att.dev_sha, p) else "A", p) for p in files]
    dirty = cage_checks().blue_dirty(ctx.repo.path, att.dev_sha, against_blue)
    if dirty:
        return "queued", _waiting_on_blue(dirty), files
    return "", "", files


def _request(ctx: Context, att: Attempt) -> str:
    """What a candidate is for. Nobody asked for it in a project, so its own commits say."""
    cand = att.candidate
    since = att.onto or att.dev_sha  # a stacked candidate brings only its own commit (apply_candidate pick)
    said = ctx.repo.out("log", "--no-merges", "--format=- %s%n%b", f"{since}..{cand.sha}")
    if len(said) > REQUEST_SHOWN:
        said = said[:REQUEST_SHOWN] + "\n(older commits not shown)"
    return (
        f"Land {cand.ref} ({cand.sha[:12]}) onto dev ({att.dev_sha[:12]}): work made earlier that never reached dev, "
        "merged in this copy without a commit. It must do what its commits say and nothing else. Edits to Thomas's "
        "board and task plans are left out on purpose. Its commits, newest first:\n" + (said or "(none)")
    )


def _second_look(ctx: Context, att: Attempt, verdict: proof.Verdict) -> str:
    """The card line a second model's SAFE earns ("" when the second look is off); raises on anything else."""
    if review.turned_off():
        return ""
    patch = att.checked_patch
    line = (
        f"The ratchet proved it in the cage: {verdict.files} test file(s) on dev with and without it; failing on dev "
        f"{verdict.base_failing}, with it {verdict.with_failing}; {verdict.reason}."
    )
    checked = Checked(PASSED, line, patch=patch, patch_sha256=patch_sha256(patch))
    review.second_look(att.green.execution_id, _request(ctx, att), checked)
    return review.SAFE_LINE


async def _ready(ctx: Context, att: Attempt) -> tuple[str, str, list[str]]:
    """``_last_checks``, waiting a while when the running copy holds uncommitted edits to the same files."""
    waited = 0.0
    while True:
        state, reason, files = await asyncio.to_thread(_last_checks, ctx, att)
        if state != "queued" or waited >= ctx.hooks.dirty_wait_s:
            return state, reason, files
        await ctx.hooks.sleep(ctx.hooks.poll_s)
        waited += max(ctx.hooks.poll_s, 1.0)


async def settle_attempt(
    ctx: Context,
    att: Attempt,
    verdict: proof.Verdict,
    *,
    settle: Callable[[str, str], Path | None],
    looked: bool = False,
    **extra: Any,
) -> str:
    """Check the green, have a second model read it, check it again, then hand it in.

    ``looked`` is for a hand-off that gives the change a second look of its own (a repair settled by
    ``settle_if_finished``). The second look raises ``review.ChangeFailedReview`` when it finds the change not
    safe and ``review.ReviewUnavailable`` when it cannot run; the caller records which.
    """
    note = functools.partial(ctx.ledger.record, candidate=att.candidate, dev_sha=att.dev_sha, **extra)
    state, reason, files = await _ready(ctx, att)
    line = ""
    if not state and not looked:
        line = await workers.off_the_loop(_second_look, ctx, att, verdict)
        state, reason, files = await _ready(ctx, att)  # the read takes minutes: dev and the green are read again
    if state:
        note(state=state, reason=reason, proof=verdict.as_dict())
        return state
    handed = {
        "files": sorted(files),
        "beyond_the_candidate": list(att.extra),
        "execution_id": att.green.execution_id,
        "proof": verdict.as_dict(),
    }
    # What the hand-off will be called is decided inside it (green_handoff.py:149), so this is the likely
    # name and not the record: a run cut short here is matched to its hand-off by ``execution_id``, which
    # is in ``handed`` and is exact (``landing.submissions_from``).
    sid = f"self-{att.green.execution_id}"
    note(state="settling", reason="handing it to the promoter", submission=sid, **handed)
    summary = "\n".join(part for part in (landing_summary(att, verdict, files), line) if part)
    submission = await workers.off_the_loop(settle, summary, ctx.chat)
    if submission is None:
        kept = green_checkout.find_green(att.green.execution_id) is not None
        why = "the hand-off to the promoter failed, so nothing was submitted" if kept else "nothing was submitted"
        note(state="reported", reason=why, proof=verdict.as_dict())
        return "reported"
    note(state="awaiting_card", reason="waiting for your card", submission=submission.name, **handed)
    return "awaiting_card"


__all__ = [
    "HELD",
    "Attempt",
    "Context",
    "DevMoved",
    "Hooks",
    "base_result",
    "discard",
    "end_processes",
    "execution_id",
    "fresh_green",
    "green_repo",
    "landing_summary",
    "prove_candidate",
    "prove_green",
    "restore_left_out",
    "settle_attempt",
    "side_at",
]
