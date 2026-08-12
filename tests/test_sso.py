"""Tests for CAP-123: OIDC+PKCE SSO enforced at one auth choke point.

Every test is hermetic: no network (a fake IdP transport is injected), no live
secret, injected clock and deterministic session-token factory, temp-free. The
fake IdP mints HS256-signed ID tokens so the real signature/validation path runs
fully offline.
"""

from __future__ import annotations

import json
import time

import pytest

from thomas.security.sso import (
    HS256Verifier,
    IDTokenValidationError,
    PendingLogin,
    SSOConfig,
    SSODecision,
    SSODenied,
    SSOEngine,
    SSORequestContext,
    SSOSessionStore,
    TokenExchangeError,
    b64url_encode,
    enforce_sso,
    pkce_challenge,
    request_context_from_request,
    require_sso,
)

ISSUER = "https://idp.example.test"
CLIENT_ID = "thomas-relying-party"
REDIRECT = "https://app.thomas.test/auth/callback"
SHARED_SECRET = "hermetic-hs256-signing-secret"
FIXED_NOW = 1_000_000.0


# ---------------------------------------------------------------------------
# Hermetic fake IdP (the injected transport) -- no network
# ---------------------------------------------------------------------------


def _encode_hs256_jwt(claims: dict, *, secret: str = SHARED_SECRET, alg: str = "HS256") -> str:
    import hashlib
    import hmac

    header = {"alg": alg, "typ": "JWT"}
    header_b64 = b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = b64url_encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{b64url_encode(sig)}"


