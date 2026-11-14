"""Talking to Voice Studio, the speech program that runs on this computer.

Voice Studio (github.com/debpalash/VoiceStudio) starts a small web server on this computer, port 3900 unless it was
moved, with no sign-in. It copies OpenAI's audio calls: ``POST /v1/audio/speech`` turns text into sound,
``POST /v1/audio/transcriptions`` turns a recording into text, ``GET /v1/audio/voices`` lists its voices and
``GET /health`` says it is up. ``WS /v1/audio/transcriptions/stream`` hears a live microphone: 16-bit sound goes in, and
the words come back while you speak, with a ``final`` each time you pause. Nothing here starts it. If it is not running, every call here fails fast with
``VoiceStudioError`` and the caller falls back to what the browser can do alone.

Only an address on this computer is ever used, so a saved setting cannot make Thomas call another machine.
"""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlencode, urlsplit

import aiohttp

DEFAULT_URL = "http://127.0.0.1:3900"
MAX_TEXT = 4096  # Voice Studio refuses more than this in one call
MAX_AUDIO_BYTES = 20 * 1024 * 1024
_HOSTS = {"127.0.0.1", "localhost", "::1"}
_NETWORK_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError, OSError)


class VoiceStudioError(RuntimeError):
    """Voice Studio could not be reached or would not do what was asked. The text is safe to show."""


def local_url(value: object) -> str | None:
    """The address if it is plain http on this computer, otherwise None."""
    text = str(value or "").strip().rstrip("/")
    try:
        parts = urlsplit(text)
        parts.port  # noqa: B018  (reading it is what raises on a bad port)
    except ValueError:
        return None
    if parts.scheme != "http" or parts.hostname not in _HOSTS or parts.username or parts.password:
        return None
    if parts.path or parts.query or parts.fragment:
        return None
    return text


def _base(url: str) -> str:
    base = local_url(url)
    if base is None:
        raise VoiceStudioError("Voice Studio's address must be on this computer")
    return base


def _timeout(seconds: float) -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(total=seconds)


async def is_running(url: str, *, timeout: float = 1.5) -> bool:
    """True when Voice Studio answers its health check."""
    try:
        async with aiohttp.ClientSession(timeout=_timeout(timeout)) as http:
            async with http.get(_base(url) + "/health") as reply:
                return reply.status == 200
    except (*_NETWORK_ERRORS, VoiceStudioError):
        return False


_voices_seen: dict[str, tuple[float, list[dict[str, str]]]] = {}
_VOICES_KEEP = 300.0  # Voice Studio takes about 2 s to list its voices; the list barely changes, so keep it a while


def voice_name(url: str, voice_id: str) -> str:
    """The name of a voice from the list last seen, or '' when it has not been seen. Never asks Voice Studio."""
    kept = _voices_seen.get(url)
    return next((row["name"] for row in (kept[1] if kept else []) if row["id"] == voice_id), "")


async def voices(url: str, *, timeout: float = 5.0, fresh: bool = False) -> list[dict[str, str]]:
    """Each voice as ``{"id", "name"}``, the ones Voice Studio lists for use as ``voice``. Kept for five minutes."""
    kept = _voices_seen.get(url)
    if kept and not fresh and time.monotonic() - kept[0] < _VOICES_KEEP:
        return list(kept[1])
    found = await _list_voices(url, timeout=timeout)
    _voices_seen[url] = (time.monotonic(), found)
    return list(found)


async def _list_voices(url: str, *, timeout: float) -> list[dict[str, str]]:
    try:
        async with aiohttp.ClientSession(timeout=_timeout(timeout)) as http:
            async with http.get(_base(url) + "/v1/audio/voices") as reply:
                if reply.status != 200:
                    raise VoiceStudioError(f"Voice Studio could not list its voices ({reply.status})")
                body = await reply.json(content_type=None)
    except _NETWORK_ERRORS as exc:
        raise VoiceStudioError("Voice Studio is not running") from exc
    rows = body.get("voices") if isinstance(body, dict) else None
    found: list[dict[str, str]] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and str(row.get("id") or row.get("voice_id") or "").strip():
            voice_id = str(row.get("id") or row.get("voice_id")).strip()
            found.append({"id": voice_id, "name": str(row.get("name") or voice_id)})
    return found


async def speak(url: str, text: str, voice: str, *, speed: float = 1.0, timeout: float = 90.0) -> tuple[bytes, str]:
    """The spoken text as ``(sound, content type)``. WAV, because it needs nothing installed to make."""
    body = {"input": text[:MAX_TEXT], "voice": voice or "default", "response_format": "wav", "speed": speed}
    try:
        async with aiohttp.ClientSession(timeout=_timeout(timeout)) as http:
            async with http.post(_base(url) + "/v1/audio/speech", json=body) as reply:
                if reply.status != 200:
                    raise VoiceStudioError(await _reason(reply, "speak"))
                sound = await reply.content.read(MAX_AUDIO_BYTES + 1)
                kind = reply.headers.get("Content-Type", "audio/wav").split(";")[0].strip() or "audio/wav"
    except _NETWORK_ERRORS as exc:
        raise VoiceStudioError("Voice Studio is not running") from exc
    if not sound or len(sound) > MAX_AUDIO_BYTES:
        raise VoiceStudioError("Voice Studio sent back no usable sound")
    return sound, kind


