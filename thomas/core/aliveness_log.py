"""The mute log — everything Thomas would have said, and what came of it.

Design: `plans/thomas/ALIVENESS_DESIGN_2026-08-27.md` §6 (measurement) and §8
(build order).

While the mouth is disconnected, every candidate message is written here
instead of being sent. The log has two jobs, and the second one is the reason
it exists at all:

1. It is training data for the judge. Judging whether an interruption was
   wanted is the tractable half of this problem; generating good ones is not.
2. It is the **draft grant list**. After a couple of weeks you read it, and the
   entries you would have wanted become the first explicit per-topic
   permissions (design §5). That is a better bootstrap than tuning a threshold,
   and it means the first message Thomas ever sends unprompted falls in a
   category you already approved.

The load-bearing rule is :data:`OUTCOME_SCORES`: **an ignored message scores
negative, never zero.** If silence is free, the expected value of sending is
always positive and any system built on top of this will reason its way into
sending more forever. Silence has to be profitable in the arithmetic, not just
in the prose.

The file is append-only. Resolving an entry appends a resolution record rather
than rewriting the original, so the log stays an audit trail of what was
proposed and when it was judged.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# What each outcome is worth. Ignored is negative on purpose (design §6 rule 1).
OUTCOME_SCORES: dict[str, float] = {
    "acted": 1.0,  # you did something attributable to it
    "replied": 0.75,  # you engaged, without a clear downstream action
    "seen": -0.25,  # you looked and moved on: it cost attention, bought nothing
    "ignored": -1.0,  # the default. Never zero.
    "stopped": -3.0,  # you told it to stop. The most expensive outcome there is.
}
DEFAULT_OUTCOME = "ignored"

# Where an entry would have surfaced. Pull costs no attention; push does.
CHANNEL_BRIEF = "brief"
CHANNEL_PUSH = "push"

_RECORD_CANDIDATE = "candidate"
_RECORD_RESOLUTION = "resolution"


def outcome_score(outcome: str) -> float:
    """Score for an outcome, defaulting to the ignored penalty when unknown."""
    return OUTCOME_SCORES.get(str(outcome or "").strip().lower(), OUTCOME_SCORES[DEFAULT_OUTCOME])


def _default_log_path() -> Path:
    override = os.environ.get("THOMAS_ALIVENESS_LOG")
    if override:
        return Path(override).expanduser()
    try:
        from thomas.core.config import resolve_thomas_data_dir

        root = resolve_thomas_data_dir()
    except (ImportError, ModuleNotFoundError, OSError, ValueError):
        root = Path.home() / ".thomas"
    return Path(root) / "aliveness" / "mute_log.jsonl"


@dataclass
class CandidateMessage:
    """Something Thomas would have said, had it been allowed to speak.

    ``proposed_level`` is the escalation level from design §5 that this would
    have needed. In mute mode nothing is granted, so every candidate lands here
    regardless of level — but recording the level it *wanted* is what makes the
    log readable later as a grant list.
    """

    topic: str
    text: str
    evidence: list[str] = field(default_factory=list)
    proposed_level: int = 1
    channel: str = CHANNEL_BRIEF
    drives: dict[str, Any] = field(default_factory=dict)
    gate: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    at: float = field(default_factory=time.time)
    outcome: str = DEFAULT_OUTCOME
    outcome_at: float | None = None

    @property
    def score(self) -> float:
        return outcome_score(self.outcome)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": _RECORD_CANDIDATE,
            "id": self.id,
            "at": self.at,
            "topic": self.topic,
            "text": self.text,
            "evidence": list(self.evidence),
            "proposed_level": self.proposed_level,
            "channel": self.channel,
            "drives": dict(self.drives),
            "gate": dict(self.gate),
            "outcome": self.outcome,
            "outcome_at": self.outcome_at,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CandidateMessage:
        return cls(
            topic=str(payload.get("topic") or ""),
            text=str(payload.get("text") or ""),
            evidence=[str(e) for e in payload.get("evidence") or []],
            proposed_level=int(payload.get("proposed_level") or 1),
            channel=str(payload.get("channel") or CHANNEL_BRIEF),
            drives=dict(payload.get("drives") or {}),
            gate=dict(payload.get("gate") or {}),
            id=str(payload.get("id") or uuid.uuid4().hex[:16]),
            at=float(payload.get("at") or time.time()),
            outcome=str(payload.get("outcome") or DEFAULT_OUTCOME),
            outcome_at=payload.get("outcome_at"),
        )


# One lock per FILE, not per MuteLog. Every call site builds its own MuteLog for
# the same path - the branch's own concurrency test builds one per thread - so a
# per-instance lock serialises nothing and appended lines are lost. Measured on
# Windows: six threads writing 50 lines each landed fewer than the 300 they wrote.
_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(str(path)))
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.Lock())


class MuteLog:
    """Append-only JSONL store of candidates and their resolutions."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else _default_log_path()
        self._lock = _lock_for(self._path)
        # Incremental read state. The file is append-only, so a reader only
        # ever needs the bytes it has not seen. Without this, every call to
        # entries(), action_rate() or draft_grant_list() re-parsed the whole
        # log — measured at ~490ms for 20,000 entries, and growing.
        self._offset: int = 0
        self._candidates: dict[str, CandidateMessage] = {}
        self._order: list[str] = []
        self._pending_resolutions: dict[str, dict[str, Any]] = {}

    @property
    def path(self) -> Path:
        return self._path

    def _append(self, payload: dict[str, Any]) -> bool:
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except (OSError, ValueError) as exc:
                log.warning("mute log write failed (%s): %s", self._path, exc)
                return False
        return True

    def record(self, candidate: CandidateMessage) -> CandidateMessage:
        """Write a candidate. It is not sent — that is the point of the log."""
        self._append(candidate.to_dict())
        return candidate

    def resolve(self, candidate_id: str, outcome: str, at: float | None = None) -> bool:
        """Record what became of a candidate, without rewriting the original."""
        normalized = str(outcome or "").strip().lower()
        if normalized not in OUTCOME_SCORES:
            raise ValueError(f"unknown outcome: {outcome!r} (expected one of {sorted(OUTCOME_SCORES)})")
        return self._append(
            {
                "record": _RECORD_RESOLUTION,
                "id": str(candidate_id),
                "outcome": normalized,
                "outcome_at": float(at if at is not None else time.time()),
                "score": outcome_score(normalized),
            }
        )

    def _reset_cache(self) -> None:
        self._offset = 0
        self._candidates = {}
        self._order = []
        self._pending_resolutions = {}

    def _apply(self, payload: dict[str, Any]) -> None:
        kind = str(payload.get("record") or _RECORD_CANDIDATE)
        entry_id = str(payload.get("id") or "")
        if not entry_id:
            return
        if kind == _RECORD_RESOLUTION:
            candidate = self._candidates.get(entry_id)
            if candidate is None:
                # A resolution can only precede its candidate in a corrupt or
                # hand-edited file, but hold it in case the candidate follows.
                self._pending_resolutions[entry_id] = payload
                return
            candidate.outcome = str(payload.get("outcome") or DEFAULT_OUTCOME)
            candidate.outcome_at = payload.get("outcome_at")
            return
        if entry_id not in self._candidates:
            self._order.append(entry_id)
        candidate = CandidateMessage.from_dict(payload)
        self._candidates[entry_id] = candidate
        held = self._pending_resolutions.pop(entry_id, None)
        if held is not None:
            candidate.outcome = str(held.get("outcome") or DEFAULT_OUTCOME)
            candidate.outcome_at = held.get("outcome_at")

    def _catch_up(self) -> None:
        """Parse only the bytes appended since the last read."""
        try:
            size = self._path.stat().st_size
        except OSError:
            self._reset_cache()
            return

        if size < self._offset:
            # Truncated or rotated underneath us: the cache is no longer valid.
            self._reset_cache()
        if size == self._offset:
            return

        try:
            with self._path.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
        except (OSError, ValueError) as exc:
            log.warning("mute log read failed (%s): %s", self._path, exc)
            return

        # A trailing fragment means someone is mid-append. Leave it unread so
        # the next call sees the whole line rather than half of one.
        consumed = len(chunk)
        newline = chunk.rfind(b"\n")
        if newline == -1:
            return
        if newline != len(chunk) - 1:
            consumed = newline + 1
            chunk = chunk[:consumed]

        for raw in chunk.decode("utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                self._apply(payload)

        self._offset += consumed

    def entries(self) -> list[CandidateMessage]:
        """Candidates with their resolutions folded in, oldest first."""
        with self._lock:
            self._catch_up()
            return [self._candidates[i] for i in self._order if i in self._candidates]

    # -- the numbers worth watching ---------------------------------------

    def action_rate(self, last_n: int = 20, topic: str | None = None) -> float | None:
        """Share of the last N candidates that led to action (design §6 rule 5).

        This is the leading indicator. It decays weeks before you would notice
        you had stopped reading. Returns None when there is nothing to measure.

        Pass ``topic`` to measure one topic rather than the mixture. During a
        mute run the mixture is close to useless: one high-volume noisy topic
        fills the whole window, and the rate reads zero even on a run where
        plenty was acted on. Once permission is granted per topic, the per-topic
        rate is the one that means anything anyway.
        """
        pool = self.entries()
        if topic is not None:
            pool = [c for c in pool if c.topic == topic]
        recent = pool[-max(1, last_n) :]
        if not recent:
            return None
        acted = sum(1 for c in recent if c.outcome in {"acted", "replied"})
        return acted / len(recent)

    def net_score(self, last_n: int = 20) -> float:
        """Summed score of the last N candidates. Negative means stop talking."""
        recent = self.entries()[-max(1, last_n) :]
        return sum(c.score for c in recent)

    def draft_grant_list(self) -> list[tuple[str, int, float, float]]:
        """Topics ranked for the first permission grants (design §5).

        Returns ``(topic, candidate_count, net_score, hit_rate)``. Read this
        after a mute run: the top rows are what Thomas should be allowed to
        speak about, the bottom rows are what he would have been annoying about.

        Ranked by **hit rate, not net score.** Net score rewards volume, which
        gets the decision backwards: a rare topic you act on every single time
        is exactly what deserves permission to interrupt, while a frequent topic
        you act on half the time is what alert fatigue is made of. Sorting by
        net would rank a chatty topic above production going down.

        The sort key is Laplace-smoothed — ``(acted + 1) / (count + 2)`` — so a
        topic that fired once and got lucky does not outrank one that has proven
        itself over twenty fires. The reported ``hit_rate`` is the raw rate; the
        smoothing only decides the order, and ``candidate_count`` is there so
        you can see how much evidence each row actually rests on.
        """
        buckets: dict[str, list[CandidateMessage]] = {}
        for candidate in self.entries():
            buckets.setdefault(candidate.topic, []).append(candidate)

        rows: list[tuple[str, int, float, float]] = []
        keys: dict[str, float] = {}
        for topic, items in buckets.items():
            acted = sum(1 for c in items if c.outcome in {"acted", "replied"})
            count = len(items)
            rows.append(
                (
                    topic,
                    count,
                    round(sum(c.score for c in items), 3),
                    round(acted / count, 3) if count else 0.0,
                )
            )
            keys[topic] = (acted + 1) / (count + 2)

        rows.sort(key=lambda row: (-keys[row[0]], -row[2], row[0]))
        return rows
