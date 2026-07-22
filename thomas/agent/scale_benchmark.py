"""Orchestration scale benchmark (stdlib-only) -- CAP-032.

This module answers one question honestly: *when Thomas fans work out to N
concurrent agents, does the orchestration layer actually reach that
concurrency, and is the merged result any good?*

It is a sibling of :mod:`thomas.agent.swarm` (the in-process concurrent agent
graph) and reuses no swarm internals -- it is a self-contained, deterministic
harness so that a "20-25 concurrent agents" run can be reproduced on a clean
clone without a live model.

Two injectable edges (the "honest adapter" pattern)
---------------------------------------------------
1. **Agent worker** -- ``AgentWorker`` produces one :class:`AgentChange` per
   task. The real edge is a live model/agent; the hermetic default is a pure
   function of the task spec (:func:`deterministic_worker`). Tests inject a
   fake worker (often gated on an ``asyncio.Barrier``) to *prove* real
   concurrency: if all N workers can sit at a shared barrier simultaneously,
   peak concurrency truly reached N.

2. **Merge/gate checker** -- ``MergeChecker`` takes the ordered list of agent
   changes and reports, per agent, whether the change merged cleanly,
   conflicted, and passed gates.

   * :class:`InProcessMergeChecker` -- deterministic, dependency-free; the
     default and the one tests use.
   * :class:`GitMergeChecker` -- the *real* default edge: it materializes a
     throwaway git repo in a temp dir, branches each change off a common base,
     merges sequentially into an integration branch, and reads conflicts from
     git's exit code. Its git invocation layer is itself injectable so it can
     be exercised hermetically, but a genuine ``git``-backed run is documented
     as a live lane and is not claimed here.

The published artifact is a structured :class:`ScaleReport` (N, peak
concurrency, clean-merge %, conflict %, gate-pass %, and per-agent outcomes).

Everything is deterministic given an injected worker, checker, and clock:
no network, no wall-clock dependence, temp dirs only.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import shutil
import subprocess
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class BenchTask:
    """One independent unit of work handed to an agent worker."""

    task_id: str
    agent_id: str
    target: str  # the fixture region/file this task is expected to touch
    spec: Mapping[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class AgentChange:
    """A change an agent produced for its task (a diff against the fixture)."""

    agent_id: str
    task_id: str
    target: str  # region/file identifier the change writes
    content: str  # new content for that region
    gate_ok: bool = True  # worker's self-report that the change should pass gates


@dataclasses.dataclass(frozen=True)
class AgentOutcome:
    """Merge-quality verdict for a single agent's change."""

    agent_id: str
    task_id: str
    clean_merge: bool
    conflict: bool
    gate_pass: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ScaleReport:
    """Published benchmark result."""

    n_agents: int
    peak_concurrency: int
    target_concurrency: int
    clean_merge_pct: float
    conflict_pct: float
    gate_pass_pct: float
    per_agent: tuple[AgentOutcome, ...]
    duration_s: float

    @property
    def clean_merge_count(self) -> int:
        return sum(1 for o in self.per_agent if o.clean_merge)

    @property
    def conflict_count(self) -> int:
        return sum(1 for o in self.per_agent if o.conflict)

    @property
    def gate_pass_count(self) -> int:
        return sum(1 for o in self.per_agent if o.gate_pass)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_agents": self.n_agents,
            "peak_concurrency": self.peak_concurrency,
            "target_concurrency": self.target_concurrency,
            "clean_merge_pct": self.clean_merge_pct,
            "conflict_pct": self.conflict_pct,
            "gate_pass_pct": self.gate_pass_pct,
            "clean_merge_count": self.clean_merge_count,
            "conflict_count": self.conflict_count,
            "gate_pass_count": self.gate_pass_count,
            "duration_s": self.duration_s,
            "per_agent": [o.to_dict() for o in self.per_agent],
        }


# ---------------------------------------------------------------------------
# Injectable edges
# ---------------------------------------------------------------------------


class AgentWorker(Protocol):
    """Async callable that turns a task into a change. The live edge is a model."""

    def __call__(self, task: BenchTask) -> Awaitable[AgentChange]: ...


