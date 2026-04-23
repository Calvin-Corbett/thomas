from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _age_hours(now_ms: int, ts_ms: int) -> float:
    return max(0.0, (now_ms - ts_ms) / 1000.0 / 3600.0)


def _tokenize(s: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(s or "") if len(t) >= 2]


def _overlap_boost(query_toks: Sequence[str], text: str) -> float:
    if not query_toks:
        return 0.0
    toks = set(_tokenize(text))
    if not toks:
        return 0.0
    hit = sum(1 for t in set(query_toks) if t in toks)
    return min(1.0, hit / max(3, len(set(query_toks))))


@dataclass
class MemorySettings:
    enabled: bool = True
    include_thread: bool = True
    include_global: bool = True
    include_profile: bool = True
    pins_only: bool = False
    max_pack_tokens: int = 1200
    max_results: int = 30
    decay_half_life_hours: float = 240.0
    auto_compact_enabled: bool = True
    auto_compact_episode_threshold: int = 2000
    auto_compact_min_interval_hours: float = 24.0
    auto_optimize_enabled: bool = True
    auto_optimize_waste_threshold: float = 0.22
    auto_optimize_min_interval_hours: float = 12.0
