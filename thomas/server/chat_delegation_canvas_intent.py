"""Fail-closed intent classification for Thomas Canvas routing."""

from __future__ import annotations

import re

_NON_VISUAL_CONTEXT_RE = re.compile(
    r"\b(?:chart\s+of\s+accounts|graph\s+(?:database|query|theory)|"
    r"(?:medical|patient|astrology|birth)\s+chart|plot\s+(?:summary|of\s+(?:the\s+)?(?:story|book|movie)))\b",
    re.IGNORECASE,
)
_VISUAL_OBJECT_RE = re.compile(
    r"\b(?:pie|bar|line|area|scatter|gantt|org(?:anization(?:al)?)?)\s+(?:chart|graph|plot)\b|"
    r"\b(?:chart|graph|plot|dashboard|histogram|heat\s*map|timeline|mind\s*map|flow\s*chart|"
    r"diagram|mock\s*up|wireframe|infographic|logo|poster|banner|landing\s+page|web\s*page|"
    r"ui\s+(?:design|mockup)|illustration|picture|image|drawing|svg|playable\s+(?:browser\s+)?game|"
    r"interactive\s+(?:chart|graph|dashboard|site|app|visual))\b",
    re.IGNORECASE,
)
_VISUAL_ACTION_RE = re.compile(
    r"\b(?:create|make|draw|sketch|design|paint|illustrate|render|visuali[sz]e|generate|build|"
    r"show|display|present|turn\s+.+?\s+into)\b",
    re.IGNORECASE,
)
_LEADING_VISUAL_RE = re.compile(
    r"^\s*(?:(?:please|can\s+you|could\s+you)\s+)?(?:a\s+|an\s+|the\s+)?"
    r"(?:chart|graph|plot|dashboard|histogram|heat\s*map|timeline|mind\s*map|flow\s*chart|diagram|"
    r"mock\s*up|wireframe|infographic|logo|poster|banner|landing\s+page|illustration|drawing)\b",
    re.IGNORECASE,
)
_NAMED_DELIVERABLE_RE = re.compile(
    r"\b[A-Za-z0-9][A-Za-z0-9_.-]*\."
    r"(?:md|rst|txt|json|ya?ml|xml|csv|tsv|sql|html?|pdf|docx|xlsx|pptx|zip|"
    r"py|go|rs|java|c|cpp|h|js|mjs|ts|tsx|jsx|vue|svelte|css|svg|png|jpe?g|gif|webp)\b",
    re.IGNORECASE,
)
_NAMED_OUTPUT_CUE_RE = re.compile(
    r"(?:\b(?:named|called|saved\s+as|exported\s+as|write(?:n)?\s+to|output(?:\s+to)?|"
    r"deliver(?:\s+as)?|as|to|into|in)\s+|"
    r"\b(?:create|make|write|save|export|produce|generate|build|draft)\s+(?:an?\s+)?(?:file\s+)?)$",
    re.IGNORECASE,
)
_NAMED_SOURCE_CUE_RE = re.compile(
    r"\b(?:from|using|based\s+(?:on|upon)|read|load|input|source|data(?:\s+is)?\s+in)\s+$",
    re.IGNORECASE,
)
_CANVAS_EXPORT_NAMES = frozenset({"chart.pdf", "chart.png", "chart-data.csv", "chart-data.xlsx"})


def _named_outputs(text: str) -> set[str]:
    outputs: set[str] = set()
    for match in _NAMED_DELIVERABLE_RE.finditer(text):
        prefix = text[max(0, match.start() - 80) : match.start()]
        if _NAMED_SOURCE_CUE_RE.search(prefix):
            continue
        if _NAMED_OUTPUT_CUE_RE.search(prefix):
            outputs.add(match.group(0).lower())
    return outputs


def is_canvas_task(prompt: str) -> bool:
    """Return true only for an actual request to create a visual artifact."""

    text = re.sub(r"\s+", " ", str(prompt or "")).strip()
    if not text:
        return False
    named_outputs = _named_outputs(text)
    if named_outputs and not named_outputs.issubset(_CANVAS_EXPORT_NAMES):
        return False
    candidate = _NON_VISUAL_CONTEXT_RE.sub(" ", text)
    if not _VISUAL_OBJECT_RE.search(candidate):
        return False
    return bool(_VISUAL_ACTION_RE.search(candidate) or _LEADING_VISUAL_RE.search(candidate))


__all__ = ["is_canvas_task"]
