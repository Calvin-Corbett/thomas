"""OIDC + PKCE single sign-on engine, enforced at one auth choke point (CAP-123).

This module gives Thomas a self-contained SSO engine so that *every* surface --
web UI, native app, gateway, realtime -- enforces sign-on through the **same**
decision function.  It has four pieces the acceptance line demands:

1. **Authorization-code + PKCE flow.**  :meth:`SSOEngine.begin_login` builds an
   OIDC authorize URL carrying a ``code_challenge`` (S256) and returns the
   matching :class:`PendingLogin` (state, nonce, verifier).  :meth:`SSOEngine.
   complete_login` exchanges the returned ``code`` + ``code_verifier`` for
   tokens against an *injectable* :class:`IdPTransport` -- the real default
   (:class:`UrllibIdPTransport`) uses only the standard library's ``urllib``;
   tests inject a hermetic fake IdP so the whole flow runs offline.

2. **ID-token validation.**  :meth:`SSOEngine.validate_id_token` checks the
   issuer, audience, expiry and nonce, and verifies the JWS signature through an
   *injectable* :class:`SignatureVerifier`.  The real default,
   :class:`HS256Verifier`, verifies HS256 with :mod:`hmac` (stdlib, no deps); an
   RS256/JWKS verifier is supplied by injecting a verifier over the IdP's JWKS
   endpoint (the credential/network-gated live lane -- see module notes).

3. **Session establishment.**  A validated login yields an :class:`SSOSession`
   held in an :class:`SSOSessionStore`; the session is what the enforcement hook
   consumes.

4. **One enforcement choke point.**  :func:`enforce_sso` takes a surface-neutral
   :class:`SSORequestContext` and returns an :class:`SSODecision`.  It never
   reads ``ctx.surface`` -- so two different surfaces presenting the *same*
   session token receive byte-for-byte identical decisions.  :func:`require_sso`
   wraps that decision as a raise-on-deny hook that
   ``app_middleware_handlers._require_api_access`` can import and call, without
   this module editing the middleware file.

Everything is deterministic and hermetic: the clock, the PKCE randomness source,
the session-token factory, the IdP transport and the signature verifier are all
injectable, and nothing here touches the network unless the real
``UrllibIdPTransport`` is used against a real IdP.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets as _secrets
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlencode

# Reuse the existing, audited PKCE pair generator instead of re-deriving S256.
from thomas.server.openai_codex_oauth_flow import generate_pkce_pair

logger = logging.getLogger(__name__)

__all__ = [
    "SSOConfig",
    "PendingLogin",
    "SSOSession",
    "SSOSessionStore",
    "SSORequestContext",
    "SSODecision",
    "SSOEngine",
    "IdPTransport",
    "UrllibIdPTransport",
    "SignatureVerifier",
    "HS256Verifier",
    "SSOError",
    "TokenExchangeError",
    "IDTokenValidationError",
    "SSODenied",
    "enforce_sso",
    "require_sso",
    "request_context_from_request",
    "b64url_encode",
    "b64url_decode",
    "pkce_challenge",
]

# Small default clock leeway (seconds) for expiry/issued-at skew.
_DEFAULT_LEEWAY_S = 60.0
# Default session lifetime once SSO is established.
_DEFAULT_SESSION_TTL_S = 3600.0
# Header name and cookie name surfaces use to carry the SSO session token.
SSO_SESSION_HEADER = "X-SSO-Session"
SSO_SESSION_COOKIE = "thomas_sso_session"
_BEARER_PREFIX = "bearer "


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SSOError(Exception):
    """Base class for every SSO failure raised by this module."""


class TokenExchangeError(SSOError):
    """The authorization-code -> token exchange failed or was rejected."""


class IDTokenValidationError(SSOError):
    """The ID token failed issuer/audience/expiry/nonce/signature validation."""


class SSODenied(SSOError):
    """Enforcement denied a request at the auth choke point."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# base64url helpers (public so a hermetic fake IdP can mint test tokens)
# ---------------------------------------------------------------------------


