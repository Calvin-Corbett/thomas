"""Conversation-driven UI control resolution.

This module turns natural-language control requests into a generic UI state patch.
It is intentionally surface-agnostic: adding a new setting should only require
updating the setting spec registry below.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from thomas.core.autonomy import autonomy_level_name, clamp_autonomy_level
from thomas.models.switching import ModelSwitchResolution

_DIRECTIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(set|change|switch|use|turn|enable|disable|show|hide|open|close)\b", re.IGNORECASE),
    re.compile(r"^\s*i\s+(want|need|prefer)\b", re.IGNORECASE),
    re.compile(r"\b(can|could|would)\s+you\b", re.IGNORECASE),
    re.compile(r"\bplease\b", re.IGNORECASE),
)

_MODE_VALUES: tuple[str, ...] = ("auto", "fast", "thinking")

_ENABLE_MARKERS: tuple[str, ...] = (
    "turn on",
    "switch on",
    "enable",
    "show",
    "open",
    "activate",
    "start",
)
_DISABLE_MARKERS: tuple[str, ...] = (
    "turn off",
    "switch off",
    "disable",
    "hide",
    "close",
    "deactivate",
    "stop",
    "do not",
    "don't",
)


@dataclass(frozen=True)
class UiControlResolution:
    patch: dict[str, Any]
    operations: list[dict[str, Any]]
    confirmation: str


_BOOLEAN_SETTING_SPECS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "showToolDetails",
        (
            "tool details",
            "tool detail",
            "tool call details",
            "thinking details",
            "show tools by default",
        ),
        "tool details",
    ),
    (
        "showInspector",
        (
            "inspector",
            "debug panel",
            "inspector panel",
            "right panel",
        ),
        "inspector",
    ),
    (
        "voiceConversation",
        (
            "voice conversation",
            "hands free voice",
            "hands-free voice",
            "always listening",
            "voice mode",
        ),
        "voice conversation",
    ),
    (
        "voiceAutoSend",
        (
            "voice auto send",
            "voice autosend",
            "auto send voice",
        ),
        "voice auto-send",
    ),
    (
        "ttsEnabled",
        (
            "text to speech",
            "tts",
            "voice replies",
            "speak replies",
            "read replies aloud",
        ),
        "text-to-speech",
    ),
)

_THEME_ALIASES: tuple[str, ...] = ("theme", "appearance mode", "ui theme")
_THEME_VALUES: tuple[str, ...] = ("light", "dark", "system")

_AUTONOMY_HINTS: dict[int, tuple[str, ...]] = {
    1: ("level 1", "l1", "manual review", "manual mode", "review-first"),
    2: ("level 2", "l2", "guarded assist", "guarded mode", "approved tasks"),
    3: ("level 3", "l3", "tool-bounded auto", "bounded auto", "normal auto"),
    4: ("level 4", "l4", "full auto", "max autonomy", "fully autonomous"),
}

_CONTROL_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(set|change|switch|use|run|turn|enable|disable|show|hide|open|close|update|make)\b", re.IGNORECASE),
    re.compile(r"\bmode\s*(to|=|:)\b", re.IGNORECASE),
    re.compile(r"\bautonomy\s*(to|level|=|:)\b", re.IGNORECASE),
    re.compile(r"\btheme\s*(to|=|:)\b", re.IGNORECASE),
)

_QUESTION_PREFIXES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(why|what|how|is|are|was|were|can|could|would|do|does|did)\b", re.IGNORECASE),
)

_AUTONOMY_SHORTHAND_COMMANDS: tuple[str, ...] = (
    "full auto",
    "max autonomy",
    "fully autonomous",
    "manual review",
    "manual mode",
    "guarded assist",
    "guarded mode",
    "tool-bounded auto",
    "bounded auto",
    "normal auto",
)


def _norm(text: str) -> str:
    return str(text or "").strip().lower()


def _is_directive(text: str) -> bool:
    raw = str(text or "")
    low = _norm(raw)
    if not low:
        return False
    return any(p.search(raw) for p in _DIRECTIVE_PATTERNS)


def _contains_alias(low: str, aliases: Sequence[str]) -> bool:
    return any(a in low for a in aliases)


def _is_question_like(text: str) -> bool:
    raw = str(text or "").strip()
    low = _norm(raw)
    if not low:
        return False
    if "?" in raw:
        return True
    return any(p.search(raw) for p in _QUESTION_PREFIXES)


def _has_explicit_control_intent(text: str) -> bool:
    raw = str(text or "")
    if not raw.strip():
        return False
    return any(p.search(raw) for p in _CONTROL_INTENT_PATTERNS)


def _is_autonomy_shorthand_command(low: str) -> bool:
    return low in _AUTONOMY_SHORTHAND_COMMANDS


def _parse_bool_intent(low: str) -> bool | None:
    has_on = any(marker in low for marker in _ENABLE_MARKERS)
    has_off = any(marker in low for marker in _DISABLE_MARKERS)
    if has_on and not has_off:
        return True
    if has_off and not has_on:
        return False

    explicit = re.search(r"\b(on|off|true|false|enabled|disabled)\b", low)
    if not explicit:
        return None
    value = explicit.group(1)
    if value in {"on", "true", "enabled"}:
        return True
    if value in {"off", "false", "disabled"}:
        return False
    return None


def _parse_mode(text: str, *, directive: bool) -> str | None:
    low = _norm(text)
    if "autonomy" in low and "mode" not in low:
        return None
    if "mode" not in low:
        return None
    explicit_control = _has_explicit_control_intent(text)
    if _is_question_like(text) and not explicit_control:
        return None
    if not explicit_control and not directive:
        return None

    explicit_patterns = (
        rf"\b(?:set|change|switch)\s+(?:the\s+)?mode\s+(?:to\s+)?(?P<mode>{'|'.join(_MODE_VALUES)})\b",
        rf"\b(?:use|run)\s+(?:in\s+)?(?P<mode>{'|'.join(_MODE_VALUES)})\s+mode\b",
        rf"\bmode\s*(?:to|=|:)\s*(?P<mode>{'|'.join(_MODE_VALUES)})\b",
    )
    for pat in explicit_patterns:
        m = re.search(pat, low)
        if m:
            return str(m.group("mode") or "").strip().lower() or None

    # Short imperative fallback (e.g. "thinking mode")
    if explicit_control and len(low.split()) <= 4:
        m = re.search(rf"\b(?P<mode>{'|'.join(_MODE_VALUES)})\s+mode\b", low)
        if m:
            return str(m.group("mode") or "").strip().lower() or None
    return None


def _parse_theme(text: str, *, directive: bool) -> str | None:
    low = _norm(text)
    if not directive and not _contains_alias(low, _THEME_ALIASES):
        return None
    if not _contains_alias(low, _THEME_ALIASES):
        return None
    for val in _THEME_VALUES:
        if re.search(rf"\b{re.escape(val)}\b", low):
            return val
    return None


def _parse_autonomy_level(text: str, *, directive: bool) -> int | None:
    low = _norm(text)
    explicit_control = _has_explicit_control_intent(text)
    if _is_question_like(text) and not explicit_control:
        return None
    shorthand = _is_autonomy_shorthand_command(low)

    has_autonomy_keyword = bool(re.search(r"\bautonomy\b", low)) or bool(re.search(r"\bautonomous\b", low))
    has_explicit_phrase = any(
        phrase in low
        for phrase in (
            "full auto",
            "max autonomy",
            "fully autonomous",
            "manual review",
            "manual mode",
            "guarded assist",
            "guarded mode",
            "tool-bounded auto",
            "bounded auto",
            "normal auto",
        )
    )
    likely = shorthand or (
        explicit_control
        and (
            has_autonomy_keyword
            or has_explicit_phrase
            or bool(re.search(r"\blevel\s*[1-4]\b", low))
            or bool(re.search(r"\bl[1-4]\b", low))
        )
    )
    if not likely:
        return None

    m = re.search(r"\blevel\s*([1-4])\b", low)
    if m:
        return clamp_autonomy_level(m.group(1), default=3)
    m = re.search(r"\bl([1-4])\b", low) if (explicit_control or has_autonomy_keyword) else None
    if m:
        return clamp_autonomy_level(m.group(1), default=3)

    for level, hints in _AUTONOMY_HINTS.items():
        for hint in hints:
            if re.fullmatch(r"l[1-4]", hint):
                if not (explicit_control or has_autonomy_keyword):
                    continue
                if re.search(rf"\b{re.escape(hint)}\b", low):
                    return int(level)
                continue
            if hint in low:
                return int(level)
    return None


def _build_confirmation(operations: Sequence[Mapping[str, Any]]) -> str:
    bits: list[str] = []
    for op in operations:
        summary = str(op.get("summary") or "").strip()
        if summary:
            bits.append(summary)
    if not bits:
        return "Updated requested settings."
    if len(bits) == 1:
        return f"Updated {bits[0]}."
    return "Updated " + "; ".join(bits) + "."


def _is_conversational_not_control(text: str) -> bool:
    """Detect messages that are clearly conversational, not control directives.

    This prevents the control resolver from hijacking normal questions
    that happen to contain words like 'can you', 'please', or 'I want'.
    """
    low = _norm(text)
    if not low:
        return False
    word_count = len(low.split())

    # Long messages (>8 words) that end with '?' are almost always questions
    if "?" in text and word_count > 6:
        # Unless they explicitly mention a control target
        control_targets = (
            "mode",
            "theme",
            "autonomy",
            "tool details",
            "inspector",
            "voice",
            "tts",
            "text to speech",
            "auto send",
        )
        if not any(ct in low for ct in control_targets):
            return True

    # Common conversational patterns that shouldn't trigger control
    _conv_pats = (
        re.compile(
            r"^\s*(?:can|could|would)\s+you\s+(?:help|tell|explain|show|write|make|create|find|do|fix|check|build|look)\b",
            re.I,
        ),
        re.compile(
            r"^\s*(?:please|pls)\s+(?:help|tell|explain|show|write|make|create|find|do|fix|check|build|look)\b", re.I
        ),
        re.compile(
            r"^\s*i\s+(?:want|need|prefer)\s+(?:you\s+)?to\s+(?:help|tell|explain|show|write|make|create|find|do|fix|check|build|look)\b",
            re.I,
        ),
        re.compile(r"^\s*(?:what|how|why|where|when|who)\b", re.I),
    )
    for pat in _conv_pats:
        if pat.search(text):
            control_targets = (
                "mode",
                "theme",
                "autonomy",
                "tool details",
                "inspector",
                "voice",
                "tts",
                "text to speech",
                "auto send",
            )
            if not any(ct in low for ct in control_targets):
                return True

    return False


def resolve_ui_control_request(
    text: str,
    *,
    model_switch: ModelSwitchResolution | None = None,
) -> UiControlResolution | None:
    low = _norm(text)

    # Guard: don't hijack normal conversational messages
    if _is_conversational_not_control(text) and model_switch is None:
        return None

    directive = _is_directive(text)
    explicit_control = _has_explicit_control_intent(text)
    shorthand_autonomy = _is_autonomy_shorthand_command(low)
    settings_directive = (directive and explicit_control) or shorthand_autonomy

    patch: dict[str, Any] = {}
    operations: list[dict[str, Any]] = []

    if model_switch is not None:
        profile = str(model_switch.profile or "").strip()
        model_override = str(model_switch.model_id or "").strip()
        matched_model = str(model_switch.matched_model or model_override).strip()
        if profile:
            patch["activeProfile"] = profile
        patch["activeModelId"] = model_override
        operations.append(
            {
                "kind": "model",
                "key": "model",
                "value": matched_model,
                "profile": profile,
                "model_id": model_override,
                "active_model": matched_model,
                "confidence": float(model_switch.confidence),
                "explanation": str(model_switch.explanation or ""),
                "summary": f"model to {profile}/{matched_model}" if profile else f"model to {matched_model}",
            }
        )

    if settings_directive:
        mode_val = _parse_mode(text, directive=directive)
        if mode_val:
            patch["mode"] = mode_val
            operations.append(
                {
                    "kind": "mode",
                    "key": "mode",
                    "value": mode_val,
                    "summary": f"mode to {mode_val}",
                    "confidence": 0.8,
                    "explanation": "mode_directive",
                }
            )

        settings_patch: dict[str, Any] = {}
        for setting_key, aliases, label in _BOOLEAN_SETTING_SPECS:
            if not _contains_alias(low, aliases):
                continue
            desired = _parse_bool_intent(low)
            if desired is None:
                continue
            settings_patch[setting_key] = bool(desired)
            operations.append(
                {
                    "kind": "setting",
                    "key": setting_key,
                    "value": bool(desired),
                    "summary": f"{label} {'on' if desired else 'off'}",
                    "confidence": 0.78,
                    "explanation": "boolean_setting_directive",
                }
            )

        theme_val = _parse_theme(text, directive=directive)
        if theme_val:
            settings_patch["theme"] = theme_val
            operations.append(
                {
                    "kind": "setting",
                    "key": "theme",
                    "value": theme_val,
                    "summary": f"theme to {theme_val}",
                    "confidence": 0.82,
                    "explanation": "theme_directive",
                }
            )

        autonomy_level = _parse_autonomy_level(text, directive=directive)
        if autonomy_level is not None:
            settings_patch["autonomyLevel"] = int(autonomy_level)
            operations.append(
                {
                    "kind": "setting",
                    "key": "autonomyLevel",
                    "value": int(autonomy_level),
                    "summary": f"autonomy to L{autonomy_level} {autonomy_level_name(autonomy_level)}",
                    "confidence": 0.86,
                    "explanation": "autonomy_level_directive",
                }
            )

        if settings_patch:
            patch["settings"] = settings_patch

    if not operations:
        return None

    return UiControlResolution(
        patch=patch,
        operations=operations,
        confirmation=_build_confirmation(operations),
    )
