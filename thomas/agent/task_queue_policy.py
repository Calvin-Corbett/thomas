"""Priority scheduling policy for the in-process swarm task queue (stdlib-only).

This module decides *which* ready task a swarm worker should pick up next.
It layers priority, aging, and a preemption decision on top of the existing
FIFO ready-queue in :mod:`thomas.agent.swarm` without changing the swarm's
task structures: priorities are read from the existing ``TaskSpec.meta`` dict.

Semantics
---------
Priority
    ``meta["priority"]`` may be an int or a named tier ("low" | "normal" |
    "high" | "critical", mapped to -10/0/10/20). Tasks without a priority get
    ``DEFAULT_PRIORITY`` (0, i.e. "normal"). When no task declares a priority
    everything ties and selection falls back to arrival order, so existing
    graphs keep their exact FIFO behavior.

Aging
    A waiting task's *effective* priority is ``base + waited_seconds * rate``
    (``QueuePolicyConfig.aging_rate_per_sec``, default 1.0). Because effective
    priority grows without bound while base priorities are bounded, a
    low-priority task's wait is bounded: it overtakes any fresh task of base
    priority ``P`` after at most ``(P - base) / rate`` seconds
    (:meth:`TaskQueuePolicy.starvation_bound_seconds`). A rate of 0 disables
    aging (pure strict priority).

Preemption — honest boundary (READ THIS BEFORE EXTENDING)
    The swarm executes a task by awaiting ``Subagent.run_task`` *inline*
    inside a worker coroutine. There is no per-task ``asyncio.Task`` handle,
    and the only cancellation signal handed to subagents is the run-global
    cancel event — interrupting one started task would mean cancelling the
    whole run (or silently violating the Subagent protocol). Therefore a task
    that has STARTED executing cannot be safely preempted.

    What *is* safely possible, and what the swarm enacts, is **cooperative
    requeue-before-start**: a task that a worker has claimed but that is still
    waiting for a per-agent concurrency slot yields its claim back to the
    ready queue when strictly-higher-effective-priority work is waiting
    (:meth:`TaskQueuePolicy.should_yield_claim`). The requeue preserves the
    task's original ready timestamp ("requeue-with-state"), so its aging
    credit survives preemption. Tasks may opt out with
    ``meta["preemptible"] = False``.

    Note that with the swarm's default config (worker count == global slot
    budget, no per-agent limits) a claimed task never waits, so the yield
    point only arises when ``max_parallel_per_agent`` creates contention.
    :meth:`TaskQueuePolicy.decide_preemption` additionally reports the full
    textbook decision (lowest-priority preemptible victim among *running*
    tasks) for observability and tests, but per the boundary above the swarm
    does not kill started tasks — the decision is only enacted for
    claimed-not-started work.

Comparisons use *waiting* effective priority (base + aging) for ready and
claimed tasks, and *base* priority for started tasks (they are no longer
waiting, so aging does not apply to them).
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any

PRIORITY_TIERS: dict[str, int] = {"low": -10, "normal": 0, "high": 10, "critical": 20}
DEFAULT_PRIORITY: int = PRIORITY_TIERS["normal"]
DEFAULT_AGING_RATE_PER_SEC: float = 1.0


def parse_priority(value: Any) -> int:
    """Parse a priority value from task meta. Unknown/invalid values -> DEFAULT_PRIORITY."""
    if isinstance(value, bool):  # bool is an int subclass; True/False are not priorities
        return DEFAULT_PRIORITY
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        name = value.strip().lower()
        if name in PRIORITY_TIERS:
            return PRIORITY_TIERS[name]
        try:
            return int(name)
        except ValueError:
            return DEFAULT_PRIORITY
    return DEFAULT_PRIORITY


def priority_from_meta(meta: Mapping[str, Any] | None) -> int:
    """Base priority for a task's ``meta`` dict (missing/invalid -> DEFAULT_PRIORITY)."""
    if not isinstance(meta, Mapping):
        return DEFAULT_PRIORITY
    if "priority" not in meta:
        return DEFAULT_PRIORITY
    return parse_priority(meta.get("priority"))


