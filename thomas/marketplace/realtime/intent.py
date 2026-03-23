from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Intent:
    name: str
    confidence: float
    slots: dict[str, Any] | None = None


def _has_any(text: str, patterns: list[str]) -> bool:
    t = text.lower()
    return any(p in t for p in patterns)


def predict_intent(text: str, *, context: dict[str, Any] | None = None) -> Intent:
    """Heuristic intent prediction. Replace with model-based predictor if desired."""
    t = text.strip().lower()
    if not t:
        return Intent("none", 0.0, {})

    # Action-y intents
    if _has_any(t, ["remind", "every day", "schedule", "tomorrow", "next week", "recurring"]):
        return Intent("schedule_job", 0.78, {})
    if _has_any(t, ["search", "look up", "find", "google", "web"]):
        return Intent("web_search", 0.72, {})
    if _has_any(t, ["open", "show", "file", "folder", "repo", "path"]):
        return Intent("navigate", 0.62, {})
    if _has_any(t, ["summarize", "tl;dr", "recap"]):
        return Intent("summarize", 0.70, {})
    if _has_any(t, ["pin this", "save this", "remember this", "goal"]):
        return Intent("pin_goal", 0.64, {})
    if _has_any(t, ["run tests", "pytest", "unittest", "build"]):
        return Intent("dev_action", 0.66, {})
    if t.endswith("?") or _has_any(t, ["what is", "how do", "why does", "can you"]):
        return Intent("question", 0.55, {})

    return Intent("chat", 0.45, {})


def next_action_suggestions(intent: Intent, *, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    name = intent.name
    if name == "schedule_job":
        suggestions.append({"title": "Create reminder/job", "kind": "job", "action": "open_scheduler"})
    if name == "web_search":
        suggestions.append({"title": "Open Web Search", "kind": "tool", "action": "open_search"})
    if name == "navigate":
        suggestions.append({"title": "Open File Browser", "kind": "ui", "action": "open_files"})
    if name == "pin_goal":
        suggestions.append({"title": "Pin as goal", "kind": "memory", "action": "pin_goal"})
    if name == "dev_action":
        suggestions.append({"title": "Run unit tests", "kind": "dev", "action": "run_tests"})
    if name in ("question", "chat"):
        suggestions.append({"title": "Switch to deep mode", "kind": "mode", "action": "set_mode_deep"})
        suggestions.append({"title": "Switch to fast mode", "kind": "mode", "action": "set_mode_fast"})
    return suggestions