class MergeChecker(Protocol):
    """Merge/gate oracle over the ordered set of agent changes."""

    def check(self, changes: Sequence[AgentChange]) -> list[AgentOutcome]: ...


async def deterministic_worker(task: BenchTask) -> AgentChange:
    """Hermetic default worker: derive a change purely from the task spec.

    No model, no I/O -- the change is a pure function of the task, so a run is
    perfectly reproducible. ``spec`` may carry ``content`` and ``gate_ok``.
    """
    spec = task.spec or {}
    content = str(spec.get("content", f"{task.task_id}:{task.target}"))
    gate_ok = bool(spec.get("gate_ok", True))
    return AgentChange(
        agent_id=task.agent_id,
        task_id=task.task_id,
        target=task.target,
        content=content,
        gate_ok=gate_ok,
    )


class InProcessMergeChecker:
    """Deterministic, dependency-free merge/gate oracle (the hermetic default).

    Model: changes are applied to a shared fixture keyed by ``target`` region.
    The first change to a region merges cleanly. A later change to a region
    that already holds *different* content conflicts (the classic two-writers
    collision); an identical rewrite is a clean no-op merge. Only cleanly
    merged changes are gate-checked.
    """

    def __init__(
        self,
        *,
        base_regions: Mapping[str, str] | None = None,
        gate: Callable[[AgentChange], bool] | None = None,
    ) -> None:
        self._base: dict[str, str] = dict(base_regions or {})
        self._gate: Callable[[AgentChange], bool] = gate or (lambda ch: ch.gate_ok)

    def check(self, changes: Sequence[AgentChange]) -> list[AgentOutcome]:
        applied: dict[str, str] = dict(self._base)
        # Track which regions have been *modified by an applied change* so that
        # a base region matching by luck does not mask a genuine collision.
        modified: dict[str, str] = {}
        outcomes: list[AgentOutcome] = []
        for ch in changes:
            prev_owner = modified.get(ch.target)
            prev_content = applied.get(ch.target)
            if prev_owner is not None and prev_content != ch.content:
                outcomes.append(
                    AgentOutcome(
                        agent_id=ch.agent_id,
                        task_id=ch.task_id,
                        clean_merge=False,
                        conflict=True,
                        gate_pass=False,
                        detail=f"conflict on region '{ch.target}' with agent '{prev_owner}'",
                    )
                )
                continue
            applied[ch.target] = ch.content
            modified[ch.target] = ch.agent_id
            gate_pass = bool(self._gate(ch))
            outcomes.append(
                AgentOutcome(
                    agent_id=ch.agent_id,
                    task_id=ch.task_id,
                    clean_merge=True,
                    conflict=False,
                    gate_pass=gate_pass,
                    detail="clean" if gate_pass else "clean-merge, gate failed",
                )
            )
        return outcomes


# -- git-backed real edge ---------------------------------------------------


@dataclasses.dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


GitRunner = Callable[[Sequence[str], str], GitResult]


