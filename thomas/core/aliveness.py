"""The aliveness loop — sensors, drives, and a mouth that is not connected yet.

Design: `plans/thomas/ALIVENESS_DESIGN_2026-08-27.md`.

This is the first slice of that design: the world model (§2), the drive
hierarchy (§4), and the mute log (§6), wired together into a tick that costs
nothing and says nothing.

What it does today:

- sweeps the cheap sensors and diffs them into changes;
- moves the three drives accordingly;
- when a drive that is not Contact crosses its setpoint, builds the message it
  would have sent and **writes it to the mute log instead of sending it.**

What it deliberately does not do yet:

- speak. Nothing in this module has a channel to the user. Per design §5 the
  permission store does not exist, which is expressed here as
  :func:`granted_level` returning 0 for every topic — the exact behaviour of a
  permission store with no grants in it. Ship the mouth last.
- execute goals. :func:`build_initiative_executor` returns an executor that
  records what it *would* have run. The InitiativeEngine runs it in dry-run
  mode, so no goal is executed and no goal is closed.

Off by default. ``THOMAS_ALIVENESS_ENABLED=1`` turns the loop on; without it
nothing here starts, and the engine stays as honestly dark as it was.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from thomas.core.aliveness_drives import Drives
from thomas.core.aliveness_gate import GateDecision, SpeakGate
from thomas.core.aliveness_log import CandidateMessage, MuteLog
from thomas.core.aliveness_permissions import NOTIFY, PermissionStore, level_name
from thomas.core.aliveness_world import SENSOR_FAULTS, Change, WorldModel, default_sensors

log = logging.getLogger(__name__)

ENABLE_ENV = "THOMAS_ALIVENESS_ENABLED"
INTERVAL_ENV = "THOMAS_ALIVENESS_INTERVAL_S"

# The cycle band from design §3: cheap enough to run unattended, slow enough
# that it is nowhere near the cost of thinking. Measured at ~30ms per sweep.
DEFAULT_SWEEP_INTERVAL_S: float = 300.0

# Maintenance (decay sweep, proposal harvest) is daily, not per tick.
MAINTENANCE_EVERY_TICKS: int = 288  # 24h at the default 5-minute interval


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_enabled() -> bool:
    """Whether the aliveness loop may run at all. Off unless explicitly set."""
    return _truthy(os.environ.get(ENABLE_ENV))


def sweep_interval_s() -> float:
    """Seconds between unattended sweeps."""
    raw = os.environ.get(INTERVAL_ENV)
    if not raw:
        return DEFAULT_SWEEP_INTERVAL_S
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_SWEEP_INTERVAL_S
    return value if value > 0 else DEFAULT_SWEEP_INTERVAL_S


def granted_level(topic: str) -> int:
    """Escalation ceiling granted for ``topic``, from the default store."""
    return PermissionStore().level_for(topic)


def _repo_root() -> Path | None:
    override = os.environ.get("THOMAS_ALIVENESS_REPO")
    if override:
        candidate = Path(override).expanduser()
        return candidate if (candidate / ".git").exists() else None
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    return None


def _summarise(topic: str, changes: list[Change]) -> str:
    """The sentence Thomas would have said about ``topic``."""
    if len(changes) == 1:
        return changes[0].describe()
    head = "; ".join(c.describe() for c in changes[:3])
    if len(changes) > 3:
        return f"{head}; and {len(changes) - 3} more"
    return head


class AlivenessLoop:
    """One tick of being awake: look, feel, decide, stay quiet.

    The loop owns no thread. Callers drive :meth:`tick` — the InitiativeEngine
    daemon, a test, or a CLI — which keeps the cost model honest and the whole
    thing testable without waiting on wall-clock time.
    """

    def __init__(
        self,
        world: WorldModel | None = None,
        drives: Drives | None = None,
        mute_log: MuteLog | None = None,
        gate: SpeakGate | None = None,
        sink: Any | None = None,
    ) -> None:
        self.world = world or WorldModel(default_sensors(_repo_root()))
        self.drives = drives or Drives()
        self.mute_log = mute_log or MuteLog()
        self.gate = gate or SpeakGate()
        self.gate.permissions.ensure_seed()
        # The mouth. Still not connected to anything that reaches you: the
        # default sink records and counts. A real channel plugs in here, and
        # this is the only place it should ever plug in.
        self.sink = sink or _RecordingSink()
        self._ticks = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None

    @property
    def ticks(self) -> int:
        return self._ticks

    def _open_goal_count(self) -> int:
        snapshot = self.world.snapshot()
        for (topic, key), obs in snapshot.items():
            if topic == "goals.open" and key == "count":
                try:
                    return int(obs.value)
                except (TypeError, ValueError):
                    return 0
        return 0

    def _candidates(self, changes: list[Change]) -> list[CandidateMessage]:
        """Build one candidate per changed topic.

        One per topic, not one per change: the topic is the unit permission is
        granted in, so it has to be the unit the log is readable in.

        The drives set the *level* a candidate asks for, not whether it is
        recorded. Recording is unconditional in mute mode — a log that only
        captured the changes a drive happened to be hot for would be a biased
        sample, and this log's whole job is to be the evidence for the first
        permission grants.
        """
        by_topic: dict[str, list[Change]] = {}
        for change in changes:
            by_topic.setdefault(change.topic, []).append(change)

        drives_snapshot = self.drives.to_dict()
        out: list[CandidateMessage] = []
        for topic, topic_changes in sorted(by_topic.items()):
            out.append(
                CandidateMessage(
                    topic=topic,
                    text=_summarise(topic, topic_changes),
                    evidence=[c.describe() for c in topic_changes[:10]],
                    # What it asks for depends on what has been granted for this
                    # topic, so the gate works it out per candidate.
                    proposed_level=self.gate.asked_level(self.drives, self.gate.permissions.level_for(topic)),
                    drives=drives_snapshot,
                )
            )
        return out

    def tick(self, idle_seconds: float = 0.0, now: float | None = None) -> dict[str, Any]:
        """Run one cycle. Returns a summary; sends nothing, ever.

        Every changed topic is recorded. The drives shape what each record
        *asks* for and are stored alongside it as features for the judge; they
        do not decide whether the record is written. What the drives do gate is
        acting — see :meth:`Drives.wants_action` and the executor below.
        """
        moment = time.time() if now is None else now
        changes = self.world.sweep()

        self.drives.observe_world(len(changes), now=moment)
        self.drives.observe_debt(self._open_goal_count())
        self.drives.observe_silence(idle_seconds)

        recorded: list[CandidateMessage] = []
        delivered = 0
        for candidate in self._candidates(changes) + self._maintenance(moment):
            decision = self.gate.decide(
                topic=candidate.topic,
                text=candidate.text,
                drives=self.drives,
                evidence=candidate.evidence,
                idle_seconds=idle_seconds,
                now=moment,
            )
            candidate.gate = decision.to_dict()
            candidate.channel = decision.channel
            recorded.append(self.mute_log.record(candidate))
            if decision.deliver:
                delivered += 1
                self.sink.deliver(candidate, decision)

        # Looking is what discharges Freshness — we just looked.
        self.drives.freshness.discharge(now=moment)
        self._ticks += 1

        return {
            "tick": self._ticks,
            "at": moment,
            "changes": len(changes),
            "recorded": len(recorded),
            "delivered": delivered,
            "drives": self.drives.to_dict(),
            "topics": self.world.topics(),
            "budget": self.gate.budget.to_dict(),
        }

    def _maintenance(self, now: float) -> list[CandidateMessage]:
        """Daily housekeeping: decay stale grants, propose earned ones.

        Both produce brief-level candidates on the seed topic, because both are
        things you need to see: a grant that quietly stopped working is worse
        than one that never existed, and earned permission has to *ask*.
        """
        if self._ticks % MAINTENANCE_EVERY_TICKS != 0:
            return []

        out: list[CandidateMessage] = []
        system = self.gate.permissions.SYSTEM_TOPIC
        drives_snapshot = self.drives.to_dict()

        for topic, before, after in self.gate.permissions.decay(now=now):
            out.append(
                CandidateMessage(
                    topic=system,
                    text=(
                        f"I've stopped flagging {topic} "
                        f"({level_name(before)} -> {level_name(after)}); "
                        "nothing has been acted on there in a month."
                    ),
                    evidence=[f"decay: {topic}"],
                    proposed_level=NOTIFY,
                    drives=drives_snapshot,
                )
            )

        for topic, samples, _net, hit_rate in self.mute_log.draft_grant_list():
            proposal = self.gate.permissions.maybe_propose(topic, samples, hit_rate)
            if proposal is None:
                continue
            out.append(
                CandidateMessage(
                    topic=system,
                    text=proposal.question(),
                    evidence=[f"proposal: {topic}", f"{samples} samples", f"{hit_rate:.0%} acted"],
                    proposed_level=NOTIFY,
                    drives=drives_snapshot,
                )
            )
        return out

    def record_outcome(self, candidate_id: str, topic: str, outcome: str) -> None:
        """Tell the loop what became of a message it delivered.

        Feeds all three loops at once: the log (evidence), the budget (a message
        you acted on is refunded), and the grant (a topic you act on stays
        fresh and does not decay).
        """
        self.mute_log.resolve(candidate_id, outcome)
        channel = next(
            (c.channel for c in self.mute_log.entries() if c.id == candidate_id),
            None,
        )
        if channel is not None:
            self.gate.record_outcome(topic, outcome, channel)

    # -- unattended operation ---------------------------------------------

    @staticmethod
    def _idle_seconds() -> float:
        """How long the user has been quiet, for the Contact drive.

        Read from the InitiativeEngine, which already tracks it. Unavailable
        means zero: Contact cannot cause anything on its own, so a missing
        reading costs nothing.
        """
        try:
            from thomas.core.initiative import get_initiative_engine

            return float(get_initiative_engine().idle_seconds())
        except (ImportError, ModuleNotFoundError, AttributeError, TypeError, ValueError):
            return 0.0

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    @property
    def last_error(self) -> str | None:
        """Most recent sweep failure, or None. Surfaced in engine status."""
        return self._last_error

    def start(self, interval_s: float | None = None) -> None:
        """Sweep on a timer, independently of whether there is work to do.

        Without this the loop only ticks when the InitiativeEngine happens to
        fire a goal — which needs 30 minutes of silence *and* an open goal — so
        a run with no open goals would record nothing at all. The mute log is
        the entire point of this slice, so the sweep cannot be contingent on
        having work.
        """
        if self.running:
            return
        every = float(interval_s) if interval_s else sweep_interval_s()
        self._stop.clear()

        def _run() -> None:
            # A sweep thread that dies quietly is the worst outcome here: the
            # loop would report itself stopped and nothing would notice it had
            # stopped being alive. The finally clause makes any exit loud.
            try:
                while not self._stop.is_set():
                    try:
                        self.tick(idle_seconds=self._idle_seconds())
                    except SENSOR_FAULTS as exc:
                        self._last_error = f"{type(exc).__name__}: {exc}"
                        log.warning("aliveness sweep failed: %s", exc)
                    self._stop.wait(every)
            finally:
                if self._stop.is_set():
                    log.info("AlivenessLoop: sweep stopped as requested")
                else:
                    log.error(
                        "AlivenessLoop: sweep thread exited unexpectedly after "
                        "%d tick(s) — the loop is no longer observing anything. "
                        "Last error: %s",
                        self._ticks,
                        self._last_error or "none recorded",
                    )

        self._thread = threading.Thread(target=_run, daemon=True, name="thomas-aliveness")
        self._thread.start()
        log.info("AlivenessLoop: sweeping every %.0fs (mute)", every)

    def stop(self, timeout: float = 2.0) -> None:
        """Stop sweeping. Safe to call when not running."""
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None


class _RecordingSink:
    """The default mouth: it counts, and goes nowhere.

    Ship the mouth last. Everything upstream of here — sensors, drives,
    permission, budget, hard mutes — is real and decides for real; this is the
    one piece deliberately left unplugged.
    """

    def __init__(self) -> None:
        self.delivered: list[tuple[str, str, int]] = []

    def deliver(self, candidate: CandidateMessage, decision: GateDecision) -> None:
        self.delivered.append((candidate.topic, decision.channel, decision.level))
        log.info(
            "aliveness would deliver [%s] via %s: %s",
            candidate.topic,
            decision.channel,
            candidate.text[:120],
        )


_loop: AlivenessLoop | None = None


def get_aliveness_loop() -> AlivenessLoop:
    """Process-level loop. Created on first use; owns no thread of its own."""
    global _loop
    if _loop is None:
        _loop = AlivenessLoop()
    return _loop


def reset_aliveness_loop() -> None:
    """Drop the process-level loop. For tests and for a clean restart."""
    global _loop
    if _loop is not None:
        _loop.stop()
    _loop = None


def build_initiative_executor(loop: AlivenessLoop | None = None):
    """An ``executor_fn`` for :class:`~thomas.core.initiative.InitiativeEngine`.

    This is build-order item 2 — the function whose absence is why the engine
    reports ``disabled: no executor`` and has never run in production.

    It does not execute the goal. It ticks the world and records the goal it
    would have picked up, so a mute run produces the one artefact worth having:
    a log of what Thomas would have done and said, with an outcome field that
    defaults to a penalty. The engine must run this in dry-run mode so the goal
    is neither closed nor announced.
    """
    engine_loop = loop

    def executor(goal_text: str) -> str:
        active = engine_loop or get_aliveness_loop()
        summary = active.tick()
        candidate = CandidateMessage(
            topic="goals.open",
            text=f"would have worked on: {str(goal_text)[:200]}",
            evidence=[f"tick {summary['tick']}", f"{summary['changes']} world changes"],
            proposed_level=1,
            drives=active.drives.to_dict(),
        )
        active.mute_log.record(candidate)
        log.info(
            "aliveness: recorded (not executed) goal %r; %d changes this tick",
            str(goal_text)[:80],
            summary["changes"],
        )
        return "recorded: aliveness loop is in mute mode, nothing was executed"

    return executor
