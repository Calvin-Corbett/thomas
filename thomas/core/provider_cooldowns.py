"""Which model profiles are resting, and for how long.

The LLM client parks a profile after a rate limit or a run of server
failures (``thomas/core/llm_client.py``, one process-wide registry keyed by
profile name). A chat turn that hits the park fails with a generic error and
the person learns nothing about when the model is back. This reader lets a
route say so, and the page count it down (frontier parity: Codex shows its
rate-limit reset; 2026-09-05).
"""

from __future__ import annotations

import math
from typing import Any

from thomas.core import llm_client


def active_cooldowns() -> list[dict[str, Any]]:
    """Resting profiles, longest wait first; empty when every profile is available."""
    rows: list[dict[str, Any]] = []
    for profile, cooldown in list(llm_client._PROVIDER_COOLDOWNS.items()):
        remaining = float(cooldown.remaining())
        if remaining <= 0:
            continue
        rows.append(
            {
                "profile": str(profile),
                "remaining_s": int(math.ceil(remaining)),
                "failure_type": str(cooldown.failure_type or ""),
            }
        )
    rows.sort(key=lambda r: r["remaining_s"], reverse=True)
    return rows


__all__ = ["active_cooldowns"]
