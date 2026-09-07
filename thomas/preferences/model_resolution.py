"""Model resolution that consults a user's saved preferences.

Split out of ``thomas/core/model_resolution.py`` on 2026-08-12. The pure half of
that module -- name matching, fallback selection, label formatting -- needs
nothing but an ``AppConfig`` and stays in ``core``. The half below reads a saved
preference out of the sqlite-backed preferences store, and that is a dependency
``core`` is not allowed to take: ``thomas.preferences`` itself depends on
``thomas.core``, so pointing core back at it forms a cycle the architecture
fitness test correctly refuses. Living here, the edge runs one way only.

Callers that previously imported ``resolve_effective_model`` and friends from
``thomas.core.model_resolution`` import them from here instead. Nothing about
their behaviour changed in the move.
"""

from __future__ import annotations

import logging
import sqlite3

from thomas.core.config import AppConfig
from thomas.core.model_resolution import (
    _model_fallback_profile,
    build_model_label,
    resolve_model_profile_name,
)

logger = logging.getLogger(__name__)

# Reading a stored preference touches the sqlite preferences store. These are the
# failures that path can actually produce: the optional dependency is missing,
# the sqlite file is unreadable, or the stored key fails to decrypt
# (thomas/preferences/_db.py raises ValueError on a key mismatch). An empty
# result is indistinguishable from "no preference set", so the reason is logged
# rather than discarded.
_PREFERENCE_READ_ERRORS = (ImportError, OSError, sqlite3.Error, ValueError)


def _read_user_model_prefs(config: AppConfig, *, user_id: str, db_path: str | None = None) -> tuple[str, str]:
    """Read persisted user model preferences.

    Returns ``(active_profile, model_id)`` when available. Unknown or malformed
    values are ignored.
    """
    if not user_id:
        return "", ""
    try:
        from thomas.preferences.model_prefs import read_user_model_preferences

        preferred_profile, preferred_model_id = read_user_model_preferences(user_id=user_id, db_path=db_path)
    except _PREFERENCE_READ_ERRORS:
        logger.debug("model preference read failed for user %s; using fallback", user_id, exc_info=True)
        return "", ""

    preferred_profile = resolve_model_profile_name(config, preferred_profile)
    if not preferred_profile:
        return "", ""
    return preferred_profile, preferred_model_id


def _read_user_model_role_prefs(
    config: AppConfig, *, user_id: str, role: str | None, db_path: str | None = None
) -> tuple[str, str]:
    """Read persisted role-specific model preferences.

    Unknown profiles are ignored so a stale role override cannot strand startup.
    """
    resolved_role = str(role or "").strip()
    if not user_id or not resolved_role:
        return "", ""
    try:
        from thomas.preferences.model_prefs import read_user_model_role_preferences

        preferred_profile, preferred_model_id = read_user_model_role_preferences(
            user_id=user_id,
            role=resolved_role,
            db_path=db_path,
        )
    except _PREFERENCE_READ_ERRORS:
        logger.debug(
            "role model preference read failed for user %s role %s; using fallback",
            user_id,
            resolved_role,
            exc_info=True,
        )
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
    role: str | None = None,
    user_id: str = "default",
    db_path: str | None = None,
) -> tuple[str, str]:
    """Resolve active model profile and optional model-id override.

    Precedence is: CLI flag -> env var -> role prefs -> user prefs -> project default -> first model.
    Model-id is read from user prefs when the selected profile came from or matches
    persisted user profile data.
    """
    candidate_profile = resolve_model_profile_name(config, cli_profile)
    if not candidate_profile:
        candidate_profile = resolve_model_profile_name(config, env_profile)

    user_profile = ""
    user_model_id = ""
    role_profile = ""
    role_model_id = ""
    if candidate_profile:
        candidate_profile = resolve_model_profile_name(config, candidate_profile)

    if not candidate_profile and role:
        role_profile, role_model_id = _read_user_model_role_prefs(
            config,
            user_id=user_id or "default",
            role=role,
            db_path=db_path,
        )
        if role_profile:
            candidate_profile = role_profile

    if not candidate_profile:
        user_profile, user_model_id = _read_user_model_prefs(config, user_id=user_id or "default", db_path=db_path)
        if user_profile:
            candidate_profile = user_profile

    if not candidate_profile:
        candidate_profile = _model_fallback_profile(config)

    active_model_id = ""
    if role_profile and candidate_profile and role_profile == candidate_profile:
        active_model_id = role_model_id
    elif user_profile and candidate_profile and user_profile == candidate_profile:
        active_model_id = user_model_id
    return candidate_profile, active_model_id


def resolve_effective_model_for_role(
    config: AppConfig,
    role: str,
    *,
    cli_profile: str | None = None,
    env_profile: str | None = None,
    user_id: str = "default",
    db_path: str | None = None,
) -> tuple[str, str]:
    """Resolve active model profile/model-id for a named specialty role."""
    return resolve_effective_model(
        config,
        cli_profile=cli_profile,
        env_profile=env_profile,
        role=role,
        user_id=user_id,
        db_path=db_path,
    )


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
