"""Offline Windows speech providers with bounded, cancellable subprocesses."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import wave
from typing import Any

from thomas.tools.voice_models import AudioData, STTProvider, TTSProvider, VoiceProviderException

_WINDOWS_SPEECH_INVENTORY: dict[str, Any] | None = None


def _powershell_executable() -> str:
    return shutil.which("powershell.exe") or shutil.which("powershell") or ""


def _run_windows_speech_script(script: str, *, timeout: float = 30.0) -> str:
    executable = _powershell_executable()
    if os.name != "nt" or not executable:
        raise VoiceProviderException("Windows speech services are unavailable")
    completed = subprocess.run(
        [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Windows speech command failed").strip()
        raise VoiceProviderException(detail[:500])
    return str(completed.stdout or "").strip()


def windows_speech_inventory(*, refresh: bool = False) -> dict[str, Any]:
    """Return installed offline recognizers and voices without exposing system paths."""
    global _WINDOWS_SPEECH_INVENTORY
    if _WINDOWS_SPEECH_INVENTORY is not None and not refresh:
        return json.loads(json.dumps(_WINDOWS_SPEECH_INVENTORY))
    if os.name != "nt" or not _powershell_executable():
        _WINDOWS_SPEECH_INVENTORY = {"available": False, "recognizers": [], "voices": []}
        return dict(_WINDOWS_SPEECH_INVENTORY)
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$recognizers = @([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | ForEach-Object {
  [pscustomobject]@{ language = $_.Culture.Name; name = $_.Description }
})
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
  [pscustomobject]@{ language = $_.VoiceInfo.Culture.Name; name = $_.VoiceInfo.Name }
})
$synth.Dispose()
[pscustomobject]@{ available = (($recognizers.Count -gt 0) -and ($voices.Count -gt 0)); recognizers = $recognizers; voices = $voices } | ConvertTo-Json -Depth 5 -Compress
"""
    try:
        payload = json.loads(_run_windows_speech_script(script, timeout=15.0))
        _WINDOWS_SPEECH_INVENTORY = payload if isinstance(payload, dict) else {}
    except (VoiceProviderException, json.JSONDecodeError, OSError, subprocess.TimeoutExpired):
        _WINDOWS_SPEECH_INVENTORY = {"available": False, "recognizers": [], "voices": []}
    return json.loads(json.dumps(_WINDOWS_SPEECH_INVENTORY))


