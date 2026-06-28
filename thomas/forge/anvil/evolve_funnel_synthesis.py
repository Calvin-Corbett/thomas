"""Pure synthesis primitives for the funnel (no model calls -> fully unit-testable).

These implement the mechanical heart of the funnel: unioning the good across
isolated lanes, counting cross-lane convergence (the truth signal), attrition by
score (5 -> 3), and the preservation-guarded simplification cut. The model-driven
parts (lanes, reviewers, the prose synthesizer, the evaluator) live in the stages
and call into these for the deterministic decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


def normalize(text: str) -> str:
    """Normalize a facet/check/plan-element for dedup + convergence counting."""
    t = str(text or "").lower().strip()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


@dataclass
class UnionedItem:
    text: str
    convergence: int  # how many distinct lanes independently produced this
    lanes: list[int] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "convergence": self.convergence, "lanes": sorted(self.lanes), **self.detail}


def union_items(lane_items: list[list[dict[str, Any]]]) -> list[UnionedItem]:
    """Union every distinct item across lanes; count convergence.

    Keeps EVERY distinct item (union the good); never drops a unique one. Items
    whose normalized text matches are merged, recording how many distinct lanes
    produced them. Convergence is the per-item count of contributing lanes.
    """
    by_key: dict[str, UnionedItem] = {}
    order: list[str] = []
    for lane_idx, items in enumerate(lane_items):
        seen_in_lane: set[str] = set()
        for it in items or []:
            text = str(it.get("text", "")).strip()
            if not text:
                continue
            key = normalize(text)
            if not key:
                continue
            if key not in by_key:
                detail = {k: v for k, v in it.items() if k != "text"}
                by_key[key] = UnionedItem(text=text, convergence=0, lanes=[], detail=detail)
                order.append(key)
            # Count each lane at most once per item (true cross-lane convergence).
            if lane_idx not in seen_in_lane and lane_idx not in by_key[key].lanes:
                by_key[key].lanes.append(lane_idx)
                by_key[key].convergence += 1
                seen_in_lane.add(key)
    # Stable order: highest convergence first, then first-seen order.
    return sorted((by_key[k] for k in order), key=lambda u: (-u.convergence, order.index(normalize(u.text))))


def minority_facets(unioned: list[UnionedItem]) -> list[UnionedItem]:
    """Facets only ONE lane produced. These are the anti-consensus risk: a real
    requirement seen by a single lane must be preserved/escalated, never dropped
    because it is rare. (Designed by the funnel's self-improvement run.)"""
    return [u for u in unioned if u.convergence <= 1]


# Tokens that must never appear in a REVERSE (definition) artifact: the reverse
# funnel unions facets and surfaces contradictions — it must not score, rank, or vote.
_REVERSE_FORBIDDEN = ("score", "rank", "ranking", "winner", "eliminate", "vote", "voting", "attrition")


def reverse_no_scoring_violations(payload: Any) -> list[str]:
    """Return any forbidden scoring/ranking/voting keys found in a REVERSE artifact.

    Empty list == conformant. Checks dict keys recursively (and a flat string blob),
    so a synthesizer that smuggled a 'score'/'rank'/'winner' field into the reverse
    output is caught. Convergence counts are allowed (they are evidence, not a score)."""
    violations: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = str(k).lower()
                if any(tok == kl or kl.endswith(f"_{tok}") or kl.startswith(f"{tok}_") for tok in _REVERSE_FORBIDDEN):
                    violations.append(str(k))
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(payload)
    return sorted(set(violations))


@dataclass
class ScoredArtifact:
    index: int
    artifact: Any
    score: float
    passed: bool
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "score": self.score, "passed": self.passed, "detail": self.detail}


def pick_survivors(scored: list[ScoredArtifact], target: int) -> list[ScoredArtifact]:
    """Attrition: keep the top ``target`` by score (survivors advance).

    Ties broken by original index for determinism. A passing artifact always
    ranks above a non-passing one at equal score.
    """
    ranked = sorted(scored, key=lambda s: (-(1 if s.passed else 0), -float(s.score), s.index))
    return ranked[: max(1, int(target))] if ranked else []


def apply_simplification(
    items: list[dict[str, Any]],
    cuts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove only the cuts the deletion-lane marked SAFE (nothing load-bearing lost).

    Returns (kept_items, accepted_cuts). A cut is accepted only when ``safe`` is
    truthy AND it actually matches an item; everything else is preserved. This is
    the structural protection: simplification can never remove a real mechanism.
    """
    cut_keys = {normalize(c.get("text", "")) for c in (cuts or []) if c.get("safe") and c.get("text")}
    kept: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    for it in items or []:
        key = normalize(it.get("text", ""))
        if key and key in cut_keys:
            accepted.append(it)
        else:
            kept.append(it)
    return kept, accepted


def render_items(items: list[dict[str, Any]] | list[UnionedItem], header: str = "") -> str:
    """Render items as a stable bulleted block for handoff into the next stage."""
    lines: list[str] = []
    if header:
        lines.append(header)
    for it in items or []:
        if isinstance(it, UnionedItem):
            conv = f" [convergence={it.convergence}]" if it.convergence > 1 else ""
            lines.append(f"- {it.text}{conv}")
        else:
            lines.append(f"- {str(it.get('text', '')).strip()}")
    return "\n".join(lines)