def b64url_encode(raw: bytes) -> str:
    """URL-safe base64 without padding (JOSE/JWT encoding)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    """Decode URL-safe base64, tolerating missing padding.

    Raises :class:`IDTokenValidationError` on malformed input so callers get a
    single, specific error type rather than a raw ``binascii`` fault.
    """
    text = str(value or "")
    padded = text + "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise IDTokenValidationError("malformed base64url segment") from exc


def pkce_challenge(code_verifier: str) -> str:
    """Compute the S256 PKCE code challenge for a verifier."""
    digest = hashlib.sha256(str(code_verifier or "").encode("ascii")).digest()
    return b64url_encode(digest)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SSOConfig:
    """Static OIDC relying-party configuration for one IdP.

    ``audience`` defaults to ``client_id`` (the standard OIDC ``aud`` for an ID
    token issued to this client).  Endpoints default to the conventional OIDC
    paths under ``issuer`` but may be overridden for IdPs that differ.
    """

    issuer: str
    client_id: str
    redirect_uri: str
    scopes: str = "openid profile email"
    audience: str | None = None
    authorize_endpoint: str | None = None
    token_endpoint: str | None = None
    jwks_endpoint: str | None = None

    def __post_init__(self) -> None:
        for name in ("issuer", "client_id", "redirect_uri"):
            if not str(getattr(self, name) or "").strip():
                raise SSOError(f"SSOConfig.{name} must be a non-empty string")

    @property
    def expected_audience(self) -> str:
        return str(self.audience or self.client_id)

    @property
    def authorize_url_base(self) -> str:
        return str(self.authorize_endpoint or f"{self.issuer.rstrip('/')}/authorize")

    @property
    def token_url(self) -> str:
        return str(self.token_endpoint or f"{self.issuer.rstrip('/')}/token")

    @property
    def jwks_url(self) -> str:
        return str(self.jwks_endpoint or f"{self.issuer.rstrip('/')}/.well-known/jwks.json")


# ---------------------------------------------------------------------------
# Injectable IdP transport (real default: stdlib urllib; fake for tests)
# ---------------------------------------------------------------------------


@runtime_checkable
class IdPTransport(Protocol):
    """Edge that performs the token-endpoint HTTP call.

    A single method keeps the flow logic fully testable: the real default hits
    the network, a fake returns a canned token response offline.
    """

    def exchange_code(self, token_endpoint: str, form: Mapping[str, str]) -> dict[str, Any]:
        """POST ``form`` (application/x-www-form-urlencoded) and return JSON."""
        ...


class UrllibIdPTransport:
    """Real :class:`IdPTransport` built on the standard-library ``urllib``.

    No third-party HTTP dependency.  All faults are narrowed to
    :class:`TokenExchangeError` with a log line -- concrete exception types are
    caught (never a bare ``except``).
    """

    def __init__(self, *, timeout_s: float = 30.0) -> None:
        self._timeout_s = float(timeout_s)

    def exchange_code(self, token_endpoint: str, form: Mapping[str, str]) -> dict[str, Any]:
        body = urlencode(dict(form)).encode("ascii")
        request = urllib.request.Request(  # noqa: S310 - endpoint is operator-configured, not user input
            str(token_endpoint),
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as resp:  # noqa: S310
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            logger.warning("SSO token exchange HTTP %s from %s", exc.code, token_endpoint)
            raise TokenExchangeError(f"token exchange failed with HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            logger.warning("SSO token exchange could not reach %s: %s", token_endpoint, exc)
            raise TokenExchangeError("token exchange could not reach the identity provider") from exc
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise TokenExchangeError("token exchange returned invalid JSON") from exc
        if not isinstance(obj, dict):
            raise TokenExchangeError("token exchange returned a non-object response")
        if obj.get("error"):
            raise TokenExchangeError(f"identity provider rejected the exchange: {obj.get('error')}")
        return obj


# ---------------------------------------------------------------------------
# Injectable signature verifier (real default: HS256 via stdlib hmac)
# ---------------------------------------------------------------------------


@runtime_checkable
class SignatureVerifier(Protocol):
    """Verifies a JWS signature over the ``header.payload`` signing input."""

    def verify(self, signing_input: bytes, signature: bytes, header: Mapping[str, Any]) -> bool: ...


@dataclass(frozen=True)
class HS256Verifier:
    """Real HS256 verifier using :mod:`hmac` -- fully hermetic, no deps.

    HS256 is a legitimate JOSE algorithm for symmetric (client-secret signed)
    ID tokens.  RS256/JWKS verification is provided by injecting a different
    :class:`SignatureVerifier` backed by the IdP's JWKS endpoint.
    """

    secret: str

    def verify(self, signing_input: bytes, signature: bytes, header: Mapping[str, Any]) -> bool:
        alg = str(header.get("alg") or "").upper()
        if alg != "HS256":
            return False
        expected = hmac.new(self.secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Flow value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingLogin:
    """State carried between :meth:`SSOEngine.begin_login` and ``complete_login``.

    Persist this server-side (keyed by ``state``) between the redirect out and
    the callback in; ``code_verifier`` must never leave the relying party.
    """

    state: str
    nonce: str
    code_verifier: str
    code_challenge: str
    redirect_uri: str
    authorize_url: str
    expires_at: float

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at


@dataclass(frozen=True)
class SSOSession:
    """An established SSO session -- what the enforcement hook consumes."""

    session_id: str
    subject: str
    email: str
    issuer: str
    audience: str
    established_at: float
    expires_at: float

    def is_active(self, now: float) -> bool:
        return self.expires_at > now

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "subject": self.subject,
            "email": self.email,
            "issuer": self.issuer,
            "audience": self.audience,
            "established_at": self.established_at,
            "expires_at": self.expires_at,
        }


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------


class SSOSessionStore:
    """In-memory registry of established sessions keyed by an opaque token.

    The token factory is injectable so tests get deterministic session ids; the
    default uses :func:`secrets.token_urlsafe`.
    """

    def __init__(self, *, token_factory: Callable[[], str] | None = None) -> None:
        self._sessions: dict[str, SSOSession] = {}
        self._token_factory = token_factory or (lambda: _secrets.token_urlsafe(32))

    def establish(
        self,
        claims: Mapping[str, Any],
        *,
        now: float,
        ttl_s: float = _DEFAULT_SESSION_TTL_S,
        session_id: str | None = None,
    ) -> SSOSession:
        """Create, store and return a session for validated ID-token claims."""
        token = str(session_id or self._token_factory())
        if not token:
            raise SSOError("session token factory produced an empty token")
        aud = claims.get("aud")
        audience = aud[0] if isinstance(aud, list) and aud else str(aud or "")
        session = SSOSession(
            session_id=token,
            subject=str(claims.get("sub") or ""),
            email=str(claims.get("email") or ""),
            issuer=str(claims.get("iss") or ""),
            audience=str(audience),
            established_at=float(now),
            expires_at=float(now) + float(ttl_s),
        )
        self._sessions[token] = session
        return session

    def get(self, token: str | None) -> SSOSession | None:
        if not token:
            return None
        return self._sessions.get(str(token))

    def revoke(self, token: str) -> None:
        self._sessions.pop(str(token), None)

    def __len__(self) -> int:
        return len(self._sessions)


# ---------------------------------------------------------------------------
# Enforcement: one choke point, surface-neutral
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SSORequestContext:
    """Surface-neutral view of an inbound request for the enforcement hook.

    ``surface`` (``"web"`` / ``"app"`` / ``"gateway"`` / ``"realtime"``) is
    carried for audit only -- :func:`enforce_sso` never reads it, which is why
    two surfaces presenting the same ``session_token`` get identical decisions.
    """

    surface: str
    session_token: str | None = None


@dataclass(frozen=True)
class SSODecision:
    """Outcome of :func:`enforce_sso`.

    Deliberately excludes the surface, so decisions are byte-for-byte equal for
    any two surfaces that present the same session token.
    """

    allowed: bool
    reason: str
    subject: str | None = None
    session_id: str | None = None

    def __bool__(self) -> bool:
        return self.allowed


def enforce_sso(
    ctx: SSORequestContext,
    store: SSOSessionStore,
    *,
    now: float | None = None,
) -> SSODecision:
    """Single SSO decision for *every* surface.

    Default-deny: no token, an unknown token, or an expired session all deny;
    only a live session allows.  The decision reads only the session token --
    never ``ctx.surface`` -- so the choke point is identical everywhere.
    """
    moment = time.time() if now is None else float(now)
    token = str(ctx.session_token or "").strip()
    if not token:
        return SSODecision(False, "no sso session token presented")
    session = store.get(token)
    if session is None:
        return SSODecision(False, "unknown or revoked sso session")
    if not session.is_active(moment):
        return SSODecision(False, "sso session expired", subject=session.subject, session_id=session.session_id)
    return SSODecision(True, "sso session active", subject=session.subject, session_id=session.session_id)


def require_sso(
    ctx: SSORequestContext,
    store: SSOSessionStore,
    *,
    now: float | None = None,
) -> SSOSession:
    """Raise-on-deny hook for the ``_require_api_access`` choke point.

    Returns the live :class:`SSOSession` on success; raises :class:`SSODenied`
    (a subclass of :class:`SSOError`) otherwise.  The middleware imports and
    calls this so every surface enforces through :func:`enforce_sso`.
    """
    decision = enforce_sso(ctx, store, now=now)
    if not decision.allowed:
        raise SSODenied(decision.reason)
    session = store.get(ctx.session_token)
    if session is None:  # pragma: no cover - enforce_sso already proved presence
        raise SSODenied("sso session vanished during enforcement")
    return session


def _token_from_mapping_headers(headers: Mapping[str, Any]) -> str:
    """Pull the SSO session token from request headers (bearer or explicit)."""
    explicit = str(headers.get(SSO_SESSION_HEADER) or "").strip()
    if explicit:
        return explicit
    auth = str(headers.get("Authorization") or "").strip()
    if auth.lower().startswith(_BEARER_PREFIX):
        return auth[len(_BEARER_PREFIX) :].strip()
    return ""


def request_context_from_request(request: Any, surface: str) -> SSORequestContext:
    """Adapt a duck-typed request (``.headers`` + ``.cookies``) into a context.

    Works for any surface's request object without importing aiohttp: web
    requests carry the token in a cookie, gateway/app/realtime requests carry it
    in a header or bearer credential -- all funnel to the same context shape and
    therefore the same enforcement decision.
    """
    headers = getattr(request, "headers", {}) or {}
    token = _token_from_mapping_headers(headers)
    if not token:
        cookies = getattr(request, "cookies", {}) or {}
        token = str(cookies.get(SSO_SESSION_COOKIE) or "").strip()
    return SSORequestContext(surface=str(surface or "unknown"), session_token=token or None)


# ---------------------------------------------------------------------------
# The engine: PKCE flow + ID-token validation + session establishment
# ---------------------------------------------------------------------------


def _split_jwt(id_token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    """Split a compact JWS into (header, payload, signing_input, signature)."""
    token = str(id_token or "").strip()
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise IDTokenValidationError("id token is not a well-formed compact JWS")
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(b64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(b64url_decode(payload_b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise IDTokenValidationError("id token header/payload is not valid JSON") from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise IDTokenValidationError("id token header/payload must be JSON objects")
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = b64url_decode(sig_b64)
    return header, payload, signing_input, signature


@dataclass
class SSOEngine:
    """Relying-party engine wiring the config, transport, verifier and store."""

    config: SSOConfig
    verifier: SignatureVerifier
    transport: IdPTransport = field(default_factory=UrllibIdPTransport)
    store: SSOSessionStore = field(default_factory=SSOSessionStore)
    clock: Callable[[], float] = time.time
    rand: Callable[[], str] = field(default=lambda: _secrets.token_urlsafe(32))
    leeway_s: float = _DEFAULT_LEEWAY_S

    # -- step 1: authorization request --------------------------------------

    def begin_login(
        self,
        *,
        state: str | None = None,
        nonce: str | None = None,
        ttl_s: float = 900.0,
    ) -> PendingLogin:
        """Build the authorize URL (with PKCE ``code_challenge``) + pending state."""
        code_verifier, code_challenge = generate_pkce_pair()
        resolved_state = str(state or self.rand())
        resolved_nonce = str(nonce or self.rand())
        query = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": self.config.scopes,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": resolved_state,
            "nonce": resolved_nonce,
        }
        authorize_url = f"{self.config.authorize_url_base}?{urlencode(query)}"
        return PendingLogin(
            state=resolved_state,
            nonce=resolved_nonce,
            code_verifier=code_verifier,
            code_challenge=code_challenge,
            redirect_uri=self.config.redirect_uri,
            authorize_url=authorize_url,
            expires_at=self.clock() + max(60.0, float(ttl_s)),
        )

    # -- step 2: token exchange + validation + session ----------------------

    def complete_login(
        self,
        pending: PendingLogin,
        code: str,
        *,
        returned_state: str | None = None,
        now: float | None = None,
        session_ttl_s: float = _DEFAULT_SESSION_TTL_S,
    ) -> SSOSession:
        """Exchange ``code`` + verifier, validate the ID token, establish a session.

        Rejects (raising :class:`SSOError` subclasses) on: an expired pending
        login, a mismatched ``state`` (CSRF), a token exchange the IdP refuses
        (e.g. a bad ``code_verifier``), or an ID token failing signature /
        issuer / audience / expiry / nonce validation.
        """
        moment = self.clock() if now is None else float(now)
        if pending.is_expired(moment):
            raise TokenExchangeError("authorization request expired before completion")
        if returned_state is not None and not hmac.compare_digest(str(returned_state), pending.state):
            raise TokenExchangeError("state mismatch on authorization callback")
        if not str(code or "").strip():
            raise TokenExchangeError("authorization code is required")

        form = {
            "grant_type": "authorization_code",
            "code": str(code).strip(),
            "redirect_uri": pending.redirect_uri,
            "client_id": self.config.client_id,
            "code_verifier": pending.code_verifier,
        }
        token_response = self.transport.exchange_code(self.config.token_url, form)
        id_token = str(token_response.get("id_token") or "").strip()
        if not id_token:
            raise TokenExchangeError("token response did not include an id_token")

        claims = self.validate_id_token(id_token, expected_nonce=pending.nonce, now=moment)
        return self.store.establish(claims, now=moment, ttl_s=session_ttl_s)

    # -- ID-token validation ------------------------------------------------

    def validate_id_token(
        self,
        id_token: str,
        *,
        expected_nonce: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Validate signature, issuer, audience, expiry and nonce; return claims."""
        moment = self.clock() if now is None else float(now)
        header, payload, signing_input, signature = _split_jwt(id_token)

        if not self.verifier.verify(signing_input, signature, header):
            raise IDTokenValidationError("id token signature verification failed")

        issuer = str(payload.get("iss") or "")
        if issuer != self.config.issuer:
            raise IDTokenValidationError(f"id token issuer {issuer!r} does not match expected issuer")

        if not _audience_matches(payload.get("aud"), self.config.expected_audience):
            raise IDTokenValidationError("id token audience does not include this client")

        exp = _as_float(payload.get("exp"))
        if exp is None:
            raise IDTokenValidationError("id token is missing the exp claim")
        if exp <= moment - self.leeway_s:
            raise IDTokenValidationError("id token has expired")

        nbf = _as_float(payload.get("nbf"))
        if nbf is not None and nbf > moment + self.leeway_s:
            raise IDTokenValidationError("id token is not yet valid (nbf in the future)")

        token_nonce = str(payload.get("nonce") or "")
        if not expected_nonce or not hmac.compare_digest(token_nonce, str(expected_nonce)):
            raise IDTokenValidationError("id token nonce does not match the authorization request")

        return payload


def _audience_matches(aud: Any, expected: str) -> bool:
    if isinstance(aud, str):
        return aud == expected
    if isinstance(aud, list):
        return expected in [str(a) for a in aud]
    return False


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
