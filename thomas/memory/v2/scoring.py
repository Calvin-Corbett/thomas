from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SalienceInputs:
    base_salience: float
    age_hours: float
    half_life_hours: float
    retrieval_count: int
    pinned: bool
    relevance_boost: float


def score(inputs: SalienceInputs) -> float:
    """Deterministic salience score with age decay and relevance boost."""
    base = max(0.0, float(inputs.base_salience))
    age = max(0.0, float(inputs.age_hours))
    half_life = max(1.0, float(inputs.half_life_hours))
    retrieval_count = max(0, int(inputs.retrieval_count))
    relevance = max(0.0, min(1.0, float(inputs.relevance_boost)))

    # Exponential decay around half-life horizon.
    decay = 0.5 ** (age / half_life)
    # Slightly down-rank repeatedly retrieved items to diversify packs.
    novelty = 1.0 / (1.0 + (0.08 * retrieval_count))
    pin_boost = 1.25 if bool(inputs.pinned) else 1.0

    value = (base * decay * novelty * pin_boost) + (0.9 * relevance)
    return round(max(0.0, value), 6)

