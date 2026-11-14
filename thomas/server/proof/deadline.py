"""One clock for a whole proof, so no single step can spend more than the proof has left.

Each step used to carry a timeout of its own and nothing added them up: 900 s for each of up to 5 shards on
each copy, 180 s for each of up to 80 re-runs, 300 s for each of 4 ruff calls. That is about 24,600 s for
one check. The real check measured on 2026-09-25 took 1,321 s. A :class:`Deadline` is made once per proof,
and every step asks it how long it may take (:meth:`Deadline.cap`). Once the deadline has passed, nothing
more starts and the caller says the proof ran out of time. A proof that ran out of time never counts as
passed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# What a step is given once the deadline has passed. A subprocess with a zero timeout is not started at all.
_NOTHING_LEFT_S = 0.0


@dataclass
class Deadline:
    """When a proof must be done by, on the monotonic clock. ``seconds`` is its whole allowance."""

    seconds: float
    started: float = field(default_factory=time.monotonic)

    def remaining(self) -> float:
        return max(_NOTHING_LEFT_S, self.started + self.seconds - time.monotonic())

    @property
    def passed(self) -> bool:
        return self.remaining() <= _NOTHING_LEFT_S

    def cap(self, step_s: float) -> float:
        """How long one step may take: its own limit, or what is left of the proof's, whichever is shorter."""
        return min(float(step_s), self.remaining())

    def words(self) -> str:
        return f"it ran out of its {self.seconds / 60:g}-minute limit before it finished"


def cap(deadline: Deadline | None, step_s: float) -> float:
    """``deadline.cap(step_s)``, or *step_s* itself when a caller runs a step with no overall deadline."""
    return float(step_s) if deadline is None else deadline.cap(step_s)


def passed(deadline: Deadline | None) -> bool:
    return deadline is not None and deadline.passed


__all__ = ["Deadline", "cap", "passed"]
