"""Model-family identity + independent-evaluator selection.

The external evaluator must be lineage-independent from the lanes: a different
model FAMILY (claude vs gpt vs gemini ...). If no disjoint family is available
we run a clearly-labeled degraded mode (annotate-only, self-veto disabled) — we
never fake independence.
"""

from __future__ import annotations

from collections.abc import Callable

__all__ = ["family_of", "lane_families", "select_independent_evaluator", "ModelInfo"]


def family_of(provider: str, model: str) -> str:
    """Coarse model-family identity from a provider name + model id."""
    p = str(provider or "").lower()
    m = str(model or "").lower()
    blob = f"{p} {m}"
    if "claude" in blob or "anthropic" in blob:
        return "anthropic"
    if "gemini" in blob or "google" in blob:
        return "google"
    if "gpt" in blob or "openai" in blob or "codex" in blob or " o1" in f" {m}" or m.startswith("o"):
        return "openai"
    if "mistral" in blob:
        return "mistral"
    if "llama" in blob or "ollama" in blob:
        return "meta"
    if "grok" in blob or "xai" in blob:
        return "xai"
    # Fall back to the provider token so distinct providers stay distinguishable.
    return p or "unknown"


# (profile name) -> (provider, model). Injected so this stays pure/testable.
ModelInfo = Callable[[str], "tuple[str, str]"]


def lane_families(lane_profiles: list[str], model_info: ModelInfo) -> set[str]:
    """The set of families used by the lanes/synthesizer (what the evaluator must avoid)."""
    fams: set[str] = set()
    for prof in lane_profiles:
        try:
            provider, model = model_info(prof)
        except Exception:  # noqa: BLE001 - unknown profile -> skip, do not crash selection
            continue
        fams.add(family_of(provider, model))
    return fams


def select_independent_evaluator(
    candidates: list[str],
    used_families: set[str],
    model_info: ModelInfo,
) -> tuple[str | None, str, bool]:
    """Pick the first candidate profile whose family is disjoint from the lanes.

    Returns (profile_or_None, family, degraded). ``degraded`` is True when no
    candidate has an independent family — caller must then annotate-only and
    disable any self-veto, and label the result as not-independent.
    """
    for prof in candidates or []:
        try:
            provider, model = model_info(prof)
        except Exception:  # noqa: BLE001
            continue
        fam = family_of(provider, model)
        if fam and fam not in used_families:
            return prof, fam, False
    return None, "", True
