"""Conversation-driven UI control resolution.

This module turns natural-language control requests into a generic UI state patch.
It is intentionally surface-agnostic: adding a new setting should only require
updating the setting spec registry below.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from thomas.core.autonomy import autonomy_level_name, clamp_autonomy_level
from thomas.models.switching import ModelSwitchResolution


_DIRECTIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(set|change|switch|use|turn|enable|disable|show|hide|open|close)\b", re.IGNORECASE),
    re.compile(r"^\s*i\s+(want|need|prefer)\b", re.IGNORECASE),
    re.compile(r"\b(can|could|would)\s+you\b", re.IGNORECASE),
    re.compile(r"\bplease\b", re.IGNORECASE),
)

_MODE_VALUES: tuple[str, ...] = ("auto", "fast", "thinking", "swarm")

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
    patch: Dict[str, Any]
    operations: List[Dict[str, Any]]
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

_AUTONOMY_HINTS: Dict[int, tuple[str, ...]] = {
    1: ("level 1", "l1", "manual review", "manual mode", "review-first"),
    2: ("level 2", "l2", "guarded assist", "guarded mode", "approved tasks"),
    3: ("level 3", "l3", "tool-bounded auto", "bounded auto", "normal auto"),
    4: ("level 4", "l4", "full auto", "max autonomy", "fully autonomous"),
}


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


def _parse_bool_intent(low: str) -> Optional[bool]:
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


def _parse_mode(text: str, *, directive: bool) -> Optional[str]:
    low = _norm(text)
    if "autonomy" in low and "mode" not in low:
        return None
    if not directive and "mode" not in low:
        return None

    hits: List[tuple[int, str]] = []
    for mode in _MODE_VALUES:
        m = re.search(rf"\b{re.escape(mode)}\b", low)
        if m:
            hits.append((m.start(), mode))
    if not hits:
        return None

    # Prefer explicit "mode" context; otherwise fallback to first detected mode token.
    if "mode" in low or re.search(r"\b(set|switch|change|use|run)\b", low):
        hits.sort(key=lambda x: x[0])
        return hits[0][1]
    return None


def _parse_theme(text: str, *, directive: bool) -> Optional[str]:
    low = _norm(text)
    if not directive and not _contains_alias(low, _THEME_ALIASES):
        return None
    if not _contains_alias(low, _THEME_ALIASES):
        return None
    for val in _THEME_VALUES:
        if re.search(rf"\b{re.escape(val)}\b", low):
            return val
    return None


def _parse_autonomy_level(text: str, *, directive: bool) -> Optional[int]:
    low = _norm(text)
    likely = (
        bool(re.search(r"\bautonomy\b", low))
        or bool(re.search(r"\bautonomous\b", low))
        or "full auto" in low
        or bool(re.search(r"\blevel\s*[1-4]\b", low))
        or bool(re.search(r"\bl[1-4]\b", low))
    )
    if not likely and not directive:
        return None

    m = re.search(r"\blevel\s*([1-4])\b", low)
    if m:
        return clamp_autonomy_level(m.group(1), default=3)
    m = re.search(r"\bl([1-4])\b", low)
    if m:
        return clamp_autonomy_level(m.group(1), default=3)

    for level, hints in _AUTONOMY_HINTS.items():
        if any(h in low for h in hints):
            return int(level)
    return None


def _build_confirmation(operations: Sequence[Mapping[str, Any]]) -> str:
    bits: List[str] = []
    for op in operations:
        summary = str(op.get("summary") or "").strip()
        if summary:
            bits.append(summary)
    if not bits:
        return "Updated requested settings."
    if len(bits) == 1:
        return f"Updated {bits[0]}."
    return "Updated " + "; ".join(bits) + "."


def resolve_ui_control_request(
    text: str,
    *,
    model_switch: Optional[ModelSwitchResolution] = None,
) -> Optional[UiControlResolution]:
    low = _norm(text)
    directive = _is_directive(text)

    patch: Dict[str, Any] = {}
    operations: List[Dict[str, Any]] = []

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

    if directive:
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

        settings_patch: Dict[str, Any] = {}
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

    autonomy_level = _parse_autonomy_level(text, directive=directive)
    if autonomy_level is not None and not any(str(op.get("key") or "") == "autonomyLevel" for op in operations):
        settings_patch = patch.get("settings")
        if not isinstance(settings_patch, dict):
            settings_patch = {}
        settings_patch["autonomyLevel"] = int(autonomy_level)
        patch["settings"] = settings_patch
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

    if not operations:
        return None

    return UiControlResolution(
        patch=patch,
        operations=operations,
        confirmation=_build_confirmation(operations),
    )
