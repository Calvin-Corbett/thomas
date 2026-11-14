# tests/test_generic_and_claude_model_sources.py
"""Anthropic, OpenAI, Gemini, OpenRouter and local servers answer through one reader;
the Claude CLI's always-newest names stand in when there is no Anthropic key."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from thomas.core.config import ModelConfig
from thomas.models import sources
from thomas.models.sources import claude_cli, generic


def _handshake(ok: bool, models: list[str], error: str = "") -> SimpleNamespace:
    return SimpleNamespace(ok=ok, status="ok" if ok else "auth_error", models=models, error=error)


def _answer(cfg: ModelConfig, handshake: SimpleNamespace, monkeypatch: pytest.MonkeyPatch):
    async def fake(_cfg, *, timeout_s=10.0, max_results=200):  # noqa: ANN001
        return handshake

    monkeypatch.setattr(generic, "handshake_models_async", fake)
    return asyncio.run(sources.list_profile_models(cfg.name, cfg))


def test_openai_keeps_every_chat_model_and_drops_what_names_itself_otherwise(monkeypatch) -> None:
    cfg = ModelConfig(
        name="openai", provider="openai_compat", base_url="https://api.openai.com/v1", api_key="k", model="gpt-5.5"
    )
    ids = [
        "gpt-6-astra",
        "text-embedding-3-small",
        "whisper-1",
        "tts-1",
        "dall-e-3",
        "omni-moderation-latest",
        "gpt-image-1",
        "gpt-4o-transcribe",
        "gpt-4o-mini-tts",
        "o9-preview",
    ]
    answer = _answer(cfg, _handshake(True, ids), monkeypatch)
    assert [m.id for m in answer.models] == ["gpt-6-astra", "o9-preview"]


def test_anthropic_with_a_key_lists_what_anthropic_lists(monkeypatch) -> None:
    cfg = ModelConfig(name="anthropic", provider="anthropic", base_url="https://api.anthropic.com/v1", api_key="k")
    answer = _answer(cfg, _handshake(True, ["claude-nova-5", "claude-sonnet-4-5-20250929"]), monkeypatch)
    assert answer.ok and answer.source == "provider"
    assert [m.id for m in answer.models] == ["claude-nova-5", "claude-sonnet-4-5-20250929"]


def test_a_refusal_is_a_failure_not_an_empty_list(monkeypatch) -> None:
    cfg = ModelConfig(name="gemini", provider="openai_compat", base_url="https://example.invalid/v1", api_key="bad")
    answer = _answer(cfg, _handshake(False, [], "HTTP 401"), monkeypatch)
    assert not answer.ok and "401" in answer.error


def test_without_an_anthropic_key_the_claude_cli_names_stand_in(monkeypatch) -> None:
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _name: "C:/bin/claude.exe")
    cfg = ModelConfig(name="anthropic", provider="anthropic", base_url="https://api.anthropic.com/v1", api_key="")
    answer = asyncio.run(sources.list_profile_models("anthropic", cfg))
    assert answer.ok and answer.source == "claude-cli"
    assert [m.id for m in answer.models] == ["opus", "sonnet", "haiku"]


def test_without_a_key_or_the_cli_nothing_is_claimed() -> None:
    answer = claude_cli.list_claude_cli_models(which=lambda _name: None)
    assert not answer.ok and "Claude CLI" in answer.error


def test_a_keyless_non_local_profile_is_refused_without_asking_the_provider() -> None:
    cfg = ModelConfig(name="openrouter", provider="openai_compat", base_url="https://openrouter.ai/api/v1", api_key="")
    answer = asyncio.run(sources.list_profile_models(cfg.name, cfg))
    assert not answer.ok
    assert answer.error == "no API key for openrouter"
    assert answer.models == ()


def test_a_keyed_profile_still_lists(monkeypatch) -> None:
    cfg = ModelConfig(name="openrouter", provider="openai_compat", base_url="https://openrouter.ai/api/v1", api_key="k")
    answer = _answer(cfg, _handshake(True, ["a-model"]), monkeypatch)
    assert answer.ok and answer.source == "provider"
    assert [m.id for m in answer.models] == ["a-model"]


def test_a_local_profile_without_a_key_still_lists_by_loopback_host(monkeypatch) -> None:
    cfg = ModelConfig(name="local", provider="openai_compat", base_url="http://127.0.0.1:11434/v1", api_key="")
    answer = _answer(cfg, _handshake(True, ["qwen2.5-coder:7b"]), monkeypatch)
    assert answer.ok
    assert [m.id for m in answer.models] == ["qwen2.5-coder:7b"]


def test_a_local_profile_without_a_key_still_lists_by_provider_name(monkeypatch) -> None:
    cfg = ModelConfig(name="local", provider="ollama", base_url="", api_key="")
    answer = _answer(cfg, _handshake(True, ["llama3"]), monkeypatch)
    assert answer.ok
    assert [m.id for m in answer.models] == ["llama3"]


def test_a_refusal_names_the_connection_and_never_leaks_a_raw_json_body(monkeypatch) -> None:
    cfg = ModelConfig(name="openrouter", provider="openai_compat", base_url="https://openrouter.ai/api/v1", api_key="k")
    body = '{"error": {"message": "invalid api key"}}'
    answer = _answer(cfg, _handshake(False, [], body), monkeypatch)
    assert not answer.ok
    assert answer.error.startswith("openrouter:")
    assert "invalid api key" in answer.error
    assert "{" not in answer.error
