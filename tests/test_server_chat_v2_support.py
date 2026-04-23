import json

from thomas.tools.voice import VoiceProviderException


def parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class FakeBrain:
    calls = []

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        payload = dict(kwargs or {})
        payload["prompt"] = prompt
        FakeBrain.calls.append(payload)
        updated = conversation.append_message("user", prompt)
        reply = "Thomas reply."
        await dispatcher.emit_text(reply)
        updated = updated.append_message(
            "assistant", reply, metadata={"specialists": ["reasoning"], "mode": "conversation"}
        )
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=updated.version,
            thinking_summary="conversation",
            total_thinking_ms=0,
            iterations=1,
            tool_calls=0,
            tokens_used=0,
            specialists_used=["reasoning"],
        )
        return updated


class FakeLLMClient:
    calls = []
    closed = []

    def __init__(self, config, fallback_configs=None, failover_enabled=False):  # noqa: ANN001
        self.config = config
        self._primary_config = config
        self._fallback_configs = list(fallback_configs or [])
        self._failover_enabled = bool(failover_enabled)
        self._codex_provider = None
        FakeLLMClient.calls.append(
            {
                "reasoning_effort": getattr(config, "reasoning_effort", ""),
                "model": getattr(config, "model", ""),
                "failover_enabled": bool(failover_enabled),
                "fallback_count": len(list(fallback_configs or [])),
            }
        )

    async def close(self):
        FakeLLMClient.closed.append(
            {
                "reasoning_effort": getattr(self.config, "reasoning_effort", ""),
                "model": getattr(self.config, "model", ""),
            }
        )


class FakeDispatchResult:
    def __init__(self, *, ok=True, execution_id="exec-123", task_id="task-123", error="") -> None:
        self.ok = ok
        self.execution_id = execution_id
        self.task_id = task_id
        self.error = error


class FakeDispatch:
    calls = []

    @staticmethod
    async def run(prompt, session_id, emit_event=None):  # noqa: ANN001
        _ = emit_event
        FakeDispatch.calls.append(
            {
                "session_id": session_id,
                "prompt": prompt,
            }
        )
        return FakeDispatchResult()


async def fake_stream_ack(llm, *, user_text, emit_text):  # noqa: ANN001
    _ = llm, user_text
    text = "Yeah, I'm getting started now."
    await emit_text(text)
    return text


class FakeVoiceBridge:
    calls = []

    async def transcribe(self, audio):  # noqa: ANN001
        FakeVoiceBridge.calls.append(
            {
                "format": getattr(audio, "format", ""),
                "bytes": len(getattr(audio, "data", b"")),
            }
        )
        return "hello from mic"


class VoiceProviderBoom:
    async def transcribe(self, audio):  # noqa: ANN001
        _ = audio
        raise VoiceProviderException("voice offline")


class VoiceGenericBoom:
    async def transcribe(self, audio):  # noqa: ANN001
        _ = audio
        raise RuntimeError("decoder crashed")


class FakeBrainBoom:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        _ = session_id, conversation, prompt, dispatcher, kwargs
        raise RuntimeError("brain exploded")
