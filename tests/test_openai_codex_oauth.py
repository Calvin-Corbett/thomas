import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.models.discovery import handshake_models_async
from thomas.server.app import create_app
from thomas.server.app_keys import APP_CONFIG, APP_SECRETS
from thomas.server.openai_codex_oauth import (
    OPENAI_CODEX_CLIENT_ID,
    OpenAICodexOAuthError,
    build_authorize_url,
    clear_openai_codex_token,
    ensure_openai_codex_access_token,
    generate_pkce_pair,
    has_openai_codex_token,
    import_local_codex_token,
    read_openai_codex_token,
    write_openai_codex_token,
)


def _jwt(payload: dict) -> str:
    def enc(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc(payload)}.sig"


def _token_payload(*, email: str = "test@example.com", exp: int | None = None) -> dict:
    exp = exp or int(time.time() + 3600)
    claims = {
        "exp": exp,
        "https://api.openai.com/profile": {"email": email},
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "acct_123",
            "chatgpt_plan_type": "pro",
            "chatgpt_user_id": "user_123",
        },
    }
    return {
        "access_token": _jwt(claims),
        "refresh_token": "refresh_123",
        "id_token": _jwt(claims),
        "expires_in": 3600,
    }


def _write_codex_auth(codex_home: Path, tokens: dict) -> None:
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(
        json.dumps({"auth_mode": "chatgpt", "tokens": tokens}),
        encoding="utf-8",
    )


def test_authorize_url_matches_codex_pkce_shape() -> None:
    verifier, challenge = generate_pkce_pair()
    assert verifier
    url = build_authorize_url(code_challenge=challenge, state="state-1")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.openai.com"
    assert qs["client_id"] == [OPENAI_CODEX_CLIENT_ID]
    assert qs["response_type"] == ["code"]
    assert qs["redirect_uri"] == ["http://localhost:1455/auth/callback"]
    assert qs["code_challenge"] == [challenge]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["id_token_add_organizations"] == ["true"]
    assert qs["codex_cli_simplified_flow"] == ["true"]
    assert "api.connectors.read" in qs["scope"][0]
    assert "api.connectors.invoke" in qs["scope"][0]


