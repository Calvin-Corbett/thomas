"""What your card decided, confirmed in git before anything is called landed.

The promoter re-derives a change on whatever dev is when it picks the submission
up, 3-way-applies it if it must, and never compares the submission's base with
dev; a per-file card you decline leaves that file out while the rest lands. So
"landed" is recorded only when git agrees: the commit is on dev, it carries this
submission's id, and it changes the files proven. A landing on another parent,
or with files left out, is proven again as it landed. If that proof finds new
failures, an issue is recorded and a halt is written beside the ledger, and every
later run stops until the tests it names pass on dev.

A run cut short between recording ``settling`` and ``awaiting_card`` leaves the
hand-off unaccounted for; ``reconcile`` asks the promoter's folders which it was.
It asks by the green the change was handed in from (``submissions_from``), not by
the name the run wrote down before the hand-off: what a hand-off is called is
decided when it is made, and only the green is known before that.
"""

from __future__ import annotations

import asyncio
import functools
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from thomas.server import green_handoff, self_change_status
from thomas.server.issue_ledger import record_issue
from thomas.server.ratchet.archive import archive_refs
from thomas.server.ratchet.attempt import Context, prove_candidate, side_at
from thomas.server.ratchet.candidates import Candidate
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import DECLINED, WITHDRAWN
from thomas.server.ratchet.proof import Verdict, compare
from thomas.server.ratchet.proof_set import select

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


async def run_candidate(ctx: Context, cand: Candidate, *, onto: str = "") -> str:
    """Prove *cand*, and when it went to your card, wait for what you decided."""
    state = await prove_candidate(ctx, cand, onto=onto)
    if state != "awaiting_card":
        return state
    return await await_landing(ctx, ctx.ledger.latest()[cand.sha])


async def await_landing(ctx: Context, event: dict[str, Any]) -> str:
    sid = str(event.get("submission") or "")
    if ctx.chat:
        asyncio.create_task(self_change_status.follow(sid, ctx.chat), name=f"ratchet-cards:{sid}")
    waited = 0.0
    while True:
        decided = await asyncio.to_thread(ctx.hooks.read_verdict, sid)
        if decided is not None:
            if decided.get("status") == "withdrawn":
                ctx.ledger.record(
                    sha=str(event["candidate_sha"]),
                    refs=list(event.get("refs") or [event.get("candidate_ref", "")]),
                    dev_sha=str(event["dev_sha"]),
                    submission=sid,
                    state="queued",
                    reason=WITHDRAWN,
                )
                return "queued"
            return await conclude(ctx, event, decided)
        if waited >= ctx.hooks.verdict_timeout_s:
            return "awaiting_card"
        await ctx.hooks.sleep(ctx.hooks.poll_s)
        waited += max(ctx.hooks.poll_s, 1.0)


def verify_landed(repo: Repo, commit: str, sid: str) -> str:
    """What git says instead of a landing of submission *sid* as *commit* ("" when it is on dev and carries it)."""
    if not _SHA_RE.match(commit):
        return "its verdict names no commit"
    if repo.run("merge-base", "--is-ancestor", commit, "refs/heads/dev", ok=(0, 1, 128)).returncode != 0:
        return f"{commit[:12]} is not on dev"
    carried = repo.out("show", "-s", "--format=%(trailers:key=Thomas-Submission-Id,valueonly)", commit).strip()
    if carried != sid:
        return f"{commit[:12]} carries submission {carried or 'none'}, not {sid}"
    return ""


def _landed_shape(repo: Repo, commit: str) -> tuple[list[str], str]:
    files = sorted(repo.out("diff-tree", "--no-commit-id", "--no-renames", "--name-only", "-r", commit).splitlines())
    return files, repo.out("rev-parse", f"{commit}^")


async def reprove_landed(ctx: Context, commit: str, parent: str, files: list[str]) -> Verdict:
    """The proof again, on the commit as it landed against the commit it landed on."""
    pset = await asyncio.to_thread(select, ctx.repo, commit, files, base=parent)
    on_parent = await asyncio.to_thread(lambda: [f for f in pset.files if ctx.repo.has_path(parent, f)])
    base_files = [*on_parent, *pset.gone]
    base = await side_at(ctx, parent, base_files, label="prnt", execution=f"ratchet-prnt-{commit[:7]}", confirm=True)
    landed = await side_at(ctx, commit, list(pset.files), label="land", execution=f"ratchet-land-{commit[:7]}")
    return compare(base, landed, changed=files, left_out=pset.left_out)


def submission_exists(sid: str) -> bool:
    """Whether submission *sid* is in the inbox, processed, withdrawn, or has a verdict."""
    inbox = green_handoff.inbox_dir()
    places = (inbox / sid, inbox.parent / "processed" / sid, inbox.parent / "withdrawn" / sid,
              self_change_status.outbox_dir() / f"{sid}.verdict.json")  # fmt: skip
    return bool(sid) and any(place.exists() for place in places)


def _promoter_names() -> Iterator[str]:
    """Submission ids in the inbox, processed, withdrawn, or named by a verdict."""
    inbox = green_handoff.inbox_dir()
    for folder in (inbox, inbox.parent / "processed", inbox.parent / "withdrawn"):
        yield from (entry.name for entry in _entries(folder) if entry.is_dir())
    for entry in _entries(self_change_status.outbox_dir()):
        name = entry.name.removesuffix(".verdict.json")
        if name != entry.name:
            yield name


def _entries(folder: Path) -> list[Path]:
    """What is in *folder*; nothing when it is not there yet (the promoter makes each one on first use)."""
    try:
        return list(folder.iterdir())
    except OSError:
        return []


