"""PKCE / authorize-URL / OAuth-flow-start helpers for ChatGPT/Codex OAuth.

This module holds the self-contained pieces of the native ChatGPT/Codex OAuth
flow: the configuration constants, the PKCE pair generator, the authorize-URL
builder, the ``OAuthStart`` value object, and the request/callback parsing
helpers. None of these touch the secret store or perform network I/O, so they
live here to keep ``openai_codex_oauth`` focused on token persistence and the
async token-exchange/refresh calls.

``openai_codex_oauth`` re-exports every public name defined here so existing
``from thomas.server.openai_codex_oauth import ...`` callers keep working.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets as secrets_lib
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse

OPENAI_CODEX_CLIENT_ID = os.environ.get("THOMAS_OPENAI_CODEX_OAUTH_CLIENT_ID", "app_EMoamEEZ73f0CkXaXp7hrann")
OPENAI_CODEX_ISSUER = os.environ.get("THOMAS_OPENAI_CODEX_OAUTH_ISSUER", "https://auth.openai.com")
OPENAI_CODEX_REDIRECT_URI = os.environ.get(
    "THOMAS_OPENAI_CODEX_REDIRECT_URI",
    "http://localhost:1455/auth/callback",
)
OPENAI_CODEX_SCOPES = os.environ.get(
    "THOMAS_OPENAI_CODEX_OAUTH_SCOPES",
    "openid profile email offline_access api.connectors.read api.connectors.invoke",
)
OPENAI_CODEX_ORIGINATOR = os.environ.get("THOMAS_OPENAI_CODEX_ORIGINATOR", "thomas")

_TOKEN_SECRET_PREFIX = "__openai_codex_oauth__:"
_CANONICAL_OPENAI_CODEX_PROFILE = "openai_codex"
_OPENAI_CODEX_PROFILE_ALIASES = (
    _CANONICAL_OPENAI_CODEX_PROFILE,
    "chatgpt",
    "codex",
    "openai-codex",
    "forgecode",
)


@dataclass(frozen=True)
class OAuthStart:
    profile: str
    state: str
    code_verifier: str
    code_challenge: str
    redirect_uri: str
    auth_url: str
    expires_at: float


def normalize_openai_codex_profile(profile: str | None = None) -> str:
    value = str(profile or "").strip()
    return value or _CANONICAL_OPENAI_CODEX_PROFILE


def canonical_openai_codex_secret_profile(profile: str | None = None) -> str:
    """Return the shared secret identity for compatible ChatGPT/Codex profiles."""

    value = normalize_openai_codex_profile(profile)
    if value.casefold() in _OPENAI_CODEX_PROFILE_ALIASES:
        return _CANONICAL_OPENAI_CODEX_PROFILE
    return value


def _raw_openai_codex_secret_key(profile: str) -> str:
    return f"{_TOKEN_SECRET_PREFIX}{profile}"


def openai_codex_secret_key(profile: str | None = None) -> str:
    return _raw_openai_codex_secret_key(canonical_openai_codex_secret_profile(profile))


def openai_codex_secret_key_candidates(profile: str | None = None) -> tuple[str, ...]:
    """Return canonical-first keys plus legacy alias keys for migration reads."""

    value = normalize_openai_codex_profile(profile)
    canonical = canonical_openai_codex_secret_profile(value)
    profiles = (
        (canonical, *_OPENAI_CODEX_PROFILE_ALIASES) if canonical == _CANONICAL_OPENAI_CODEX_PROFILE else (canonical,)
    )
    return tuple(dict.fromkeys(_raw_openai_codex_secret_key(item) for item in profiles))


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets_lib.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_authorize_url(
    *,
    code_challenge: str,
    state: str,
    redirect_uri: str = OPENAI_CODEX_REDIRECT_URI,
    client_id: str = OPENAI_CODEX_CLIENT_ID,
    issuer: str = OPENAI_CODEX_ISSUER,
    originator: str = OPENAI_CODEX_ORIGINATOR,
) -> str:
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": OPENAI_CODEX_SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": originator,
    }
    return f"{issuer.rstrip('/')}/oauth/authorize?{urlencode(query)}"


def start_oauth_flow(
    *,
    profile: str | None = None,
    redirect_uri: str = OPENAI_CODEX_REDIRECT_URI,
    ttl_s: float = 900.0,
) -> OAuthStart:
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets_lib.token_urlsafe(32)
    auth_url = build_authorize_url(
        code_challenge=code_challenge,
        state=state,
        redirect_uri=redirect_uri,
    )
    return OAuthStart(
        profile=normalize_openai_codex_profile(profile),
        state=state,
        code_verifier=code_verifier,
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
        auth_url=auth_url,
        expires_at=time.time() + max(60.0, float(ttl_s)),
    )


def parse_oauth_callback(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)
        return str((qs.get("code") or [""])[0]), str((qs.get("state") or [""])[0])
    return raw, ""