def preemptible_from_meta(meta: Mapping[str, Any] | None) -> bool:
    """Tasks are preemptible unless ``meta["preemptible"]`` is explicitly False."""
    if not isinstance(meta, Mapping):
        return True
    return meta.get("preemptible") is not False


@dataclasses.dataclass(frozen=True)
class QueuePolicyConfig:
    """Tunables for the queue policy.

    aging_rate_per_sec: effective-priority points a waiting task gains per
        second. 0 disables aging (pure strict priority + FIFO ties).
    preemption_enabled: master switch for yield/preemption decisions.
    """

    aging_rate_per_sec: float = DEFAULT_AGING_RATE_PER_SEC
    preemption_enabled: bool = True


@dataclasses.dataclass(frozen=True)
class PreemptionDecision:
    """A recommendation that ``victim_id`` should yield to ``incoming_id``."""

    victim_id: str
    incoming_id: str
    victim_priority: float
    incoming_priority: float


@dataclasses.dataclass
class _ReadyEntry:
    task_id: str
    ready_since: float  # first time the task became ready (preserved across requeues)
    seq: int  # arrival sequence, FIFO tie-break


class TaskQueuePolicy:
    """Priority + aging selection over the swarm's ready tasks.

    The policy tracks the *ready set* (tasks whose deps are satisfied and that
    are waiting for a worker). The swarm keeps its existing token queue for
    worker wake-ups; each ``mark_ready``/``requeue`` is paired with one token,
    and each token consumption with one ``pop_next``.
    """

    def __init__(
        self,
        *,
        priorities: Mapping[str, int] | None = None,
        preemptible: Mapping[str, bool] | None = None,
        config: QueuePolicyConfig | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._priorities: dict[str, int] = dict(priorities or {})
        self._preemptible: dict[str, bool] = dict(preemptible or {})
        self.config = config or QueuePolicyConfig()
        self._clock: Callable[[], float] = clock or time.monotonic
        self._ready: dict[str, _ReadyEntry] = {}
        self._first_ready: dict[str, float] = {}
        self._seq = 0

    @classmethod
    def for_graph(
        cls,
        graph: Any,
        *,
        config: QueuePolicyConfig | None = None,
        aging_rate_per_sec: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> TaskQueuePolicy:
        """Build a policy from a swarm ``TaskGraph`` (reads ``TaskSpec.meta``)."""
        tasks = getattr(graph, "tasks", None) or {}
        priorities = {tid: priority_from_meta(getattr(t, "meta", None)) for tid, t in tasks.items()}
        preemptible = {tid: preemptible_from_meta(getattr(t, "meta", None)) for tid, t in tasks.items()}
        if config is None:
            rate = DEFAULT_AGING_RATE_PER_SEC if aging_rate_per_sec is None else float(aging_rate_per_sec)
            config = QueuePolicyConfig(aging_rate_per_sec=rate)
        return cls(priorities=priorities, preemptible=preemptible, config=config, clock=clock)

    # -- registration / state ------------------------------------------------

    def register(self, task_id: str, *, priority: int | str | None = None, preemptible: bool = True) -> None:
        """Register a task not present in the original graph (mainly for tests/tools)."""
        if priority is not None:
            self._priorities[task_id] = parse_priority(priority)
        self._preemptible[task_id] = bool(preemptible)

    def base_priority(self, task_id: str) -> int:
        return self._priorities.get(task_id, DEFAULT_PRIORITY)

    def is_preemptible(self, task_id: str) -> bool:
        return self._preemptible.get(task_id, True)

    def mark_ready(self, task_id: str) -> None:
        """Add a task to the ready set. Idempotent while the task is ready."""
        if task_id in self._ready:
            return
        now = self._clock()
        since = self._first_ready.setdefault(task_id, now)
        self._seq += 1
        self._ready[task_id] = _ReadyEntry(task_id=task_id, ready_since=since, seq=self._seq)

    def requeue(self, task_id: str) -> None:
        """Return a claimed-but-not-started task to the ready set.

        Requeue-with-state: the original ready timestamp is preserved, so the
        task keeps the aging credit it accumulated before being preempted.
        """
        self.mark_ready(task_id)

    def ready_ids(self) -> tuple[str, ...]:
        return tuple(self._ready.keys())

    def ready_count(self) -> int:
        return len(self._ready)

    # -- priority math -------------------------------------------------------

    def effective_priority(self, task_id: str, now: float | None = None) -> float:
        """base + aging for waiting (ready or claimed) tasks; base otherwise."""
        base = float(self.base_priority(task_id))
        since = self._first_ready.get(task_id)
        if since is None:
            return base
        if now is None:
            now = self._clock()
        waited = max(0.0, now - since)
        return base + waited * max(0.0, self.config.aging_rate_per_sec)

    def starvation_bound_seconds(self, base_priority: float, ceiling_priority: float) -> float:
        """Max wait before a task at ``base_priority`` outranks fresh ``ceiling_priority`` work.

        Infinite (float("inf")) when aging is disabled.
        """
        rate = self.config.aging_rate_per_sec
        gap = max(0.0, float(ceiling_priority) - float(base_priority))
        if rate <= 0.0:
            return float("inf") if gap > 0.0 else 0.0
        return gap / rate

    # -- selection -----------------------------------------------------------

    def pop_next(self) -> str | None:
        """Remove and return the best ready task (highest effective priority, FIFO ties)."""
        if not self._ready:
            return None
        now = self._clock()
        best = min(self._ready.values(), key=lambda e: (-self.effective_priority(e.task_id, now), e.seq))
        del self._ready[best.task_id]
        return best.task_id

    def peek_next(self) -> str | None:
        """Best ready task without removing it."""
        if not self._ready:
            return None
        now = self._clock()
        best = min(self._ready.values(), key=lambda e: (-self.effective_priority(e.task_id, now), e.seq))
        return best.task_id

    # -- preemption ----------------------------------------------------------

    def should_yield_claim(self, claimed_task_id: str) -> bool:
        """True if a claimed-but-not-started task should yield its worker slot.

        Yields only when the ready set holds a task whose effective priority
        STRICTLY exceeds the claimed task's, and the claimed task is
        preemptible. Both sides use waiting semantics (base + aging), so an
        aged low-priority claim is not bounced by fresh mid-priority work it
        already outranks.
        """
        if not self.config.preemption_enabled:
            return False
        if not self.is_preemptible(claimed_task_id):
            return False
        if not self._ready:
            return False
        now = self._clock()
        claimed_eff = self.effective_priority(claimed_task_id, now)
        return any(self.effective_priority(e.task_id, now) > claimed_eff for e in self._ready.values())

    def decide_preemption(self, running: Iterable[str]) -> PreemptionDecision | None:
        """Full preemption decision over *running* tasks (advisory — see module docstring).

        When the slot budget is full and the best ready task's effective
        priority strictly exceeds the base priority of the lowest-priority
        preemptible running task, return that pairing. The swarm cannot kill a
        started task (boundary documented above), so callers use this for
        telemetry/tests and enact only the claimed-not-started yield path.
        """
        if not self.config.preemption_enabled or not self._ready:
            return None
        incoming = self.peek_next()
        if incoming is None:
            return None
        now = self._clock()
        incoming_eff = self.effective_priority(incoming, now)
        candidates = [tid for tid in running if self.is_preemptible(tid)]
        if not candidates:
            return None
        # Started tasks are no longer waiting: compare on base priority.
        victim = min(candidates, key=lambda tid: float(self.base_priority(tid)))
        victim_pri = float(self.base_priority(victim))
        if incoming_eff <= victim_pri:
            return None
        return PreemptionDecision(
            victim_id=victim,
            incoming_id=incoming,
            victim_priority=victim_pri,
            incoming_priority=incoming_eff,
        )
