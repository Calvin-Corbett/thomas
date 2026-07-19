"""Speech upload, synthesis, and capability handlers for Chat V2."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from aiohttp import web

from thomas.server.routes.chat_v2_support import _uploaded_audio_format, _voice_bridge_for_request
from thomas.tools.voice import AudioData, VoiceProviderException, windows_speech_inventory

log = logging.getLogger(__name__)
_MAX_TRANSCRIBE_BYTES = 10 * 1024 * 1024


async def _runtime_voice_bridge(app: web.Application):
    # Resolve through the public compatibility module so existing embedders and
    # tests that override chat_v2._voice_bridge_for_request keep working.
    from thomas.server.routes import chat_v2

    return await chat_v2._voice_bridge_for_request(app)


def _runtime_upload_limit() -> int:
    from thomas.server.routes import chat_v2

    return int(getattr(chat_v2, "_MAX_TRANSCRIBE_BYTES", _MAX_TRANSCRIBE_BYTES))


async def handle_chat_transcribe(request: web.Request) -> web.Response:
    if not str(request.content_type or "").lower().startswith("multipart/"):
        return web.json_response({"error": "Expected multipart/form-data"}, status=400)
    try:
        reader = await request.multipart()
    except (AssertionError, OSError, RuntimeError, ValueError):
        return web.json_response({"error": "Unable to read upload"}, status=400)
    audio_bytes = b""
    audio_name = "audio.webm"
    audio_content_type = "audio/webm"
    language = ""
    while True:
        field = await reader.next()
        if field is None:
            break
        field_name = str(getattr(field, "name", "") or "")
        if field_name == "language":
            with contextlib.suppress(Exception):
                language = str(await field.text()).strip()[:32]
            continue
        if field_name != "audio":
            with contextlib.suppress(Exception):
                await field.release()
            continue
        audio_name = str(getattr(field, "filename", "") or "audio.webm")
        audio_content_type = str(field.headers.get("Content-Type", "audio/webm") or "audio/webm")
        parts = []
        total = 0
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            total += len(chunk)
            if total > _runtime_upload_limit():
                return web.json_response({"error": "Audio upload too large"}, status=413)
            parts.append(chunk)
        audio_bytes = b"".join(parts)
    if not audio_bytes:
        return web.json_response({"error": "Missing audio upload"}, status=400)
    bridge = await _runtime_voice_bridge(request.app)
    audio = AudioData(
        data=audio_bytes,
        format=_uploaded_audio_format(audio_name, audio_content_type),
        sample_rate=16000,
        duration_ms=0,
        language=language,
    )
    try:
        text = await bridge.transcribe(audio)
    except VoiceProviderException as exc:
        return web.json_response({"error": str(exc)}, status=503)
    except (OSError, RuntimeError, ValueError) as exc:
        log.warning("Chat transcription failed: %s", exc, exc_info=True)
        return web.json_response({"error": f"Transcription failed: {exc}"}, status=500)
    provider = getattr(getattr(bridge, "_current_stt", None), "get_provider_name", lambda: "")()
    return web.json_response(
        {"ok": True, "text": str(text or ""), "provider": str(provider or ""), "language": language or "auto"}
    )


async def handle_chat_speak(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"error": "Payload must be a JSON object"}, status=400)
    text = str(payload.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "Speech text is empty"}, status=400)
    if len(text) > 4096:
        return web.json_response({"error": "Speech text is too long"}, status=413)
    voice = str(payload.get("voice") or "default").strip() or "default"
    try:
        speed = float(payload.get("speed", 1.0) or 1.0)
    except (TypeError, ValueError):
        return web.json_response({"error": "speed must be a number"}, status=400)
    bridge = await _runtime_voice_bridge(request.app)
    try:
        audio = await bridge.synthesize(text, voice=voice, speed=max(0.5, min(2.0, speed)))
    except VoiceProviderException as exc:
        return web.json_response({"error": str(exc)}, status=503)
    except (OSError, RuntimeError, ValueError) as exc:
        log.warning("Chat speech synthesis failed: %s", exc, exc_info=True)
        return web.json_response({"error": f"Speech synthesis failed: {exc}"}, status=500)
    provider = getattr(getattr(bridge, "_current_tts", None), "get_provider_name", lambda: "")()
    content_type = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg", "flac": "audio/flac"}.get(
        str(audio.format or "").lower(), "application/octet-stream"
    )
    return web.Response(
        body=audio.data,
        content_type=content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Thomas-Voice-Provider": str(provider or ""),
            "X-Thomas-Audio-Format": str(audio.format or ""),
            "X-Thomas-Audio-Duration-Ms": str(max(0, int(audio.duration_ms))),
            "X-Thomas-Audio-Language": str(audio.language or ""),
        },
    )


async def handle_chat_voice_status(request: web.Request) -> web.Response:
    bridge = await _runtime_voice_bridge(request.app)
    stt_rows = []
    for provider in bridge.stt_providers:
        try:
            available = bool(await provider.is_available())
        except (OSError, RuntimeError, ValueError, VoiceProviderException):
            available = False
        stt_rows.append({"provider": provider.get_provider_name(), "available": available})
    tts_rows = []
    for provider in bridge.tts_providers:
        try:
            available = bool(await provider.is_available())
            voices = await provider.list_voices() if available else []
        except (OSError, RuntimeError, ValueError, VoiceProviderException):
            available = False
            voices = []
        tts_rows.append({"provider": provider.get_provider_name(), "available": available, "voices": voices})
    inventory = await asyncio.to_thread(windows_speech_inventory)
    languages = sorted(
        {str(row.get("language") or "") for row in inventory.get("recognizers", []) if row.get("language")}
    )
    return web.json_response(
        {
            "ok": True,
            "speech_to_text": stt_rows,
            "text_to_speech": tts_rows,
            "supported_languages": languages,
            "turn_taking": {"realtime_websocket": "/api/realtime/ws", "interrupt_event": "interrupt", "barge_in": True},
        }
    )


__all__ = ["handle_chat_speak", "handle_chat_transcribe", "handle_chat_voice_status"]
