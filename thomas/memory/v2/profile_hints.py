from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ProfileHint:
    key: str
    value: str
    confidence: float


_PATTERNS = [
    (re.compile(r"\bmy name is ([A-Za-z][A-Za-z' -]{0,40})\b", re.I), "user.name", 0.92),
    (re.compile(r"\bi am ([A-Za-z][A-Za-z' -]{0,40})\b", re.I), "user.name", 0.70),
    (re.compile(r"\bmy son(?:'s)? name is ([A-Za-z][A-Za-z' -]{0,40})\b", re.I), "family.son_name", 0.9),
    (re.compile(r"\bmy daughter(?:'s)? name is ([A-Za-z][A-Za-z' -]{0,40})\b", re.I), "family.daughter_name", 0.9),
    (re.compile(r"\bi run ([A-Za-z0-9][A-Za-z0-9'& .-]{1,80})\b", re.I), "user.org", 0.78),
    (re.compile(r"\bi prefer ([^.,;\n]{1,80})", re.I), "user.preference", 0.72),
]


def _clean(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "").strip()).strip(" .,:;")


def extract_profile_hints(text: str) -> list[ProfileHint]:
    src = text or ""
    out: list[ProfileHint] = []
    seen = set()
    for rx, key, conf in _PATTERNS:
        for m in rx.finditer(src):
            val = _clean(m.group(1))
            if not val:
                continue
            k = (key, val.lower())
            if k in seen:
                continue
            seen.add(k)
            out.append(ProfileHint(key=key, value=val, confidence=float(conf)))
    return out
