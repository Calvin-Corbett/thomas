"""Subagent/worktree progress aggregation core (CAP-139).

Backend core behind the *subagent / worktree progress visibility* UI. It models a
set of **worktrees** (subagents) each executing **nodes** of a shared **task
graph**, ingests node lifecycle events (started / finished, with tokens + cost),
and folds them into three dashboard-ready views:

1. **Per-worktree status** -- ``active`` / ``idle`` / ``done``, the current node,
   and elapsed time. A worktree with a running (started-but-unfinished) node is
   ``active`` and reports elapsed-so-far against the injected clock; one whose
   nodes have all finished is ``done``; one that is registered but has started no
   node is ``idle``.
2. **Task-graph timing** -- per-node durations and the **critical path**: the
   longest-duration path through the dependency DAG, plus its total duration.
   A still-running node contributes its elapsed-so-far, so the critical path is
   well defined before the graph finishes.
3. **Cost rollup** -- per-node cost/tokens summed to per-worktree and then to an
   overall total.

Everything is deterministic given the ingested events and the injected clock:
there is no wall-clock read or RNG in any computation. ``duration`` of a running
node is ``now() - started_at`` where ``now`` is the injected clock, so two
snapshots taken at the same clock value are byte-for-byte identical.

This is a stdlib-only leaf module in the ``observability`` (infra) tier: it
imports nothing from other Thomas packages, so it adds no dependency edge.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

__all__ = [
    "NodeProgress",
    "WorktreeStatus",
    "NodeTiming",
    "CriticalPath",
    "CostRollup",
    "ProgressSnapshot",
    "ProgressAggregator",
]

# Worktree lifecycle states.
STATE_IDLE = "idle"
STATE_ACTIVE = "active"
STATE_DONE = "done"


@dataclass(frozen=True)
class NodeProgress:
    """One task-graph node, its owning worktree, and its timing/cost.

    ``depends_on`` names the nodes that must complete before this one (the DAG
    edges). ``finished_at`` is ``None`` while the node is still running.
    """

    node_id: str
    worktree_id: str
    started_at: float
    depends_on: tuple[str, ...] = ()
    finished_at: float | None = None
    tokens: int = 0
    cost: float = 0.0

    @property
    def running(self) -> bool:
        return self.finished_at is None

    def duration(self, now: float) -> float:
        """Wall duration: ``finished_at - started_at``, or elapsed-so-far.

        For a running node this is ``now - started_at`` (the elapsed-so-far),
        which is why a still-running node has a well-defined duration.
        """

        end = now if self.finished_at is None else self.finished_at
        return end - self.started_at


@dataclass(frozen=True)
class WorktreeStatus:
    """Per-worktree status view: state, current node, elapsed, cost/tokens."""

    worktree_id: str
    state: str
    current_node: str | None
    elapsed_s: float
    node_count: int
    running_nodes: tuple[str, ...]
    total_cost: float
    total_tokens: int

    def to_dict(self) -> dict:
        return {
            "worktree_id": self.worktree_id,
            "state": self.state,
            "current_node": self.current_node,
            "elapsed_s": self.elapsed_s,
            "node_count": self.node_count,
            "running_nodes": list(self.running_nodes),
            "total_cost": self.total_cost,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class NodeTiming:
    """Timing for a single node: its duration and whether it is still running."""

    node_id: str
    worktree_id: str
    started_at: float
    finished_at: float | None
    duration_s: float
    running: bool

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "worktree_id": self.worktree_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "running": self.running,
        }


@dataclass(frozen=True)
class CriticalPath:
    """The longest-duration path through the dependency DAG and its total."""

    nodes: tuple[str, ...]
    duration_s: float

    def to_dict(self) -> dict:
        return {"nodes": list(self.nodes), "duration_s": self.duration_s}


@dataclass(frozen=True)
class CostRollup:
    """Cost/token rollup: per-node -> per-worktree -> total."""

    per_node: dict[str, float]
    per_worktree: dict[str, float]
    total: float
    tokens_per_node: dict[str, int]
    tokens_per_worktree: dict[str, int]
    tokens_total: int

    def to_dict(self) -> dict:
        return {
            "per_node": dict(self.per_node),
            "per_worktree": dict(self.per_worktree),
            "total": self.total,
            "tokens_per_node": dict(self.tokens_per_node),
            "tokens_per_worktree": dict(self.tokens_per_worktree),
            "tokens_total": self.tokens_total,
        }


@dataclass(frozen=True)
class ProgressSnapshot:
    """A full, deterministic view: worktree statuses, timing, critical path, cost.

    ``at`` is the clock value the snapshot was computed against, so a running
    node's elapsed-so-far is reproducible.
    """

    at: float
    worktrees: tuple[WorktreeStatus, ...]
    node_timings: tuple[NodeTiming, ...]
    critical_path: CriticalPath
    cost: CostRollup

    def worktree(self, worktree_id: str) -> WorktreeStatus | None:
        for w in self.worktrees:
            if w.worktree_id == worktree_id:
                return w
        return None

    def timing(self, node_id: str) -> NodeTiming | None:
        for t in self.node_timings:
            if t.node_id == node_id:
                return t
        return None

    def to_dict(self) -> dict:
        return {
            "at": self.at,
            "worktrees": [w.to_dict() for w in self.worktrees],
            "node_timings": [t.to_dict() for t in self.node_timings],
            "critical_path": self.critical_path.to_dict(),
            "cost": self.cost.to_dict(),
        }


class ProgressAggregator:
    """Ingests worktree/subagent node events and aggregates progress views.

    Parameters
    ----------
    clock:
        ``() -> float`` seconds source used to stamp events that omit ``at`` and
        to measure elapsed-so-far for running nodes. Injectable for deterministic
        tests; defaults to :func:`time.time`.
    """

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._now: Callable[[], float] = clock or time.time
        self._nodes: dict[str, NodeProgress] = {}
        # Insertion order of node ids per worktree, to break ties deterministically.
        self._order: list[str] = []
        self._worktrees: list[str] = []

    # -- registration / ingestion ----------------------------------------
    def register_worktree(self, worktree_id: str) -> None:
        """Make a worktree known even before it starts a node (so it is ``idle``)."""

        if worktree_id not in self._worktrees:
            self._worktrees.append(worktree_id)

    def node_started(
        self,
        *,
        worktree_id: str,
        node_id: str,
        depends_on: Sequence[str] = (),
        at: float | None = None,
    ) -> None:
        """Record that ``worktree_id`` began executing task-graph node ``node_id``.

        ``depends_on`` are the upstream nodes (DAG edges). Re-starting an existing
        node id updates its worktree/start/deps and clears any prior finish.
        """

        if node_id in self._nodes:
            raise ValueError(f"node {node_id!r} already started")
        start = self._now() if at is None else at
        self.register_worktree(worktree_id)
        self._nodes[node_id] = NodeProgress(
            node_id=node_id,
            worktree_id=worktree_id,
            started_at=start,
            depends_on=tuple(depends_on),
        )
        self._order.append(node_id)

    def node_finished(
        self,
        *,
        node_id: str,
        at: float | None = None,
        tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        """Record that ``node_id`` finished, attaching its ``tokens`` and ``cost``."""

        node = self._nodes.get(node_id)
        if node is None:
            raise ValueError(f"node {node_id!r} was never started")
        finish = self._now() if at is None else at
        if finish < node.started_at:
            raise ValueError(f"node {node_id!r} finished before it started")
        self._nodes[node_id] = replace(
            node,
            finished_at=finish,
            tokens=int(tokens),
            cost=float(cost),
        )

    # -- accessors --------------------------------------------------------
    def node(self, node_id: str) -> NodeProgress | None:
        return self._nodes.get(node_id)

    def worktree_ids(self) -> list[str]:
        return sorted(self._worktrees)

    def _nodes_for(self, worktree_id: str) -> list[NodeProgress]:
        return [self._nodes[nid] for nid in self._order if self._nodes[nid].worktree_id == worktree_id]

    # -- per-worktree status ---------------------------------------------
    def worktree_status(self, worktree_id: str, *, now: float | None = None) -> WorktreeStatus:
        """Status for one worktree at ``now`` (defaults to the injected clock)."""

        moment = self._now() if now is None else now
        nodes = self._nodes_for(worktree_id)

        if not nodes:
            return WorktreeStatus(
                worktree_id=worktree_id,
                state=STATE_IDLE,
                current_node=None,
                elapsed_s=0.0,
                node_count=0,
                running_nodes=(),
                total_cost=0.0,
                total_tokens=0,
            )

        running = [n for n in nodes if n.running]
        total_cost = sum(n.cost for n in nodes)
        total_tokens = sum(n.tokens for n in nodes)

        if running:
            # Active: current node is the earliest-started running node
            # (tie-broken by node id); elapsed is its elapsed-so-far.
            current = min(running, key=lambda n: (n.started_at, n.node_id))
            state = STATE_ACTIVE
            elapsed = moment - current.started_at
            current_id: str | None = current.node_id
        else:
            # Done: every node finished. Current node is the last-started one;
            # elapsed spans the worktree's own first start to its last finish.
            state = STATE_DONE
            last = max(nodes, key=lambda n: (n.started_at, n.node_id))
            first_start = min(n.started_at for n in nodes)
            last_finish = max(n.finished_at for n in nodes if n.finished_at is not None)
            elapsed = last_finish - first_start
            current_id = last.node_id

        return WorktreeStatus(
            worktree_id=worktree_id,
            state=state,
            current_node=current_id,
            elapsed_s=elapsed,
            node_count=len(nodes),
            running_nodes=tuple(sorted(n.node_id for n in running)),
            total_cost=total_cost,
            total_tokens=total_tokens,
        )

    def worktree_statuses(self, *, now: float | None = None) -> list[WorktreeStatus]:
        moment = self._now() if now is None else now
        return [self.worktree_status(wid, now=moment) for wid in self.worktree_ids()]

    # -- task-graph timing ------------------------------------------------
    def node_timings(self, *, now: float | None = None) -> list[NodeTiming]:
        """Per-node timing for every node, ordered by node id."""

        moment = self._now() if now is None else now
        out: list[NodeTiming] = []
        for nid in sorted(self._nodes):
            n = self._nodes[nid]
            out.append(
                NodeTiming(
                    node_id=n.node_id,
                    worktree_id=n.worktree_id,
                    started_at=n.started_at,
                    finished_at=n.finished_at,
                    duration_s=n.duration(moment),
                    running=n.running,
                )
            )
        return out

    def _topo_order(self) -> list[str]:
        """Deterministic topological order of node ids (Kahn, id-sorted)."""

        ids = set(self._nodes)
        indegree: dict[str, int] = {nid: 0 for nid in ids}
        successors: dict[str, list[str]] = {nid: [] for nid in ids}
        for nid in ids:
            for dep in self._nodes[nid].depends_on:
                if dep in ids:
                    indegree[nid] += 1
                    successors[dep].append(nid)

        ready = sorted(nid for nid, d in indegree.items() if d == 0)
        order: list[str] = []
        while ready:
            nid = ready.pop(0)
            order.append(nid)
            newly: list[str] = []
            for succ in successors[nid]:
                indegree[succ] -= 1
                if indegree[succ] == 0:
                    newly.append(succ)
            if newly:
                ready = sorted(ready + newly)

        if len(order) != len(ids):
            raise ValueError("task graph has a cycle; cannot compute critical path")
        return order

    def critical_path(self, *, now: float | None = None) -> CriticalPath:
        """Longest-duration path through the DAG and its total duration.

        Node weight is its :meth:`NodeProgress.duration` at ``now`` (a running
        node contributes elapsed-so-far). Ties are broken by node id so the path
        is deterministic.
        """

        moment = self._now() if now is None else now
        if not self._nodes:
            return CriticalPath(nodes=(), duration_s=0.0)

        weight = {nid: self._nodes[nid].duration(moment) for nid in self._nodes}
        best: dict[str, float] = {}
        prev: dict[str, str | None] = {}
        for nid in self._topo_order():
            deps = [d for d in self._nodes[nid].depends_on if d in self._nodes]
            chosen: str | None = None
            base = 0.0
            for dep in sorted(deps):
                cand = best[dep]
                if chosen is None or cand > base:
                    base = cand
                    chosen = dep
            best[nid] = base + weight[nid]
            prev[nid] = chosen

        # End node: max total, tie-broken by node id (sorted iteration).
        end = None
        top = float("-inf")
        for nid in sorted(best):
            if best[nid] > top:
                top = best[nid]
                end = nid

        chain: list[str] = []
        cursor = end
        while cursor is not None:
            chain.append(cursor)
            cursor = prev[cursor]
        chain.reverse()
        return CriticalPath(nodes=tuple(chain), duration_s=best[end] if end is not None else 0.0)

    # -- cost rollup ------------------------------------------------------
    def cost_rollup(self) -> CostRollup:
        """Cost + token rollup from per-node up to per-worktree and total."""

        per_node: dict[str, float] = {}
        per_worktree: dict[str, float] = {}
        tokens_per_node: dict[str, int] = {}
        tokens_per_worktree: dict[str, int] = {}
        total = 0.0
        tokens_total = 0

        for nid in sorted(self._nodes):
            n = self._nodes[nid]
            per_node[nid] = n.cost
            tokens_per_node[nid] = n.tokens
            per_worktree[n.worktree_id] = per_worktree.get(n.worktree_id, 0.0) + n.cost
            tokens_per_worktree[n.worktree_id] = tokens_per_worktree.get(n.worktree_id, 0) + n.tokens
            total += n.cost
            tokens_total += n.tokens

        # Ensure idle (node-less) worktrees still appear with a zero rollup.
        for wid in self._worktrees:
            per_worktree.setdefault(wid, 0.0)
            tokens_per_worktree.setdefault(wid, 0)

        return CostRollup(
            per_node=per_node,
            per_worktree=dict(sorted(per_worktree.items())),
            total=total,
            tokens_per_node=tokens_per_node,
            tokens_per_worktree=dict(sorted(tokens_per_worktree.items())),
            tokens_total=tokens_total,
        )

    # -- full snapshot ----------------------------------------------------
    def snapshot(self, *, now: float | None = None) -> ProgressSnapshot:
        """A single deterministic snapshot combining every view at ``now``."""

        moment = self._now() if now is None else now
        return ProgressSnapshot(
            at=moment,
            worktrees=tuple(self.worktree_statuses(now=moment)),
            node_timings=tuple(self.node_timings(now=moment)),
            critical_path=self.critical_path(now=moment),
            cost=self.cost_rollup(),
        )