def submissions_from(execution_id: str) -> list[str]:
    """Every submission the promoter has from the green *execution_id*, in the order it handed them in.

    The ratchet records ``settling`` before a hand-off, and cannot know what the
    hand-off will be called: ``green_handoff`` names a first hand-in
    ``self-<execution id>``, but a green kept for its verdict names its second and
    later ones ``self-<execution id>-2``, ``-3`` (``green_handoff._next_id``), and a
    repair green is kept that way -- ``thomas_project.settle_if_finished`` calls
    ``await_verdict`` immediately before it settles. So a cut-short run is matched
    to its hand-off by the green it came from, which the ledger does record, rather
    than by a name that is only right while that green has handed in once.
    """
    if not execution_id:
        return []
    first = f"self-{execution_id}"
    later = re.compile(rf"^{re.escape(first)}-([0-9]+)$")
    found: dict[str, int] = {}
    for name in _promoter_names():
        if name == first:
            found[name] = 1
        elif match := later.match(name):
            found[name] = int(match.group(1))
    return [name for name, _nth in sorted(found.items(), key=lambda pair: pair[1])]


def reconcile(ctx: Context) -> None:
    """Reconcile a cut-short hand-off: withdrawn is queued, a live hand-in awaits its card."""
    for sha, event in ctx.ledger.latest().items():
        if event.get("state") != "settling":
            continue
        sid = str(event.get("submission") or "")
        handed = submissions_from(str(event.get("execution_id") or ""))
        # The green's latest hand-in, or the recorded name when the green is not known (an older ledger line).
        found = handed[-1] if handed else (sid if submission_exists(sid) else "")
        refs = list(event.get("refs") or [])
        note = functools.partial(ctx.ledger.record, sha=sha, refs=refs, dev_sha=str(event.get("dev_sha") or ""))
        if found and (self_change_status.read_hand_in_state(found) or {}).get("status") == "withdrawn":
            note(state="queued", reason=WITHDRAWN, submission=found)
        elif found:
            carried = ("files", "beyond_the_candidate", "execution_id", "conversation_id", "autonomy")
            kept = {k: event[k] for k in carried if k in event}
            note(
                state="awaiting_card",
                reason="waiting for your card",
                submission=found,
                proof=event.get("proof"),
                **kept,
            )
        else:
            why = "a hand-off to the promoter was cut short before it was written; it is proven again"
            note(state="queued", reason=why)


async def conclude(ctx: Context, event: dict[str, Any], decided: dict[str, Any]) -> str:
    """Record what your card decided. Returns landed, reported, or halted (landed, and it broke a test)."""
    sha = str(event["candidate_sha"])
    refs = list(event.get("refs") or [event.get("candidate_ref", "")])
    note = functools.partial(
        ctx.ledger.record, sha=sha, refs=refs, dev_sha=str(event["dev_sha"]), submission=event.get("submission", "")
    )
    status, detail = str(decided.get("status") or "error"), str(decided.get("detail") or "")
    if status == "declined":
        note(state="reported", reason=f"{DECLINED}: {detail}")
        return "reported"
    if status != "landed":
        refused = "refused" if status == "refused" else "could not land"
        note(state="reported", reason=f"the promoter {refused} it: {detail}")
        return "reported"
    commit = str(decided.get("commit_sha") or "")
    problem = await asyncio.to_thread(verify_landed, ctx.repo, commit, str(event.get("submission") or ""))
    if problem:
        note(state="reported", reason=f"the promoter says it landed, but {problem}", landed_commit=commit)
        return "reported"
    landed_files, parent = await asyncio.to_thread(_landed_shape, ctx.repo, commit)
    proven = sorted(event.get("files") or [])
    archive = await asyncio.to_thread(archive_refs, ctx.repo, refs, sha)
    doubts = []
    if parent != event["dev_sha"]:
        doubts.append(f"it landed on dev {parent[:12]}, not the dev its proof ran on ({str(event['dev_sha'])[:12]})")
    left = sorted(set(proven) - set(landed_files))
    if left:
        doubts.append("you left out " + ", ".join(left[:6]))
    if set(landed_files) - set(proven):
        doubts.append("the landed commit changes files the proof did not")
    if not doubts:
        note(
            state="landed",
            reason=f"landed as {commit[:12]} on the dev its proof ran on",
            landed_commit=commit,
            archive=archive,
        )
        return "landed"
    why = "; ".join(doubts)
    after = await reprove_landed(ctx, commit, parent, landed_files)
    if after.ok:
        note(
            state="landed",
            reason=f"{why}; the landed commit was proven again and holds",
            landed_commit=commit,
            archive=archive,
            after_landing=after.as_dict(),
        )
        return "landed"
    message = f"{commit[:12]} landed for {refs[0]}, and proving it as it landed finds: {after.reason}"
    record_issue(
        surface="ratchet",
        kind="landed_regression",
        message=message,
        context={"candidate": sha, "commit": commit},
    )
    ctx.ledger.halt(
        candidate_sha=sha,
        candidate_ref=refs[0],
        commit=commit,
        reason=message,
        failures=list(after.new_failures),
        missing=list(after.missing),
    )
    note(
        state="landed",
        reason=f"{why}; proving the landed commit again finds: {after.reason}. Every run stops until those tests "
        "pass on dev",
        landed_commit=commit,
        archive=archive,
        after_landing=after.as_dict(),
    )
    return "halted"


__all__ = [
    "await_landing",
    "conclude",
    "reconcile",
    "reprove_landed",
    "run_candidate",
    "submission_exists",
    "submissions_from",
    "verify_landed",
]
