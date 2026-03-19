from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .contradiction_review import (
    list_contradictions as list_contradictions_with_reviews,
)
from .contradiction_review import (
    list_contradictions_for_review as list_contradictions_for_review_rows,
)
from .contradiction_review import (
    review_contradiction as apply_contradiction_review,
)
from .contradiction_review import (
    severity_route as contradiction_severity_route,
)
from .contradiction_review import (
    upsert_review_state as upsert_contradiction_review_state,
)
from .contradictions import contradiction_score_for_fact
from .db import SqliteDB
from .profile_hints import extract_profile_hints
from .schema import FACTS_FTS_TRIGGERS_SQL, FTS_TRIGGERS_SQL, INIT_SQL, SCHEMA_VERSION, facts_fts_sql, fts_sql
from .scoring import SalienceInputs
from .scoring import score as salience_score
from .token import compact_lines, estimate_tokens, normalize_lines, redundancy_ratio, truncate_to_token_budget
from .types import RetrievalItem, RetrievalResult

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
log = logging.getLogger(__name__)


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
