"""The speak gate — the hard part is not acting, it is shutting up.

Design: `plans/thomas/ALIVENESS_DESIGN_2026-08-27.md` §5 and §6.

Acting unprompted is easy and should be free, constant and silent. Speaking
unprompted is the entire product risk. This module is the only place a message
can get out, and it is built so that the default answer is no.

Four things decide, in order:

1. **Permission** (:mod:`thomas.core.aliveness_permissions`). No grant, no
   message. This is the whole design: silent about everything by default.
2. **The drives.** They set how loudly a granted topic asks — this is where
   Freshness and Debt stop being decoration and start deciding something.
   Contact may only *raise* an ask that already has content behind it; a message
   whose sole justification is "it has been a while" is what makes a product
   feel needy, so Contact can never originate one.
3. **Hard mutes.** Never mid-conversation, never twice about the same thing,
   never to report that nothing happened. These override permission and budget
   both; a level-5 interrupt is the single exception to the first.
4. **The budget**, and only for pushes. A brief entry is *pull* — you open it
   when you choose, it costs no attention, so it spends nothing. Interrupts are
   *push* and they spend. The budget is closed-loop: a message you act on is
   refunded, one you ignore drains extra, and an empty balance mutes pushes
   until it recovers.

The budget is a backstop that should almost never bind. When it does bind, that
is the signal to prune grants, and it says so rather than dropping the message
on the floor quietly.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field

from thomas.core.aliveness_drives import Drives
from thomas.core.aliveness_permissions import (
    BRIEF_ALWAYS,
    BRIEF_IF_ROOM,
    INTERRUPT,
    NOTIFY,
    SILENT,
    PermissionStore,
    clamp_level,
    level_name,
)

log = logging.getLogger(__name__)

CHANNEL_HELD = "held"
CHANNEL_BRIEF = "brief"
CHANNEL_PUSH = "push"

# Design §7: the attention ceiling is 3-5 notifications a day across everything
# competing for it, and 1 is the sane default. These are pushes only; brief
# entries are unlimited because they cost nothing.
DEFAULT_DAILY_PUSHES: float = 1.0
MAX_DAILY_PUSHES: float = 3.0
# Being told to stop is the most expensive outcome there is, so it does not just
# empty the balance — it puts it in debt, and the daily top-up has to climb back
# out. That debt *is* the auto-mute period the design asks for.
MIN_BALANCE: float = -6.0
STOPPED_PENALTY: float = -2.0

# A user who typed this recently is mid-something. Only a level-5 interrupt may
# cross that line.
ACTIVE_WITHIN_S: float = 5 * 60.0

# The same thing, said twice, is the fastest way to lose the channel.
DEDUPE_WINDOW_S: float = 6 * 60 * 60.0


@dataclass
class GateDecision:
    """What the gate decided, and why. The reason is for the log, not for show."""

    deliver: bool
    channel: str
    level: int
    reason: str
    asked_level: int = SILENT
    ceiling: int = SILENT

    def to_dict(self) -> dict[str, object]:
        return {
            "deliver": self.deliver,
            "channel": self.channel,
            "level": self.level,
            "level_name": level_name(self.level),
            "reason": self.reason,
            "asked_level": self.asked_level,
            "ceiling": self.ceiling,
        }


@dataclass
class PushBudget:
    """Closed-loop daily allowance for interrupts.

    Acting on a message refunds it — a message that worked should not have cost
    anything. Ignoring one drains extra, so a run of ignored pushes shuts the
    channel before you have to.
    """

    daily: float = DEFAULT_DAILY_PUSHES
    balance: float = field(default=DEFAULT_DAILY_PUSHES)
    day: str = ""

    def _roll(self, now: float) -> None:
        """Top up by the daily allowance — never reset to it.

        Resetting would erase the closed loop: a balance drained by a run of
        ignored pushes, or put in debt by being told to stop, would come back
        full the next morning and the feedback would mean nothing.
        """
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if self.day == today:
            return
        if not self.day:
            self.day = today
            return
        self.day = today
        self.balance = min(MAX_DAILY_PUSHES, self.balance + self.daily)

    def can_spend(self, now: float | None = None) -> bool:
        self._roll(time.time() if now is None else now)
        return self.balance >= 1.0

    def spend(self, now: float | None = None) -> None:
        self._roll(time.time() if now is None else now)
        self.balance = max(MIN_BALANCE, self.balance - 1.0)

    def record_outcome(self, outcome: str) -> None:
        normalized = str(outcome or "").strip().lower()
        if normalized in {"acted", "replied"}:
            self.balance = min(MAX_DAILY_PUSHES, self.balance + 1.0)
        elif normalized == "ignored":
            self.balance = max(MIN_BALANCE, self.balance - 0.5)
        elif normalized == "stopped":
            self.balance = STOPPED_PENALTY

    def to_dict(self) -> dict[str, object]:
        return {"daily": self.daily, "balance": round(self.balance, 2), "day": self.day}


class SpeakGate:
    """The only path from a candidate message to a person."""

    def __init__(
        self,
        permissions: PermissionStore | None = None,
        budget: PushBudget | None = None,
    ) -> None:
        self.permissions = permissions or PermissionStore()
        self.budget = budget or PushBudget()
        self._recent: dict[str, tuple[str, float]] = {}

    # -- the drives decide how loudly a granted topic asks -----------------

    @staticmethod
    def asked_level(drives: Drives, ceiling: int) -> int:
        """How loudly to use a ceiling that has already been granted.

        The ceiling is the standing instruction — you said "notify me about CI",
        so a CI change asks to notify. The drives' job is to **hold it back**,
        not to build it up: when nothing is pressing, a granted topic settles for
        the quieter end of its ceiling and waits for the brief.

        This direction matters. Asking upward from the floor made every ceiling
        above "always in the brief" unreachable, because nothing the drives can
        do ever reached that high — a NOTIFY grant produced brief entries
        forever, and the escalation levels were decoration.

        Contact still supports and never causes. It cannot lift anything above
        its ceiling, and where nothing was granted there is nothing to lift; all
        it does is spare a message the calm-day downgrade.
        """
        ceiling = clamp_level(ceiling)
        if ceiling <= SILENT:
            return SILENT
        if drives.wants_action() or drives.speak_support():
            return ceiling
        return max(BRIEF_IF_ROOM, ceiling - 1)

    # -- hard mutes --------------------------------------------------------

    def _is_duplicate(self, topic: str, text: str, now: float) -> bool:
        digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
        previous = self._recent.get(topic)
        if previous is not None:
            last_digest, last_at = previous
            if last_digest == digest and (now - last_at) < DEDUPE_WINDOW_S:
                return True
        self._recent[topic] = (digest, now)
        return False

    # -- the decision ------------------------------------------------------

    def decide(
        self,
        topic: str,
        text: str,
        drives: Drives,
        evidence: list[str] | None = None,
        idle_seconds: float = 0.0,
        now: float | None = None,
    ) -> GateDecision:
        moment = time.time() if now is None else now
        ceiling = self.permissions.level_for(topic)
        asked = self.asked_level(drives, ceiling)

        if not (evidence or text.strip()):
            # Never to report that nothing happened.
            return GateDecision(False, CHANNEL_HELD, SILENT, "nothing to say", asked, ceiling)

        if ceiling <= SILENT:
            return GateDecision(False, CHANNEL_HELD, SILENT, "no permission for this topic", asked, ceiling)

        level = clamp_level(min(asked, ceiling))
        if level <= SILENT:
            return GateDecision(False, CHANNEL_HELD, SILENT, "nothing is asking", asked, ceiling)

        if self._is_duplicate(topic, text, moment):
            return GateDecision(False, CHANNEL_HELD, level, "already said this recently", asked, ceiling)

        # Pull surface: costs no attention, so it is never rationed.
        if level <= BRIEF_ALWAYS:
            return GateDecision(True, CHANNEL_BRIEF, level, "brief entry", asked, ceiling)

        # Push from here down.
        # Whether deep work may be crossed is decided by the *ceiling*, not by
        # how loud the drives happen to be right now. A level-5 grant is a
        # standing instruction — "wake me for this" — and a lukewarm moment does
        # not revoke it. Deciding on `level` instead made a level-5 grant
        # unreachable, because nothing the drives can do asks for 5.
        mid_something = idle_seconds < ACTIVE_WITHIN_S
        if mid_something and ceiling < INTERRUPT:
            return GateDecision(False, CHANNEL_HELD, level, "you are mid-something", asked, ceiling)
        if mid_something:
            # It is about to interrupt deep work, so the level it reports says
            # so. Anything less would log a nag while doing an interrupt.
            level = INTERRUPT

        if ceiling < INTERRUPT and not self.budget.can_spend(moment):
            # The backstop bound. Design §5: say so rather than dropping it
            # quietly — a bound budget means there are too many grants.
            log.info("push budget exhausted; holding %s. Too many grants is the usual cause.", topic)
            return GateDecision(False, CHANNEL_HELD, level, "push budget spent for today", asked, ceiling)

        if ceiling < INTERRUPT:
            self.budget.spend(moment)
        return GateDecision(True, CHANNEL_PUSH, level, f"{level_name(level)} allowed", asked, ceiling)

    def record_outcome(self, topic: str, outcome: str, channel: str = CHANNEL_HELD) -> None:
        """Feed a result back into the budget and the grant's freshness.

        Only a **push** touches the budget. A message that was held was never
        sent, and a brief entry costs no attention, so neither can be allowed to
        drain the allowance for interrupts. Letting them drain it was not
        theoretical: a fortnight of ignored held candidates drove the balance to
        its floor, which would have silently disabled every future push,
        including on topics explicitly granted the right to interrupt.
        """
        if channel == CHANNEL_PUSH:
            self.budget.record_outcome(outcome)
        if channel in {CHANNEL_PUSH, CHANNEL_BRIEF}:
            self.permissions.record_outcome(topic, outcome)
