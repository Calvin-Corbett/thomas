"""Process-wide provider cooldown state for the LLM client."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

_DEFAULT_RATE_LIMIT_COOLDOWN_S = 20.0
_MAX_RETRY_AFTER_S = 300.0
_AUTH_FAILURE_BASE_S = 18_000.0  # 5 hours (billing/auth failures)
_SERVER_FAILURE_BASE_S = 300.0  # 5 minutes (general server errors)
_MAX_BACKOFF_S = 86_400.0  # 24 hours cap
_RATE_LIMIT_BACKOFF_CAP_S = 600.0  # 10 minutes cap for rate limits


@dataclass
class _ProviderCooldown:
    """Tracks per-provider cooldown with exponential backoff."""

    until: float = 0.0
    failure_count: int = 0
    failure_type: str = ""  # "rate_limit" | "auth" | "server" | "connect"
    # The provider's own words for the refusal that parked this profile. A park
    # after a rate limit lasts ten minutes at most; the plan limit that caused it
    # can last a day and a half, and every message sent in between hits the park
    # rather than the provider. Without these words the park has nothing to say
    # about which limit it is or when it resets, which is the one thing you asked
    # to be told (thomas/core/provider_limits.py reads them back out).
    refusal: str = ""

    def mark(self, failure_type: str, base_s: float = _SERVER_FAILURE_BASE_S, refusal: str = "") -> None:
        self.failure_type = failure_type
        self.refusal = refusal
        self.failure_count += 1
        wait = base_s * (2 ** min(self.failure_count - 1, 7))
        wait = min(wait, _MAX_BACKOFF_S)
        if failure_type == "rate_limit":
            wait = min(wait, _RATE_LIMIT_BACKOFF_CAP_S)
        self.until = time.monotonic() + wait

    def remaining(self) -> float:
        rem = self.until - time.monotonic()
        return rem if rem > 0 else 0.0

    def is_active(self) -> bool:
        return self.remaining() > 0

    def clear(self) -> None:
        self.until = 0.0
        self.failure_count = 0
        self.failure_type = ""
        self.refusal = ""


_PROVIDER_COOLDOWNS: dict[str, _ProviderCooldown] = {}


def get_cooldown(
    key: str,
    *,
    cooldowns: dict[str, _ProviderCooldown] | None = None,
    cooldown_factory: Callable[[], _ProviderCooldown] = _ProviderCooldown,
) -> _ProviderCooldown:
    """Return the shared cooldown for a provider key, creating it if needed."""
    registry = _PROVIDER_COOLDOWNS if cooldowns is None else cooldowns
    if key not in registry:
        registry[key] = cooldown_factory()
    return registry[key]