async def transcribe(
    url: str,
    audio: bytes,
    *,
    filename: str = "speech.webm",
    content_type: str = "audio/webm",
    language: str = "",
    timeout: float = 90.0,
) -> str:
    """The words in a recording."""
    form = aiohttp.FormData()
    form.add_field("file", audio, filename=filename or "speech.webm", content_type=content_type or "audio/webm")
    form.add_field("response_format", "json")
    if language:
        form.add_field("language", language)
    try:
        async with aiohttp.ClientSession(timeout=_timeout(timeout)) as http:
            async with http.post(_base(url) + "/v1/audio/transcriptions", data=form) as reply:
                if reply.status != 200:
                    raise VoiceStudioError(await _reason(reply, "listen"))
                body = await reply.json(content_type=None)
    except _NETWORK_ERRORS as exc:
        raise VoiceStudioError("Voice Studio is not running") from exc
    return str(body.get("text") or "").strip() if isinstance(body, dict) else ""


async def _reason(reply: aiohttp.ClientResponse, doing: str) -> str:
    """Voice Studio's own words for a refusal, from its error body, trimmed."""
    try:
        body = await reply.json(content_type=None)
    except (ValueError, aiohttp.ClientError):
        body = None
    detail = body.get("error") if isinstance(body, dict) else None
    message = detail.get("message") if isinstance(detail, dict) else detail
    text = str(message or "").strip()[:200]
    return f"Voice Studio could not {doing} ({reply.status}){': ' + text if text else ''}"


# Live listening needs a model small enough to keep up on the processor while the graphics card is busy. These are Voice
# Studio's own, fastest first. Each has a licence that is accepted once, in Voice Studio's model list, before it will run.
LIVE_MODELS = ("sherpa-parakeet-tdt-v3", "sherpa-parakeet-tdt-v2", "sherpa-zipformer-en-20m", "sherpa-whisper-tiny")
LIVE_RATE = 16000
_live_seen: dict[str, tuple[float, str | None, str]] = {}
_LIVE_KEEP = 30.0  # seconds a found answer is kept, so opening the page does not ask Voice Studio every time


def live_address(url: str, model: str) -> str:
    """The websocket address of Voice Studio's live listening, for one model, taking 16 kHz 16-bit sound."""
    query = urlencode({"model": model, "sr": LIVE_RATE, "pcm": 1})
    return "ws" + _base(url)[4:] + "/v1/audio/transcriptions/stream?" + query


async def _try_live(http: aiohttp.ClientSession, url: str, model: str) -> str:
    """'' when the model can listen now, otherwise Voice Studio's reason it cannot."""
    async with http.ws_connect(live_address(url, model), timeout=aiohttp.ClientWSTimeout(ws_close=1.0)) as ws:
        deadline = time.monotonic() + 3.0
        while (left := deadline - time.monotonic()) > 0:
            message = await ws.receive(timeout=left)
            if message.type != aiohttp.WSMsgType.TEXT:
                return "Voice Studio closed the line before it was ready"
            event = json.loads(message.data)
            if event.get("type") == "error":
                return str(event.get("message") or event.get("detail") or "Voice Studio could not listen")[:300]
            if event.get("type") == "status" and event.get("stage") == "ready":
                return ""
        return ""  # started and raised nothing: it is listening


async def live_model(url: str, *, fresh: bool = False) -> tuple[str | None, str]:
    """``(model, '')`` for the first live model Voice Studio will run now, or ``(None, why not)``."""
    kept = _live_seen.get(url)
    if kept and not fresh and time.monotonic() - kept[0] < _LIVE_KEEP:
        return kept[1], kept[2]
    reasons: list[str] = []
    try:
        async with aiohttp.ClientSession(timeout=_timeout(6.0)) as http:
            for model in LIVE_MODELS:
                try:
                    why = await _try_live(http, url, model)
                except (asyncio.TimeoutError, ValueError):
                    why = "Voice Studio did not answer in time"
                if not why:
                    _live_seen[url] = (time.monotonic(), model, "")
                    return model, ""
                reasons.append(why)
    except (*_NETWORK_ERRORS, VoiceStudioError):
        reasons = ["Voice Studio is not running"]
    why = reasons[0] if reasons else "Voice Studio has no live listening model"
    _live_seen[url] = (time.monotonic(), None, why)
    return None, why
