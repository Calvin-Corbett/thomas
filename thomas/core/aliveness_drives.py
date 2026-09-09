"""Homeostatic drives — why Thomas acts, as distinct from when.

Design: `plans/thomas/ALIVENESS_DESIGN_2026-08-27.md` §4.

A heartbeat answers *when*. These answer *why*. Each drive is a level with a
setpoint: something raises it, something discharges it, and it is the error
between the two — not the clock — that makes the loop do anything. That is the
whole point of the design, and it is why the tick rate is allowed to be boring.

Three drives:

- **Freshness** — does my picture of your world still match your world? Rises
  with elapsed time and with change I have not looked at. Discharged by looking.
  Silent by construction, and the one carrying most of the value.
- **Debt** — what did I say I would do that isn't done? Rises with open goals
  and their age. Discharged by finishing.
- **Contact** — how long has it been? Rises with silence. Discharged by
  speaking, and subject to one hard rule: contact alone is never sufficient to
  speak. It may only lower the bar for a message that already has content.

Everything here is pure arithmetic over injected state, so it is testable
without a clock, a repo, or a model.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Time for Freshness to travel from empty to full with nothing observed.
FRESHNESS_HORIZON_S: float = 30 * 60.0
# Each unobserved change adds this much Freshness on top of elapsed time.
FRESHNESS_PER_CHANGE: float = 0.15
# Open-goal count at which Debt is considered full.
DEBT_FULL_AT: int = 8
# Silence required for Contact to reach full.
CONTACT_HORIZON_S: float = 8 * 60 * 60.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass
class Drive:
    """One level with a setpoint.

    ``level`` is normalised 0..1. ``setpoint`` is the level at which the drive
    is considered to be asking for something.
    """

    name: str
    setpoint: float = 0.7
    level: float = 0.0
    last_discharged_at: float | None = None

    @property
    def crossed(self) -> bool:
        return self.level >= self.setpoint

    def add(self, amount: float) -> None:
        self.level = _clamp(self.level + amount)

    def set_level(self, value: float) -> None:
        self.level = _clamp(value)

    def discharge(self, now: float | None = None) -> None:
        """Satisfy the drive: level to zero, discharge time recorded."""
        self.level = 0.0
        self.last_discharged_at = time.time() if now is None else now

    def to_dict(self) -> dict[str, float | str | bool | None]:
        return {
            "name": self.name,
            "level": round(self.level, 4),
            "setpoint": self.setpoint,
            "crossed": self.crossed,
            "last_discharged_at": self.last_discharged_at,
        }


@dataclass
class Drives:
    """The three drives, updated together from one sweep of the world."""

    freshness: Drive = field(default_factory=lambda: Drive("freshness", setpoint=0.6))
    debt: Drive = field(default_factory=lambda: Drive("debt", setpoint=0.5))
    contact: Drive = field(default_factory=lambda: Drive("contact", setpoint=0.9))

    def all(self) -> list[Drive]:
        return [self.freshness, self.debt, self.contact]

    # -- updates ----------------------------------------------------------

    def observe_world(self, change_count: int, now: float | None = None) -> None:
        """Raise Freshness for change seen but not yet acted on.

        Looking is what discharges Freshness, so a sweep that found nothing new
        leaves it to keep drifting up on elapsed time alone; a sweep that found
        change raises it further, because there is now something in the world
        the rest of the loop has not caught up with.
        """
        moment = time.time() if now is None else now
        last = self.freshness.last_discharged_at
        if last is None:
            self.freshness.last_discharged_at = moment
            elapsed = 0.0
        else:
            elapsed = max(0.0, moment - last)
        drift = elapsed / FRESHNESS_HORIZON_S if FRESHNESS_HORIZON_S > 0 else 0.0
        self.freshness.set_level(drift + FRESHNESS_PER_CHANGE * max(0, change_count))

    def observe_debt(self, open_goal_count: int) -> None:
        """Debt tracks unfinished work. Finishing is what discharges it."""
        if DEBT_FULL_AT <= 0:
            self.debt.set_level(0.0)
            return
        self.debt.set_level(max(0, open_goal_count) / float(DEBT_FULL_AT))

    def observe_silence(self, idle_seconds: float) -> None:
        """Contact rises with silence, and only ever supports — never causes."""
        if CONTACT_HORIZON_S <= 0:
            self.contact.set_level(0.0)
            return
        self.contact.set_level(max(0.0, idle_seconds) / CONTACT_HORIZON_S)

    # -- queries ----------------------------------------------------------

    def crossed(self) -> list[Drive]:
        return [d for d in self.all() if d.crossed]

    def wants_action(self) -> bool:
        """True when a drive other than Contact is asking for something.

        Contact is excluded deliberately. A loop that acts because it has been
        quiet is a loop that invents work to feel useful.
        """
        return self.freshness.crossed or self.debt.crossed

    def speak_support(self) -> bool:
        """Whether Contact may lower the bar for a message that has content.

        Never a reason to speak on its own — design §4. The caller must already
        have something worth saying before consulting this.
        """
        return self.contact.crossed

    def to_dict(self) -> dict[str, object]:
        return {d.name: d.to_dict() for d in self.all()}
