from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class TodoMarker:
    path: str
    line: int
    kind: str
    text: str
    author: str
    commit: str
    committed_at: datetime | None
    age_days: int | None
    stale: bool
