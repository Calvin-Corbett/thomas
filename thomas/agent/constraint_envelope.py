"""Constraint envelopes for the agent loop (CAP-048).

A :class:`ConstraintEnvelope` wraps a running task with a *token ceiling* and a
*checkpoint interval*. As the loop reports cumulative token usage it calls
:meth:`ConstraintEnvelope.observe`, which returns a fully deterministic
:class:`EnvelopeDecision`:

* the same sequence of ``observe`` inputs always yields the same decisions;
* a checkpoint-summary request is emitted every ``checkpoint_every_tokens``
  tokens of cumulative spend (a non-stopping signal);
* crossing ``token_ceiling`` yields a deterministic terminal
  :class:`StopReason` of ``TOKEN_CEILING_REACHED``.

The envelope carries no wall-clock or randomness, so :meth:`to_state` /
:meth:`from_state` let an in-flight envelope survive a process restart and
resume with identical behavior.

This module lives in ``thomas.agent`` and imports only from ``thomas.core``,
respecting the dependency hierarchy in ``thomas/agent/_architecture`` (agent may
import core).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from thomas.core.events import AgentEvent, EventType

__all__ = [
    "StopReason",
    "CheckpointSummary",
    "EnvelopeDecision",
    "ConstraintEnvelope",
    "envelope_events",
]

# State schema version so ``from_state`` can reject payloads it does not
# understand rather than silently resuming with wrong semantics.
_STATE_VERSION = 1


class StopReason(Enum):
    """Deterministic, fixed outcome vocabulary for a constraint envelope.

    ``CONTINUE`` and ``CHECKPOINT_DUE`` are *non-stopping* signals: the loop
    keeps running. ``TOKEN_CEILING_REACHED`` and ``COMPLETED`` are terminal.
    """

    CONTINUE = "continue"
    CHECKPOINT_DUE = "checkpoint_due"
    TOKEN_CEILING_REACHED = "token_ceiling_reached"
    COMPLETED = "completed"

    @property
    def is_terminal(self) -> bool:
        return self in (StopReason.TOKEN_CEILING_REACHED, StopReason.COMPLETED)


@dataclass(frozen=True)
class CheckpointSummary:
    """A request for a checkpoint summary at a token milestone."""

    checkpoint_index: int
    tokens_used: int
    token_ceiling: int | None
    checkpoint_every_tokens: int
    fraction_used: float | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_index": int(self.checkpoint_index),
            "tokens_used": int(self.tokens_used),
            "token_ceiling": (None if self.token_ceiling is None else int(self.token_ceiling)),
            "checkpoint_every_tokens": int(self.checkpoint_every_tokens),
            "fraction_used": (None if self.fraction_used is None else float(self.fraction_used)),
            "message": str(self.message),
            "summary_requested": True,
        }


@dataclass(frozen=True)
class EnvelopeDecision:
    """The deterministic outcome of a single :meth:`ConstraintEnvelope.observe`."""

    stop_reason: StopReason
    tokens_used: int
    token_ceiling: int | None
    checkpoint_summary: CheckpointSummary | None = None
    stop_message: str = ""

    @property
    def should_stop(self) -> bool:
        return self.stop_reason.is_terminal


def _coerce_positive_int(value: Any) -> int | None:
    """Return a strictly-positive int, or ``None`` for absent/invalid input."""

    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class ConstraintEnvelope:
    """Token ceiling + checkpoint summaries with deterministic stop reasons.

    Parameters
    ----------
    token_ceiling:
        Cumulative token budget for the run. ``None`` (or a non-positive value)
        means *no ceiling* — the envelope never emits a terminal stop reason.
    checkpoint_every_tokens:
        Emit a checkpoint-summary request every N cumulative tokens. ``None``
        (or non-positive) disables checkpoints.
    """

    def __init__(
        self,
        token_ceiling: int | None = None,
        checkpoint_every_tokens: int | None = None,
    ) -> None:
        self.token_ceiling = _coerce_positive_int(token_ceiling)
        self.checkpoint_every_tokens = _coerce_positive_int(checkpoint_every_tokens)
        self._tokens_used: int = 0
        self._checkpoints_emitted: int = 0
        self._stopped: bool = False

    # ── Introspection ────────────────────────────────────────────────
    @property
    def tokens_used(self) -> int:
        return self._tokens_used

    @property
    def checkpoints_emitted(self) -> int:
        return self._checkpoints_emitted

    @property
    def active(self) -> bool:
        """True when this envelope can ever alter loop behavior."""

        return self.token_ceiling is not None or self.checkpoint_every_tokens is not None

    def _fraction_used(self) -> float | None:
        if not self.token_ceiling:
            return None
        return round(self._tokens_used / self.token_ceiling, 6)

    # ── Core decision ────────────────────────────────────────────────
    def observe(self, tokens_used: int) -> EnvelopeDecision:
        """Fold a cumulative token count into the envelope and decide.

        ``tokens_used`` is the *cumulative* tokens spent so far. The count is
        clamped to be monotonic so a provider that briefly under-reports cannot
        rewind an already-emitted checkpoint. Given identical input sequences
        the returned decisions are identical (no clock, no randomness).
        """

        try:
            incoming = int(tokens_used)
        except (TypeError, ValueError):
            incoming = self._tokens_used
        if incoming < 0:
            incoming = 0
        # Monotonic: cumulative spend never decreases.
        self._tokens_used = max(self._tokens_used, incoming)

        checkpoint = self._advance_checkpoints()

        if self.token_ceiling is not None and self._tokens_used >= self.token_ceiling:
            self._stopped = True
            message = (
                f"Token ceiling reached: {self._tokens_used} of {self.token_ceiling} "
                "tokens used; stopping the run deterministically."
            )
            return EnvelopeDecision(
                stop_reason=StopReason.TOKEN_CEILING_REACHED,
                tokens_used=self._tokens_used,
                token_ceiling=self.token_ceiling,
                checkpoint_summary=checkpoint,
                stop_message=message,
            )

        reason = StopReason.CHECKPOINT_DUE if checkpoint is not None else StopReason.CONTINUE
        return EnvelopeDecision(
            stop_reason=reason,
            tokens_used=self._tokens_used,
            token_ceiling=self.token_ceiling,
            checkpoint_summary=checkpoint,
        )

    def complete(self) -> EnvelopeDecision:
        """Signal caller-driven completion with a deterministic terminal reason."""

        self._stopped = True
        return EnvelopeDecision(
            stop_reason=StopReason.COMPLETED,
            tokens_used=self._tokens_used,
            token_ceiling=self.token_ceiling,
            stop_message="Run completed within the constraint envelope.",
        )

    def _advance_checkpoints(self) -> CheckpointSummary | None:
        interval = self.checkpoint_every_tokens
        if not interval:
            return None
        expected = self._tokens_used // interval
        if expected <= self._checkpoints_emitted:
            return None
        # Advance straight to the latest milestone even if the count jumped
        # several intervals in a single observation; report the newest index.
        self._checkpoints_emitted = int(expected)
        index = int(expected)
        message = (
            f"Checkpoint {index}: {self._tokens_used} tokens used"
            + (f" of {self.token_ceiling}" if self.token_ceiling else "")
            + " — summarize progress so far and confirm remaining work."
        )
        return CheckpointSummary(
            checkpoint_index=index,
            tokens_used=self._tokens_used,
            token_ceiling=self.token_ceiling,
            checkpoint_every_tokens=int(interval),
            fraction_used=self._fraction_used(),
            message=message,
        )

    # ── Persistence ──────────────────────────────────────────────────
    def to_state(self) -> dict[str, Any]:
        """Serialize the envelope so it can survive a process restart."""

        return {
            "version": _STATE_VERSION,
            "token_ceiling": self.token_ceiling,
            "checkpoint_every_tokens": self.checkpoint_every_tokens,
            "tokens_used": self._tokens_used,
            "checkpoints_emitted": self._checkpoints_emitted,
            "stopped": self._stopped,
        }

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> ConstraintEnvelope:
        """Rebuild an envelope from :meth:`to_state` output.

        Unknown or missing versions raise ``ValueError`` rather than resuming
        with mismatched semantics.
        """

        version = state.get("version")
        if version != _STATE_VERSION:
            raise ValueError(f"Unsupported constraint envelope state version: {version!r}")
        envelope = cls(
            token_ceiling=state.get("token_ceiling"),
            checkpoint_every_tokens=state.get("checkpoint_every_tokens"),
        )
        restored = _coerce_positive_int(state.get("tokens_used")) or 0
        envelope._tokens_used = max(0, int(restored))
        envelope._checkpoints_emitted = max(0, int(state.get("checkpoints_emitted") or 0))
        envelope._stopped = bool(state.get("stopped"))
        return envelope

    # ── Construction from environment ────────────────────────────────
    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ConstraintEnvelope:
        """Build an envelope from ``THOMAS_TOKEN_CEILING`` / checkpoint env vars.

        With neither variable set the envelope is inert (no ceiling, no
        checkpoints), so default loop behavior is unchanged.
        """

        source: Mapping[str, str] = env if env is not None else os.environ
        return cls(
            token_ceiling=_coerce_positive_int(source.get("THOMAS_TOKEN_CEILING")),
            checkpoint_every_tokens=_coerce_positive_int(source.get("THOMAS_TOKEN_CHECKPOINT_EVERY")),
        )


def envelope_events(decision: EnvelopeDecision, iteration: int) -> list[AgentEvent]:
    """Translate an :class:`EnvelopeDecision` into loop events to yield.

    Emits a STATUS event for a checkpoint-summary request and a terminal event
    (carrying the deterministic ``stop_reason``) when the ceiling is reached.
    Returns an empty list when the decision is a plain ``CONTINUE``.
    """

    events: list[AgentEvent] = []
    if decision.checkpoint_summary is not None:
        events.append(
            AgentEvent(
                type=EventType.STATUS,
                data={
                    "message": decision.checkpoint_summary.message,
                    "constraint_checkpoint": decision.checkpoint_summary.to_dict(),
                },
                iteration=iteration,
            )
        )
    if decision.stop_reason is StopReason.TOKEN_CEILING_REACHED:
        events.append(
            AgentEvent(
                type=EventType.AGENT_ERROR,
                data={
                    "error": decision.stop_message,
                    "stop_reason": decision.stop_reason.value,
                    "tokens_used": int(decision.tokens_used),
                    "token_ceiling": (None if decision.token_ceiling is None else int(decision.token_ceiling)),
                },
                iteration=iteration,
            )
        )
    return events
