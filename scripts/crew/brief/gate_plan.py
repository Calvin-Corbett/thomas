"""Which gates a landing runs, in what order they start, and which stage they belong to. Stdlib only.

Split out of gate_runner.py. Nothing here runs a process: it turns the registry into a list of jobs, leaving out the gates
that do not apply, the ones whose script git does not track, and the proven no-ops (gate_skips). gate_runner re-exports
these names, so ``gate_runner.plan_jobs`` and ``gate_runner.Job`` still work.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

# Stage 1: gates that read the working-tree WORKBOARD.md, which active_folder_guard (stage 0) may rewrite.
BOARD_READERS = frozenset(
    {
        "workboard_inbox",
        "workboard_claims",
        "workboard_task_problems",
        "workboard_changed_files",
        "workboard_agent_claim",
    }
)
LAST = frozenset({"workboard_inbox_final"})
# Typical seconds on the live checkout, used only to start the long gates first. Never a correctness input.
TYPICAL_SECONDS = {
    "active_folder_guard": 4.4,
    "problem_closure": 3.3,
    "enforcement_integrity": 3.0,
    "workboard_task_plans": 1.5,
    "workboard_agent_claim": 1.0,
    "monolith_guard": 0.5,
    "repo_identity": 0.5,
}


def stage_of(name: str) -> int:
    return 2 if name in LAST else 1 if name in BOARD_READERS else 0


def start_order(jobs: Iterable[Job]) -> list[Job]:
    """Longest gate first, so the one that sets the stage's length is never the one left for last."""
    return sorted(jobs, key=lambda j: (-TYPICAL_SECONDS.get(j.name, 0.2), j.index))


@dataclass(frozen=True)
class Job:
    index: int  # position in the registry: the order verdicts are reported in
    name: str
    command: tuple[str, ...]

    @property
    def stage(self) -> int:
        return stage_of(self.name)


def plan_jobs(
    gates: Sequence[tuple[str, Sequence[str]]],
    *,
    applies: Callable[[str], bool],
    resolve: Callable[[str, Sequence[str]], Sequence[str]],
    script_of: Callable[[Sequence[str]], str],
    tracked: Callable[[Iterable[str]], set[str] | None],
    skips: dict[str, str],
) -> tuple[list[Job], list[str]]:
    """The jobs to run, and the gates left out for being unreviewed. ``skips`` names provable no-ops (gate_skips).

    A gate whose script git does not track is one nobody committed. It is named and skipped, as it always was
    (commit.py explains the twelve hours that decision came from). One ``git ls-files`` answers for all of them.
    """
    live = [(i, n, c) for i, (n, c) in enumerate(gates) if applies(n)]
    scripts = {script_of(c) for _i, _n, c in live} - {""}
    known = tracked(scripts) if scripts else set()
    jobs: list[Job] = []
    unreviewed: list[str] = []
    for index, name, command in live:
        script = script_of(command)
        if script and known is not None and script not in known:
            unreviewed.append(f"{name} ({script})")
        elif name not in skips:
            jobs.append(Job(index, name, tuple(resolve(name, command))))
    return jobs, unreviewed
