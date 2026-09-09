"""Regression tests for the local-model readiness probe.

A healthy model that answers the tool-readiness prompt "honestly"
(tool_ready=false instead of echoing true) must still pass the probe:
readiness is "responded and followed the JSON contract", while the
self-reported tool_ready value is only a recorded capability signal.
llama3.1:8b answered exactly this way at temperature 0 and was failed —
and auto-repaired — in a loop that could never succeed.
"""

from __future__ import annotations

import pytest

from thomas.server.routes import setup_local_sync as sync


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response_text: str):
        self._response_text = response_text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        return _FakeResponse({"response": self._response_text})


@pytest.fixture
def fake_ollama(monkeypatch):
    def _install(response_text: str):
        monkeypatch.setattr(sync.httpx, "AsyncClient", lambda timeout=None: _FakeClient(response_text))

    return _install


class TestExtractToolReadinessFlag:
    def test_echoed_true(self):
        assert sync._extract_tool_readiness_flag('{"tool_ready": true}') == (True, True)

    def test_honest_false_is_json_like(self):
        json_like, tool_ready = sync._extract_tool_readiness_flag(
            '{"tool_ready": false, "probe": "error", "model": "unknown"}'
        )
        assert json_like is True
        assert tool_ready is False

    def test_prose_is_not_json_like(self):
        assert sync._extract_tool_readiness_flag("Sure! I can help with that.") == (False, False)


class TestProbeVerdict:
    @pytest.mark.asyncio
    async def test_honest_tool_ready_false_still_passes(self, fake_ollama):
        fake_ollama('{"tool_ready": false, "probe": "error", "model": "unknown"}')
        out = await sync.probe_ollama_model("http://localhost:11434", "llama3.1:8b", require_tool_signal=True)
        assert out["ok"] is True
        assert out["json_like"] is True
        assert out["tool_signal"] is False  # recorded, not gating

    @pytest.mark.asyncio
    async def test_echoed_json_passes(self, fake_ollama):
        fake_ollama('{"tool_ready": true, "probe": "ok", "model": "m"}')
        out = await sync.probe_ollama_model("http://localhost:11434", "m", require_tool_signal=True)
        assert out["ok"] is True
        assert out["tool_signal"] is True

    @pytest.mark.asyncio
    async def test_prose_response_fails_contract(self, fake_ollama):
        fake_ollama("Hello! How can I help you today?")
        out = await sync.probe_ollama_model("http://localhost:11434", "m", require_tool_signal=True)
        assert out["ok"] is False
        assert out["error"] == "json_contract_not_followed"

    @pytest.mark.asyncio
    async def test_empty_response_fails(self, fake_ollama):
        fake_ollama("")
        out = await sync.probe_ollama_model("http://localhost:11434", "m", require_tool_signal=True)
        assert out["ok"] is False
        assert out["error"] == "empty generation response"
