"""Fakes and the shared app fixture for the max-mode chat route tests.

Split out of tests/test_server_chat_v2_max_mode.py when it passed 800 lines,
and shared by it, tests/test_server_chat_v2_max_mode_dispatch.py and
tests/test_server_chat_v2_max_mode_controls.py. The route builds its brain in
thomas.server.routes.chat_v2_support, so that is where the tests patch
OrchestratorBrain.
"""

import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.tools.voice import AudioData, VoiceProviderException


def _parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class _FakeBrain:
    calls = []
    init_calls = []

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _FakeBrain.init_calls.append(dict(kwargs or {}))

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        payload = dict(kwargs or {})
        payload["prompt"] = prompt
        _FakeBrain.calls.append(payload)
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


class _FakeLLMClient:
    calls = []
    closed = []

    def __init__(
        self,
        config,
        fallback_configs=None,
        failover_enabled=False,
        failover_cooldown_s=300,
        failover_on_auth_error=False,
        max_retries=3,
        base_retry_delay_s=0.8,
        request_overrides=None,
    ):  # noqa: ANN001
        self.config = config
        self._primary_config = config
        self._fallback_configs = list(fallback_configs or [])
        self._failover_enabled = bool(failover_enabled)
        self._failover_cooldown_s = int(failover_cooldown_s)
        self._failover_on_auth_error = bool(failover_on_auth_error)
        self._max_retries = int(max_retries)
        self._base_retry_delay = float(base_retry_delay_s)
        self._request_overrides = dict(request_overrides or {})
        self._codex_provider = None
        _FakeLLMClient.calls.append(
            {
                "reasoning_effort": getattr(config, "reasoning_effort", ""),
                "model": getattr(config, "model", ""),
                "failover_enabled": bool(failover_enabled),
                "fallback_count": len(list(fallback_configs or [])),
            }
        )

    async def close(self):
        _FakeLLMClient.closed.append(
            {
                "reasoning_effort": getattr(self.config, "reasoning_effort", ""),
                "model": getattr(self.config, "model", ""),
            }
        )

    def runtime_trace(self):  # noqa: ANN201
        runtime = {
            "profile": getattr(self.config, "name", ""),
            "provider": getattr(self.config, "provider", ""),
            "model": getattr(self.config, "model", ""),
            "base_url": getattr(self.config, "base_url", ""),
        }
        return {
            "requested": dict(runtime),
            "active": dict(runtime),
            "failover_enabled": self._failover_enabled,
            "failover_used": False,
            "attempts": [{**runtime, "status": "success"}],
        }


class _FakeDelegationStarter:
    calls = []

    @staticmethod
    async def start(
        app,
        *,
        session_id,
        prompt,
        mode,
        recent_messages,
        emit_event,
        repo_root=None,
        force=False,
        autonomy_level=4,
        profile=None,
        model_id=None,
        reasoning_effort=None,
        effort="diligent",
        file_access=None,
        guardrails="",
        guardrail_modes=None,
        session_llm=None,
        work_context_id="",
        memory_enabled=True,
        runtime_policy=None,
    ):  # noqa: ANN001
        _ = app
        _ = repo_root
        _ = guardrail_modes
        _ = session_llm
        _FakeDelegationStarter.calls.append(
            {
                "session_id": session_id,
                "prompt": prompt,
                "mode": mode,
                "recent_messages": list(recent_messages or []),
                "profile": profile,
                "model_id": model_id,
                "reasoning_effort": reasoning_effort,
                "effort": effort,
                "file_access": file_access,
                "guardrails": guardrails,
                "force": force,
                "autonomy_level": autonomy_level,
                "work_context_id": work_context_id,
                "memory_enabled": memory_enabled,
                "runtime_policy": dict(runtime_policy or {}),
            }
        )
        await emit_event(
            {
                "type": "delegation_started",
                "execution_id": "exec-123",
                "task_id": "task-123",
                "session_id": session_id,
                "backend_type": "task_manager",
                "state": "queued",
                "summary": prompt,
                "last_progress": "Queued for background execution.",
                "specialist_id": "coding",
                "bot_id": "nova",
                "bot_name": "Nova",
                "bot_color": "#4fc3f7",
                "bot_costume": "cap",
                "bot_tint": "blue",
            }
        )
        return {"execution_id": "exec-123"}


class _FakeVoiceBridge:
    calls = []

    def __init__(self) -> None:
        self._current_stt = SimpleNamespace(get_provider_name=lambda: "fake_stt")
        self._current_tts = SimpleNamespace(get_provider_name=lambda: "fake_tts")

    async def transcribe(self, audio):  # noqa: ANN001
        _FakeVoiceBridge.calls.append(
            {
                "format": getattr(audio, "format", ""),
                "bytes": len(getattr(audio, "data", b"")),
                "language": getattr(audio, "language", ""),
            }
        )
        return "hello from mic"

    async def synthesize(self, text, voice="default", speed=1.0):  # noqa: ANN001, ANN201
        _FakeVoiceBridge.calls.append({"text": text, "voice": voice, "speed": speed})
        return AudioData(data=b"RIFFfakeWAVE", format="wav", sample_rate=16000, duration_ms=250, language="en-US")


class _VoiceProviderBoom:
    async def transcribe(self, audio):  # noqa: ANN001
        _ = audio
        raise VoiceProviderException("voice offline")


class _VoiceGenericBoom:
    async def transcribe(self, audio):  # noqa: ANN001
        _ = audio
        raise RuntimeError("decoder crashed")


class _FakeBrainBoom:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        _ = session_id, conversation, prompt, dispatcher, kwargs
        raise RuntimeError("brain exploded")


class ChatV2MaxModeCase(AioHTTPTestCase):
    """A chat app on a throwaway memory root and preferences database."""

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._environment = patch.dict(
            "os.environ",
            {"THOMAS_DB_PATH": f"{self._tmpdir.name}/preferences.db"},
        )
        self._environment.start()

    def tearDown(self) -> None:
        try:
            self._environment.stop()
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={
                "local": ModelConfig(
                    name="local",
                    provider="openai_compat",
                    base_url="http://127.0.0.1:11434/v1",
                    model="dummy",
                )
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)
