"""Utility functions for preferences module."""

import base64
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._types import _PROFILE_TYPE_ALIASES, _REVIEW_DEPTH_ALIASES, ProfileType, ReviewDepth


def normalize_profile_type(value: Any, *, default: ProfileType = "adaptive") -> ProfileType:
    raw = str(value or "").strip().lower().replace("-", "_")
    if not raw:
        return default
    normalized = _PROFILE_TYPE_ALIASES.get(raw)
    if normalized:
        return normalized  # type: ignore[return-value]
    # Handle mixed separators like "non coder".
    normalized = _PROFILE_TYPE_ALIASES.get(raw.replace("_", " "))
    if normalized:
        return normalized  # type: ignore[return-value]
    return default


def normalize_review_depth(value: Any, *, default: ReviewDepth = "adaptive") -> ReviewDepth:
    raw = str(value or "").strip().lower().replace("-", "_")
    if not raw:
        return default
    normalized = _REVIEW_DEPTH_ALIASES.get(raw)
    if normalized:
        return normalized  # type: ignore[return-value]
    normalized = _REVIEW_DEPTH_ALIASES.get(raw.replace("_", " "))
    if normalized:
        return normalized  # type: ignore[return-value]
    return default


def profile_prefers_non_coder_mode(
    profile: Any = None,
    *,
    onboarding_answers: dict[str, Any] | None = None,
) -> bool:
    """Resolve whether robust non-coder defaults should be active."""
    explicit = normalize_profile_type(getattr(profile, "profile_type", None), default="adaptive")
    if explicit == "non_coder":
        return True
    if explicit == "coder":
        return False

    answers = onboarding_answers if isinstance(onboarding_answers, dict) else {}
    answers_profile = normalize_profile_type(answers.get("profile_type"), default="adaptive")
    if answers_profile == "non_coder":
        return True
    if answers_profile == "coder":
        return False

    experience = str(answers.get("experience") or "").strip().lower()
    return experience in {"new", "beginner", "non_coder", "non-coder", "noncoder"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db_path() -> str:
    env_path = os.getenv("THOMAS_DB_PATH") or os.getenv("THOMAS_SQLITE_PATH")
    if env_path:
        resolved = Path(env_path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return str(resolved)
    try:
        from thomas.core.config import resolve_thomas_data_dir

        resolved = (resolve_thomas_data_dir() / "thomas.db").resolve()
    except Exception:
        resolved = (Path.home() / ".thomas" / "thomas.db").resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return str(resolved)


def _derive_fernet_key_from_secret(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _mask_key_tail(value: str) -> str:
    v = value.strip()
    if not v:
        return ""
    tail = v[-4:] if len(v) >= 4 else v
    return f"••••••{tail}"
