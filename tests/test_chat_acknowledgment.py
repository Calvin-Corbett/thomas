from __future__ import annotations

from types import SimpleNamespace

import pytest

from thomas.server.chat_acknowledgment import stream_task_start_acknowledgment


class _FakeLLM:
    async def stream_chat(self, messages, tools=None):  # noqa: ANN001
        _ = messages, tools
        yield SimpleNamespace(type="token", data={"text": "Yeah, "})
        yield SimpleNamespace(type="token", data={"text": "I'm on it."})
        yield SimpleNamespace(type="done", data={})


class _BrokenLLM:
    async def stream_chat(self, messages, tools=None):  # noqa: ANN001
        _ = messages, tools
        raise RuntimeError("boom")
        yield  # pragma: no cover


class _SlowLLM:
    async def stream_chat(self, messages, tools=None):  # noqa: ANN001
        _ = messages, tools
        await __import__("asyncio").sleep(2.0)
        yield SimpleNamespace(type="token", data={"text": "Too late"})


@pytest.mark.asyncio
async def test_stream_task_start_acknowledgment_streams_model_text():
    parts: list[str] = []

    async def _emit(text: str) -> None:
        parts.append(text)

    text = await stream_task_start_acknowledgment(
        _FakeLLM(),
        user_text="Please make a note.",
        emit_text=_emit,
    )

    assert text == "Yeah, I'm on it."
    assert parts == ["Yeah, ", "I'm on it."]


@pytest.mark.asyncio
async def test_stream_task_start_acknowledgment_falls_back_when_stream_fails():
    parts: list[str] = []

    async def _emit(text: str) -> None:
        parts.append(text)

    text = await stream_task_start_acknowledgment(
        _BrokenLLM(),
        user_text="Please make a note.",
        emit_text=_emit,
    )

    assert text == "I'm on it now. I'll keep it moving in the background."
    assert parts == ["I'm on it now. I'll keep it moving in the background."]


@pytest.mark.asyncio
async def test_stream_task_start_acknowledgment_times_out_to_fast_fallback():
    parts: list[str] = []

    async def _emit(text: str) -> None:
        parts.append(text)

    text = await stream_task_start_acknowledgment(
        _SlowLLM(),
        user_text="Please make a note.",
        emit_text=_emit,
    )

    assert text == "I'm on it now. I'll keep it moving in the background."
    assert parts == ["I'm on it now. I'll keep it moving in the background."]
