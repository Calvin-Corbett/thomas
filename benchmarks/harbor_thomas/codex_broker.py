"""Host-side ChatGPT/Codex token broker, shared across a job's trials.

The refresh grant rotates: an exchange can return a new refresh token and
invalidate the one presented. Refreshing inside a per-trial container would
strand each rotation in a container that is then destroyed, so the next trial
would present an already-invalidated token and every trial after the first
refresh would fail. Harbor runs a whole job in one host process, so the broker
lives here at module scope, keeps the rotation, and hands each trial a freshly
minted access token.

Nothing here is written to disk: the trial directory is published with the
submission, and a refresh token in a published artifact would be a credential
disclosure. State lives only in this process.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time

# Refresh this far ahead of expiry so a token cannot lapse mid-request.
_LEEWAY_S = 300.0
# Used only when a token carries no decodable expiry.
_ASSUMED_LIFETIME_S = 1800.0

_DEFAULT_ISSUER = "https://auth.openai.com"
# Mirrors thomas/server/openai_codex_oauth_flow.py:24-25. Duplicated rather than
# imported because this runs in Harbor's interpreter, where Thomas is NOT
# importable: `harbor` is a console script, so sys.path[0] is its own bin
# directory and the cwd is absent. Relying on the import resolved the client id
# to "" and every refresh returned HTTP 400 on the first trial.
_DEFAULT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"


class CodexAuthError(RuntimeError):
    """Refresh failed for a reason retrying will not fix (bad credential)."""


class CodexTransientError(RuntimeError):
    """Refresh failed for a reason a retry might fix (network, 5xx)."""


def _jwt_expiry(token: str) -> float:
    """Best-effort ``exp`` from a JWT access token; 0.0 when unknown."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload)).get("exp") or 0.0)
    except Exception:
        return 0.0


def _oauth_config() -> tuple[str, str]:
    """Client id and issuer, preferring Thomas' own constants."""
    try:
        from thomas.server.openai_codex_oauth_flow import (
            OPENAI_CODEX_CLIENT_ID,
            OPENAI_CODEX_ISSUER,
        )

        return OPENAI_CODEX_CLIENT_ID, OPENAI_CODEX_ISSUER
    except Exception:
        import os

        return (
            os.environ.get("THOMAS_OPENAI_CODEX_OAUTH_CLIENT_ID", _DEFAULT_CLIENT_ID),
            os.environ.get("THOMAS_OPENAI_CODEX_OAUTH_ISSUER", _DEFAULT_ISSUER),
        )


class CodexTokenBroker:
    """Mints access tokens from a rotating refresh token."""

    def __init__(self, refresh_token: str, access_token: str = "") -> None:
        self._refresh_token = refresh_token.strip()
        self._access_token = access_token.strip()
        # Match _refresh: a token whose expiry cannot be decoded is given the
        # assumed lifetime rather than being treated as already expired, so an
        # opaque (non-JWT) access token is not rejected out of hand.
        self._expires_at = 0.0
        if self._access_token:
            self._expires_at = (
                _jwt_expiry(self._access_token) or time.time() + _ASSUMED_LIFETIME_S
            )
        self._lock = asyncio.Lock()

    async def access_token(self) -> str:
        """Return a valid access token, refreshing when one is due to expire."""
        async with self._lock:
            now = time.time()
            if self._access_token and self._expires_at > now + _LEEWAY_S:
                return self._access_token
            if not self._refresh_token:
                # Returning the token anyway would hand every remaining trial a
                # credential that is already expired, so they 401 inside the
                # container and score zero with nothing visible on the host.
                raise CodexAuthError(
                    "Codex access token has expired and no refresh token was "
                    "supplied; export THOMAS_CODEX_REFRESH_TOKEN in the host "
                    "shell. Do not pass it with --ae: that injects it into the "
                    "task container."
                )
            return await self._refresh()

    async def _refresh(self) -> str:
        import httpx

        client_id, issuer = _oauth_config()
        if not client_id:
            raise CodexAuthError(
                "Codex OAuth client id resolved empty; set "
                "THOMAS_OPENAI_CODEX_OAUTH_CLIENT_ID."
            )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{issuer.rstrip('/')}/oauth/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self._refresh_token,
                        "client_id": client_id,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.HTTPError as exc:
            raise CodexTransientError(
                f"Codex token endpoint unreachable: {type(exc).__name__}."
            ) from None

        status = int(resp.status_code)
        if status >= 400:
            # The body is deliberately excluded: it can echo the token back.
            # 4xx means the credential is bad, and retrying it 46 times just
            # burns the job; 5xx may pass on a retry.
            error = CodexAuthError if status < 500 else CodexTransientError
            raise error(f"Codex token refresh failed with HTTP {status}.")

        try:
            payload = resp.json()
        except ValueError:
            # Never surface the body; it can contain the token.
            raise CodexTransientError(
                "Codex token endpoint returned a non-JSON response."
            ) from None
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise CodexAuthError("Codex token refresh returned no access token.")

        # Keep the rotation. Thomas' own server path persists this for the same
        # reason (thomas/server/openai_codex_oauth.py:108); dropping it means the
        # next refresh presents an invalidated token.
        rotated = str(payload.get("refresh_token") or "").strip()
        if rotated:
            self._refresh_token = rotated

        expires_at = _jwt_expiry(access_token)
        if expires_at <= 0.0:
            expires_at = time.time() + (
                float(payload.get("expires_in") or 0.0) or _ASSUMED_LIFETIME_S
            )

        self._access_token = access_token
        self._expires_at = expires_at
        return access_token


_broker: CodexTokenBroker | None = None
_broker_key: str | None = None


def get_broker(refresh_token: str, access_token: str = "") -> CodexTokenBroker:
    """Return the job-wide broker, creating it on first use.

    Keyed on the supplied credential. The broker must be shared so a rotated
    refresh token survives between trials, but a cache that ignored its
    arguments would pin whichever credential arrived first: a later trial
    supplying a different token would silently keep using the earlier one, and
    a first trial supplying only an access token would disable refresh for the
    whole job. A changed credential builds a new broker instead.
    """
    global _broker, _broker_key
    key = refresh_token or f"access:{access_token}"
    if _broker is None or _broker_key != key:
        _broker = CodexTokenBroker(refresh_token, access_token)
        _broker_key = key
    return _broker
