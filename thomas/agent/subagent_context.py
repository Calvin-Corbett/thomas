"""Isolated per-subagent context containers (stdlib-only).

Purpose
-------
When a parent agent spawns subagents (see :mod:`thomas.agent.swarm`), each
subagent must reason inside its OWN context window with a hard token budget and
with *no* shared mutable state with its siblings. This module provides that
isolation primitive explicitly and provably:

- :class:`IsolatedContext` -- a self-contained container holding a subagent's
  system prompt, task, and private scratch, bounded by a per-subagent token
  budget (default 50_000). It exposes accessors for *its own* data only; it
  holds no reference to its parent or siblings, so there is structurally no
  accessor through which one subagent could read another's context.
- :class:`SubagentContextManager` -- hands each spawned subagent a freshly
  created isolated context and lets the parent collect each child's RESULT
  (the returned summary string) without exposing the children's full contexts
  to each other or letting children reach into the parent.

Design guarantees (each is covered by tests/test_subagent_context.py)
---------------------------------------------------------------------
1. Creation: :func:`create_subagent_context` / ``manager.create_subagent_context``
   returns an isolated context seeded from the parent's *shared* system prompt
   (copied by value -- strings are immutable) plus the child's task.
2. Sibling isolation: writes to one child's scratch are never visible in a
   sibling's context, and no accessor on a context returns another context's
   private data.
3. Budget enforcement: content that would push a context past its budget is
   rejected or truncated deterministically (chars/4 default token counting)
   with a clear structured signal, and each subagent carries its own budget.
4. Result collection: the parent collects each child's summary via the manager,
   but children cannot reach into the parent's or a sibling's full context.

Everything here is stdlib-only, deterministic, and hermetic (no network, no
model, no filesystem).
"""

from __future__ import annotations

import dataclasses
import enum
import uuid
from collections.abc import Callable

# A token counter maps text -> non-negative integer token count. The default is
# deterministic ("chars / 4"), matching the rough heuristic used elsewhere, and
# is fully injectable so tests can pin exact counts.
TokenCounter = Callable[[str], int]

DEFAULT_BUDGET_TOKENS = 50_000


def default_token_counter(text: str) -> int:
    """Deterministic chars/4 token estimate (injectable elsewhere)."""
    if not text:
        return 0
    return len(text) // 4


class OverflowPolicy(str, enum.Enum):
    """What to do when a write would exceed the context budget."""

    REJECT = "reject"  # leave the context unchanged; signal rejection
    TRUNCATE = "truncate"  # store as much as fits; signal truncation


class ContextBudgetError(ValueError):
    """Raised when a context is created with a budget too small for its seed."""


@dataclasses.dataclass(frozen=True)
class WriteResult:
    """Structured, deterministic signal returned by every scratch write.

    Attributes
    ----------
    accepted:
        True if any of the write was stored.
    rejected:
        True if the write was refused wholesale (REJECT policy, over budget).
    truncated:
        True if only part of the write was stored (TRUNCATE policy).
    stored_tokens:
        Token count actually added to the context by this write.
    dropped_tokens:
        Token count of the write that was not stored.
    tokens_used:
        Total tokens used by the context after this write.
    budget:
        The context's hard token budget.
    signal:
        Short machine-readable reason code ("ok" | "rejected" | "truncated").
    """

    accepted: bool
    rejected: bool
    truncated: bool
    stored_tokens: int
    dropped_tokens: int
    tokens_used: int
    budget: int
    signal: str


