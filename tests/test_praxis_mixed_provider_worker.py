"""A Praxis read child uses its selected connected account and observed model."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from thomas.core.config import ModelConfig
from thomas.server.app_keys import APP_CONFIG, APP_SECRETS
from thomas.server.praxis import worker
from thomas.server.worker_runtime import _embed_secrets


def _app(*, anthropic_key: str = ""):
    return {
        APP_CONFIG: SimpleNamespace(
            models={
                "openai_codex": ModelConfig(name="openai_codex", provider="openai_codex", model="gpt-5.6-luna"),
                "anthropic": ModelConfig(
                    name="anthropic", provider="anthropic", model="claude-sonnet-4-5", api_key=anthropic_key
                ),
            }
        ),
        APP_SECRETS: SimpleNamespace(has=lambda _name: False),
    }


def _receipt(profile: str, provider: str, model: str):
    identity = {"profile": profile, "provider": provider, "model": model}
    return {
        "requested": {**identity, "api_key": "PRIVATE"},
        "active": {**identity, "api_key": "PRIVATE"},
        "attempts": [{**identity, "status": "success", "authorization": "PRIVATE"}],
    }


def test_ui_saved_api_key_is_embedded_by_profile_without_secret_name():
    cfg = ModelConfig(name="anthropic", provider="anthropic", model="claude-sonnet-4-5")
    store = SimpleNamespace(get=lambda name: "test-key" if name == "anthropic" else "")
    embedded = _embed_secrets(cfg, "anthropic", store)
    assert embedded.api_key == "test-key"
    assert not cfg.api_key


@pytest.mark.asyncio
async def test_ui_saved_api_key_admits_selected_anthropic_child(tmp_path, monkeypatch):
    app = _app()
    app[APP_SECRETS] = SimpleNamespace(has=lambda name: name == "anthropic")

    async def fake_worker(_app, **kwargs):
        assert kwargs["profile"] == "anthropic"
        yield {"type": "model_runtime", "runtime": _receipt("anthropic", "anthropic", "claude-sonnet-4-5")}
        yield {"type": "done"}

    monkeypatch.setattr(worker, "run_agent_worker_events", fake_worker)
    runner = worker.build_read_child_runner(app, tmp_path, model_id="gpt-5.6-luna", run_id="run")
    events = [event async for event in runner("child", "review", "Review", "Inspect", {"profile": "anthropic"})]
    assert [event["type"] for event in events] == ["model_runtime", "done"]


@pytest.mark.asyncio
async def test_explicit_connected_anthropic_choice_is_exact_and_secret_safe(tmp_path, monkeypatch):
    captured = {}

    async def fake_worker(_app, **kwargs):
        captured.update(kwargs)
        yield {"type": "model_runtime", "runtime": _receipt("anthropic", "anthropic", "claude-sonnet-4-5")}
        yield {"type": "done"}

    monkeypatch.setattr(worker, "run_agent_worker_events", fake_worker)
    runner = worker.build_read_child_runner(
        _app(anthropic_key="secret"), tmp_path, model_id="gpt-5.6-luna", run_id="run"
    )
    events = [event async for event in runner("child", "review", "Review", "Inspect", {"profile": "anthropic"})]
    assert [event["type"] for event in events] == ["model_runtime", "done"]
    assert (captured["profile"], captured["model_id"], captured["role"]) == ("anthropic", "claude-sonnet-4-5", None)
    assert captured["runtime_policy"]["model"]["failover_enabled"] is False
    assert events[0]["model_used"] == "claude-sonnet-4-5"
    assert "PRIVATE" not in str(events)


@pytest.mark.asyncio
async def test_claude_cli_login_does_not_pretend_anthropic_api_is_connected(tmp_path, monkeypatch):
    calls = []

    async def fake_worker(_app, **_kwargs):
        calls.append(True)
        yield {"type": "done"}

    monkeypatch.setattr(worker, "run_agent_worker_events", fake_worker)
    runner = worker.build_read_child_runner(_app(), tmp_path, model_id="gpt-5.6-luna", run_id="run")
    events = [event async for event in runner("child", "review", "Review", "Inspect", {"profile": "anthropic"})]
    assert events == [{"type": "error", "error": "Build child model account is not connected", "retryable": False}]
    assert not calls


@pytest.mark.asyncio
async def test_provider_substitution_receipt_fails_closed(tmp_path, monkeypatch):
    async def fake_worker(_app, **_kwargs):
        yield {"type": "model_runtime", "runtime": _receipt("openai_codex", "openai_codex", "gpt-5.6-luna")}
        yield {"type": "done"}

    monkeypatch.setattr(worker, "run_agent_worker_events", fake_worker)
    runner = worker.build_read_child_runner(
        _app(anthropic_key="secret"), tmp_path, model_id="gpt-5.6-luna", run_id="run"
    )
    events = [event async for event in runner("child", "review", "Review", "Inspect", {"profile": "anthropic"})]
    assert events == [
        {"type": "error", "error": "Build child model receipt did not match its selection", "retryable": False}
    ]


@pytest.mark.asyncio
async def test_terminal_without_runtime_receipt_is_not_success(tmp_path, monkeypatch):
    async def fake_worker(_app, **_kwargs):
        yield {"type": "done"}

    monkeypatch.setattr(worker, "run_agent_worker_events", fake_worker)
    runner = worker.build_read_child_runner(
        _app(anthropic_key="secret"), tmp_path, model_id="gpt-5.6-luna", run_id="run"
    )
    events = [event async for event in runner("child", "review", "Review", "Inspect", {"profile": "anthropic"})]
    assert events == [
        {"type": "error", "error": "Build child completed without a verified model receipt", "retryable": False}
    ]


@pytest.mark.asyncio
async def test_provider_exception_does_not_expose_credential(tmp_path, monkeypatch):
    async def fake_worker(_app, **_kwargs):
        yield {
            "type": "error",
            "error": "authorization PRIVATE at https://example.com/?key=PRIVATE",
            "retryable": True,
            "provider_status": 429,
            "provider_credential": "openai_codex",
            "quota": {"kind": "transient", "retry_at": 123.0, "reason": "PRIVATE"},
        }

    monkeypatch.setattr(worker, "run_agent_worker_events", fake_worker)
    runner = worker.build_read_child_runner(
        _app(anthropic_key="secret"), tmp_path, model_id="gpt-5.6-luna", run_id="run"
    )
    events = [event async for event in runner("child", "review", "Review", "Inspect", {"profile": "anthropic"})]
    assert events == [
        {
            "type": "error",
            "error": "Build child provider HTTP 429",
            "retryable": True,
            "provider_status": 429,
            "provider_credential": "openai_codex",
            "quota": {"kind": "transient", "retry_at": 123.0},
        }
    ]
    assert "PRIVATE" not in str(events)
