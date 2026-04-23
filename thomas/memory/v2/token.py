from __future__ import annotations

from typing import Iterable, List, Tuple


def estimate_tokens(text: str) -> int:
    """Cheap token estimate good enough for budgeting."""
    if not text:
        return 0
    # Rough rule-of-thumb used for prompt sizing.
    return max(1, (len(text) + 3) // 4)


def normalize_lines(text: str) -> List[str]:
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    # Keep structure but drop repeated blank runs.
    out: List[str] = []
    blank = False
    for ln in lines:
        if ln.strip():
            out.append(ln)
            blank = False
            continue
        if not blank:
            out.append("")
            blank = True
    return out


def redundancy_ratio(lines: Iterable[str]) -> float:
    items = [str(x).strip() for x in lines if str(x).strip()]
    if not items:
        return 0.0
    uniq = len(set(items))
    return max(0.0, min(1.0, 1.0 - (uniq / float(len(items)))))


def compact_lines(lines: List[str], max_lines: int = 2000) -> List[str]:
    seen = set()
    out: List[str] = []
    for ln in lines:
        key = ln.strip().lower()
        # Keep section headers and non-content lines even if repeated.
        if key and not (key.startswith("[") and key.endswith("]")):
            if key in seen:
                continue
            seen.add(key)
        out.append(ln)
        if len(out) >= max(1, int(max_lines)):
            break
    return out


def truncate_to_token_budget(text: str, budget_tokens: int) -> Tuple[str, int]:
    budget = max(1, int(budget_tokens))
    if estimate_tokens(text) <= budget:
        return text, estimate_tokens(text)

    words = (text or "").split()
    if not words:
        return "", 0

    # Binary search for the largest word prefix that fits.
    lo, hi = 1, len(words)
    best = 1
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = " ".join(words[:mid])
        tok = estimate_tokens(cand)
        if tok <= budget:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    out = " ".join(words[:best]).strip()
    if out and best < len(words):
        out += "\n... (memory pack truncated)"
    return out, estimate_tokens(out)

