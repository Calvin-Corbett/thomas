"""Voice roundtrip, resilience, and interruption parity probes."""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.error
import urllib.request
import wave
from array import array
from typing import Any

from chatgpt_parity_conversation_probe import _event_text, _privacy_chat, _privacy_http_json
from chatgpt_parity_runtime_action_probes import _realtime_interrupt_receipt


def _voice_speak(
    ctx: Any, text: str, *, voice: str = "default", speed: float = 1.0
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        ctx.base_url.rstrip("/") + "/api/v2/chat/speak",
        data=json.dumps({"text": text, "voice": voice, "speed": speed}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(ctx.timeout_seconds, 60.0)) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            return int(response.status), headers, response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), {}, exc.read()


def _voice_transcribe(
    ctx: Any,
    audio: bytes,
    *,
    audio_format: str = "wav",
    language: str = "en-US",
) -> tuple[int, Any]:
    boundary = f"----ThomasVoiceParity{time.time_ns()}"
    chunks = [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="audio"; filename="sample.{audio_format}"\r\n'
            f"Content-Type: audio/{'mpeg' if audio_format == 'mp3' else audio_format}\r\n\r\n"
        ).encode(),
        audio,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="language"\r\n\r\n',
        language.encode("utf-8"),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(
        ctx.base_url.rstrip("/") + "/api/v2/chat/transcribe",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(ctx.timeout_seconds, 60.0)) as response:
            return int(response.status), json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return int(exc.code), json.loads(raw)
        except json.JSONDecodeError:
            return int(exc.code), {"raw": raw[:1000]}


