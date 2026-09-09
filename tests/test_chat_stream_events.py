from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from thomas.core.events import AgentEvent
from thomas.server.routes.chat_stream_events import stream_agent_events


@pytest.mark.asyncio
async def test_legacy_chat_stream_serializes_only_secret_safe_model_runtime() -> None:
    sent: list[dict] = []

    class _Agent:
        def run(self, _prompt, **_kwargs):  # noqa: ANN001, ANN202
            async def events():  # noqa: ANN202
                yield AgentEvent.agent_done("Complete.", iterations=1, tool_calls=0)

            return events()

    class _LLM:
        session_usage = {}

        def reset_runtime_trace(self) -> None:
            return None

        def runtime_trace(self) -> dict:
            return {
                "requested": {
                    "profile": "chatgpt",
                    "provider": "openai",
                    "model": "gpt-5.6-sol",
                    "api_key": "sk-never-stream",
                },
                "active": {
                    "profile": "chatgpt",
                    "provider": "openai",
                    "model": "gpt-5.6-sol",
                    "base_url": "https://user:pass@example.test/private?token=never-stream",
                },
                "failover_enabled": False,
                "failover_used": False,
                "attempts": [
                    {
                        "profile": "chatgpt",
                        "provider": "openai",
                        "model": "gpt-5.6-sol",
                        "status": "success",
                        "error": "raw provider exception never streams",
                    }
                ],
                "access_token": "never-stream",
            }

    async def send(event: dict) -> None:
        sent.append(event)

    async def send_timing(_name: str) -> None:
        return None

    async def apply_usage_budget(_tokens: int):  # noqa: ANN202
        return None

    session = SimpleNamespace(autonomy_level=3, session_token_spend=0, last_assistant_message="")
    cfg = SimpleNamespace(journal=SimpleNamespace(enabled=False), failover=SimpleNamespace(enabled=True))
    run_done: dict = {}

    await stream_agent_events(
        agent=_Agent(),
        prompt="hello",
        send=send,
        send_timing=send_timing,
        cfg=cfg,
        session=session,
        sid="secret-safe-stream",
        raw_user_text="hello",
        ledger=None,
        deps=SimpleNamespace(task_ledger_update=lambda *_args, **_kwargs: None),
        run_id="run-secret-safe",
        model_cfg=SimpleNamespace(model="gpt-5.6-sol", provider="openai"),
        requested_runtime={"profile": "chatgpt", "model": "gpt-5.6-sol"},
        failover_enabled_for_chat=False,
        mode="auto",
        advanced_tools=None,
        requested_job_type=None,
        applied_token_economy="balanced",
        token_economy_meta={},
        run_max_iterations=None,
        run_done=run_done,
        no_human_mode=None,
        require_command_approval=False,
        llm=_LLM(),
        memory=None,
        start_t=time.monotonic(),
        apply_usage_budget=apply_usage_budget,
        normalize_usage_payload=lambda value: value if isinstance(value, dict) else {},
    )

    serialized = json.dumps(sent)
    assert "sk-never-stream" not in serialized
    assert "user:pass" not in serialized
    assert "token=never-stream" not in serialized
    assert "raw provider exception" not in serialized
    runtime_event = next(event for event in sent if event.get("type") == "model_runtime")
    done_event = next(event for event in sent if event.get("type") == "done")
    assert runtime_event["runtime"]["active"] == {
        "profile": "chatgpt",
        "provider": "openai",
        "model": "gpt-5.6-sol",
    }
    assert done_event["runtime_model"] == runtime_event["runtime"]
