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


def _read_user_model_prefs(config: AppConfig, *, user_id: str, db_path: str | None = None) -> tuple[str, str]:
    """Read persisted user model preferences.

    Returns ``(active_profile, model_id)`` when available. Unknown or malformed
    values are ignored.
    """
    if not user_id:
        return "", ""
    try:
        from thomas.server.model_preferences import read_user_model_preferences

        preferred_profile, preferred_model_id = read_user_model_preferences(user_id=user_id, db_path=db_path)
    except Exception:
        return "", ""

    preferred_profile = resolve_model_profile_name(config, preferred_profile)
    if not preferred_profile:
        return "", ""
    return preferred_profile, preferred_model_id


def resolve_effective_model(
    config: AppConfig,
    *,
    cli_profile: str | None = None,
    env_profile: str | None = None,
    user_id: str = "default",
    db_path: str | None = None,
) -> tuple[str, str]:
    """Resolve active model profile and optional model-id override.

    Precedence is: CLI flag -> env var -> user prefs -> project default -> first model.
    Model-id is read from user prefs when the selected profile came from or matches
    persisted user profile data.
    """
    candidate_profile = resolve_model_profile_name(config, cli_profile)
    if not candidate_profile:
        candidate_profile = resolve_model_profile_name(config, env_profile)

    user_profile = ""
    user_model_id = ""
    if candidate_profile:
        candidate_profile = resolve_model_profile_name(config, candidate_profile)

    if not candidate_profile:
        user_profile, user_model_id = _read_user_model_prefs(config, user_id=user_id or "default", db_path=db_path)
        if user_profile:
            candidate_profile = user_profile

    if not candidate_profile:
        candidate_profile = _model_fallback_profile(config)

    active_model_id = ""
    if user_profile and candidate_profile and user_profile == candidate_profile:
        active_model_id = user_model_id
    return candidate_profile, active_model_id


def build_model_label(profile: str, model_id: str) -> str:
    profile_text = str(profile or "").strip() or ""
    model_text = str(model_id or "").strip() or ""
    if profile_text and model_text:
        return f"{profile_text} / {model_text}"
    return profile_text or model_text


def resolve_default_model_label(
    config: AppConfig, *, env_profile: str | None = None, user_id: str = "default", db_path: str | None = None
) -> str:
    profile, model_id = resolve_effective_model(
        config,
        cli_profile=None,
        env_profile=env_profile,
        user_id=user_id,
        db_path=db_path,
    )
    return build_model_label(
        profile,
        str(
            config.models.get(profile).model
            if model_id == "" and profile and profile in config.models
            else model_id or ""
        ),
    )
