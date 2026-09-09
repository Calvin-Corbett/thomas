"""Pure model-profile resolution: name matching, fallback, and labelling.

Everything here needs an ``AppConfig`` and nothing else. The preference-aware
half -- ``resolve_effective_model``, ``resolve_effective_model_for_role`` and
``resolve_default_model_label`` -- moved to ``thomas/preferences/model_resolution.py``
on 2026-08-12, because reading a saved preference means touching the preferences
store, and ``thomas.preferences`` already depends on ``thomas.core``. Pointing
core back at it would close a cycle.
"""

from __future__ import annotations

from thomas.core.config import AppConfig


def resolve_model_profile_name(config: AppConfig, profile_name: str | None) -> str:
    """Resolve a model profile name case-insensitively against a config profile map."""
    requested = str(profile_name or "").strip()
    if not requested:
        return ""
    if requested in config.models:
        return requested
    requested_l = requested.lower()
    for profile in config.models:
        if profile.lower() == requested_l:
            return profile
    return ""


def _model_fallback_profile(config: AppConfig) -> str:
    """Return a deterministic fallback profile from config/defaults."""
    configured_default = str(config.default_model or "").strip()
    resolved_default = resolve_model_profile_name(config, configured_default)
    if resolved_default:
        return resolved_default
    for profile in config.models:
        if str(profile or "").strip():
            return str(profile)
    return ""


def build_model_label(profile: str, model_id: str) -> str:
    profile_text = str(profile or "").strip() or ""
    model_text = str(model_id or "").strip() or ""
    if profile_text and model_text:
        return f"{profile_text} / {model_text}"
    return profile_text or model_text
