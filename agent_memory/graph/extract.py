from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple

# Cheap, safe, rule-based extractor for v3:
# Pulls ONLY "relationships worth paying rent" (high precision, low recall).
# Upgrade later with ML extraction.

LIKES = re.compile(r"\b(i like|i love)\s+(?P<thing>[^.?!]+)", re.IGNORECASE)
HATES = re.compile(r"\b(i hate|i don\x27t like|i do not like)\s+(?P<thing>[^.?!]+)", re.IGNORECASE)

PROJECT = re.compile(r"\b(project|repo)\s+(?P<name>[A-Za-z0-9_\-]{2,})", re.IGNORECASE)

def extract_edges(text: str) -> List[Dict[str, Any]]:
    edges: List[Dict[str, Any]] = []
    m = PROJECT.search(text)
    if m:
        pname = m.group("name").strip()
        edges.append({
            "src": ("User", "self", "User"),
            "rel": "MENTIONS",
            "dst": ("Project", pname.lower(), pname),
            "confidence": 0.8,
        })
    for pat, rel in [(LIKES, "LIKES"), (HATES, "DISLIKES")]:
        m2 = pat.search(text)
        if m2:
            thing = m2.group("thing").strip()
            key = thing.lower()[:80]
            edges.append({
                "src": ("User", "self", "User"),
                "rel": rel,
                "dst": ("Preference", key, thing),
                "confidence": 0.9,
            })
    return edges
