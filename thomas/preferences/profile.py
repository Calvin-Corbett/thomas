"""Compatibility exports for legacy preference-profile helpers."""

from __future__ import annotations

from thomas.preferences._utils import (
    normalize_profile_type,
    normalize_review_depth,
    profile_prefers_non_coder_mode,
)

__all__ = [
    "normalize_profile_type",
    "normalize_review_depth",
    "profile_prefers_non_coder_mode",
]
