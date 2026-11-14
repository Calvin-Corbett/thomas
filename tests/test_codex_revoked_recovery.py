"""Offline provider 401 recovery and terminal Build failure regressions."""

import json
import time
from types import SimpleNamespace

import httpx
import pytest

from thomas.core import codex_auth
from thomas.core.llm_shared import LLMError
from thomas.core.llm_streaming import stream_openai_codex
from thomas.server import openai_codex_oauth as oauth
from thomas.server.praxis.worker import build_read_child_runner
from thomas.server.secrets import SecretStore


class _Lease:
    output_cap = 4096


class _Owner:
    _max_retries = 1
    _base_retry_delay = 0

    def __init__(self, client):
        self.client = client
        self.config = SimpleNamespace(
            name="openai_codex",
            model="gpt-test",
            api_key="",
            base_url="https://chatgpt.com/backend-api/codex",
            max_tokens=4096,
        )

    async def _get_client(self):
        return self.client

    async def begin_budget_attempt(self, *_):
        return _Lease()

    async def abort_budget_attempt(self, *_):
        pass

    async def finish_budget_attempt(self, *_):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("live_accepted", [True, False])
async def test_rejected_stored_token_imports_live_login_once(tmp_path, monkeypatch, live_accepted):
    store = SecretStore(tmp_path / "store")
    oauth.write_openai_codex_token(
        store,
        "openai_codex",
        {"access_token": "old", "refresh_token": "old-refresh", "expires_at": time.time() + 67 * 3600},
    )
    home = tmp_path / "codex"
    home.mkdir()
    source = home / "auth.json"
    source.write_text(
        json.dumps({"tokens": {"access_token": "live", "refresh_token": "new-refresh"}}), encoding="utf-8"
    )
    original = source.read_bytes()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("THOMAS_SECRET_ROOT", str(tmp_path / "store"))
    monkeypatch.setattr(oauth, "_server_secret_store", store)
    monkeypatch.setattr(codex_auth, "_access_token_resolver", oauth._resolve_registered_access_token)
    monkeypatch.setattr(codex_auth, "_rejected_token_recovery", oauth._recover_rejected_access_token)
    attempts = []

    def reply(request):
        token = request.headers["Authorization"].removeprefix("Bearer ")
        attempts.append(token)
        if token == "old" or not live_accepted:
            return httpx.Response(401, json={"error": {"code": "token_revoked", "message": "invalidated oauth token"}})
        return httpx.Response(
            200,
            text='event: response.output_text.delta\ndata: {"delta":"hello"}\n\nevent: response.completed\ndata: {"response":{}}\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        owner = _Owner(client)
        if live_accepted:
            events = [event async for event in stream_openai_codex(owner, [{"role": "user", "content": "hello"}])]
            assert any(event.type == "token" for event in events)
        else:
            with pytest.raises(LLMError, match="live Codex login was revoked or invalidated") as exc:
                [event async for event in stream_openai_codex(owner, [{"role": "user", "content": "hello"}])]
            assert exc.value.status == 401
    assert attempts == ["old", "live"]
    assert source.read_bytes() == original
    assert oauth.read_openai_codex_token(store, "openai_codex")["access_token"] == "live"
    assert await oauth._resolve_registered_access_token("openai_codex") == "live"
    assert oauth._default_secret_store() is store
    store.set("other", "value", persist=True)
    assert oauth.read_openai_codex_token(SecretStore(tmp_path / "store"), "openai_codex")["access_token"] == "live"


@pytest.mark.asyncio
async def test_recovered_token_survives_multiple_calls_and_other_workers(tmp_path, monkeypatch):
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
    attempts = []

    def respond(request):
        token = request.headers["Authorization"].removeprefix("Bearer ")
        attempts.append(token)
        if token == "old":
            return httpx.Response(401, json={"error": {"code": "token_revoked"}})
        return httpx.Response(
            200,
            text='event: response.output_text.delta\ndata: {"delta":"ok"}\n\nevent: response.completed\ndata: {"response":{}}\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        first = _Owner(client)
        second = _Owner(client)
        second.config.api_key = "old"  # A worker configured before the first recovery.
        for owner in (first, first, second):
            events = [event async for event in stream_openai_codex(owner, [{"role": "user", "content": "hi"}])]
            assert any(event.type == "token" for event in events)
        assert first.config.api_key == "", "a config that brought no token keeps reading the store"
    assert attempts == ["old", "live", "live", "live"]
    assert oauth.read_openai_codex_token(store, "openai_codex")["access_token"] == "live"


@pytest.mark.asyncio
async def test_rejected_token_without_live_login_does_not_retry(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "store")
    oauth.write_openai_codex_token(store, "openai_codex", {"access_token": "old", "expires_at": time.time() + 3600})
    monkeypatch.setattr(oauth, "_server_secret_store", store)
    monkeypatch.setenv("THOMAS_SECRET_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing"))
    monkeypatch.setattr(codex_auth, "_access_token_resolver", oauth._resolve_registered_access_token)
    monkeypatch.setattr(codex_auth, "_rejected_token_recovery", oauth._recover_rejected_access_token)
    attempts = []

    def reject(request):
        attempts.append(request.headers["Authorization"])
        return httpx.Response(401, json={"error": {"code": "token_revoked"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        with pytest.raises(LLMError, match="stored token was revoked or invalidated") as exc:
            [event async for event in stream_openai_codex(_Owner(client), [{"role": "user", "content": "hi"}])]
    assert attempts == ["Bearer old"]
    assert str(exc.value) == (
        "ChatGPT/Codex HTTP 401: The stored token was revoked or invalidated by the server. "
        "No retry with a different access token was made."
    )
    assert oauth.read_openai_codex_token(store, "openai_codex") is None


@pytest.mark.asyncio
async def test_recovery_uses_a_newer_stored_token_without_deleting_it(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "store")
    oauth.write_openai_codex_token(store, "openai_codex", {"access_token": "new", "expires_at": time.time() + 3600})
    monkeypatch.setattr(oauth, "_server_secret_store", store)
    monkeypatch.setenv("THOMAS_SECRET_ROOT", str(tmp_path / "store"))
    home = tmp_path / "codex"
    home.mkdir()
    (home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "live"}}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    replacement, live_rejected = await oauth._recover_rejected_access_token("openai_codex", "old")
    assert replacement == "new"
    assert live_rejected is False
    assert oauth.read_openai_codex_token(store, "openai_codex")["access_token"] == "new"


@pytest.mark.asyncio
async def test_second_401_from_newer_stored_token_does_not_claim_live_login_was_rejected(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "store")
    oauth.write_openai_codex_token(store, "openai_codex", {"access_token": "new", "expires_at": time.time() + 3600})
    monkeypatch.setattr(oauth, "_server_secret_store", store)
    monkeypatch.setattr(codex_auth, "_recovered_tokens", {})
    monkeypatch.setenv("THOMAS_SECRET_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing"))
    monkeypatch.setattr(codex_auth, "_access_token_resolver", oauth._resolve_registered_access_token)
    monkeypatch.setattr(codex_auth, "_rejected_token_recovery", oauth._recover_rejected_access_token)
    attempts = []

    def reject(request):
        attempts.append(request.headers["Authorization"])
        return httpx.Response(401, json={"error": {"code": "token_revoked"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        owner = _Owner(client)
        owner.config.api_key = "old"
        with pytest.raises(LLMError, match="stored token was revoked or invalidated") as exc:
            [event async for event in stream_openai_codex(owner, [{"role": "user", "content": "hi"}])]
    assert attempts == ["Bearer old", "Bearer new"]
    assert oauth.read_openai_codex_token(store, "openai_codex") is None
    assert "A retry with a different stored token was also rejected" in str(exc.value)
    assert "Run `codex login`" not in str(exc.value)


@pytest.mark.asyncio
async def test_second_401_imports_live_login_without_a_second_retry(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "store")
    oauth.write_openai_codex_token(store, "openai_codex", {"access_token": "new", "expires_at": time.time() + 3600})
    home = tmp_path / "codex"
    home.mkdir()
    source = home / "auth.json"
    source.write_text(json.dumps({"tokens": {"access_token": "live"}}), encoding="utf-8")
    original = source.read_bytes()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("THOMAS_SECRET_ROOT", str(tmp_path / "store"))
    monkeypatch.setattr(oauth, "_server_secret_store", store)
    monkeypatch.setattr(codex_auth, "_recovered_tokens", {})
    monkeypatch.setattr(codex_auth, "_access_token_resolver", oauth._resolve_registered_access_token)
    monkeypatch.setattr(codex_auth, "_rejected_token_recovery", oauth._recover_rejected_access_token)
    attempts = []

    def reject(request):
        attempts.append(request.headers["Authorization"])
        return httpx.Response(401, json={"error": {"code": "token_revoked"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        owner = _Owner(client)
        owner.config.api_key = "old"
        with pytest.raises(LLMError) as exc:
            [event async for event in stream_openai_codex(owner, [{"role": "user", "content": "hi"}])]
    assert attempts == ["Bearer old", "Bearer new"]
    assert "A retry with a different stored token was also rejected" in str(exc.value)
    assert "The live Codex login was imported for the next call" in str(exc.value)
    assert "Run `codex login`" not in str(exc.value)
    assert owner.config.api_key == "live"
    assert oauth.read_openai_codex_token(store, "openai_codex")["access_token"] == "live"
    assert source.read_bytes() == original


@pytest.mark.asyncio
async def test_second_stored_401_with_same_live_login_reports_checked_login(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "store")
    oauth.write_openai_codex_token(store, "openai_codex", {"access_token": "new", "expires_at": time.time() + 3600})
    home = tmp_path / "codex"
    home.mkdir()
    source = home / "auth.json"
    source.write_text(json.dumps({"tokens": {"access_token": "new"}}), encoding="utf-8")
    original = source.read_bytes()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("THOMAS_SECRET_ROOT", str(tmp_path / "store"))
    monkeypatch.setattr(oauth, "_server_secret_store", store)
    monkeypatch.setattr(codex_auth, "_recovered_tokens", {})
    monkeypatch.setattr(codex_auth, "_access_token_resolver", oauth._resolve_registered_access_token)
    monkeypatch.setattr(codex_auth, "_rejected_token_recovery", oauth._recover_rejected_access_token)
    attempts = []

    def reject(request):
        attempts.append(request.headers["Authorization"])
        return httpx.Response(401, json={"error": {"code": "token_revoked"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        owner = _Owner(client)
        owner.config.api_key = "old"
        with pytest.raises(LLMError) as exc:
            [event async for event in stream_openai_codex(owner, [{"role": "user", "content": "hi"}])]
    assert attempts == ["Bearer old", "Bearer new"]
    assert "live Codex login still contains the rejected stored token" in str(exc.value)
    assert oauth.read_openai_codex_token(store, "openai_codex") is None
    assert source.read_bytes() == original


@pytest.mark.asyncio
async def test_newer_stored_token_is_used_when_live_login_is_missing(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "store")
    oauth.write_openai_codex_token(store, "openai_codex", {"access_token": "new", "expires_at": time.time() + 3600})
    monkeypatch.setattr(oauth, "_server_secret_store", store)
    monkeypatch.setenv("THOMAS_SECRET_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing"))
    replacement, live_rejected = await oauth._recover_rejected_access_token("openai_codex", "old")
    assert replacement == "new"
    assert live_rejected is False
    assert oauth.read_openai_codex_token(store, "openai_codex")["access_token"] == "new"


@pytest.mark.asyncio
async def test_same_rejected_token_in_live_login_is_reported_without_retry(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "store")
    oauth.write_openai_codex_token(store, "openai_codex", {"access_token": "old", "expires_at": time.time() + 3600})
    home = tmp_path / "codex"
    home.mkdir()
    source = home / "auth.json"
    source.write_text(json.dumps({"tokens": {"access_token": "old"}}), encoding="utf-8")
    original = source.read_bytes()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("THOMAS_SECRET_ROOT", str(tmp_path / "store"))
    monkeypatch.setattr(oauth, "_server_secret_store", store)
    monkeypatch.setattr(codex_auth, "_access_token_resolver", oauth._resolve_registered_access_token)
    monkeypatch.setattr(codex_auth, "_rejected_token_recovery", oauth._recover_rejected_access_token)
    attempts = []

    def rejected(request):
        attempts.append(request.headers["Authorization"])
        return httpx.Response(401, json={"error": {"code": "token_revoked"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(rejected)) as client:
        with pytest.raises(LLMError, match="live Codex login was revoked or invalidated") as exc:
            [event async for event in stream_openai_codex(_Owner(client), [{"role": "user", "content": "hi"}])]
    assert exc.value.status == 401
    assert attempts == ["Bearer old"]
    assert oauth.read_openai_codex_token(store, "openai_codex") is None
    assert source.read_bytes() == original


@pytest.mark.asyncio
async def test_build_child_does_not_call_stored_refusal_a_live_rejection(monkeypatch, tmp_path):
    from thomas.server.praxis import worker

    async def failed_worker(*args, **kwargs):
        yield {
            "type": "error",
            "error": "The stored token was revoked or invalidated by the server; live Codex login not checked",
            "provider_status": 401,
        }

    monkeypatch.setattr(worker, "_selected_model", lambda *args: ("openai_codex", "gpt-6-sol", object()))
    monkeypatch.setattr(worker, "run_agent_worker_events", failed_worker)
    run = build_read_child_runner(None, tmp_path, model_id="gpt-6-sol", run_id="offline")
    events = [event async for event in run("child", "review", "title", "brief")]
    assert len(events) == 1
    assert events[0]["provider_status"] == 401
    assert events[0]["error"] == "Build child provider HTTP 401: access token revoked or invalidated"


@pytest.mark.asyncio
async def test_build_child_newer_stored_token_rejection_does_not_name_live_login(monkeypatch, tmp_path):
    from thomas.server.praxis import worker

    async def failed_worker(*args, **kwargs):
        yield {
            "type": "error",
            "error": "ChatGPT/Codex HTTP 401: The stored token was revoked or invalidated by the server. "
            "A retry with a different stored token was also rejected.",
            "provider_status": 401,
        }

    monkeypatch.setattr(worker, "_selected_model", lambda *args: ("openai_codex", "gpt-6-sol", object()))
    monkeypatch.setattr(worker, "run_agent_worker_events", failed_worker)
    run = build_read_child_runner(None, tmp_path, model_id="gpt-6-sol", run_id="offline")
    events = [event async for event in run("child", "review", "title", "brief")]
    assert events[0]["error"] == "Build child provider HTTP 401: different stored token revoked or invalidated"
    assert events[0]["retryable"] is False


@pytest.mark.asyncio
async def test_build_child_refresh_401_names_checked_login(monkeypatch, tmp_path):
    from thomas.server.praxis import worker

    async def failed_worker(*args, **kwargs):
        yield {"type": "error", "error": "Token refresh failed with HTTP 401", "provider_status": 401}

    monkeypatch.setattr(worker, "_selected_model", lambda *args: ("openai_codex", "gpt-6-sol", object()))
    monkeypatch.setattr(worker, "run_agent_worker_events", failed_worker)
    run = build_read_child_runner(None, tmp_path, model_id="gpt-6-sol", run_id="offline")
    events = [event async for event in run("child", "review", "title", "brief")]
    assert events[0]["error"] == "Build child provider HTTP 401: live Codex login rejected during token refresh"
    assert events[0]["retryable"] is False


@pytest.mark.asyncio
async def test_build_child_401_is_terminal_with_reason(monkeypatch, tmp_path):
    from thomas.server.praxis import worker

    async def failed_worker(*args, **kwargs):
        yield {
            "type": "error",
            "error": "The live Codex login was revoked or invalidated by the server",
            "provider_status": 401,
            "retryable": True,
        }

    monkeypatch.setattr(worker, "_selected_model", lambda *args: ("openai_codex", "gpt-6-sol", object()))
    monkeypatch.setattr(worker, "run_agent_worker_events", failed_worker)
    run = build_read_child_runner(None, tmp_path, model_id="gpt-6-sol", run_id="offline")
    events = [event async for event in run("child", "review", "title", "brief")]
    assert len(events) == 1
    assert events[0]["retryable"] is False
    assert events[0]["provider_status"] == 401
    assert "revoked or invalidated" in events[0]["error"]
