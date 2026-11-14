"""The one setting that asks for the aliveness loop, readable without loading the loop.

A Thomas with the loop off must not load ``thomas.core.aliveness``, so whatever decides that before the loop exists
reads the setting here.
"""

from __future__ import annotations

import os

ENABLE_ENV = "THOMAS_ALIVENESS_ENABLED"


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_enabled() -> bool:
    """Whether the setting asks for the loop. Off unless explicitly set."""
    return truthy(os.environ.get(ENABLE_ENV))