class FakeIdP:
    """A hermetic OIDC IdP: registers PKCE challenges and enforces the verifier.

    ``authorize`` is what the browser redirect would hit -- it binds a code to a
    ``code_challenge`` and a ``nonce``.  ``exchange_code`` is the injected
    :class:`IdPTransport` method: it recomputes the S256 challenge from the
    presented ``code_verifier`` (exactly as a real IdP does) and refuses on
    mismatch, otherwise returns an HS256-signed ID token.
    """

    def __init__(self, *, now: float = FIXED_NOW, id_token_ttl_s: float = 3600.0) -> None:
        self._codes: dict[str, dict] = {}
        self._now = now
        self._id_token_ttl_s = id_token_ttl_s
        self.exchange_calls = 0

    def authorize(self, *, code: str, code_challenge: str, nonce: str, sub: str = "user-123") -> None:
        self._codes[code] = {"code_challenge": code_challenge, "nonce": nonce, "sub": sub}

    # -- IdPTransport protocol --------------------------------------------
    def exchange_code(self, token_endpoint: str, form) -> dict:
        self.exchange_calls += 1
        code = str(form.get("code") or "")
        record = self._codes.get(code)
        if record is None:
            return {"error": "invalid_grant", "error_description": "unknown code"}
        presented_verifier = str(form.get("code_verifier") or "")
        if pkce_challenge(presented_verifier) != record["code_challenge"]:
            # This is exactly how a real IdP rejects a bad code_verifier.
            return {"error": "invalid_grant", "error_description": "pkce verification failed"}
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": record["sub"],
            "email": "user@thomas.test",
            "nonce": record["nonce"],
            "iat": self._now,
            "exp": self._now + self._id_token_ttl_s,
        }
        return {
            "access_token": "fake-access-token",
            "token_type": "Bearer",
            "id_token": _encode_hs256_jwt(claims),
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config() -> SSOConfig:
    return SSOConfig(issuer=ISSUER, client_id=CLIENT_ID, redirect_uri=REDIRECT)


@pytest.fixture()
def counter_tokens():
    seq = iter(f"sess-{i}" for i in range(1, 1000))
    return lambda: next(seq)


@pytest.fixture()
def engine(config, counter_tokens) -> tuple[SSOEngine, FakeIdP]:
    idp = FakeIdP(now=FIXED_NOW)
    eng = SSOEngine(
        config=config,
        verifier=HS256Verifier(SHARED_SECRET),
        transport=idp,
        store=SSOSessionStore(token_factory=counter_tokens),
        clock=lambda: FIXED_NOW,
        rand=iter(["state-A", "nonce-A", "state-B", "nonce-B"]).__next__,
    )
    return eng, idp


def _run_pkce_login(eng: SSOEngine, idp: FakeIdP, *, code: str = "auth-code-1") -> PendingLogin:
    pending = eng.begin_login()
    # Simulate the authorize redirect: IdP records the challenge + nonce.
    idp.authorize(code=code, code_challenge=pending.code_challenge, nonce=pending.nonce)
    return pending


# ---------------------------------------------------------------------------
# (1) PKCE flow completes and establishes a session
# ---------------------------------------------------------------------------


def test_pkce_flow_completes_and_establishes_session(engine):
    eng, idp = engine
    pending = _run_pkce_login(eng, idp)

    # Authorize URL carries the S256 code_challenge and matches the verifier.
    assert "code_challenge_method=S256" in pending.authorize_url
    assert f"code_challenge={pending.code_challenge}" in pending.authorize_url
    assert pkce_challenge(pending.code_verifier) == pending.code_challenge

    session = eng.complete_login(pending, "auth-code-1", returned_state=pending.state)
    assert session.subject == "user-123"
    assert session.email == "user@thomas.test"
    assert session.issuer == ISSUER
    assert session.audience == CLIENT_ID
    assert session.is_active(FIXED_NOW)
    # Session is retrievable from the store by its opaque token.
    assert eng.store.get(session.session_id) is session


# ---------------------------------------------------------------------------
# (2) bad code_verifier is rejected
# ---------------------------------------------------------------------------


def test_bad_code_verifier_is_rejected(engine):
    eng, idp = engine
    pending = _run_pkce_login(eng, idp)
    tampered = PendingLogin(
        state=pending.state,
        nonce=pending.nonce,
        code_verifier="not-the-real-verifier",
        code_challenge=pending.code_challenge,
        redirect_uri=pending.redirect_uri,
        authorize_url=pending.authorize_url,
        expires_at=pending.expires_at,
    )
    with pytest.raises(TokenExchangeError):
        eng.complete_login(tampered, "auth-code-1", returned_state=pending.state)
    assert len(eng.store) == 0


# ---------------------------------------------------------------------------
# (3) wrong nonce is rejected
# ---------------------------------------------------------------------------


def test_wrong_nonce_is_rejected(engine):
    eng, idp = engine
    pending = eng.begin_login()
    # IdP records a DIFFERENT nonce than the pending login expects.
    idp.authorize(code="auth-code-1", code_challenge=pending.code_challenge, nonce="attacker-nonce")
    with pytest.raises(IDTokenValidationError):
        eng.complete_login(pending, "auth-code-1", returned_state=pending.state)
    assert len(eng.store) == 0


# ---------------------------------------------------------------------------
# (4) expired token is rejected
# ---------------------------------------------------------------------------


def test_expired_id_token_is_rejected(engine, config, counter_tokens):
    # IdP issues a token that expired well before the engine's clock.
    idp = FakeIdP(now=FIXED_NOW - 10_000.0, id_token_ttl_s=1.0)
    eng = SSOEngine(
        config=config,
        verifier=HS256Verifier(SHARED_SECRET),
        transport=idp,
        store=SSOSessionStore(token_factory=counter_tokens),
        clock=lambda: FIXED_NOW,
        rand=iter(["state-A", "nonce-A"]).__next__,
    )
    pending = eng.begin_login()
    idp.authorize(code="auth-code-1", code_challenge=pending.code_challenge, nonce=pending.nonce)
    with pytest.raises(IDTokenValidationError):
        eng.complete_login(pending, "auth-code-1", returned_state=pending.state)


def test_forged_signature_is_rejected(engine):
    eng, idp = engine
    # Verifier expects SHARED_SECRET; validate a token signed with a wrong key.
    forged = _encode_hs256_jwt(
        {"iss": ISSUER, "aud": CLIENT_ID, "sub": "x", "nonce": "n", "exp": FIXED_NOW + 100},
        secret="wrong-secret",
    )
    with pytest.raises(IDTokenValidationError):
        eng.validate_id_token(forged, expected_nonce="n", now=FIXED_NOW)


def test_state_mismatch_is_rejected(engine):
    eng, idp = engine
    pending = _run_pkce_login(eng, idp)
    with pytest.raises(TokenExchangeError):
        eng.complete_login(pending, "auth-code-1", returned_state="forged-state")


# ---------------------------------------------------------------------------
# (5) enforce_sso denies unauthenticated and allows an authenticated session
# ---------------------------------------------------------------------------


def test_enforce_denies_unauthenticated_and_allows_session(engine):
    eng, idp = engine
    store = eng.store

    anon = SSORequestContext(surface="web", session_token=None)
    denied = enforce_sso(anon, store, now=FIXED_NOW)
    assert denied.allowed is False
    assert bool(denied) is False

    pending = _run_pkce_login(eng, idp)
    session = eng.complete_login(pending, "auth-code-1", returned_state=pending.state)

    authed = SSORequestContext(surface="web", session_token=session.session_id)
    allowed = enforce_sso(authed, store, now=FIXED_NOW)
    assert allowed.allowed is True
    assert allowed.subject == session.subject

    # An unknown/forged token is denied.
    bogus = SSORequestContext(surface="web", session_token="not-a-session")
    assert enforce_sso(bogus, store, now=FIXED_NOW).allowed is False

    # An expired session is denied at the same choke point.
    assert enforce_sso(authed, store, now=session.expires_at + 1).allowed is False


def test_require_sso_hook_raises_on_deny_and_returns_session(engine):
    eng, idp = engine
    store = eng.store
    with pytest.raises(SSODenied):
        require_sso(SSORequestContext(surface="gateway", session_token=None), store, now=FIXED_NOW)

    pending = _run_pkce_login(eng, idp)
    session = eng.complete_login(pending, "auth-code-1", returned_state=pending.state)
    got = require_sso(
        SSORequestContext(surface="gateway", session_token=session.session_id),
        store,
        now=FIXED_NOW,
    )
    assert got.session_id == session.session_id


# ---------------------------------------------------------------------------
# (6) SAME enforcement result for two different surface contexts (one choke point)
# ---------------------------------------------------------------------------


def test_identical_decision_across_surfaces(engine):
    eng, idp = engine
    store = eng.store
    pending = _run_pkce_login(eng, idp)
    session = eng.complete_login(pending, "auth-code-1", returned_state=pending.state)

    surfaces = ["web", "app", "gateway", "realtime"]
    decisions = [
        enforce_sso(SSORequestContext(surface=s, session_token=session.session_id), store, now=FIXED_NOW)
        for s in surfaces
    ]
    # Byte-for-byte identical decision regardless of surface.
    first = decisions[0]
    assert first.allowed is True
    for d in decisions[1:]:
        assert d == first

    # And identical denials across surfaces for an unauthenticated request.
    denials = [enforce_sso(SSORequestContext(surface=s, session_token=None), store, now=FIXED_NOW) for s in surfaces]
    assert all(d == denials[0] for d in denials)
    assert denials[0].allowed is False


class _FakeRequest:
    """Duck-typed request with headers + cookies, no aiohttp needed."""

    def __init__(self, headers=None, cookies=None) -> None:
        self.headers = headers or {}
        self.cookies = cookies or {}


def test_request_adapter_funnels_every_surface_to_same_context(engine):
    eng, idp = engine
    store = eng.store
    pending = _run_pkce_login(eng, idp)
    session = eng.complete_login(pending, "auth-code-1", returned_state=pending.state)
    token = session.session_id

    # Web surface carries the token in a cookie; gateway in a bearer header;
    # app in the explicit SSO header. All must produce the SAME allow decision.
    web_ctx = request_context_from_request(_FakeRequest(cookies={"thomas_sso_session": token}), "web")
    gw_ctx = request_context_from_request(_FakeRequest(headers={"Authorization": f"Bearer {token}"}), "gateway")
    app_ctx = request_context_from_request(_FakeRequest(headers={"X-SSO-Session": token}), "app")

    d_web = enforce_sso(web_ctx, store, now=FIXED_NOW)
    d_gw = enforce_sso(gw_ctx, store, now=FIXED_NOW)
    d_app = enforce_sso(app_ctx, store, now=FIXED_NOW)
    assert d_web.allowed is True
    assert d_web == d_gw == d_app


def test_decision_is_a_plain_value_object():
    # Guards the "identical decision" contract: SSODecision equality ignores no
    # relevant field and includes no surface, so cross-surface equality holds.
    a = SSODecision(True, "sso session active", subject="s", session_id="sid")
    b = SSODecision(True, "sso session active", subject="s", session_id="sid")
    assert a == b


def test_real_default_transport_is_stdlib_urllib():
    # The real default transport must be constructible with no third-party deps.
    from thomas.security.sso import UrllibIdPTransport

    transport = UrllibIdPTransport(timeout_s=5.0)
    assert hasattr(transport, "exchange_code")


def test_clock_defaults_to_walltime_but_is_injectable(config):
    eng = SSOEngine(config=config, verifier=HS256Verifier(SHARED_SECRET))
    assert callable(eng.clock)
    # Default clock is time.time; sanity check it returns a float near now.
    assert abs(eng.clock() - time.time()) < 5.0
