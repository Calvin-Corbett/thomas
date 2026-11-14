"""Configuration serialization and identity preferences shared by CLI setup."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import click
import yaml

PERSONALITY_DESCRIPTIONS = {
    "casual": "Use a relaxed, friendly conversational style, with humor when appropriate.",
    "balanced": "Use a clear, thoughtful conversational style. Balance warmth with precision.",
    "professional": "Use a formal, precise, business-focused style.",
}


def toml_string(value: str) -> str:
    """Quote a literal value without allowing it to change the TOML structure."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def save_personality(style: str, *, overwrite: bool = True) -> Path:
    """Merge the chosen style into the identity configuration read by AgentLoop.

    Quickstart supplies a default only; the guided wizard supplies an explicit
    choice. Preserve the rest of the identity and all unrelated user settings.
    """
    personality = PERSONALITY_DESCRIPTIONS[style]
    user_dir = Path(os.environ.get("THOMAS_USER_DIR") or Path.home() / ".thomas")
    path = user_dir / "config.yaml"
    temporary_path: Path | None = None
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        data = yaml.safe_load(text) if text.strip() else {}
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("The existing user configuration must be a YAML mapping.")
        identity = data.get("identity", {})
        if not isinstance(identity, dict):
            raise ValueError("The existing identity configuration must be a YAML mapping.")
        if not overwrite and "personality" in identity:
            return path
        identity["personality"] = personality
        data["identity"] = identity
        user_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=user_dir, delete=False) as output:
            temporary_path = Path(output.name)
            yaml.safe_dump(data, output, allow_unicode=True, sort_keys=False)
        temporary_path.replace(path)
        return path
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise click.ClickException(f"Could not save personality preferences to {path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
