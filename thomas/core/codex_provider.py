"""Shared ChatGPT/Codex provider constants.

These low-level symbols live in ``thomas.core`` so that the ``models`` and
``core`` layers can identify the native ChatGPT/Codex provider and resolve its
base URL without importing the ``server`` layer (which would violate the
dependency-direction architecture rule).

The ``server`` OAuth module re-exports these names for backwards compatibility.
"""

from __future__ import annotations

import os

OPENAI_CODEX_PROVIDER = "openai_codex"
OPENAI_CODEX_BASE_URL = os.environ.get("THOMAS_OPENAI_CODEX_BASE_URL", "https://chatgpt.com/backend-api/codex")


def is_openai_codex_provider(provider: str | None) -> bool:
    normalized = str(provider or "").strip().lower().replace("-", "_")
    return normalized == OPENAI_CODEX_PROVIDER
