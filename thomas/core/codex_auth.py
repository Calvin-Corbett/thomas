"""Core-side boundary for resolving ChatGPT/Codex access tokens.

The core LLM transport must not import the HTTP server or its secret store.
Server startup registers the owner-scoped resolver through this small boundary;
standalone core callers can instead provide ``ModelConfig.api_key`` directly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

AccessTokenResolver = Callable[[str | None], Awaitable[str]]

_access_token_resolver: AccessTokenResolver | None = None


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
