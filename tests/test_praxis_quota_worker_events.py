"""Actual worker event seam keeps quota metadata without credential secrets."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.test_agent_worker_parity import _app_with_model, _FakeLLM
from thomas.core.events import EventType
from thomas.core.llm_request_admission import admission_key
from thomas.core.llm_shared import LLMError, quota_error_fields
from thomas.server import app_helpers, worker_runtime
from thomas.tools.registry import ToolRegistry


def test_transport_keeps_only_allowlisted_reset_hints_and_error_code():
    code, headers = quota_error_fields(
        b'{"error":{"code":"insufficient_quota","message":"private provider details"}}',
        {"Retry-After": "901", "Authorization": "Bearer secret", "X-Request-ID": "private-id"},
    )
    error = LLMError("limited", status=429, retryable=True, error_code=code, response_headers=headers)
    assert error.error_code == "insufficient_quota"
    assert error.response_headers == {"retry-after": "901"}
    assert error.quota_hint
    assert "secret" not in str(error.response_headers)
    assert not LLMError("busy", status=429, retryable=True, response_headers={"retry-after": "30"}).quota_hint


@pytest.mark.asyncio
async def test_worker_emits_opaque_credential_and_structured_quota(monkeypatch, tmp_path):
    class QuotaLoop:
        def __init__(self, _cfg, llm, _tools, **_kwargs):
            self.llm = llm

        async def run(self, _prompt, **_kwargs):
            yield SimpleNamespace(
                type=EventType.AGENT_ERROR,
                data={
                    "error": "provider refused request",
                    "status": 429,
                    "retryable": True,
                    "error_code": "insufficient_quota",
                    "response_headers": {"retry-after": "901"},
                },
            )

    monkeypatch.setattr(worker_runtime, "LLMClient", _FakeLLM)
    monkeypatch.setattr(worker_runtime, "AgentLoop", QuotaLoop)
    monkeypatch.setattr(app_helpers, "_build_tools", lambda *_args, **_kwargs: ToolRegistry())
    app = _app_with_model("openai", "fixture", "worker")
    app[worker_runtime.APP_CONFIG].models["worker"].api_key = "this-is-secret"
    events = [
        event
        async for event in worker_runtime.run_agent_worker_events(
            app,
            prompt="check project",
            instructions="Read only",
            work_dir=tmp_path,
            profile="worker",
        )
    ]
    error = events[-1]
    assert error["type"] == "error"
    assert error["provider_status"] == 429
    assert error["provider_credential"] == admission_key(_FakeLLM.instances[-1].config)
    assert error["quota"]["kind"] == "quota"
    assert error["quota"]["reason"] == "provider_quota"
    assert "this-is-secret" not in str(error)