def _voice_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _add_pcm_noise(wav_bytes: bytes, *, amplitude: int = 72) -> bytes:
    from io import BytesIO

    source = BytesIO(wav_bytes)
    output = BytesIO()
    with wave.open(source, "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(reader.getnframes())
    if params.sampwidth != 2:
        return wav_bytes
    samples = array("h")
    samples.frombytes(frames)
    for index in range(len(samples)):
        noise = amplitude if index % 2 == 0 else -amplitude
        samples[index] = max(-32768, min(32767, samples[index] + noise))
    with wave.open(output, "wb") as writer:
        writer.setparams(params)
        writer.writeframes(samples.tobytes())
    return output.getvalue()


def voice_audio_roundtrip_probe(ctx: Any) -> tuple[bool, str]:
    """Run real audio-in -> GPT-5.6 chat -> spoken-audio-out -> STT verification."""
    session_id = f"parity-voice-{time.time_ns()}"
    status_code, status_payload = _privacy_http_json(ctx, "/api/v2/chat/voice/status")
    input_phrase = "Thomas voice parity cedar nine three six"
    t0 = time.perf_counter()
    speak_status, speak_headers, input_audio = _voice_speak(ctx, input_phrase)
    t1 = time.perf_counter()
    audio_format = str(speak_headers.get("x-thomas-audio-format") or "wav")
    language = str(speak_headers.get("x-thomas-audio-language") or "en-US")
    transcribe_status, transcript_payload = _voice_transcribe(
        ctx,
        input_audio,
        audio_format=audio_format,
        language=language,
    )
    t2 = time.perf_counter()
    transcript = str(transcript_payload.get("text") or "") if isinstance(transcript_payload, dict) else ""
    chat_events: list[dict[str, Any]] = []
    output_audio = b""
    output_headers: dict[str, str] = {}
    output_transcribe_status = 0
    output_transcript_payload: Any = {}
    try:
        _, chat_events = _privacy_chat(
            ctx,
            session_id=session_id,
            message=f'The microphone transcript is: "{transcript}". Reply exactly: VOICE-CONVERSATION-OK.',
            temporary=False,
            external_access=False,
            memory=False,
        )
        assistant_text = _event_text(chat_events)
        output_status, output_headers, output_audio = _voice_speak(ctx, assistant_text)
        output_transcribe_status, output_transcript_payload = _voice_transcribe(
            ctx,
            output_audio,
            audio_format=str(output_headers.get("x-thomas-audio-format") or "wav"),
            language=str(output_headers.get("x-thomas-audio-language") or language),
        )
    finally:
        _privacy_http_json(ctx, f"/api/v2/chat/session/{session_id}", method="DELETE")
    assistant_text = _event_text(chat_events)
    spoken_back = (
        str(output_transcript_payload.get("text") or "") if isinstance(output_transcript_payload, dict) else ""
    )
    input_words = _voice_words(transcript)
    assistant_words = _voice_words(assistant_text)
    spoken_words = _voice_words(spoken_back)
    available_stt = (
        [
            row.get("provider")
            for row in status_payload.get("speech_to_text", [])
            if isinstance(row, dict) and row.get("available")
        ]
        if isinstance(status_payload, dict)
        else []
    )
    available_tts = (
        [
            row.get("provider")
            for row in status_payload.get("text_to_speech", [])
            if isinstance(row, dict) and row.get("available")
        ]
        if isinstance(status_payload, dict)
        else []
    )
    errors = [str(event.get("error") or "") for event in chat_events if event.get("type") == "error"]
    passed = bool(
        status_code == 200
        and available_stt
        and available_tts
        and speak_status == 200
        and input_audio.startswith(b"RIFF")
        and transcribe_status == 200
        and {"thomas", "voice", "parity", "cedar"}.issubset(set(input_words))
        and ("936" in input_words or {"nine", "three", "six"}.issubset(set(input_words)))
        and {"voice", "conversation"}.issubset(set(assistant_words))
        and bool({"ok", "okay"}.intersection(assistant_words))
        and output_status == 200
        and output_audio.startswith(b"RIFF")
        and output_transcribe_status == 200
        and {"voice", "conversation"}.issubset(set(spoken_words))
        and bool({"ok", "okay"}.intersection(spoken_words))
        and not errors
    )
    actual = {
        "status_code": status_code,
        "available_stt": available_stt,
        "available_tts": available_tts,
        "supported_languages": status_payload.get("supported_languages", [])
        if isinstance(status_payload, dict)
        else [],
        "input_audio_bytes": len(input_audio),
        "input_audio_format": audio_format,
        "input_tts_ms": round((t1 - t0) * 1000),
        "input_stt_ms": round((t2 - t1) * 1000),
        "transcript": transcript,
        "assistant_text": assistant_text,
        "output_audio_bytes": len(output_audio),
        "output_transcript": spoken_back,
        "output_provider": output_headers.get("x-thomas-voice-provider"),
        "errors": errors,
    }
    return passed, json.dumps(actual, ensure_ascii=False)


def voice_noise_language_interrupt_latency_probe(ctx: Any) -> tuple[bool, str]:
    """Exercise noisy dictation, supported-language contracts, Unicode speech, barge-in, and budgets."""
    status_code, status = _privacy_http_json(ctx, "/api/v2/chat/voice/status")
    languages = status.get("supported_languages", []) if isinstance(status, dict) else []
    language = str(languages[0] if languages else "en-US")
    phrase = "Thomas dictation cedar nine three six"
    t0 = time.perf_counter()
    speak_status, headers, clean_audio = _voice_speak(ctx, phrase, voice="default", speed=1.15)
    t1 = time.perf_counter()
    noisy_audio = _add_pcm_noise(clean_audio)
    transcribe_status, transcription = _voice_transcribe(
        ctx,
        noisy_audio,
        audio_format=str(headers.get("x-thomas-audio-format") or "wav"),
        language=language,
    )
    t2 = time.perf_counter()
    transcript = str(transcription.get("text") or "") if isinstance(transcription, dict) else ""
    unsupported_status, unsupported = _voice_transcribe(
        ctx,
        clean_audio,
        audio_format=str(headers.get("x-thomas-audio-format") or "wav"),
        language="zz-ZZ",
    )
    multilingual_status, multilingual_headers, multilingual_audio = _voice_speak(
        ctx,
        "Hola, mundo. Bonjour, le monde. Hello, world.",
    )
    interrupt = _realtime_interrupt_receipt()
    tts_ms = round((t1 - t0) * 1000)
    stt_ms = round((t2 - t1) * 1000)
    transcript_words = set(_voice_words(transcript))
    provider_error = str(unsupported.get("error") or "") if isinstance(unsupported, dict) else ""
    passed = bool(
        status_code == 200
        and languages
        and speak_status == 200
        and clean_audio.startswith(b"RIFF")
        and noisy_audio != clean_audio
        and transcribe_status == 200
        and {"thomas", "dictation", "cedar"}.issubset(transcript_words)
        and ("936" in transcript_words or {"nine", "three", "six"}.issubset(transcript_words))
        and unsupported_status == 503
        and "not installed" in provider_error.lower()
        and multilingual_status == 200
        and multilingual_audio.startswith(b"RIFF")
        and len(multilingual_audio) > 1000
        and multilingual_headers.get("x-thomas-audio-language") in languages
        and interrupt.get("canceled") is True
        and interrupt.get("barge_in_events", 0) >= 1
        and interrupt.get("assistant_canceled", 0) >= 1
        and interrupt.get("late_delta_seen") is False
        and interrupt.get("interrupt_ms", 9999) < 250
        and tts_ms < 2000
        and stt_ms < 2500
    )
    actual = {
        "status_code": status_code,
        "supported_languages": languages,
        "spoken_language": headers.get("x-thomas-audio-language"),
        "noise_added": noisy_audio != clean_audio,
        "transcribe_status": transcribe_status,
        "noisy_transcript": transcript,
        "unsupported_language_status": unsupported_status,
        "unsupported_language_error": provider_error,
        "multilingual_audio_status": multilingual_status,
        "multilingual_audio_bytes": len(multilingual_audio),
        "multilingual_voice_language": multilingual_headers.get("x-thomas-audio-language"),
        "interrupt": interrupt,
        "tts_ms": tts_ms,
        "stt_ms": stt_ms,
        "latency_budget_ms": {"tts": 2000, "stt": 2500, "interrupt": 250},
    }
    return passed, json.dumps(actual, ensure_ascii=False)
