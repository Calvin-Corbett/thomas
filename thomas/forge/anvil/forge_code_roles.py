"""Saved Build role choices, frozen per dispatch without moving credentials."""

from __future__ import annotations

import json
import re
from copy import copy
from typing import Any

from thomas.preferences.model_prefs import read_user_model_role_preferences

ROLE_ENV = "THOMAS_BUILD_ROLE_MODELS"
ROLES = ("builder", "reviewer")
_GPT_MODEL = re.compile(r"^gpt-[A-Za-z0-9][A-Za-z0-9._-]{0,110}$")
_PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def validate_model(value: Any) -> str:
    if not isinstance(value, str) or (value and not _GPT_MODEL.fullmatch(value)):
        raise ValueError("Build helpers require a GPT model from the connected ChatGPT account")
    return value


def resolve_role_choices(requested: Any = None) -> dict[str, dict[str, str] | None]:
    """Read and freeze role preferences; only read reviewers may cross providers."""
    if requested is not None and (not isinstance(requested, dict) or set(requested) - set(ROLES)):
        raise ValueError("build_roles must contain only builder and reviewer choices")
    result: dict[str, dict[str, str] | None] = {}
    for role in ROLES:
        if requested is None or role not in requested:
            profile, model = read_user_model_role_preferences(user_id="default", role=f"build_{role}")
        else:
            choice = requested[role]
            if choice is None:
                profile, model = "", ""
            elif isinstance(choice, dict) and not set(choice) - {"profile", "model_id"}:
                profile, model = choice.get("profile", ""), choice.get("model_id", "")
            else:
                raise ValueError(f"Invalid Build {role} choice")
        if not isinstance(profile, str) or not isinstance(model, str):
            raise ValueError(f"Invalid Build {role} profile or model")
        if not profile and not model:
            result[role] = None
            continue
        if not _PROFILE.fullmatch(profile) or (model and not _MODEL.fullmatch(model)):
            raise ValueError(f"Invalid Build {role} profile or model")
        if role == "builder" and (profile != "openai_codex" or not model):
            raise ValueError("Build builder must use the existing openai_codex account or inherit the task manager")
        if profile == "openai_codex":
            model = validate_model(model)
            if not model:
                raise ValueError(f"Build {role} needs a GPT model for the connected ChatGPT account")
        result[role] = {"profile": profile, "model_id": model}
    return result


def resolve_roles(requested: Any = None) -> dict[str, str]:
    """Return only GPT role overrides for the in-process Build helpers."""
    choices = resolve_role_choices(requested)
    return {
        role: choice["model_id"] if choice and choice["profile"] == "openai_codex" else ""
        for role, choice in choices.items()
    }


def role_configs(manager: Any, encoded: str) -> dict[str, Any]:
    """Change only model IDs; credentials, provider and permission state stay inherited."""
    values = json.loads(encoded) if encoded else {}
    if not isinstance(values, dict) or set(values) - set(ROLES):
        raise ValueError("Invalid frozen Build role models")
    models = {role: validate_model(values.get(role, "")) for role in ROLES}
    if any(models.values()) and str(manager.provider) != "openai_codex":
        raise ValueError("Separate Build helper models require the connected ChatGPT account")
    configs = {}
    for role, model in models.items():
        configs[role] = copy(manager)
        if model:
            configs[role].model = model
    return configs
