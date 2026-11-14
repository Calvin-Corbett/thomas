"""What every step of a ratchet attempt shares, and the greens it makes.

``Hooks`` are the ratchet's edges to the cage and the promoter (tests replace
them), ``Context`` is one run, and ``Attempt`` is one candidate in its green.

A green the ratchet is done with is discarded here. First the cage runner is
asked to end whatever the green's commands left running: the runner holds every
process started in a green in one Windows job until it gets an ``end_green``
request (scripts/cage/shell_runner.py:318-346), and ``green_handoff.settle`` is
the only other caller that sends one (green_handoff.py:137-150). Then the
green's folders go.

Coordination files are put back here too, before every proof (Deviation 18).
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from thomas.server import green_checkout, green_handoff, self_change_status
from thomas.server.green_checkout import Green
from thomas.server.ratchet.candidates import Candidate
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import Ledger
from thomas.server.ratchet.proof import proof_folder
from thomas.server.ratchet.proof_set import ProofSet
from thomas.server.ratchet.results import Verdict
from thomas.server.ratchet.screen import Screen, left_out
from thomas.tools import cage_shell


class DevMoved(Exception):  # noqa: N818 - reads as what happened
    """dev moved while a candidate was being proven, so the proof no longer describes what would land."""


@dataclass
class Hooks:
    """The ratchet's edges to the cage and the promoter; tests replace them."""

    run_caged: Callable[..., cage_shell.CagedResult] = cage_shell.run_caged
    runner_alive: Callable[[], bool] = cage_shell.runner_alive
    settle: Callable[..., Path | None] = green_handoff.settle
    read_verdict: Callable[[str], dict[str, Any] | None] = self_change_status.read_hand_in_state
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    poll_s: float = 10.0
    verdict_timeout_s: float = 6 * 3600.0
    dirty_wait_s: float = 1800.0


@dataclass
class Attempt:
    candidate: Candidate
    dev_sha: str
    screen: Screen
    green: Green
    proof_set: ProofSet | None = None
    tree: str = ""  # the tree the proof ran on (attempt.prove_green); what reaches your card must still be it
    onto: str = ""  # the landed commit its own change sits on top of, when it is stacked (stacking.onto_for)
    repaired: bool = False  # a Build team worked in this green, so its change may reach beyond the candidate's
    extra: tuple[str, ...] = ()  # paths in the change that the candidate does not change (a repair's own work)
    checked_patch: str = ""  # patch read by the last checks before the second look


class Repairs(Protocol):
    async def repair(self, ctx: Context, att: Attempt, *, verdict: Verdict | None) -> str: ...

    async def resume(self, ctx: Context, att: Attempt, cid: str) -> str: ...


@dataclass
class Context:
    repo: Repo
    ledger: Ledger
    hooks: Hooks = field(default_factory=Hooks)
    chat: str = ""
    repairs: Repairs | None = None
    no_repair_reason: str = "this server cannot start a repair run"


def execution_id(kind: str, sha: str, dev_sha: str) -> str:
    """Short on purpose: a green's deepest path must stay under Windows' 260 characters."""
    return f"ratchet-{kind}-{sha[:7]}-{dev_sha[:7]}"


def green_repo(green: Green) -> Repo:
    """Git on green through its own git folder, never the .git pointer file in its work folder."""
    return Repo(green.work, {"GIT_DIR": str(green.git_dir), "GIT_WORK_TREE": str(green.work)})


def end_processes(green: Green, hooks: Hooks) -> None:
    """Ask the cage runner to end every process a command left running in *green*, as settle does."""
    if hooks.runner_alive():
        hooks.run_caged("", cwd="", timeout_s=10.0, extra={"action": "end_green", "green": green.execution_id})


def discard(green: Green, hooks: Hooks) -> None:
    """End what is still running in *green*, then remove it and its proof folder."""
    end_processes(green, hooks)
    shutil.rmtree(proof_folder(green), ignore_errors=True)
    try:
        green_checkout.remove_green(green)
    except OSError:
        green_checkout.mark_settled(green)  # still held open: the next sweep takes it at any age


def fresh_green(ctx: Context, execution: str) -> Green:
    """A new green for *execution*, refused unless it starts as an exact copy of what blue committed.

    ``create_green`` can hand back a green with a tracked file already missing:
    ``git checkout --detach`` exited 0 and one file was never written, so
    ``changed_paths`` was not empty before anything ran. Scratch run 9c submitted
    that hole as a deletion of a file its candidate never touched, and the proof
    passed it. A green that starts changed proves nothing about a candidate, so it
    is discarded and the attempt fails instead.
    """
    stale = green_checkout.find_green(execution)
    if stale is not None:  # an attempt a restart cut short
        discard(stale, ctx.hooks)
    green = green_checkout.create_green(ctx.repo.path, execution)
    changed = green_checkout.changed_paths(green)
    if changed:
        discard(green, ctx.hooks)
        raise green_checkout.GreenUnavailable(
            f"the green for {execution} starts with {len(changed)} file(s) already changed against "
            f"{green.base[:12]}, so it is not a copy of it: " + ", ".join(sorted(changed)[:6])
        )
    return green


def restore_left_out(green: Green) -> list[str]:
    """Put every coordination file *green* changed back as it is at green's base; return those paths.

    Run before every proof, so a Build team's board or task-plan edits never reach
    the proof or your card. ``screen.final_refusal`` refuses any that remain.
    """
    back = [p for p in green_checkout.changed_paths(green) if left_out(p)]
    if back:
        green_checkout.restore_paths(green, back)
    return back


__all__ = [
    "Attempt",
    "Context",
    "DevMoved",
    "Hooks",
    "Repairs",
    "discard",
    "end_processes",
    "execution_id",
    "fresh_green",
    "green_repo",
    "restore_left_out",
]
