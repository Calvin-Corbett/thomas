from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import List

_SENT = re.compile(r"(?<=[.!?])\s+")

@dataclass
class SummarizeConfig:
    max_sentences: int = 6
    max_chars: int = 900

def summarize(texts: list[str], cfg: SummarizeConfig = SummarizeConfig()) -> str:
    joined = " ".join(t.strip() for t in texts if t.strip())
    if not joined:
        return ""
    sents = _SENT.split(joined)
    sents = [s.strip() for s in sents if len(s.strip()) > 0]
    if len(sents) <= cfg.max_sentences:
        out = " ".join(sents)
        return out[: cfg.max_chars]

    # centroid scoring by word frequency
    words = re.findall(r"[a-zA-Z0-9_]{3,}", joined.lower())
    freqs = Counter(words)
    if not freqs:
        out = " ".join(sents[: cfg.max_sentences])
        return out[: cfg.max_chars]
    maxf = max(freqs.values())
    for k in list(freqs.keys()):
        freqs[k] /= maxf

    scores = []
    for i, s in enumerate(sents):
        sw = re.findall(r"[a-zA-Z0-9_]{3,}", s.lower())
        if not sw:
            scores.append((i, 0.0))
            continue
        score = sum(freqs.get(w, 0.0) for w in sw) / (1.0 + math.log(2 + len(sw)))
        scores.append((i, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    keep_idx = sorted([i for i, _ in scores[: cfg.max_sentences]])
    out = " ".join(sents[i] for i in keep_idx)
    return out[: cfg.max_chars]