class IsolatedContext:
    """A single subagent's private, budget-bounded context container.

    An instance holds only its own data. It deliberately has no reference to the
    manager, the parent context, or any sibling, so there is no accessor path by
    which one subagent could read another's private scratch or result.
    """

    __slots__ = (
        "_context_id",
        "_system_prompt",
        "_task",
        "_budget",
        "_token_counter",
        "_overflow_policy",
        "_scratch",
        "_result",
    )

    def __init__(
        self,
        *,
        context_id: str,
        system_prompt: str,
        task: str,
        budget: int,
        token_counter: TokenCounter,
        overflow_policy: OverflowPolicy,
    ) -> None:
        if budget <= 0:
            raise ContextBudgetError("budget must be a positive integer token count")
        # str() forces a value copy of the seed data; siblings/parent never share
        # the same mutable object.
        self._context_id = str(context_id)
        self._system_prompt = str(system_prompt or "")
        self._task = str(task or "")
        self._budget = int(budget)
        self._token_counter = token_counter
        self._overflow_policy = overflow_policy
        self._scratch: list[str] = []
        self._result: str | None = None

        seed_tokens = self._count(self._system_prompt) + self._count(self._task)
        if seed_tokens > self._budget:
            raise ContextBudgetError(
                f"seed (system prompt + task) needs {seed_tokens} tokens but budget is only {self._budget}"
            )

    # -- private helpers ---------------------------------------------------
    def _count(self, text: str) -> int:
        n = self._token_counter(text)
        if not isinstance(n, int) or n < 0:
            raise ValueError("token_counter must return a non-negative int")
        return n

    def _seed_tokens(self) -> int:
        return self._count(self._system_prompt) + self._count(self._task)

    def _scratch_tokens(self) -> int:
        return sum(self._count(chunk) for chunk in self._scratch)

    # -- read-only accessors (self-only) -----------------------------------
    @property
    def context_id(self) -> str:
        return self._context_id

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def task(self) -> str:
        return self._task

    @property
    def budget(self) -> int:
        return self._budget

    @property
    def overflow_policy(self) -> OverflowPolicy:
        return self._overflow_policy

    def tokens_used(self) -> int:
        """Total tokens consumed: seed (system prompt + task) + scratch."""
        return self._seed_tokens() + self._scratch_tokens()

    def tokens_remaining(self) -> int:
        return self._budget - self.tokens_used()

    def read_scratch(self) -> list[str]:
        """Return a *copy* of this context's own scratch chunks."""
        return list(self._scratch)

    def scratch_text(self) -> str:
        return "".join(self._scratch)

    # -- writes ------------------------------------------------------------
    def write_scratch(self, text: str) -> WriteResult:
        """Append text to this context's private scratch, enforcing the budget.

        Returns a :class:`WriteResult` describing exactly what happened. Under
        :attr:`OverflowPolicy.REJECT` an over-budget write stores nothing; under
        :attr:`OverflowPolicy.TRUNCATE` it stores the largest prefix that fits.
        """
        text = str(text or "")
        remaining = self.tokens_remaining()
        want = self._count(text)

        if want <= remaining:
            self._scratch.append(text)
            return WriteResult(
                accepted=True,
                rejected=False,
                truncated=False,
                stored_tokens=want,
                dropped_tokens=0,
                tokens_used=self.tokens_used(),
                budget=self._budget,
                signal="ok",
            )

        if self._overflow_policy is OverflowPolicy.REJECT:
            return WriteResult(
                accepted=False,
                rejected=True,
                truncated=False,
                stored_tokens=0,
                dropped_tokens=want,
                tokens_used=self.tokens_used(),
                budget=self._budget,
                signal="rejected",
            )

        # TRUNCATE: store the largest character prefix that fits the remaining
        # budget. Deterministic because the token counter is deterministic.
        prefix = self._largest_prefix_within(text, remaining)
        stored = self._count(prefix)
        if prefix:
            self._scratch.append(prefix)
        return WriteResult(
            accepted=bool(prefix),
            rejected=not prefix,
            truncated=True,
            stored_tokens=stored,
            dropped_tokens=want - stored,
            tokens_used=self.tokens_used(),
            budget=self._budget,
            signal="truncated",
        )

    def _largest_prefix_within(self, text: str, token_budget: int) -> str:
        """Longest character prefix of ``text`` whose token count <= budget.

        Uses binary search over character length, so it is O(log n) counter
        calls and fully deterministic for any monotonic-ish counter. Verified
        against the exact counter so the returned prefix never overshoots.
        """
        if token_budget <= 0:
            return ""
        if self._count(text) <= token_budget:
            return text
        lo, hi = 0, len(text)
        best = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._count(text[:mid]) <= token_budget:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return text[:best]

    # -- result (the only thing a parent collects) -------------------------
    def set_result(self, summary: str) -> None:
        """Record this subagent's final summary for the parent to collect."""
        self._result = str(summary or "")

    @property
    def result(self) -> str | None:
        return self._result

    def snapshot(self) -> dict[str, object]:
        """Debug view of THIS context only -- never exposes other contexts."""
        return {
            "context_id": self._context_id,
            "budget": self._budget,
            "tokens_used": self.tokens_used(),
            "tokens_remaining": self.tokens_remaining(),
            "overflow_policy": self._overflow_policy.value,
            "has_result": self._result is not None,
        }

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"IsolatedContext(id={self._context_id!r}, used={self.tokens_used()}/{self._budget})"