class TestOpenAICodexTokenStore(unittest.TestCase):
    def test_token_store_reports_ready_and_public_claims(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            from thomas.server.secrets import SecretStore

            store = SecretStore(root)
            stored = write_openai_codex_token(store, "chatgpt", _token_payload(), persist=True)
            assert stored["email"] == "test@example.com"
            assert stored["account_id"] == "acct_123"
            assert stored["plan_type"] == "pro"
            assert has_openai_codex_token(store, "chatgpt") is True

            reloaded = SecretStore(root)
            token = read_openai_codex_token(reloaded, "chatgpt")
            assert token is not None
            assert token["email"] == "test@example.com"

    def test_compatible_profiles_share_one_persistent_token(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            from thomas.server.secrets import SecretStore

            store = SecretStore(root)
            write_openai_codex_token(store, "chatgpt", _token_payload(), persist=True)

            reloaded = SecretStore(root)
            for profile in (
                "chatgpt",
                "codex",
                "openai-codex",
                "openai_codex",
                "forgecode",
                None,
            ):
                token = read_openai_codex_token(reloaded, profile)
                assert token is not None
                assert token["email"] == "test@example.com"

    def test_legacy_alias_token_is_read_migrated_and_cleared_as_one_identity(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            from thomas.server.secrets import SecretStore

            store = SecretStore(root)
            legacy_key = "__openai_codex_oauth__:chatgpt"
            store.set(legacy_key, json.dumps(_token_payload()), persist=True)
            assert has_openai_codex_token(store, "openai_codex") is True

            write_openai_codex_token(store, "openai_codex", _token_payload(email="migrated@example.com"), persist=True)
            reloaded = SecretStore(root)
            assert reloaded.get(legacy_key) is None
            assert read_openai_codex_token(reloaded, "chatgpt")["email"] == "migrated@example.com"

            clear_openai_codex_token(reloaded, "codex")
            final_store = SecretStore(root)
            assert has_openai_codex_token(final_store, "chatgpt") is False
            assert has_openai_codex_token(final_store, "openai_codex") is False

    def test_ensure_access_token_refreshes_expired_access_token(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            from thomas.server.secrets import SecretStore

            store = SecretStore(root)
            expired = _token_payload(exp=int(time.time() - 10))
            expired.pop("expires_in", None)
            expired["expires_at"] = int(time.time() - 10)
            write_openai_codex_token(store, "chatgpt", expired, persist=True)
            fresh = _token_payload(email="fresh@example.com")

            async def fake_refresh(refresh_token: str):
                assert refresh_token == "refresh_123"
                return fresh

            with patch("thomas.server.openai_codex_oauth.refresh_openai_codex_token", fake_refresh):
                token = __import__("asyncio").run(ensure_openai_codex_access_token("chatgpt", secret_store=store))
            assert token == fresh["access_token"]
            assert read_openai_codex_token(store, "chatgpt")["email"] == "fresh@example.com"

    def test_refresh_transport_failure_is_normalized_without_token_detail(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            from thomas.server.secrets import SecretStore

            store = SecretStore(root)
            expired = _token_payload(exp=int(time.time() - 10))
            expired.pop("expires_in", None)
            expired["expires_at"] = int(time.time() - 10)
            write_openai_codex_token(store, "chatgpt", expired, persist=True)

            class _FailingClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return False

                async def post(self, *_args, **_kwargs):
                    raise httpx.ConnectError("sensitive upstream detail")

            with patch("thomas.server.openai_codex_oauth.httpx.AsyncClient", return_value=_FailingClient()):
                with pytest.raises(OpenAICodexOAuthError, match="could not reach the OAuth service") as caught:
                    __import__("asyncio").run(ensure_openai_codex_access_token("chatgpt", secret_store=store))

            assert "sensitive upstream detail" not in str(caught.value)

    def test_refresh_http_error_never_copies_provider_body(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            from thomas.server.secrets import SecretStore

            store = SecretStore(root)
            expired = _token_payload(exp=int(time.time() - 10))
            expired.pop("expires_in", None)
            expired["expires_at"] = int(time.time() - 10)
            write_openai_codex_token(store, "chatgpt", expired, persist=True)

            class _SecretResponse:
                status_code = 400
                text = "refresh_token=TOP_SECRET_REFRESH"

            class _RejectingClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return False

                async def post(self, *_args, **_kwargs):
                    return _SecretResponse()

            with (
                patch.dict(os.environ, {"CODEX_HOME": str(Path(root) / "missing-codex-home")}),
                patch("thomas.server.openai_codex_oauth.httpx.AsyncClient", return_value=_RejectingClient()),
            ):
                with pytest.raises(OpenAICodexOAuthError, match="HTTP 400") as caught:
                    __import__("asyncio").run(ensure_openai_codex_access_token("chatgpt", secret_store=store))

            assert "TOP_SECRET_REFRESH" not in str(caught.value)


def test_default_secret_store_respects_secret_root_override(tmp_path, monkeypatch) -> None:
    from thomas.server.secrets import SecretStore

    store = SecretStore(tmp_path)
    token_payload = _token_payload()
    write_openai_codex_token(store, "chatgpt", token_payload, persist=True)
    monkeypatch.setenv("THOMAS_SECRET_ROOT", str(tmp_path))

    token = __import__("asyncio").run(ensure_openai_codex_access_token("chatgpt"))

    assert token == token_payload["access_token"]


def test_import_local_codex_token_adopts_existing_app_login(tmp_path) -> None:
    from thomas.server.secrets import SecretStore

    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    source = _token_payload(email="codex-owner@example.com")
    (codex_home / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "OPENAI_API_KEY": "must-not-be-imported",
                "tokens": {
                    "access_token": source["access_token"],
                    "refresh_token": source["refresh_token"],
                    "id_token": source["id_token"],
                    "account_id": "acct_local",
                },
            }
        ),
        encoding="utf-8",
    )
    store = SecretStore(tmp_path / "thomas-secrets")

    imported = import_local_codex_token(store, "openai_codex", codex_home=codex_home)

    assert imported is not None
    assert imported["access_token"] == source["access_token"]
    assert imported["refresh_token"] == source["refresh_token"]
    assert imported["account_id"] == "acct_local"
    assert "must-not-be-imported" not in json.dumps(imported)
    assert has_openai_codex_token(store, "openai_codex") is True


def test_import_local_codex_token_replaces_expired_store_with_ready_rotated_pair(tmp_path) -> None:
    from thomas.server.secrets import SecretStore

    store = SecretStore(tmp_path / "thomas-secrets")
    expired = _token_payload(email="stale@example.com", exp=int(time.time() - 60))
    expired["refresh_token"] = "stale-refresh"
    expired.pop("expires_in", None)
    write_openai_codex_token(store, "openai_codex", expired, persist=True)

    current = _token_payload(email="current@example.com")
    current["refresh_token"] = "current-refresh"
    codex_home = tmp_path / ".codex"
    _write_codex_auth(codex_home, current)

    imported = import_local_codex_token(store, "openai_codex", codex_home=codex_home)

    assert imported is not None
    assert imported["access_token"] == current["access_token"]
    assert imported["refresh_token"] == "current-refresh"


def test_import_local_codex_token_does_not_replace_access_ready_store(tmp_path) -> None:
    from thomas.server.secrets import SecretStore

    store = SecretStore(tmp_path / "thomas-secrets")
    stored = _token_payload(email="stored@example.com")
    stored["refresh_token"] = "stored-refresh"
    write_openai_codex_token(store, "openai_codex", stored, persist=True)

    local = _token_payload(email="local@example.com", exp=int(time.time() + 7200))
    local["refresh_token"] = "local-refresh"
    codex_home = tmp_path / ".codex"
    _write_codex_auth(codex_home, local)

    imported = import_local_codex_token(store, "openai_codex", codex_home=codex_home)

    assert imported is not None
    assert imported["access_token"] == stored["access_token"]
    assert imported["refresh_token"] == "stored-refresh"


def test_ensure_recovers_once_from_rejected_stale_refresh_with_ready_local_pair(tmp_path, monkeypatch) -> None:
    from thomas.server.secrets import SecretStore

    store = SecretStore(tmp_path / "thomas-secrets")
    expired = _token_payload(email="stale@example.com", exp=int(time.time() - 60))
    expired["refresh_token"] = "stale-refresh"
    expired.pop("expires_in", None)
    write_openai_codex_token(store, "openai_codex", expired, persist=True)

    current = _token_payload(email="current@example.com")
    current["refresh_token"] = "current-refresh"
    codex_home = tmp_path / ".codex"
    _write_codex_auth(codex_home, current)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    refresh_attempts = 0

    async def rejected_refresh(refresh_token: str):
        nonlocal refresh_attempts
        refresh_attempts += 1
        assert refresh_token == "stale-refresh"
        raise OpenAICodexOAuthError("Token refresh failed with HTTP 401.", status_code=401)

    with patch("thomas.server.openai_codex_oauth.refresh_openai_codex_token", rejected_refresh):
        access_token = __import__("asyncio").run(
            ensure_openai_codex_access_token("openai_codex", secret_store=store)
        )

    assert refresh_attempts == 1
    assert access_token == current["access_token"]
    persisted = read_openai_codex_token(store, "openai_codex")
    assert persisted is not None
    assert persisted["refresh_token"] == "current-refresh"


def test_ensure_does_not_replace_with_same_or_expired_local_pair(tmp_path, monkeypatch) -> None:
    from thomas.server.secrets import SecretStore

    store = SecretStore(tmp_path / "thomas-secrets")
    expired = _token_payload(email="stale@example.com", exp=int(time.time() - 60))
    expired["refresh_token"] = "stale-refresh"
    expired.pop("expires_in", None)
    write_openai_codex_token(store, "openai_codex", expired, persist=True)

    unusable = _token_payload(email="also-stale@example.com", exp=int(time.time() - 30))
    unusable["refresh_token"] = "different-but-unusable"
    unusable.pop("expires_in", None)
    codex_home = tmp_path / ".codex"
    _write_codex_auth(codex_home, unusable)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    refresh_attempts = 0

    async def rejected_refresh(_refresh_token: str):
        nonlocal refresh_attempts
        refresh_attempts += 1
        raise OpenAICodexOAuthError("Token refresh failed with HTTP 400.", status_code=400)

    with patch("thomas.server.openai_codex_oauth.refresh_openai_codex_token", rejected_refresh):
        with pytest.raises(OpenAICodexOAuthError, match="HTTP 400"):
            __import__("asyncio").run(ensure_openai_codex_access_token("openai_codex", secret_store=store))

    assert refresh_attempts == 1
    persisted = read_openai_codex_token(store, "openai_codex")
    assert persisted is not None
    assert persisted["refresh_token"] == "stale-refresh"


def test_import_local_codex_token_can_be_disabled(tmp_path, monkeypatch) -> None:
    from thomas.server.secrets import SecretStore

    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"tokens": _token_payload()}), encoding="utf-8")
    monkeypatch.setenv("THOMAS_IMPORT_LOCAL_CODEX_AUTH", "0")

    assert import_local_codex_token(SecretStore(tmp_path / "secrets"), codex_home=codex_home) is None


class TestOpenAICodexRoutes(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={
                "chatgpt": ModelConfig(
                    name="chatgpt",
                    provider="openai_codex",
                    base_url="https://chatgpt.com/backend-api/codex",
                    model="gpt-5.5",
                ),
                "openai_codex": ModelConfig(
                    name="openai_codex",
                    provider="openai_codex",
                    base_url="https://chatgpt.com/backend-api/codex",
                    model="gpt-5.6-sol",
                ),
            },
            default_model="chatgpt",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_status_models_and_handshake_use_stored_oauth_token(self):
        store = self.app[APP_SECRETS]
        write_openai_codex_token(store, "chatgpt", _token_payload(), persist=True)

        status_resp = await self.client.get("/api/openai-codex/status?profile=chatgpt")
        assert status_resp.status == 200
        status = await status_resp.json()
        assert status["logged_in"] is True
        assert status["email"] == "test@example.com"

        models_resp = await self.client.get("/api/openai-codex/models?profile=chatgpt")
        models = await models_resp.json()
        assert models["models"][0]["id"] == "gpt-5.5"
        assert {row["id"] for row in models["models"]}.issuperset({"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"})
        luna = next(row for row in models["models"] if row["id"] == "gpt-5.6-luna")
        assert luna["available"] is True
        assert "unavailable_reason" not in luna

        api_models_resp = await self.client.get("/api/models")
        api_models = await api_models_resp.json()
        chatgpt = next(p for p in api_models["profiles"] if p["name"] == "chatgpt")
        assert chatgpt["has_api_key"] is True
        assert chatgpt["provider"] == "openai_codex"

        cfg = self.app[APP_CONFIG].models["chatgpt"]
        cfg.api_key = "access"
        hs = await handshake_models_async(cfg)
        assert hs.ok is True
        assert hs.models == ["gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]

    async def test_status_without_profile_uses_canonical_openai_codex_profile(self):
        store = self.app[APP_SECRETS]
        write_openai_codex_token(store, "openai_codex", _token_payload(), persist=True)

        status_resp = await self.client.get("/api/openai-codex/status")

        assert status_resp.status == 200
        status = await status_resp.json()
        assert status["profile"] == "openai_codex"
        assert status["logged_in"] is True
        assert status["needs_login"] is False

    async def test_login_start_and_complete_stores_token(self):
        start_resp = await self.client.post(
            "/api/openai-codex/login/start",
            json={"profile": "chatgpt", "open_browser": False},
        )
        assert start_resp.status == 200
        start = await start_resp.json()

        async def fake_exchange_code_for_tokens(**kwargs):
            assert kwargs["code"] == "code_123"
            assert kwargs["redirect_uri"] == "http://localhost:1455/auth/callback"
            return _token_payload()

        with patch("thomas.server.routes.openai_codex_aiohttp.exchange_code_for_tokens", fake_exchange_code_for_tokens):
            complete_resp = await self.client.post(
                "/api/openai-codex/login/complete",
                json={
                    "state": start["state"],
                    "code": "code_123",
                },
            )
        assert complete_resp.status == 200
        complete = await complete_resp.json()
        assert complete["ok"] is True
        assert complete["logged_in"] is True
        assert has_openai_codex_token(self.app[APP_SECRETS], "chatgpt") is True


def test_model_settings_scopes_oauth_status_login_and_logout_to_selected_profile() -> None:
    text = (Path(__file__).parents[1] / "thomas/server/web/js/model_settings_dropdown.js").read_text(encoding="utf-8")

    assert "provider === 'codex' || provider === 'openai_codex'" in text
    assert "status?profile=' + encodeURIComponent(profile.name)" in text
    assert text.count("body: JSON.stringify({ profile: profile.name })") == 2
