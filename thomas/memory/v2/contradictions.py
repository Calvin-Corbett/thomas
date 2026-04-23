from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class ContradictionSignal:
    score: float
    reason: str


def _extract_num(s: str) -> Optional[float]:
    m = _NUM_RE.search(s or "")
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def contradiction_score_for_fact(
    old_obj: str,
    new_obj: str,
    old_polarity: int,
    new_polarity: int,
) -> Optional[ContradictionSignal]:
    old_txt = (old_obj or "").strip().lower()
    new_txt = (new_obj or "").strip().lower()
    if not old_txt or not new_txt:
        return None

    if int(old_polarity) != int(new_polarity):
        return ContradictionSignal(score=0.9, reason="polarity_conflict")

    old_num = _extract_num(old_txt)
    new_num = _extract_num(new_txt)
    if old_num is not None and new_num is not None and old_num != new_num:
        return ContradictionSignal(score=0.85, reason="numeric_mismatch")

    if old_txt != new_txt and (old_txt in ("true", "false") or new_txt in ("true", "false")):
        return ContradictionSignal(score=0.8, reason="boolean_conflict")

    return None

