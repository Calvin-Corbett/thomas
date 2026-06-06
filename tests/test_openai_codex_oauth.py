import base64
import json
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.models.discovery import handshake_models_async
from thomas.server.app import create_app
from thomas.server.app_keys import APP_CONFIG, APP_SECRETS
from thomas.server.openai_codex_oauth import (
    OPENAI_CODEX_CLIENT_ID,
    build_authorize_url,
    ensure_openai_codex_access_token,
    generate_pkce_pair,
    has_openai_codex_token,
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
                )
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

        api_models_resp = await self.client.get("/api/models")
        api_models = await api_models_resp.json()
        chatgpt = next(p for p in api_models["profiles"] if p["name"] == "chatgpt")
        assert chatgpt["has_api_key"] is True
        assert chatgpt["provider"] == "openai_codex"

        cfg = self.app[APP_CONFIG].models["chatgpt"]
        cfg.api_key = "access"
        hs = await handshake_models_async(cfg)
        assert hs.ok is True
        assert hs.models == ["gpt-5.5"]

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