async def _run_speech(script: str, *, timeout: float = 30.0) -> str:
    executable = _powershell_executable()
    if os.name != "nt" or not executable:
        raise VoiceProviderException("Windows speech services are unavailable")
    process = await asyncio.create_subprocess_exec(
        executable,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except (asyncio.CancelledError, TimeoutError):
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        raise
    if process.returncode:
        # Provider process details stay local; callers receive a usable bounded error.
        raise VoiceProviderException("Windows speech could not process this audio or text")
    return stdout.decode("utf-8-sig", errors="replace").strip()


class WindowsSpeechSTTProvider(STTProvider):
    """Offline Windows dictation provider backed by the installed System.Speech recognizer."""

    async def transcribe(self, audio: AudioData) -> str:
        if str(audio.format or "").strip().lower() != "wav":
            raise VoiceProviderException("Windows offline transcription requires PCM WAV audio")
        language = str(audio.language or "en-US").strip() or "en-US"
        inventory = await asyncio.to_thread(windows_speech_inventory)
        supported = {str(row.get("language") or "") for row in inventory.get("recognizers", [])}
        if language not in supported:
            raise VoiceProviderException(f"Windows speech recognizer is not installed for {language}")
        with tempfile.TemporaryDirectory(prefix="thomas-voice-stt-") as temp_dir:
            audio_path = os.path.join(temp_dir, "input.wav")
            await asyncio.to_thread(_write_bytes, audio_path, audio.data)
            path_b64 = base64.b64encode(audio_path.encode("utf-8")).decode("ascii")
            lang_b64 = base64.b64encode(language.encode("utf-8")).decode("ascii")
            script = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$path = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{path_b64}'))
$language = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{lang_b64}'))
$info = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | Where-Object {{ $_.Culture.Name -eq $language }} | Select-Object -First 1
if ($null -eq $info) {{ throw "recognizer unavailable for $language" }}
$recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine($info)
try {{
  $recognizer.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
  $recognizer.SetInputToWaveFile($path)
  $parts = [System.Collections.Generic.List[string]]::new()
  do {{
    $result = $recognizer.Recognize()
    if ($null -ne $result) {{ $parts.Add($result.Text) }}
  }} while ($null -ne $recognizer.AudioFormat)
  if ($parts.Count -eq 0) {{ throw 'speech was not recognized' }}
  [Console]::Write(($parts -join ' '))
}} finally {{
  $recognizer.Dispose()
}}
"""
            text = await _run_speech(script, timeout=30.0)
        if not text:
            raise VoiceProviderException("speech was not recognized")
        return text

    async def is_available(self) -> bool:
        inventory = await asyncio.to_thread(windows_speech_inventory)
        return bool(inventory.get("recognizers"))

    def get_provider_name(self) -> str:
        return "windows_system_speech"


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(data)


class WindowsSpeechTTSProvider(TTSProvider):
    """Offline Windows text-to-speech provider producing standard PCM WAV bytes."""

    def __init__(self) -> None:
        self.speech_rate = 1.0

    async def synthesize(self, text: str, voice: str = "default") -> AudioData:
        clean_text = str(text or "").strip()
        if not clean_text:
            raise VoiceProviderException("Speech text is empty")
        inventory = await asyncio.to_thread(windows_speech_inventory)
        voices = [str(row.get("name") or "") for row in inventory.get("voices", [])]
        selected = str(voice or "").strip()
        if selected in {"", "default"}:
            selected = voices[0] if voices else ""
        if selected not in voices:
            raise VoiceProviderException(f"Windows voice is not installed: {selected}")
        with tempfile.TemporaryDirectory(prefix="thomas-voice-tts-") as temp_dir:
            output_path = os.path.join(temp_dir, "speech.wav")
            path_b64 = base64.b64encode(output_path.encode("utf-8")).decode("ascii")
            text_b64 = base64.b64encode(clean_text.encode("utf-8")).decode("ascii")
            voice_b64 = base64.b64encode(selected.encode("utf-8")).decode("ascii")
            rate = max(-10, min(10, round((float(self.speech_rate) - 1.0) * 5)))
            script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$path = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{path_b64}'))
$text = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{text_b64}'))
$voice = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{voice_b64}'))
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{
  $synth.SelectVoice($voice)
  $synth.Rate = {rate}
  $synth.SetOutputToWaveFile($path)
  $synth.Speak($text)
}} finally {{
  $synth.Dispose()
}}
"""
            await _run_speech(script, timeout=30.0)
            data = await asyncio.to_thread(_read_bytes, output_path)
        if not data.startswith(b"RIFF") or b"WAVE" not in data[:16]:
            raise VoiceProviderException("Windows speech synthesis did not produce a valid WAV file")
        with wave.open(io.BytesIO(data), "rb") as recording:
            sample_rate = recording.getframerate()
            duration_ms = round(recording.getnframes() * 1000 / sample_rate)
        return AudioData(
            data=data,
            format="wav",
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            language=_voice_language(inventory, selected),
        )

    async def list_voices(self) -> list[str]:
        inventory = await asyncio.to_thread(windows_speech_inventory)
        return [str(row.get("name") or "") for row in inventory.get("voices", []) if row.get("name")]

    async def is_available(self) -> bool:
        inventory = await asyncio.to_thread(windows_speech_inventory)
        return bool(inventory.get("voices"))

    def get_provider_name(self) -> str:
        return "windows_system_speech"


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _voice_language(inventory: dict[str, Any], voice: str) -> str:
    for row in inventory.get("voices", []):
        if str(row.get("name") or "") == voice:
            return str(row.get("language") or "")
    return ""
