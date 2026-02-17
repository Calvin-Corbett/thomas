from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Tuple
import re
import time


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9 \-']+", "", s)
    return s


def _token_set(s: str) -> set[str]:
    return set(t for t in _norm(s).split(" ") if t)


def jaccard(a: str, b: str) -> float:
    sa = _token_set(a)
    sb = _token_set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


@dataclass
class DedupeDecision:
    accept: bool
    reason: str
    similarity: float = 0.0


class STTDedupeWindow:
    """Suppresses duplicate STT emissions (common with interim/final or double pipelines)."""

    def __init__(self, window_ms: int = 3500):
        self.window_ms = window_ms
        self._items: List[Tuple[int, str, bool, float]] = []  # (ts, text, is_final, confidence)

    def decide(self, text: str, *, is_final: bool, confidence: float, ts_ms: Optional[int] = None) -> DedupeDecision:
        ts = ts_ms or int(time.time() * 1000)
        norm = _norm(text)
        if not norm:
            return DedupeDecision(False, "empty", 1.0)

        # Drop old
        cutoff = ts - self.window_ms
        self._items = [(t, s, f, c) for (t, s, f, c) in self._items if t >= cutoff]

        # Check similarity vs recent
        for (t, s, f, c) in reversed(self._items):
            sim = jaccard(norm, s)
            if sim >= 0.92:
                # If final arrives after interim with same text, accept the final and suppress the interim duplicates.
                if is_final and not f:
                    self._items.append((ts, norm, is_final, confidence))
                    return DedupeDecision(True, "final_promotes_interim", sim)
                return DedupeDecision(False, "duplicate", sim)

            # Substring suppression: "turn on the lights" vs "turn on the"
            if (norm in s or s in norm) and sim >= 0.75 and (ts - t) < min(self.window_ms, 2500):
                # prefer longer final string
                if len(norm) <= len(s) and not is_final:
                    return DedupeDecision(False, "shorter_substring", sim)

        self._items.append((ts, norm, is_final, confidence))
        return DedupeDecision(True, "new", 0.0)
