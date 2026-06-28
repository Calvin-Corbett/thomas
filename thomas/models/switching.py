"""Natural-language model switch parsing for chat surfaces."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

_SWITCH_PREFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(switch|change|set|use)\b", re.IGNORECASE),
    re.compile(r"^\s*please\s+(switch|change|set|use)\b", re.IGNORECASE),
    re.compile(r"\b(can|could|would)\s+you\s+(please\s+)?(switch|change|set|use)\b", re.IGNORECASE),
)

_CLAUDE_HINTS = ("claude", "anthropic", "opus", "sonnet", "haiku")
_OPENAI_HINTS = ("openai", "gpt", "o1", "o3", "o4", "o5")
_GROK_HINTS = ("grok", "xai", "x.ai")


@dataclass(frozen=True)
class ModelSwitchResolution:
    profile: str
    # Empty string means "use the profile default model id".
    model_id: str
    matched_model: str
    confidence: float
    explanation: str


def _norm(text: str) -> str:
    return str(text or "").strip().lower()


def _tokenize_model(model_id: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _norm(model_id)) if t}


def is_model_switch_request(text: str) -> bool:
    raw = str(text or "")
    low = _norm(raw)
    if not low:
        return False
    if not any(p.search(raw) for p in _SWITCH_PREFIX_PATTERNS):
        return False
    return (
        "model" in low
        or any(k in low for k in _CLAUDE_HINTS)
        or any(k in low for k in _OPENAI_HINTS)
        or any(k in low for k in _GROK_HINTS)
    )


def infer_profile_candidates(
    text: str,
    *,
    current_profile: str,
    available_profiles: Iterable[str],
) -> list[str]:
    low = _norm(text)
    out: list[str] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        if not name:
            return
        n = str(name).strip()
        if not n or n in seen:
            return
        seen.add(n)
        out.append(n)

    profiles = [str(p).strip() for p in available_profiles if str(p).strip()]

    # Explicit profile mention takes priority.
    for p in profiles:
        if re.search(rf"\b{re.escape(p.lower())}\b", low):
            add(p)

    # Heuristic mapping from family hints to profile.
    if any(k in low for k in _CLAUDE_HINTS) and "anthropic" in profiles:
        add("anthropic")
    if any(k in low for k in _OPENAI_HINTS):
        if "openai" in profiles:
            add("openai")
        elif "openai_codex" in profiles:
            add("openai_codex")
    if any(k in low for k in _GROK_HINTS) and "xai" in profiles:
        add("xai")

    add(current_profile)
    # Include defaults as fallback options.
    for p in profiles:
        add(p)
    return out


def _extract_requested_version(text: str) -> str | None:
    low = _norm(text)
    m = re.search(r"\b([0-9])(?:[.\-]([0-9]))\b", low)
    if not m:
        return None
    return f"{m.group(1)}.{m.group(2)}"


def _extract_requested_family(text: str) -> str | None:
    low = _norm(text)
    for fam in ("opus", "sonnet", "haiku", "gpt", "grok"):
        if re.search(rf"\b{fam}\b", low):
            return fam
    return None


def _find_explicit_model_id(text: str, candidates: Sequence[str]) -> str | None:
    low = _norm(text)
    for model_id in candidates:
        mid = _norm(model_id)
        if mid and mid in low:
            return model_id
    # Allow raw claude-* mention even if not discovered yet.
    m = re.search(r"\b(claude-[a-z0-9\-]+)\b", low)
    if m:
        return m.group(1)
    # Allow raw grok-* mention even if not discovered yet.
    m = re.search(r"\b(grok-[a-z0-9\-]+)\b", low)
    if m:
        return m.group(1)
    return None


def _score_model_id(
    model_id: str,
    *,
    requested_family: str | None,
    requested_version: str | None,
    request_tokens: set[str],
) -> float:
    mid = _norm(model_id)
    tokens = _tokenize_model(mid)
    score = 0.0

    overlap = len(tokens.intersection(request_tokens))
    if overlap > 0:
        score += float(overlap)

    if requested_family:
        if requested_family in tokens or requested_family in mid:
            score += 8.0
        else:
            score -= 2.0

    if requested_version:
        major, minor = requested_version.split(".", 1)
        if requested_version in mid:
            score += 8.0
        if f"{major}-{minor}" in mid:
            score += 7.0
        if major in tokens and minor in tokens:
            score += 3.0

    # Prefer stable explicit IDs over generic aliases when both match.
    if re.search(r"\b\d{8}\b", mid):
        score += 0.2
    return score


def resolve_model_switch_request(
    text: str,
    *,
    current_profile: str,
    default_models: Mapping[str, str],
    discovered_models: Mapping[str, Sequence[str]],
) -> ModelSwitchResolution | None:
    if not is_model_switch_request(text):
        return None

    available_profiles = list(default_models.keys())
    profiles = infer_profile_candidates(
        text,
        current_profile=current_profile,
        available_profiles=available_profiles,
    )
    if not profiles:
        return None

    request_tokens = _tokenize_model(text)
    requested_version = _extract_requested_version(text)
    requested_family = _extract_requested_family(text)

    best: tuple[float, str, str] | None = None  # score, profile, model

    for profile in profiles:
        default_id = str(default_models.get(profile) or "").strip()
        candidates: list[str] = []
        if default_id:
            candidates.append(default_id)
        for mid in discovered_models.get(profile, []):
            val = str(mid or "").strip()
            if val and val not in candidates:
                candidates.append(val)
        if not candidates:
            continue

        explicit = _find_explicit_model_id(text, candidates)
        if explicit:
            score = 999.0
            if best is None or score > best[0]:
                best = (score, profile, explicit)
            continue

        for mid in candidates:
            score = _score_model_id(
                mid,
                requested_family=requested_family,
                requested_version=requested_version,
                request_tokens=request_tokens,
            )
            if best is None or score > best[0]:
                best = (score, profile, mid)

    # If we got only low-confidence fuzzy matches and user specified no family/version/model,
    # treat as profile switch to default.
    if best is None:
        target_profile = profiles[0]
        default_id = str(default_models.get(target_profile) or "").strip()
        if not default_id:
            return None
        return ModelSwitchResolution(
            profile=target_profile,
            model_id="",
            matched_model=default_id,
            confidence=0.4,
            explanation="profile_default",
        )

    score, profile, matched_model = best
    default_id = str(default_models.get(profile) or "").strip()
    model_id = "" if matched_model == default_id else matched_model

    # Guardrail: do not switch on weak fuzzy match when a specific family/version was requested.
    if score < 1.0 and (requested_family or requested_version):
        return None

    explanation_bits: list[str] = []
    if requested_family:
        explanation_bits.append(f"family={requested_family}")
    if requested_version:
        explanation_bits.append(f"version={requested_version}")
    if not explanation_bits:
        explanation_bits.append("best_match")

    return ModelSwitchResolution(
        profile=profile,
        model_id=model_id,
        matched_model=matched_model,
        confidence=min(1.0, max(0.0, score / 12.0)),
        explanation=",".join(explanation_bits),
    )
