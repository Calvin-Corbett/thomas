"""CAP-041: cheap-model periodic status summaries with change-only cadence.

Acceptance line: "Add low-cost periodic status summaries with change-only
cadence and per-summary cost."

A long-running (in-flight) run wants a cheap, glanceable status feed without
paying to re-summarize state that has not moved. :class:`StatusSummarizer`
provides exactly that:

* **Cheap model** -- the summary is produced by a configurable low-cost model
  profile id via an *injectable* adapter, so the model call is swappable and
  tests never touch a live model.
* **Periodic cadence** -- a summary is only considered at a configured interval,
  measured in steps *or* seconds (exactly one).
* **Change-only** -- when cadence fires but the caller-provided state digest is
  identical to the last emitted one, nothing materially changed, so NO model
  call is made and a :class:`SkippedSummary` (``changed=False``) is recorded
  instead. This is what keeps the feed low-cost.
* **Per-summary cost** -- each *emitted* summary carries its own prompt +
  completion token record and a cost estimate from a configurable per-1k rate.
  Costs also accumulate into a session running total.
* **Schema-validated payload** -- the summary object is validated through
  :func:`thomas.core.summary_channel.return_summary` (reused, not duplicated).

This module is core-clean: stdlib plus :mod:`thomas.core.summary_channel` and
:mod:`thomas.core.usage_telemetry` (both themselves core-clean).
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable

from thomas.core.summary_channel import return_summary
from thomas.core.usage_telemetry import UsageTelemetry

__all__ = [
    "DEFAULT_STATUS_SCHEMA",
    "SkippedSummary",
    "StatusSummary",
    "StatusSummarizer",
]

# Default status-summary schema for callers who define none. Kept tiny and
# strict (``additionalProperties`` false) so the cheap model returns a compact,
# glanceable object and nothing else.
DEFAULT_STATUS_SCHEMA: dict[str, Any] = {
    "title": "thomas.status_summary",
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "summary": {"type": "string"},
        "progress": {"type": "string"},
    },
    "required": ["summary"],
    "additionalProperties": False,
}

# Default char->token divisor, matching ``usage_telemetry`` / context estimators.
_CHARS_PER_TOKEN = 4


def _default_token_estimator(text: str) -> int:
    """Estimate a token count from ``text`` (chars / 4, floor)."""
    return len(text) // _CHARS_PER_TOKEN


def _context_text(context: str | Sequence[Mapping[str, Any]]) -> str:
    """Flatten a prompt string or OpenAI-style message list to plain text."""
    if isinstance(context, str):
        return context
    parts: list[str] = []
    for message in context:
        content = message.get("content", "")
        parts.append(content if isinstance(content, str) else json.dumps(content, default=str))
    return "\n".join(parts)


@dataclass(frozen=True)
class StatusSummary:
    """An emitted, schema-validated status summary with its own cost record.

    Attributes:
        text: the primary human-readable status line (the ``text_field`` of the
            validated object, or a JSON rendering when that field is absent).
        fields: the full validated summary object.
        digest: the state signature this summary was produced for.
        step: the cadence step it was emitted at (``None`` in seconds mode).
        model_profile: the low-cost model profile id used to produce it.
        prompt_tokens: estimated prompt tokens for this summary's model call(s).
        completion_tokens: estimated completion tokens across every model call
            (including any schema self-repair round-trips) for this summary.
        total_tokens: ``prompt_tokens + completion_tokens``.
        cost: estimated cost of this single summary at the configured per-1k rate.
        schema_id: id of the schema the payload was validated against.
        attempts: model calls made to obtain a valid payload (>=2 => repaired).
        changed: always ``True`` for an emitted summary.
    """

    text: str
    fields: dict[str, Any]
    digest: str
    step: int | None
    model_profile: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    schema_id: str
    attempts: int
    changed: bool = True


@dataclass(frozen=True)
class SkippedSummary:
    """A change-only skip marker: cadence fired but state did not change.

    No model call was made, so this marker carries zero cost. A caller/UI can
    render it in the feed to show that a checkpoint elapsed without change.
    """

    digest: str
    step: int | None
    reason: str = "unchanged"
    changed: bool = False
    cost: float = 0.0


@dataclass
class _CadenceState:
    anchor_step: int | None = None
    anchor_time: float | None = None
    last_digest: str | None = None
    history: list[StatusSummary | SkippedSummary] = field(default_factory=list)


class StatusSummarizer:
    """Emit low-cost, change-only periodic status summaries of an in-flight run.

    Args:
        adapter: injectable LLM adapter (see
            :data:`thomas.core.summary_channel.return_summary`) that performs the
            cheap model call. Injectable so tests need no live model.
        model_profile: the configurable low-cost model profile id. Recorded on
            each summary and in telemetry metadata for provenance.
        interval_steps: emit cadence measured in steps. Mutually exclusive with
            ``interval_seconds``; supply exactly one positive value.
        interval_seconds: emit cadence measured in wall-clock seconds.
        cost_per_1k: cost per 1000 tokens used to price each emitted summary.
        summary_schema: schema the payload is validated against (via
            ``summary_channel``); defaults to :data:`DEFAULT_STATUS_SCHEMA`.
        text_field: which validated field supplies :attr:`StatusSummary.text`.
        token_estimator: maps text -> token count; defaults to chars/4. Injectable
            so a caller can plug a real tokenizer.
        max_repair_attempts: schema self-repair round-trips allowed per summary.
        telemetry: an existing :class:`UsageTelemetry` to record into; a fresh
            one is created when omitted.
    """

    def __init__(
        self,
        adapter: Callable[[list[dict[str, Any]]], Any],
        *,
        model_profile: str,
        interval_steps: int | None = None,
        interval_seconds: float | None = None,
        cost_per_1k: float = 0.0,
        summary_schema: Mapping[str, Any] | None = None,
        text_field: str = "summary",
        token_estimator: Callable[[str], int] = _default_token_estimator,
        max_repair_attempts: int = 1,
        telemetry: UsageTelemetry | None = None,
    ) -> None:
        steps_set = interval_steps is not None
        seconds_set = interval_seconds is not None
        if steps_set == seconds_set:
            raise ValueError("supply exactly one of interval_steps or interval_seconds")
        if steps_set and (
            isinstance(interval_steps, bool) or not isinstance(interval_steps, int) or interval_steps <= 0
        ):
            raise ValueError(f"interval_steps must be a positive int, got {interval_steps!r}")
        if seconds_set and (isinstance(interval_seconds, bool) or interval_seconds <= 0):
            raise ValueError(f"interval_seconds must be a positive number, got {interval_seconds!r}")
        if cost_per_1k < 0:
            raise ValueError(f"cost_per_1k must be >= 0, got {cost_per_1k}")

        self._adapter = adapter
        self.model_profile = model_profile
        self._interval_steps = interval_steps
        self._interval_seconds = interval_seconds
        self._cost_per_1k = float(cost_per_1k)
        self._schema = DEFAULT_STATUS_SCHEMA if summary_schema is None else summary_schema
        self._text_field = text_field
        self._estimate = token_estimator
        self._max_repair_attempts = max_repair_attempts
        self.telemetry = telemetry if telemetry is not None else UsageTelemetry()
        self._state = _CadenceState()
        self.total_cost = 0.0

    # -- public feed ---------------------------------------------------------

    @property
    def history(self) -> list[StatusSummary | SkippedSummary]:
        """The ordered change-only feed of emitted summaries and skip markers."""
        return list(self._state.history)

    @property
    def summaries(self) -> list[StatusSummary]:
        """Only the emitted (changed) summaries, in order."""
        return [item for item in self._state.history if isinstance(item, StatusSummary)]

    @property
    def skipped(self) -> list[SkippedSummary]:
        """Only the change-only skip markers, in order."""
        return [item for item in self._state.history if isinstance(item, SkippedSummary)]

    @property
    def total_tokens(self) -> int:
        """Total prompt + completion tokens billed across the session."""
        return self.telemetry.grand_total()

    # -- cadence -------------------------------------------------------------

    def _cadence_due(self, step: int | None, now: float | None) -> bool:
        if self._interval_steps is not None:
            if step is None:
                raise ValueError("step is required in steps cadence mode")
            anchor = self._state.anchor_step
            return anchor is None or (step - anchor) >= self._interval_steps
        anchor_t = self._state.anchor_time
        return anchor_t is None or (now - anchor_t) >= float(self._interval_seconds)

    def _advance_cadence(self, step: int | None, now: float | None) -> None:
        if self._interval_steps is not None:
            self._state.anchor_step = step
        else:
            self._state.anchor_time = now

    # -- entry point ---------------------------------------------------------

    async def maybe_summarize(
        self,
        digest: str,
        context: str | Sequence[Mapping[str, Any]],
        *,
        step: int | None = None,
        now: float | None = None,
    ) -> StatusSummary | SkippedSummary | None:
        """Emit a status summary if cadence fires and state changed.

        Args:
            digest: a caller-provided state signature. Identical to the last
                emitted digest => nothing materially changed => skipped.
            context: the working context to summarize (prompt string or an
                OpenAI-style message list).
            step: current step count (required in steps cadence mode).
            now: current monotonic time (seconds mode; defaults to
                :func:`time.monotonic`).

        Returns:
            * ``None`` -- cadence not yet due (no checkpoint this call).
            * :class:`SkippedSummary` -- cadence due but digest unchanged; no
              model call was made and it carries zero cost.
            * :class:`StatusSummary` -- cadence due and state changed; a fresh,
              schema-validated, priced summary from the cheap model.
        """
        if now is None and self._interval_seconds is not None:
            now = time.monotonic()
        if not self._cadence_due(step, now):
            return None
        self._advance_cadence(step, now)

        if digest == self._state.last_digest:
            skipped = SkippedSummary(digest=digest, step=step)
            self._state.history.append(skipped)
            return skipped

        summary = await self._emit(digest, context, step)
        self._state.last_digest = digest
        self._state.history.append(summary)
        return summary

    async def _emit(
        self,
        digest: str,
        context: str | Sequence[Mapping[str, Any]],
        step: int | None,
    ) -> StatusSummary:
        result = await return_summary(
            self._adapter,
            context,
            self._schema,
            max_repair_attempts=self._max_repair_attempts,
        )
        fields = dict(result.summary)
        text_value = fields.get(self._text_field)
        text = text_value if isinstance(text_value, str) else json.dumps(fields, default=str)

        prompt_tokens = self._estimate(_context_text(context))
        completion_tokens = sum(self._estimate(entry.get("raw", "")) for entry in result.trace)
        total_tokens = prompt_tokens + completion_tokens
        cost = round((total_tokens / 1000.0) * self._cost_per_1k, 6)

        meta = {"model_profile": self.model_profile, "cost": cost, "step": step}
        self.telemetry.record_prompt(prompt_tokens, meta)
        self.telemetry.record_completion(completion_tokens, meta)
        self.total_cost = round(self.total_cost + cost, 6)

        return StatusSummary(
            text=text,
            fields=fields,
            digest=digest,
            step=step,
            model_profile=self.model_profile,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
            schema_id=result.schema_id,
            attempts=result.attempts,
        )
