"""Per-topic permission — what Thomas is allowed to be annoying about.

Design: `plans/thomas/ALIVENESS_DESIGN_2026-08-27.md` §5.

Thomas is silent about everything by default and earns permission one topic at a
time. He may be as annoying as he has been told he can be about the things he
has been told he can be annoying about, and mute everywhere else.

The alternative — a global budget with a threshold that learns from feedback —
was rejected for a specific reason worth restating where the code lives: a
learned global threshold has to be annoying in order to learn. It needs signal,
signal comes from sending messages, so it experiments on you during exactly the
window when your patience is being set. Permission that starts at zero never
experiments. Learning happens *inside* a granted topic, never on the question of
whether to speak at all.

Three ways permission accrues, strongest first:

1. **Explicit** — you say so. One call, full grant.
2. **Earned, then confirmed** — evidence raises a :class:`Proposal`, never a
   grant. Something has to ask you before it starts talking; earned permission
   that skips the question is how the contract quietly stops being inspectable.
3. **Inherited, weakly** — a sub-topic of something you already care about
   qualifies at a reduced ceiling, so you do not have to enumerate the world.

And it decays. A grant made for a project you finished is a liability, so a topic
you stop acting on falls back toward silence on its own — and the fallback is
announced rather than done quietly.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Escalation ceilings (design §5). Levels 4 and 5 are the whole point of doing
# this per topic: a global budget can never safely offer them, because it has to
# be conservative about everything at once.
SILENT = 0  # never surfaced
BRIEF_IF_ROOM = 1  # appears in the brief if there is room
BRIEF_ALWAYS = 2  # always in the brief
NOTIFY = 3  # notify when it happens
NAG = 4  # notify, and repeat until acknowledged
INTERRUPT = 5  # interrupt through quiet hours and deep work

MAX_LEVEL = INTERRUPT

LEVEL_NAMES: dict[int, str] = {
    SILENT: "silent",
    BRIEF_IF_ROOM: "brief-if-room",
    BRIEF_ALWAYS: "brief-always",
    NOTIFY: "notify",
    NAG: "nag",
    INTERRUPT: "interrupt",
}

SOURCE_EXPLICIT = "explicit"
SOURCE_EARNED = "earned"
SOURCE_INHERITED = "inherited"

# Evidence required before the store will even *propose* a topic.
PROPOSAL_MIN_SAMPLES = 4
PROPOSAL_MIN_HIT_RATE = 0.6

# A grant with no acted-on outcome for this long drops one level.
DECAY_AFTER_S: float = 30 * 24 * 60 * 60.0

_PERMISSIONS_ENV = "THOMAS_ALIVENESS_PERMISSIONS"


def clamp_level(value: Any) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        return SILENT
    return max(SILENT, min(MAX_LEVEL, level))


def level_name(level: int) -> str:
    return LEVEL_NAMES.get(clamp_level(level), "silent")


def _default_store_path() -> Path:
    override = os.environ.get(_PERMISSIONS_ENV)
    if override:
        return Path(override).expanduser()
    try:
        from thomas.core.config import resolve_thomas_data_dir

        root = resolve_thomas_data_dir()
    except (ImportError, ModuleNotFoundError, OSError, ValueError):
        root = Path.home() / ".thomas"
    return Path(root) / "aliveness" / "permissions.json"


def parent_topics(topic: str) -> list[str]:
    """Ancestors of a dotted topic, nearest first. ``a.b.c`` -> ``a.b``, ``a``."""
    parts = [p for p in str(topic or "").split(".") if p]
    return [".".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]


@dataclass
class Grant:
    """Permission to speak about one topic, up to ``level``."""

    topic: str
    level: int
    source: str = SOURCE_EXPLICIT
    granted_at: float = field(default_factory=time.time)
    last_acted_at: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "level": self.level,
            "source": self.source,
            "granted_at": self.granted_at,
            "last_acted_at": self.last_acted_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Grant:
        return cls(
            topic=str(payload.get("topic") or ""),
            level=clamp_level(payload.get("level")),
            source=str(payload.get("source") or SOURCE_EXPLICIT),
            granted_at=float(payload.get("granted_at") or time.time()),
            last_acted_at=payload.get("last_acted_at"),
            note=str(payload.get("note") or ""),
        )


@dataclass
class Proposal:
    """Evidence that a topic might deserve permission. Not permission.

    Surfaced for you to accept or decline. Nothing turns a proposal into a grant
    on its own — that is the difference between an assistant that asks and one
    that decides it knows best.
    """

    topic: str
    suggested_level: int
    samples: int
    hit_rate: float
    raised_at: float = field(default_factory=time.time)

    def question(self) -> str:
        return (
            f"You've acted on {self.topic} {int(round(self.hit_rate * self.samples))} "
            f"of the last {self.samples} times it came up. "
            f"Want me to tell you when it changes ({level_name(self.suggested_level)})?"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "suggested_level": self.suggested_level,
            "samples": self.samples,
            "hit_rate": self.hit_rate,
            "raised_at": self.raised_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Proposal:
        return cls(
            topic=str(payload.get("topic") or ""),
            suggested_level=clamp_level(payload.get("suggested_level")),
            samples=int(payload.get("samples") or 0),
            hit_rate=float(payload.get("hit_rate") or 0.0),
            raised_at=float(payload.get("raised_at") or time.time()),
        )


class PermissionStore:
    """Grants and proposals, persisted as one small JSON file.

    Deliberately readable and hand-editable: "what are you allowed to bug me
    about?" has to be a list you can open and edit, not a threshold buried in a
    model. Inspectability is the property that makes per-topic permission worth
    having.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else _default_store_path()
        self._lock = threading.Lock()
        self._grants: dict[str, Grant] = {}
        self._proposals: dict[str, Proposal] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    # -- persistence -------------------------------------------------------

    def _load_unlocked(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("permission store unreadable (%s): %s", self._path, exc)
            return
        if not isinstance(payload, dict):
            return
        for row in payload.get("grants") or []:
            if isinstance(row, dict):
                grant = Grant.from_dict(row)
                if grant.topic:
                    self._grants[grant.topic] = grant
        for row in payload.get("proposals") or []:
            if isinstance(row, dict):
                proposal = Proposal.from_dict(row)
                if proposal.topic:
                    self._proposals[proposal.topic] = proposal

    def _save_unlocked(self) -> bool:
        payload = {
            "version": 1,
            "grants": [g.to_dict() for g in self._grants.values()],
            "proposals": [p.to_dict() for p in self._proposals.values()],
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self._path)
        except (OSError, ValueError) as exc:
            log.warning("permission store write failed (%s): %s", self._path, exc)
            return False
        return True

    # -- grants ------------------------------------------------------------

    def grant(
        self,
        topic: str,
        level: int,
        source: str = SOURCE_EXPLICIT,
        note: str = "",
    ) -> Grant:
        """Allow Thomas to speak about ``topic`` up to ``level``."""
        topic = str(topic or "").strip()
        if not topic:
            raise ValueError("topic is required")
        with self._lock:
            self._load_unlocked()
            grant = Grant(topic=topic, level=clamp_level(level), source=source, note=note)
            self._grants[topic] = grant
            self._proposals.pop(topic, None)
            self._save_unlocked()
        log.info("permission granted: %s -> %s (%s)", topic, level_name(grant.level), source)
        return grant

    def revoke(self, topic: str) -> bool:
        with self._lock:
            self._load_unlocked()
            existed = self._grants.pop(str(topic or ""), None) is not None
            if existed:
                self._save_unlocked()
        return existed

    def grants(self) -> list[Grant]:
        with self._lock:
            self._load_unlocked()
            return sorted(self._grants.values(), key=lambda g: (-g.level, g.topic))

    def level_for(self, topic: str) -> int:
        """The ceiling for ``topic``: exact grant, else inherited, else silent.

        Inheritance is deliberately weak — one level below the parent — so that
        caring about ``ci.status`` covers ``ci.status.nightly`` without silently
        handing a whole subtree the parent's interrupt rights.
        """
        topic = str(topic or "").strip()
        if not topic:
            return SILENT
        with self._lock:
            self._load_unlocked()
            direct = self._grants.get(topic)
            if direct is not None:
                return direct.level
            for ancestor in parent_topics(topic):
                inherited = self._grants.get(ancestor)
                if inherited is not None and inherited.level >= BRIEF_ALWAYS:
                    return max(BRIEF_IF_ROOM, inherited.level - 1)
        return SILENT

    def source_for(self, topic: str) -> str | None:
        with self._lock:
            self._load_unlocked()
            direct = self._grants.get(str(topic or ""))
            if direct is not None:
                return direct.source
            for ancestor in parent_topics(topic):
                if self._grants.get(ancestor) is not None:
                    return SOURCE_INHERITED
        return None

    SYSTEM_TOPIC = "aliveness.system"

    def ensure_seed(self) -> None:
        """Grant the loop a pull-only channel to talk about itself.

        Without this the design deadlocks: permission starts at zero for
        everything, including the topic Thomas would use to *ask* for
        permission or to announce that a grant has decayed, so the contract
        could never grow or be corrected.

        The seed is deliberately the weakest thing that resolves it — a brief
        entry, which is pull, costs no attention and spends no budget. It never
        reaches push, and you can revoke it like any other grant.
        """
        with self._lock:
            self._load_unlocked()
            if self.SYSTEM_TOPIC in self._grants:
                return
            self._grants[self.SYSTEM_TOPIC] = Grant(
                topic=self.SYSTEM_TOPIC,
                level=BRIEF_ALWAYS,
                source=SOURCE_EXPLICIT,
                note="seed: how the loop asks for permission and reports decay",
            )
            self._save_unlocked()

    # -- feedback and decay ------------------------------------------------

    def record_outcome(self, topic: str, outcome: str) -> None:
        """Note that a granted topic earned its keep (or did not)."""
        if str(outcome or "").lower() not in {"acted", "replied"}:
            return
        with self._lock:
            self._load_unlocked()
            grant = self._grants.get(str(topic or ""))
            if grant is None:
                return
            grant.last_acted_at = time.time()
            self._save_unlocked()

    def decay(self, now: float | None = None) -> list[tuple[str, int, int]]:
        """Drop a level on grants nobody has acted on lately.

        Returns ``(topic, before, after)`` for each change so the caller can
        announce it. Design §5: the fallback is announced, not silent — a grant
        that quietly stops working is worse than one that never existed.
        """
        moment = time.time() if now is None else now
        changed: list[tuple[str, int, int]] = []
        with self._lock:
            self._load_unlocked()
            for topic, grant in list(self._grants.items()):
                reference = grant.last_acted_at or grant.granted_at
                if moment - reference < DECAY_AFTER_S:
                    continue
                before = grant.level
                after = max(SILENT, before - 1)
                if after == before:
                    continue
                changed.append((topic, before, after))
                if after == SILENT:
                    self._grants.pop(topic, None)
                else:
                    grant.level = after
                    grant.granted_at = moment
            if changed:
                self._save_unlocked()
        for topic, before, after in changed:
            log.info("permission decayed: %s %s -> %s", topic, level_name(before), level_name(after))
        return changed

    # -- proposals ---------------------------------------------------------

    def maybe_propose(
        self, topic: str, samples: int, hit_rate: float, suggested_level: int = NOTIFY
    ) -> Proposal | None:
        """Raise a proposal when the evidence is there. Never a grant.

        Returns the proposal if one was raised, else None. Already-granted and
        already-proposed topics are left alone so the same question is not asked
        twice.
        """
        topic = str(topic or "").strip()
        if not topic or samples < PROPOSAL_MIN_SAMPLES or hit_rate < PROPOSAL_MIN_HIT_RATE:
            return None
        with self._lock:
            self._load_unlocked()
            if topic in self._grants or topic in self._proposals:
                return None
            proposal = Proposal(
                topic=topic,
                suggested_level=clamp_level(suggested_level),
                samples=int(samples),
                hit_rate=float(hit_rate),
            )
            self._proposals[topic] = proposal
            self._save_unlocked()
        log.info("permission proposed: %s (%d samples, %.2f hit rate)", topic, samples, hit_rate)
        return proposal

    def proposals(self) -> list[Proposal]:
        with self._lock:
            self._load_unlocked()
            return sorted(self._proposals.values(), key=lambda p: (-p.hit_rate, p.topic))

    def accept(self, topic: str, level: int | None = None) -> Grant | None:
        with self._lock:
            self._load_unlocked()
            proposal = self._proposals.get(str(topic or ""))
        if proposal is None:
            return None
        return self.grant(
            proposal.topic,
            proposal.suggested_level if level is None else level,
            source=SOURCE_EARNED,
            note=f"accepted after {proposal.samples} samples at {proposal.hit_rate:.0%}",
        )

    def decline(self, topic: str) -> bool:
        with self._lock:
            self._load_unlocked()
            existed = self._proposals.pop(str(topic or ""), None) is not None
            if existed:
                self._save_unlocked()
        return existed
