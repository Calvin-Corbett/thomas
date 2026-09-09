from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Nudge:
    title: str
    text: str
    kind: str = "next_move"
    confidence: float = 0.55


class NudgeEngine:
    def __init__(self, *, cooldown_sec: int = 30, max_per_minute: int = 2, max_per_session: int = 18):
        self.cooldown_sec = cooldown_sec
        self.max_per_minute = max_per_minute
        self.max_per_session = max_per_session
        self._last_ts = 0.0
        self._history: list[float] = []
        self._sent = 0

    def _can_send(self) -> bool:
        now = time.time()
        if self._sent >= self.max_per_session:
            return False
        if (now - self._last_ts) < self.cooldown_sec:
            return False
        self._history = [t for t in self._history if (now - t) <= 60.0]
        if len(self._history) >= self.max_per_minute:
            return False
        return True

    def record_sent(self):
        now = time.time()
        self._last_ts = now
        self._history.append(now)
        self._sent += 1

    def maybe_nudge(
        self,
        *,
        last_user_text: str | None,
        pinned_goals: list[dict[str, Any]] | None,
        recent_tasks: list[dict[str, Any]] | None,
        mode: str,
        quality: dict[str, Any] | None = None,
    ) -> Nudge | None:
        if not self._can_send():
            return None

        pinned_goals = pinned_goals or []
        recent_tasks = recent_tasks or []

        # Heuristic rules — keep it deterministic and explainable.
        # You can replace with a model later; keep the same output schema.
        if pinned_goals:
            g = pinned_goals[0]
            title = str(g.get("title", "Pinned goal"))
            return Nudge(
                title="Next move",
                text=f"You have a pinned goal: '{title}'. Want me to draft the next concrete step or a checklist?",
                kind="goal_followup",
                confidence=0.62,
            )

        # If user asked for something actionable, propose immediate structure.
        if last_user_text and any(
            k in last_user_text.lower() for k in ["build", "implement", "create", "ship", "zip", "patch"]
        ):
            return Nudge(
                title="Next move",
                text="I can convert that into a scoped plan (files, endpoints, tests) and a merge-friendly patch outline.",
                kind="scoping",
                confidence=0.60,
            )

        # If recent tasks exist, offer progress continuation.
        if recent_tasks:
            t = recent_tasks[0]
            return Nudge(
                title="Continue",
                text=f"Last task was '{t.get('title', '(task)')}'. Want to resume where you left off?"
                f" I can summarize state + next actions.",
                kind="task_resume",
                confidence=0.58,
            )

        # Default: no nudge
        return None
