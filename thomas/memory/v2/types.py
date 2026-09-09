from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalItem:
    kind: str
    ref_id: str
    score: float
    snippet: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    pack_text: str
    trace_id: str
    items: list[RetrievalItem]
    latency_ms: int
    pack_tokens_est: int
