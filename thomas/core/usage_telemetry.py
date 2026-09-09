"""Context / token usage telemetry (CAP-014).

A single, core-clean surface that breaks a turn's token usage into five
non-overlapping categories -- ``prompt``, ``completion``, ``tool``,
``compaction`` and ``retrieval`` -- and can prove that the sum of those
categories reconciles (within a tolerance) with an independently measured
grand total.

Design notes
------------
* Stdlib only. This module lives at the bottom of the dependency tree
  (``thomas/core``) and must not import from ``agent``/``server``/``tools``.
* Thread-safe: concurrent tool calls record into the same accumulator, so
  every mutating and reading operation is guarded by a single lock.
* The accumulator itself is source-agnostic. :meth:`UsageTelemetry.from_token_report`
  adapts the agent loop's existing ``token_report`` dict (produced by
  ``thomas.agent.loop_streaming.build_token_report``) into the five
  categories without this module having to import the agent package.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "CATEGORIES",
    "CategoryUsage",
    "ReconciliationResult",
    "UsageTelemetry",
]

# The five usage categories the acceptance line requires us to expose.
CATEGORIES: tuple[str, ...] = (
    "prompt",
    "completion",
    "tool",
    "compaction",
    "retrieval",
)

# Default reconciliation tolerance: the summed categories must land within
# this percentage of an independently measured total.
_DEFAULT_TOLERANCE_PCT = 5.0

# Character-to-token divisor, matching ``context_compaction.estimate_tokens``.
# Kept local so this module carries no cross-package import.
_CHARS_PER_TOKEN = 4


def _coerce_tokens(value: Any) -> int:
    """Coerce ``value`` to a non-negative int token count."""
    try:
        tokens = int(value)
    except (TypeError, ValueError):
        return 0
    return tokens if tokens > 0 else 0


@dataclass(frozen=True)
class CategoryUsage:
    """Immutable per-category snapshot."""

    category: str
    tokens: int
    events: int

    def to_dict(self) -> dict[str, int]:
        return {"tokens": self.tokens, "events": self.events}


@dataclass(frozen=True)
class ReconciliationResult:
    """Outcome of comparing summed categories with an independent total."""

    ok: bool
    grand_total: int
    independent_total: int
    delta: int
    delta_pct: float
    tolerance_pct: float

    def __bool__(self) -> bool:
        return self.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "grand_total": self.grand_total,
            "independent_total": self.independent_total,
            "delta": self.delta,
            "delta_pct": self.delta_pct,
            "tolerance_pct": self.tolerance_pct,
        }


class UsageTelemetry:
    """Thread-safe accumulator of categorized token usage.

    Example
    -------
    >>> tel = UsageTelemetry()
    >>> tel.record_prompt(1000)
    >>> tel.record_completion(250)
    >>> tel.reconcile(1250).ok
    True
    """

    def __init__(self, *, tolerance_pct: float = _DEFAULT_TOLERANCE_PCT) -> None:
        try:
            tol = float(tolerance_pct)
        except (TypeError, ValueError):
            tol = _DEFAULT_TOLERANCE_PCT
        self._tolerance_pct = tol if tol >= 0.0 else _DEFAULT_TOLERANCE_PCT
        self._lock = threading.Lock()
        self._tokens: dict[str, int] = {name: 0 for name in CATEGORIES}
        self._events: dict[str, int] = {name: 0 for name in CATEGORIES}
        self._metadata: dict[str, list[dict[str, Any]]] = {name: [] for name in CATEGORIES}

    # -- recording -----------------------------------------------------------

    def record(
        self,
        category: str,
        tokens: Any,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Record ``tokens`` against ``category`` with optional ``metadata``.

        Unknown categories raise ``ValueError`` so miscategorized usage cannot
        silently corrupt the reconciliation.
        """
        if category not in self._tokens:
            raise ValueError(f"unknown usage category: {category!r} (expected one of {CATEGORIES})")
        amount = _coerce_tokens(tokens)
        entry = dict(metadata) if metadata else None
        with self._lock:
            self._tokens[category] += amount
            self._events[category] += 1
            if entry is not None:
                self._metadata[category].append(entry)

    def record_prompt(self, tokens: Any, metadata: Mapping[str, Any] | None = None) -> None:
        self.record("prompt", tokens, metadata)

    def record_completion(self, tokens: Any, metadata: Mapping[str, Any] | None = None) -> None:
        self.record("completion", tokens, metadata)

    def record_tool(self, tokens: Any, metadata: Mapping[str, Any] | None = None) -> None:
        self.record("tool", tokens, metadata)

    def record_compaction(self, tokens: Any, metadata: Mapping[str, Any] | None = None) -> None:
        self.record("compaction", tokens, metadata)

    def record_retrieval(self, tokens: Any, metadata: Mapping[str, Any] | None = None) -> None:
        self.record("retrieval", tokens, metadata)

    # -- reporting -----------------------------------------------------------

    def subtotals(self) -> dict[str, int]:
        """Return a per-category token subtotal snapshot."""
        with self._lock:
            return dict(self._tokens)

    def grand_total(self) -> int:
        """Return the sum of every category's tokens."""
        with self._lock:
            return sum(self._tokens.values())

    def report(self) -> dict[str, Any]:
        """Return per-category subtotals plus the grand total.

        The returned structure is a plain, JSON-serializable dict so callers in
        the agent loop / server can emit it directly.
        """
        with self._lock:
            categories = {
                name: {
                    "tokens": self._tokens[name],
                    "events": self._events[name],
                    "metadata": [dict(m) for m in self._metadata[name]],
                }
                for name in CATEGORIES
            }
            subtotals = dict(self._tokens)
            total = sum(self._tokens.values())
        return {
            "categories": categories,
            "subtotals": subtotals,
            "grand_total": total,
            "tolerance_pct": self._tolerance_pct,
        }

    def category_usage(self, category: str) -> CategoryUsage:
        """Return an immutable snapshot for a single category."""
        if category not in self._tokens:
            raise ValueError(f"unknown usage category: {category!r}")
        with self._lock:
            return CategoryUsage(
                category=category,
                tokens=self._tokens[category],
                events=self._events[category],
            )

    # -- reconciliation ------------------------------------------------------

    def reconcile(
        self,
        independent_total: Any,
        *,
        tolerance_pct: float | None = None,
    ) -> ReconciliationResult:
        """Compare summed categories against an independently measured total.

        ``ok`` is ``True`` when the categories sum to within ``tolerance_pct``
        (default 5%) of ``independent_total``. ``delta_pct`` is measured
        relative to the independent reference so a caller can see how far off
        the categorized accounting is.
        """
        tol = self._tolerance_pct if tolerance_pct is None else float(tolerance_pct)
        reference = _coerce_tokens(independent_total)
        total = self.grand_total()
        delta = total - reference
        denom = reference if reference > 0 else 1
        delta_pct = round(abs(delta) / denom * 100.0, 4)
        return ReconciliationResult(
            ok=delta_pct <= tol,
            grand_total=total,
            independent_total=reference,
            delta=delta,
            delta_pct=delta_pct,
            tolerance_pct=tol,
        )

    # -- adapters ------------------------------------------------------------

    @classmethod
    def from_token_report(
        cls,
        report: Mapping[str, Any] | None,
        *,
        tolerance_pct: float = _DEFAULT_TOLERANCE_PCT,
    ) -> UsageTelemetry:
        """Build a telemetry accumulator from the agent loop's ``token_report``.

        Maps the existing report shape (see
        ``thomas.agent.loop_streaming.build_token_report``) into the five
        categories as a *partition* of the billed total so the result
        reconciles exactly against ``total_tokens``:

        * ``retrieval`` <- ``memory_context_tokens`` (bounded to the prompt).
        * ``tool``      <- ``tool_output_chars_kept`` / 4 (bounded so
          ``retrieval + tool`` never exceeds the prompt token count).
        * ``prompt``    <- ``prompt_tokens`` minus the retrieval and tool
          portions that already live inside it (the residual base prompt),
          avoiding double counting.
        * ``completion``<- ``completion_tokens``.
        * ``compaction``<- tokens attributable to a compaction pass if the
          report carries a ``compaction`` section (``tokens`` / ``tokens_spent``
          / ``tokens_saved``); ``0`` for a plain turn report.

        With ``compaction == 0`` the summed categories equal
        ``prompt_tokens + completion_tokens`` and therefore reconcile with the
        report's ``total_tokens``.
        """
        src = dict(report or {})
        tel = cls(tolerance_pct=tolerance_pct)

        prompt_tokens = _coerce_tokens(src.get("prompt_tokens"))
        completion_tokens = _coerce_tokens(src.get("completion_tokens"))
        retrieval_tokens = min(_coerce_tokens(src.get("memory_context_tokens")), prompt_tokens)

        tool_chars_kept = _coerce_tokens(src.get("tool_output_chars_kept"))
        tool_tokens = tool_chars_kept // _CHARS_PER_TOKEN
        # Retrieval + tool are subsets of the prompt; never let them exceed it.
        tool_tokens = min(tool_tokens, max(0, prompt_tokens - retrieval_tokens))

        base_prompt_tokens = max(0, prompt_tokens - retrieval_tokens - tool_tokens)
        compaction_tokens = _compaction_tokens(src.get("compaction"))

        tel.record_prompt(
            base_prompt_tokens,
            {"source": "token_report", "prompt_chars": _coerce_tokens(src.get("prompt_chars"))},
        )
        tel.record_completion(completion_tokens, {"source": "token_report"})
        tel.record_tool(
            tool_tokens,
            {"source": "token_report", "tool_output_chars_kept": tool_chars_kept},
        )
        tel.record_retrieval(retrieval_tokens, {"source": "token_report"})
        if compaction_tokens > 0:
            tel.record_compaction(compaction_tokens, {"source": "token_report"})
        return tel


def _compaction_tokens(section: Any) -> int:
    """Extract a compaction token count from an optional report section."""
    if not isinstance(section, Mapping):
        return 0
    for key in ("tokens", "tokens_spent", "compaction_tokens", "tokens_saved"):
        if key in section:
            return _coerce_tokens(section.get(key))
    return 0