def _subprocess_git_runner(args: Sequence[str], cwd: str) -> GitResult:
    """Default git invoker: shell out to the real ``git`` binary."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return GitResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def git_available() -> bool:
    """True if a ``git`` binary is on PATH (used to gate the live lane)."""
    return shutil.which("git") is not None


class GitMergeChecker:
    """Real merge oracle: materialize a temp git repo and merge each change.

    This is the *live* default edge. Each distinct ``target`` maps to a file in
    a throwaway repo seeded from a common base commit. Every change is committed
    on its own branch off that base and merged sequentially into an
    ``integration`` branch; git's exit code decides clean-merge vs conflict.
    A conflicting merge is aborted so later merges stay well-defined. An
    optional ``gate_cmd`` runs against the integration tree after a clean merge.

    The git invocation is injected via ``git_runner`` so this class can be
    driven by a fake in tests; the default hits real ``git``. A genuine
    git-backed run is a documented live lane and is not asserted by the
    hermetic suite.
    """

    def __init__(
        self,
        *,
        git_runner: GitRunner | None = None,
        gate_cmd: Sequence[str] | None = None,
        work_root: str | None = None,
        author: str = "Thomas Bench <bench@thomas.local>",
    ) -> None:
        self._git: GitRunner = git_runner or _subprocess_git_runner
        self._gate_cmd = tuple(gate_cmd) if gate_cmd else None
        self._work_root = work_root
        self._author = author

    def _git_or_raise(self, args: Sequence[str], cwd: str) -> GitResult:
        res = self._git(args, cwd)
        if res.returncode != 0:
            logger.error("git %s failed in %s: %s", list(args), cwd, res.stderr.strip())
            raise RuntimeError(f"git {list(args)} failed: {res.stderr.strip() or res.stdout.strip()}")
        return res

    def check(self, changes: Sequence[AgentChange]) -> list[AgentOutcome]:
        targets = sorted({ch.target for ch in changes})
        tmp = tempfile.mkdtemp(prefix="thomas_scale_git_", dir=self._work_root)
        try:
            return self._check_in_repo(tmp, targets, changes)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _file_for(self, target: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in target)
        return f"region_{safe}.txt"

    def _check_in_repo(self, repo: str, targets: Sequence[str], changes: Sequence[AgentChange]) -> list[AgentOutcome]:
        repo_path = Path(repo)
        self._git_or_raise(["init", "-q", "-b", "base"], repo)
        self._git_or_raise(["config", "user.email", "bench@thomas.local"], repo)
        self._git_or_raise(["config", "user.name", "Thomas Bench"], repo)
        # Seed a common base so same-file edits produce real 3-way conflicts.
        for target in targets:
            (repo_path / self._file_for(target)).write_text("BASE\n", encoding="utf-8")
        self._git_or_raise(["add", "-A"], repo)
        self._git_or_raise(["commit", "-q", "-m", "base"], repo)
        self._git_or_raise(["branch", "integration"], repo)

        outcomes: list[AgentOutcome] = []
        for idx, ch in enumerate(changes):
            branch = f"change_{idx}"
            fname = self._file_for(ch.target)
            self._git_or_raise(["checkout", "-q", "base"], repo)
            self._git_or_raise(["checkout", "-q", "-b", branch], repo)
            (repo_path / fname).write_text(ch.content + "\n", encoding="utf-8")
            self._git_or_raise(["add", "-A"], repo)
            self._git_or_raise(["commit", "-q", "-m", f"{ch.agent_id}:{ch.task_id}"], repo)
            self._git_or_raise(["checkout", "-q", "integration"], repo)
            merge = self._git(["merge", "--no-edit", branch], repo)
            if merge.returncode != 0:
                # Conflict (or other merge failure): abort to keep integration clean.
                self._git(["merge", "--abort"], repo)
                outcomes.append(
                    AgentOutcome(
                        agent_id=ch.agent_id,
                        task_id=ch.task_id,
                        clean_merge=False,
                        conflict=True,
                        gate_pass=False,
                        detail=f"git merge conflict on {fname}",
                    )
                )
                continue
            gate_pass = self._run_gate(repo, ch)
            outcomes.append(
                AgentOutcome(
                    agent_id=ch.agent_id,
                    task_id=ch.task_id,
                    clean_merge=True,
                    conflict=False,
                    gate_pass=gate_pass,
                    detail="clean" if gate_pass else "clean-merge, gate failed",
                )
            )
        return outcomes

    def _run_gate(self, repo: str, ch: AgentChange) -> bool:
        if self._gate_cmd is None:
            return bool(ch.gate_ok)
        res = self._git(list(self._gate_cmd), repo) if self._gate_cmd[0] == "git" else self._run_cmd(repo, ch)
        return res.returncode == 0 and bool(ch.gate_ok)

    def _run_cmd(self, repo: str, ch: AgentChange) -> GitResult:
        assert self._gate_cmd is not None
        try:
            proc = subprocess.run(list(self._gate_cmd), cwd=repo, capture_output=True, text=True, check=False)
        except OSError as exc:
            logger.error("gate command %s failed to launch: %s", list(self._gate_cmd), exc)
            return GitResult(returncode=1, stderr=str(exc))
        return GitResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


def build_tasks(
    n: int,
    *,
    agent_prefix: str = "agent",
    contents: Mapping[int, str] | None = None,
    conflicting_pairs: Sequence[tuple[int, int]] = (),
) -> list[BenchTask]:
    """Build ``n`` independent benchmark tasks.

    Each task targets its own region by default (so a naive run merges 100%
    cleanly). ``conflicting_pairs`` forces two agents onto the *same* region
    with *different* content, so the merge oracle must report a conflict.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    contents = dict(contents or {})
    # Map each agent index to a target region; independent by default.
    target_of: dict[int, str] = {i: f"region-{i}" for i in range(n)}
    for a, b in conflicting_pairs:
        if not (0 <= a < n and 0 <= b < n):
            raise ValueError(f"conflicting pair ({a},{b}) out of range for n={n}")
        target_of[b] = target_of[a]  # b collides onto a's region

    tasks: list[BenchTask] = []
    for i in range(n):
        default_content = contents.get(i, f"content-{i}")
        tasks.append(
            BenchTask(
                task_id=f"T{i:03d}",
                agent_id=f"{agent_prefix}-{i:03d}",
                target=target_of[i],
                spec={"content": default_content, "gate_ok": True},
            )
        )
    return tasks


