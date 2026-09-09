"""Validate model- or API-authored task analysis metadata.

The runtime does not score task wording. If no structured analysis is supplied,
the task proceeds with a neutral analysis and no hidden intent-review gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_COMPLEXITIES = {"simple", "moderate", "hard", "unspecified"}
_EFFORTS = {"brisk", "diligent", "exhaustive", ""}


@dataclass(frozen=True)
class TaskAnalysis:
    clarity_score: int
    complexity: str
    recommended_effort: str
    needs_intent_review: bool


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def normalize_task_analysis(value: Mapping[str, Any] | TaskAnalysis | None = None) -> TaskAnalysis:
    """Normalize explicit analysis fields or return the neutral default."""

    if isinstance(value, TaskAnalysis):
        return value
    payload = dict(value) if isinstance(value, Mapping) else {}
    complexity = str(payload.get("complexity") or "unspecified").strip().lower()
    if complexity not in _COMPLEXITIES:
        complexity = "unspecified"
    recommended_effort = str(payload.get("recommended_effort") or "").strip().lower()
    if recommended_effort not in _EFFORTS:
        recommended_effort = ""
    return TaskAnalysis(
        clarity_score=_bounded_int(payload.get("clarity_score"), default=100, minimum=0, maximum=100),
        complexity=complexity,
        recommended_effort=recommended_effort,
        needs_intent_review=payload.get("needs_intent_review") is True,
    )
