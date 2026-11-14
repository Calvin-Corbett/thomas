"""A recovered ChatGPT token never gets written into a model config the client did not bring a token in.

The revoked-token recovery (34ef48a5) kept the recovered token for the rest of a run by writing it into the client's
ModelConfig. Chat announcements, self-review and the companion routes build their clients from the app's shared
config, which carries no token and reads the secret store on every call. One recovery there pinned the token into
the app's config until a restart: an account switch and a sign-out no longer took effect, and an expired token was
sent instead of refreshed. A client that brought its own token (a Build child) still keeps the recovered one.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import httpx
import pytest

from thomas.core import codex_auth
from thomas.core.llm_streaming import stream_openai_codex
from thomas.server import openai_codex_oauth as oauth
from thomas.server.secrets import SecretStore

OK = 'event: response.output_text.delta\ndata: {"delta":"ok"}\n\nevent: response.completed\ndata: {"response":{}}\n\n'


class _Lease:
    output_cap = 4096


class _Owner:
    _max_retries = 1
    _base_retry_delay = 0

    def __init__(self, client: httpx.AsyncClient, api_key: str = "") -> None:
        self.client = client
        self.config = SimpleNamespace(
            name="openai_codex", model="gpt-test", api_key=api_key, base_url="https://x/codex", max_tokens=4096
        )

    async def _get_client(self) -> httpx.AsyncClient:
        return self.client

    async def begin_budget_attempt(self, *_: object) -> _Lease:
        return _Lease()

    async def abort_budget_attempt(self, *_: object) -> None:
        pass

    async def finish_budget_attempt(self, *_: object) -> None:
        pass


@pytest.fixture
def signed_in(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "store")
    oauth.write_openai_codex_token(store, "openai_codex", {"access_token": "old", "expires_at": time.time() + 3600})
    home = tmp_path / "codex"
    home.mkdir()
    (home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "live"}}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("THOMAS_SECRET_ROOT", str(tmp_path / "store"))
    monkeypatch.setattr(oauth, "_server_secret_store", store)
    monkeypatch.setattr(codex_auth, "_access_token_resolver", oauth._resolve_registered_access_token)
    monkeypatch.setattr(codex_auth, "_rejected_token_recovery", oauth._recover_rejected_access_token)
    monkeypatch.setattr(codex_auth, "_recovered_tokens", {})
    return SimpleNamespace(store=store, home=home)


async def _call(owner: _Owner) -> None:
    [event async for event in stream_openai_codex(owner, [{"role": "user", "content": "hi"}])]


def _server(attempts: list[str]) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        token = request.headers["Authorization"].removeprefix("Bearer ")
        attempts.append(token)
        if token == "old":
            return httpx.Response(401, json={"error": {"code": "token_revoked"}})
        return httpx.Response(200, text=OK)

    return httpx.MockTransport(respond)


@pytest.mark.asyncio
async def test_an_account_switch_after_a_recovery_reaches_a_shared_client(signed_in) -> None:
    attempts: list[str] = []
    async with httpx.AsyncClient(transport=_server(attempts)) as client:
        shared = _Owner(client)
        await _call(shared)
        assert shared.config.api_key == "", "the shared config still reads the store"
        oauth.write_openai_codex_token(signed_in.store, "openai_codex", {"access_token": "switched", "expires_at": time.time() + 3600})  # fmt: skip
        await _call(shared)
    assert attempts == ["old", "live", "switched"]


@pytest.mark.asyncio
async def test_a_sign_out_after_a_recovery_reaches_a_shared_client(signed_in) -> None:
    attempts: list[str] = []
    async with httpx.AsyncClient(transport=_server(attempts)) as client:
        shared = _Owner(client)
        await _call(shared)
        oauth.clear_openai_codex_token(signed_in.store, "openai_codex")
        (signed_in.home / "auth.json").unlink()
        with pytest.raises(Exception):  # noqa: B017 - not connected, whatever the words
            await _call(shared)
    assert attempts == ["old", "live"], "the recovered token is never sent after a sign-out"


@pytest.mark.asyncio
async def test_a_client_that_brought_its_token_keeps_the_recovered_one(signed_in) -> None:
    attempts: list[str] = []
    async with httpx.AsyncClient(transport=_server(attempts)) as client:
        child = _Owner(client, api_key="old")  # a Build child handed the stored token when it started
        await _call(child)
        await _call(child)
    assert attempts == ["old", "live", "live"]