class ScaleBenchmark:
    """Runs N concurrent agent workers and publishes a merge-quality report."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock: Callable[[], float] = clock or time.monotonic

    async def run(
        self,
        *,
        tasks: Sequence[BenchTask],
        worker: AgentWorker = deterministic_worker,
        merge_checker: MergeChecker | None = None,
        max_concurrency: int | None = None,
    ) -> ScaleReport:
        """Execute ``tasks`` concurrently, then score merge quality.

        ``max_concurrency`` defaults to ``len(tasks)`` so every agent may run at
        once (required for a barrier-based concurrency proof). Peak concurrency
        is the maximum number of workers simultaneously in-flight.
        """
        n = len(tasks)
        if n == 0:
            raise ValueError("tasks must be non-empty")
        checker = merge_checker or InProcessMergeChecker()
        limit = n if max_concurrency is None else max(1, int(max_concurrency))
        sem = asyncio.Semaphore(limit)

        # active/peak are mutated only between await points (single-threaded
        # event loop), so plain ints are race-free here.
        active = 0
        peak = 0
        results: list[AgentChange | None] = [None] * n

        start = self._clock()

        async def run_one(idx: int, task: BenchTask) -> None:
            nonlocal active, peak
            async with sem:
                active += 1
                if active > peak:
                    peak = active
                try:
                    change = await worker(task)
                finally:
                    active -= 1
            if not isinstance(change, AgentChange):
                raise TypeError("AgentWorker must return an AgentChange")
            results[idx] = change

        async with asyncio.TaskGroup() as tg:
            for idx, task in enumerate(tasks):
                tg.create_task(run_one(idx, task))

        duration = max(0.0, self._clock() - start)
        changes = [r for r in results if r is not None]
        if len(changes) != n:  # pragma: no cover - defensive; TaskGroup would have raised
            raise RuntimeError("worker did not produce a change for every task")

        outcomes = checker.check(changes)
        return _build_report(
            n=n,
            peak=peak,
            target=limit,
            outcomes=outcomes,
            duration=duration,
        )


def _pct(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * count / total, 4)


def _build_report(
    *,
    n: int,
    peak: int,
    target: int,
    outcomes: Sequence[AgentOutcome],
    duration: float,
) -> ScaleReport:
    clean = sum(1 for o in outcomes if o.clean_merge)
    conflict = sum(1 for o in outcomes if o.conflict)
    gate = sum(1 for o in outcomes if o.gate_pass)
    return ScaleReport(
        n_agents=n,
        peak_concurrency=peak,
        target_concurrency=target,
        clean_merge_pct=_pct(clean, n),
        conflict_pct=_pct(conflict, n),
        gate_pass_pct=_pct(gate, n),
        per_agent=tuple(outcomes),
        duration_s=round(duration, 6),
    )