def create_subagent_context(
    parent: IsolatedContext | None,
    task: str,
    budget: int = DEFAULT_BUDGET_TOKENS,
    *,
    system_prompt: str | None = None,
    context_id: str | None = None,
    token_counter: TokenCounter | None = None,
    overflow_policy: OverflowPolicy = OverflowPolicy.REJECT,
) -> IsolatedContext:
    """Create a fresh :class:`IsolatedContext` for a spawned subagent.

    The child is seeded with ``system_prompt`` when given, otherwise it inherits
    a *copy* of the parent's system prompt (the shared instruction), never the
    parent's private scratch. The returned context holds no reference back to
    ``parent`` or to any sibling, so it cannot read their private data.
    """
    if system_prompt is None:
        system_prompt = parent.system_prompt if parent is not None else ""
    counter = token_counter or (parent._token_counter if parent is not None else default_token_counter)
    return IsolatedContext(
        context_id=context_id or uuid.uuid4().hex,
        system_prompt=system_prompt,
        task=task,
        budget=budget,
        token_counter=counter,
        overflow_policy=overflow_policy,
    )


class SubagentContextManager:
    """Hands out isolated child contexts and collects their results.

    The manager owns the parent's own context (kept private) and a registry of
    child contexts keyed by id. Children are never inserted into each other's
    registries and never receive a reference to the manager, so the only thing
    that crosses the isolation boundary is the summary a child chooses to
    publish via :meth:`IsolatedContext.set_result`.
    """

    def __init__(
        self,
        *,
        parent_context: IsolatedContext | None = None,
        default_budget: int = DEFAULT_BUDGET_TOKENS,
        token_counter: TokenCounter | None = None,
        overflow_policy: OverflowPolicy = OverflowPolicy.REJECT,
    ) -> None:
        if default_budget <= 0:
            raise ContextBudgetError("default_budget must be a positive integer")
        self._parent = parent_context
        self._default_budget = int(default_budget)
        self._token_counter = token_counter or default_token_counter
        self._overflow_policy = overflow_policy
        self._children: dict[str, IsolatedContext] = {}

    @property
    def default_budget(self) -> int:
        return self._default_budget

    def create_subagent_context(
        self,
        task: str,
        *,
        budget: int | None = None,
        system_prompt: str | None = None,
        subagent_id: str | None = None,
        overflow_policy: OverflowPolicy | None = None,
    ) -> IsolatedContext:
        """Spawn and register a new isolated child context."""
        cid = subagent_id or uuid.uuid4().hex
        if cid in self._children:
            raise ValueError(f"subagent context id already exists: {cid!r}")
        child = create_subagent_context(
            self._parent,
            task,
            budget if budget is not None else self._default_budget,
            system_prompt=system_prompt,
            context_id=cid,
            token_counter=self._token_counter,
            overflow_policy=overflow_policy or self._overflow_policy,
        )
        self._children[cid] = child
        return child

    def get_child(self, subagent_id: str) -> IsolatedContext:
        return self._children[subagent_id]

    def child_ids(self) -> list[str]:
        return list(self._children)

    def collect_results(self) -> dict[str, str | None]:
        """Return each child's published summary keyed by id.

        This is the ONLY channel by which context crosses the isolation
        boundary: a child's scratch is never returned here -- only the summary
        the child explicitly published via ``set_result``.
        """
        return {cid: child.result for cid, child in self._children.items()}
