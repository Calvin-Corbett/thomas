"""Native ChatGPT/Codex OAuth helpers for Thomas.

This mirrors the Codex PKCE login shape without depending on the Codex CLI.
Secrets are stored through Thomas' SecretStore; this module never writes tokens
directly to disk.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

# These low-level provider symbols live in thomas.core.codex_provider so the
# core/models layers can use them without importing the server layer. They are
# re-exported here so existing `from thomas.server.openai_codex_oauth import ...`
# callers keep working.
from thomas.core.codex_auth import register_access_token_resolver
from thomas.core.codex_provider import (
    OPENAI_CODEX_BASE_URL,
    OPENAI_CODEX_PROVIDER,
    is_openai_codex_provider,
)

# The PKCE / authorize-URL / OAuth-flow-start helpers live in a sibling module
# to keep this file under the repo's per-file line cap. They are re-exported
# here so existing `from thomas.server.openai_codex_oauth import ...` callers
# (and the codex_provider re-export chain) keep working unchanged.
from thomas.server.openai_codex_oauth_flow import (
    OPENAI_CODEX_CLIENT_ID,
    OPENAI_CODEX_ISSUER,
    OPENAI_CODEX_ORIGINATOR,
    OPENAI_CODEX_REDIRECT_URI,
    OPENAI_CODEX_SCOPES,
    OAuthStart,
    build_authorize_url,
    generate_pkce_pair,
    normalize_openai_codex_profile,
    openai_codex_secret_key,
    openai_codex_secret_key_candidates,
    parse_oauth_callback,
    start_oauth_flow,
)


class OpenAICodexOAuthError(RuntimeError):
    """Raised when ChatGPT/Codex OAuth cannot complete or refresh."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def decode_jwt_payload(jwt: str | None) -> dict[str, Any]:
    token = str(jwt or "").strip()
    parts = token.split(".")
    if len(parts) < 3 or not parts[1]:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        obj = json.loads(raw.decode("utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _coerce_exp(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _extract_claims(token_payload: dict[str, Any]) -> dict[str, Any]:
    profile = token_payload.get("https://api.openai.com/profile")
    if not isinstance(profile, dict):
        profile = {}
    auth = token_payload.get("https://api.openai.com/auth")
    if not isinstance(auth, dict):
        auth = {}
    return {
        "email": token_payload.get("email") or profile.get("email") or "",
        "chatgpt_user_id": auth.get("chatgpt_user_id") or auth.get("user_id") or "",
        "account_id": auth.get("chatgpt_account_id") or "",
        "plan_type": auth.get("chatgpt_plan_type") or "",
        "account_is_fedramp": bool(auth.get("chatgpt_account_is_fedramp")),
    }


def normalize_token_payload(raw: dict[str, Any], *, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = previous if isinstance(previous, dict) else {}
    now = time.time()
    access_token = str(raw.get("access_token") or previous.get("access_token") or "").strip()
    refresh_token = str(raw.get("refresh_token") or previous.get("refresh_token") or "").strip()
    id_token = str(raw.get("id_token") or previous.get("id_token") or "").strip()

    expires_at = _coerce_exp(raw.get("expires_at"))
    if expires_at <= 0 and raw.get("expires_in") is not None:
        expires_at = now + max(0.0, _coerce_exp(raw.get("expires_in")))
    if expires_at <= 0:
        expires_at = _coerce_exp(decode_jwt_payload(access_token).get("exp"))
    if expires_at <= 0:
        expires_at = _coerce_exp(previous.get("expires_at"))

    id_claims = _extract_claims(decode_jwt_payload(id_token))
    access_claims = _extract_claims(decode_jwt_payload(access_token))

    out = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "expires_at": expires_at,
        "updated_at": now,
        "email": str(
            raw.get("email") or id_claims.get("email") or access_claims.get("email") or previous.get("email") or ""
        ),
        "display_name": str(raw.get("display_name") or previous.get("display_name") or ""),
        "account_id": str(
            raw.get("account_id")
            or id_claims.get("account_id")
            or access_claims.get("account_id")
            or previous.get("account_id")
            or ""
        ),
        "chatgpt_user_id": str(
            raw.get("chatgpt_user_id")
            or id_claims.get("chatgpt_user_id")
            or access_claims.get("chatgpt_user_id")
            or previous.get("chatgpt_user_id")
            or ""
        ),
        "plan_type": str(
            raw.get("plan_type")
            or id_claims.get("plan_type")
            or access_claims.get("plan_type")
            or previous.get("plan_type")
            or ""
        ),
        "account_is_fedramp": bool(
            raw.get("account_is_fedramp")
            or id_claims.get("account_is_fedramp")
            or access_claims.get("account_is_fedramp")
            or previous.get("account_is_fedramp")
        ),
    }
    return out


def read_openai_codex_token(secret_store: Any, profile: str | None = None) -> dict[str, Any] | None:
    if secret_store is None or not hasattr(secret_store, "get"):
        return None
    for key in openai_codex_secret_key_candidates(profile):
        raw = secret_store.get(key)
        if not raw:
            continue
        try:
            obj = json.loads(str(raw))
        except (TypeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def import_local_codex_token(
    secret_store: Any,
    profile: str | None = None,
    *,
    codex_home: str | Path | None = None,
) -> dict[str, Any] | None:
    """Adopt the current Windows-user Codex login into Thomas's secret store.

    Codex and Thomas run as the same local owner but historically kept separate
    OAuth files. That made a valid Codex app login look disconnected in Thomas
    and caused a redundant sign-in prompt. Import only the OAuth token object,
    never ``OPENAI_API_KEY``, and persist it through ``SecretStore`` so subsequent
    server restarts use Thomas's normal encrypted/guarded storage path.
    """

    stored = read_openai_codex_token(secret_store, profile)
    if token_is_access_ready(stored):
        return stored
    if str(os.environ.get("THOMAS_IMPORT_LOCAL_CODEX_AUTH", "1")).strip().casefold() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return stored
    configured = str(codex_home or os.environ.get("CODEX_HOME") or "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    source = root / "auth.json"
    try:
        if not source.is_file() or source.stat().st_size > 1024 * 1024:
            return stored
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return stored
    tokens = payload.get("tokens") if isinstance(payload, dict) else None
    if not isinstance(tokens, dict):
        return stored
    imported = {
        "access_token": str(tokens.get("access_token") or "").strip(),
        "refresh_token": str(tokens.get("refresh_token") or "").strip(),
        "id_token": str(tokens.get("id_token") or "").strip(),
        "account_id": str(tokens.get("account_id") or "").strip(),
    }
    if not imported["access_token"] and not imported["refresh_token"]:
        return stored
    candidate = normalize_token_payload(imported)
    if stored is not None:
        stored_pair = (
            str(stored.get("access_token") or "").strip(),
            str(stored.get("refresh_token") or "").strip(),
        )
        imported_pair = (
            str(candidate.get("access_token") or "").strip(),
            str(candidate.get("refresh_token") or "").strip(),
        )
        if imported_pair == stored_pair or not token_is_access_ready(candidate):
            return stored
    try:
        return write_openai_codex_token(secret_store, profile, imported, persist=True)
    except (OpenAICodexOAuthError, OSError, RuntimeError, TypeError, ValueError):
        return stored


def write_openai_codex_token(
    secret_store: Any,
    profile: str | None,
    token_payload: dict[str, Any],
    *,
    persist: bool = True,
) -> dict[str, Any]:
    if secret_store is None or not hasattr(secret_store, "set"):
        raise OpenAICodexOAuthError("Secret store is unavailable.")
    previous = read_openai_codex_token(secret_store, profile)
    normalized = normalize_token_payload(token_payload, previous=previous)
    if not normalized.get("access_token") and not normalized.get("refresh_token"):
        raise OpenAICodexOAuthError("OAuth response did not include an access or refresh token.")
    raw = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    canonical_key = openai_codex_secret_key(profile)
    secret_store.set(canonical_key, raw, persist=bool(persist))
    if persist and hasattr(secret_store, "clear"):
        for legacy_key in openai_codex_secret_key_candidates(profile):
            if legacy_key != canonical_key:
                secret_store.clear(legacy_key)
    return normalized


def clear_openai_codex_token(secret_store: Any, profile: str | None = None) -> None:
    if secret_store is not None and hasattr(secret_store, "clear"):
        for key in openai_codex_secret_key_candidates(profile):
            secret_store.clear(key)


def token_is_access_ready(token_payload: dict[str, Any] | None, *, leeway_s: float = 60.0) -> bool:
    if not isinstance(token_payload, dict):
        return False
    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        return False
    expires_at = _coerce_exp(token_payload.get("expires_at"))
    return expires_at <= 0 or expires_at > time.time() + float(leeway_s)


def token_is_refreshable(token_payload: dict[str, Any] | None) -> bool:
    return bool(isinstance(token_payload, dict) and str(token_payload.get("refresh_token") or "").strip())


def has_openai_codex_token(secret_store: Any, profile: str | None = None) -> bool:
    token = read_openai_codex_token(secret_store, profile)
    return token_is_access_ready(token) or token_is_refreshable(token)


def access_token_from_store(secret_store: Any, profile: str | None = None) -> str:
    token = read_openai_codex_token(secret_store, profile)
    if token_is_access_ready(token):
        return str(token.get("access_token") or "").strip()
    return ""


def _default_secret_store() -> Any:
    from thomas.core.config import load_config
    from thomas.server.secrets import SecretStore

    secret_root = str(os.environ.get("THOMAS_SECRET_ROOT") or "").strip()
    if secret_root:
        return SecretStore(Path(secret_root).expanduser().resolve())

    config = load_config()
    return SecretStore(config.memory.root_path / ".thomas")


async def exchange_code_for_tokens(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: str = OPENAI_CODEX_CLIENT_ID,
    issuer: str = OPENAI_CODEX_ISSUER,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    endpoint = f"{issuer.rstrip('/')}/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "code": str(code or "").strip(),
        "redirect_uri": str(redirect_uri or "").strip(),
        "client_id": str(client_id or "").strip(),
        "code_verifier": str(code_verifier or "").strip(),
    }
    if not data["code"] or not data["code_verifier"]:
        raise OpenAICodexOAuthError("OAuth code and code verifier are required.")
    try:
        async with httpx.AsyncClient(timeout=float(timeout_s)) as client:
            resp = await client.post(
                endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except (httpx.HTTPError, OSError) as exc:
        raise OpenAICodexOAuthError("Token exchange could not reach the OAuth service.") from exc
    if int(resp.status_code) >= 400:
        raise OpenAICodexOAuthError(f"Token exchange failed with HTTP {int(resp.status_code)}.")
    try:
        obj = resp.json()
    except Exception as e:
        raise OpenAICodexOAuthError(f"Token exchange returned invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise OpenAICodexOAuthError("Token exchange returned a non-object response.")
    return obj


async def refresh_openai_codex_token(
    refresh_token: str,
    *,
    client_id: str = OPENAI_CODEX_CLIENT_ID,
    issuer: str = OPENAI_CODEX_ISSUER,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    endpoint = f"{issuer.rstrip('/')}/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": str(refresh_token or "").strip(),
        "client_id": str(client_id or "").strip(),
    }
    if not data["refresh_token"]:
        raise OpenAICodexOAuthError("Refresh token is required.")
    try:
        async with httpx.AsyncClient(timeout=float(timeout_s)) as client:
            resp = await client.post(
                endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except (httpx.HTTPError, OSError) as exc:
        raise OpenAICodexOAuthError("Token refresh could not reach the OAuth service.") from exc
    if int(resp.status_code) >= 400:
        status_code = int(resp.status_code)
        raise OpenAICodexOAuthError(
            f"Token refresh failed with HTTP {status_code}.",
            status_code=status_code,
        )
    try:
        obj = resp.json()
    except Exception as e:
        raise OpenAICodexOAuthError(f"Token refresh returned invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise OpenAICodexOAuthError("Token refresh returned a non-object response.")
    return obj


async def ensure_openai_codex_access_token(
    profile: str | None = None,
    *,
    secret_store: Any | None = None,
    leeway_s: float = 60.0,
) -> str:
    store = secret_store if secret_store is not None else _default_secret_store()
    token = read_openai_codex_token(store, profile) or import_local_codex_token(store, profile)
    if token_is_access_ready(token, leeway_s=leeway_s):
        return str(token.get("access_token") or "").strip()
    if not token_is_refreshable(token):
        raise OpenAICodexOAuthError("ChatGPT OAuth is not connected. Run Easy Setup or sign in first.")
    try:
        refreshed = await refresh_openai_codex_token(str(token.get("refresh_token") or ""))
    except OpenAICodexOAuthError as exc:
        if exc.status_code not in {400, 401}:
            raise
        replacement = import_local_codex_token(store, profile)
        old_pair = (
            str(token.get("access_token") or "").strip(),
            str(token.get("refresh_token") or "").strip(),
        )
        replacement_pair = (
            str((replacement or {}).get("access_token") or "").strip(),
            str((replacement or {}).get("refresh_token") or "").strip(),
        )
        if replacement_pair != old_pair and token_is_access_ready(replacement, leeway_s=leeway_s):
            return replacement_pair[0]
        raise
    normalized = write_openai_codex_token(store, profile, refreshed, persist=True)
    return str(normalized.get("access_token") or "").strip()


async def _resolve_registered_access_token(profile: str | None = None) -> str:
    """Bridge the server-owned secret store into the core transport boundary."""

    return await ensure_openai_codex_access_token(profile)


register_access_token_resolver(_resolve_registered_access_token)


def public_token_status(token_payload: dict[str, Any] | None) -> dict[str, Any]:
    token = token_payload if isinstance(token_payload, dict) else {}
    expires_at = _coerce_exp(token.get("expires_at"))
    return {
        "logged_in": bool(token_is_access_ready(token) or token_is_refreshable(token)),
        "email": str(token.get("email") or ""),
        "display_name": str(token.get("display_name") or ""),
        "avatar_url": "",
        "plan_type": str(token.get("plan_type") or ""),
        "account_id": str(token.get("account_id") or ""),
        "chatgpt_user_id": str(token.get("chatgpt_user_id") or ""),
        "account_is_fedramp": bool(token.get("account_is_fedramp")),
        "expires_at": int(expires_at) if expires_at > 0 else None,
        "access_ready": bool(token_is_access_ready(token)),
        "refreshable": bool(token_is_refreshable(token)),
        "auth_type": "chatgpt_oauth",
    }
