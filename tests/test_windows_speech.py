"""Actual Windows audio plus deterministic cancellation coverage; no cloud or LLM calls."""

import asyncio
import io
import os
import wave

import pytest

from thomas.tools import voice_windows
from thomas.tools.voice import WindowsSpeechSTTProvider, WindowsSpeechTTSProvider


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows offline provider")
async def test_windows_speech_preserves_two_sentence_utterance():
    if not await WindowsSpeechSTTProvider().is_available():
        pytest.skip("No installed Windows recognizer")
    audio = await WindowsSpeechTTSProvider().synthesize("Thomas voice conversation. Remember the word cedar.")
    with wave.open(io.BytesIO(audio.data), "rb") as reader:
        assert reader.getnchannels() == 1 and reader.getsampwidth() == 2
        assert reader.getnframes() > reader.getframerate()
    text = await WindowsSpeechSTTProvider().transcribe(audio)
    assert {"thomas", "voice", "conversation", "remember", "cedar"}.issubset(set(text.lower().split()))


@pytest.mark.asyncio
async def test_cancelling_windows_speech_kills_and_reaps_process(monkeypatch):
    started = asyncio.Event()

    class Process:
        returncode = None
        killed = False
        reaped = False

        async def communicate(self):
            started.set()
            await asyncio.Event().wait()

        def kill(self):
            self.killed = True
            self.returncode = -1

        async def wait(self):
            self.reaped = True

    process = Process()

    async def spawn(*args, **kwargs):
        assert kwargs.get("creationflags", 0) == getattr(voice_windows.subprocess, "CREATE_NO_WINDOW", 0)
        return process

    monkeypatch.setattr(voice_windows.os, "name", "nt")
    monkeypatch.setattr(voice_windows, "_powershell_executable", lambda: "powershell.exe")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(voice_windows._run_speech("fixture script"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed and process.reaped
