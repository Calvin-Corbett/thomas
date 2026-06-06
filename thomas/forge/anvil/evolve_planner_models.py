"""Data model + category vocabulary for the evolve planner.

Kept separate from the detectors and the public facade so each file stays small
and cohesive. The facade (``evolve_planner``) re-exports everything here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Categories and risk tiers
# ---------------------------------------------------------------------------

# Every improvement Thomas can make to itself falls into one of these.
CATEGORIES: tuple[str, ...] = (
    "refactor",
    "reliability",
    "efficiency",
    "security",
    "tests",
    "features",
    "docs",
    "ux",
)

# Risk tier per category -- consumed by the autonomy gate (evolve_autonomy.py)
# to decide what may auto-promote vs. what must wait for a human tap.
CATEGORY_RISK: dict[str, str] = {
    "refactor": "low",
    "reliability": "low",
    "tests": "low",
    "docs": "low",
    "efficiency": "medium",
    "features": "medium",
    "ux": "medium",
    "security": "high",
}

# Natural-language aliases so a chat "focus on hardening" maps to a category.
FOCUS_ALIASES: dict[str, str] = {
    "harden": "security",
    "hardening": "security",
    "secure": "security",
    "security": "security",
    "perf": "efficiency",
    "performance": "efficiency",
    "speed": "efficiency",
    "latency": "efficiency",
    "efficiency": "efficiency",
    "feature": "features",
    "features": "features",
    "test": "tests",
    "tests": "tests",
    "testing": "tests",
    "coverage": "tests",
    "refactor": "refactor",
    "refactoring": "refactor",
    "cleanup": "refactor",
    "reliability": "reliability",
    "resilience": "reliability",
    "robustness": "reliability",
    "docs": "docs",
    "documentation": "docs",
    "ux": "ux",
    "ui": "ux",
    "polish": "ux",
}

FOCUS_WEIGHT = 1.6  # score multiplier applied to goals matching the focus

# Lower risk sorts first on ties (we prefer the safe win when scores match).
RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def normalize_focus(focus: str) -> str:
    """Map a free-text focus hint to a canonical category, or '' if none."""
    key = str(focus or "").strip().lower()
    if not key:
        return ""
    if key in CATEGORY_RISK:
        return key
    return FOCUS_ALIASES.get(key, "")


def risk_for_category(category: str) -> str:
    return CATEGORY_RISK.get(str(category or "").lower(), "medium")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slug(text: str, *, limit: int = 48) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (cleaned[:limit] or "goal").strip("-")


def goal_id(category: str, key: str) -> str:
    return f"{category}:{slug(key)}"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class EvolveGoal:
    """A single self-chosen improvement the loop can pick up and run."""

    id: str
    category: str
    title: str
    rationale: str
    goal_prompt: str
    target_paths: list[str] = field(default_factory=list)
    risk_tier: str = "medium"
    leverage: float = 0.5
    source: str = ""
    created_at: str = ""

    def score(self, focus_category: str = "") -> float:
        """Ranking score: leverage, boosted when the goal matches the focus."""
        base = max(0.0, min(1.0, float(self.leverage)))
        if focus_category and self.category == focus_category:
            base *= FOCUS_WEIGHT
        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "rationale": self.rationale,
            "goal_prompt": self.goal_prompt,
            "target_paths": list(self.target_paths),
            "risk_tier": self.risk_tier,
            "leverage": round(float(self.leverage), 4),
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvolveGoal:
        return cls(
            id=str(payload.get("id") or ""),
            category=str(payload.get("category") or "refactor"),
            title=str(payload.get("title") or ""),
            rationale=str(payload.get("rationale") or ""),
            goal_prompt=str(payload.get("goal_prompt") or ""),
            target_paths=[str(p) for p in (payload.get("target_paths") or [])],
            risk_tier=str(payload.get("risk_tier") or "medium"),
            leverage=float(payload.get("leverage") or 0.5),
            source=str(payload.get("source") or ""),
            created_at=str(payload.get("created_at") or ""),
        )


@dataclass
class EvolveBacklog:
    """A ranked set of self-chosen goals plus the survey signals behind them."""

    goals: list[EvolveGoal] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    focus: str = ""
    generated_at: str = ""

    @property
    def top(self) -> EvolveGoal | None:
        return self.goals[0] if self.goals else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "goals": [g.to_dict() for g in self.goals],
            "signals": dict(self.signals),
            "focus": self.focus,
            "generated_at": self.generated_at,
            "count": len(self.goals),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvolveBacklog:
        return cls(
            goals=[EvolveGoal.from_dict(g) for g in (payload.get("goals") or [])],
            signals=dict(payload.get("signals") or {}),
            focus=str(payload.get("focus") or ""),
            generated_at=str(payload.get("generated_at") or ""),
        )
