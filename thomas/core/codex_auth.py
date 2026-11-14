"""Core-side boundary for resolving ChatGPT/Codex access tokens.

The core LLM transport must not import the HTTP server or its secret store.
Server startup registers the owner-scoped resolver through this small boundary;
standalone core callers can instead provide ``ModelConfig.api_key`` directly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

AccessTokenResolver = Callable[[str | None], Awaitable[str]]
RejectedTokenRecovery = Callable[[str | None, str], Awaitable[tuple[str | None, bool]]]

_access_token_resolver: AccessTokenResolver | None = None
_rejected_token_recovery: RejectedTokenRecovery | None = None
_recovered_tokens: dict[tuple[str | None, str], str] = {}


async def current_access_token(profile: str | None, configured_token: str) -> str:
    """Replace a previously rejected embedded token with the store's current token."""
    replacement = _recovered_tokens.get((profile, configured_token))
    if replacement and _access_token_resolver is not None:
        current = await resolve_access_token(profile)
        if current != configured_token:
            return current
    return configured_token


def register_rejected_token_recovery(recovery: RejectedTokenRecovery) -> None:
    """Register server-side recovery without importing storage into core."""
    global _rejected_token_recovery
    _rejected_token_recovery = recovery


async def recover_rejected_token(profile: str | None, rejected_token: str) -> tuple[str | None, bool]:
    """Return a replacement and whether the live Codex login supplied or held the token."""
    recovery = _rejected_token_recovery
    if recovery is None:
        return None, False
    replacement, live_token_checked = await recovery(profile, rejected_token)
    if replacement and replacement != rejected_token:
        _recovered_tokens[(profile, rejected_token)] = replacement
        return replacement, live_token_checked
    return None, live_token_checked


def register_access_token_resolver(resolver: AccessTokenResolver) -> None:
    """Register the process-local server resolver used by the core transport."""

    global _access_token_resolver
    _access_token_resolver = resolver


async def resolve_access_token(profile: str | None = None) -> str:
    """Resolve a token without coupling ``thomas.core`` to server storage."""

    resolver = _access_token_resolver
    if resolver is None:
        raise RuntimeError("ChatGPT OAuth is not connected. Run Easy Setup or sign in first.")
    token = str(await resolver(profile) or "").strip()
    if not token:
        raise RuntimeError("ChatGPT OAuth did not provide an access token.")
    return token
