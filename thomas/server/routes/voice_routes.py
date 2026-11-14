"""Talking to Thomas by voice: the choices, the model that answers, and Voice Studio's ears and mouth.

GET  /api/voice/status      the saved choices, whether Voice Studio is running, who will speak and the model that answers
PUT  /api/voice/settings    change any of the saved choices (engine, voice, fast_model, studio_url)
GET  /api/voice/voices      the voices Voice Studio offers ([] when it is not running)
POST /api/voice/speak       {"text", "voice"?} -> sound made by Voice Studio, 503 when it is not running
POST /api/voice/transcribe  a recording in the ``audio`` field -> {"text"}, 503 when Voice Studio is not running
GET  /api/voice/live        a websocket for live talk: 16 kHz 16-bit sound in, the words back as you speak
GET  /api/voice/setup       what setting up Thomas's own listening would download, and how far a set-up has got
POST /api/voice/setup       {"model"} set that one up: the speech engine when it is missing, then the model, checked file by file

Live listening is Thomas's own first (voice_ears: a speech model running in this process, no other program, nothing to
accept) and Voice Studio's when Thomas's model is not installed. Until it is, status carries ``setup``, which the page
uses to offer setting it up the first time you turn live talk on (voice_ears_setup does the work, voice_ears_models
lists the models and the default). The page records, shows the words and sends them
through the ordinary send path; this only does the speech work and says which model to send with. When neither can
listen the page uses the browser's own speech, so nothing here is required for voice to work.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

from thomas.server import (
    voice_ears,
    voice_ears_models,
    voice_ears_setup,
    voice_fast_model,
    voice_settings,
    voice_studio,
)
from thomas.server.voice_studio import VoiceStudioError

_MAX_UPLOAD = voice_studio.MAX_AUDIO_BYTES
_running: set[asyncio.Future] = set()  # background lookups, held until they finish so they are not dropped half-way


def _remember(task: asyncio.Future) -> None:
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _quietly(lookup: Any) -> None:
    """A background lookup whose only job is to fill a cache: if Voice Studio cannot answer, the name stays unknown."""
    with contextlib.suppress(VoiceStudioError):
        await lookup


async def _catalog_rows(config: Any) -> list[dict[str, Any]]:
    from thomas.models.catalog import build_model_catalog_async, load_cached_model_catalog

    catalog = load_cached_model_catalog(config) or await build_model_catalog_async(config, refresh=False)
    return [row for row in catalog.get("models") or [] if isinstance(row, dict)]


def _fail(message: str, status: int) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


def _setup(path: Path, saved: dict[str, str]) -> dict[str, Any] | None:
    """What setting up the chosen listening model involves and how far it has got; None once Thomas can listen."""
    entry = voice_ears_models.get(saved["ears"])
    if not voice_ears.why_not(voice_ears.find_model(path, entry["id"]), entry["id"]):
        return None
    return {
        "model": entry["id"],
        "name": entry["name"],
        "about": entry["about"],
        "licence": entry["licence"],
        "credit": entry["credit"],
        "bytes": voice_ears_models.size(entry),
        "engine": voice_ears_setup.engine_ready(),
        "progress": voice_ears_setup.progress(entry["id"]),
    }


def setup_voice_routes(
    app: web.Application,
    *,
    settings_path: Path,
    config: Any,
    require_api_access: Callable[[web.Request], Any] | None = None,
) -> None:
    guard = require_api_access or (lambda _request: None)
    path = Path(settings_path)

    async def status(request: web.Request) -> web.Response:
        guard(request)
        saved = voice_settings.load(path)
        running = await voice_studio.is_running(saved["studio_url"]) if saved["engine"] != "browser" else False
        surface = "code" if request.query.get("surface") == "code" else "chat"
        model = voice_fast_model.chosen(saved["fast_model"], await _catalog_rows(config), surface=surface)
        who = "voicestudio" if running else "browser"
        entry = voice_ears_models.get(saved["ears"])
        own_why = voice_ears.why_not(voice_ears.find_model(path, entry["id"]), entry["id"])
        live, live_why, by = (entry["label"], "", "thomas") if not own_why else (None, own_why, "")
        if live is None and running:
            live, studio_why = await voice_studio.live_model(
                saved["studio_url"], fresh=request.query.get("fresh") == "1"
            )
            by = "voicestudio" if live else ""
            live_why = "" if live else f"{own_why}; and Voice Studio: {studio_why}"
        # The chosen voice by name, from the list Thomas has already seen (Voice Studio takes ~2 s to list them, so the
        # first time the list is fetched in the background and the name is there from the next status on).
        voice_name = voice_studio.voice_name(saved["studio_url"], saved["voice"]) if running else ""
        if running and not voice_name and saved["voice"] not in ("", "default"):
            _remember(asyncio.ensure_future(_quietly(voice_studio.voices(saved["studio_url"]))))
        return web.json_response(
            {
                "ok": True,
                "settings": saved,
                "voice_name": voice_name,
                "studio": {"running": running, "url": saved["studio_url"]},
                "speaker": who,
                "listener": who,
                "fast_model": model,
                "setup": _setup(path, saved),
                "live": {
                    "model": live,
                    "why": live_why,
                    "by": by,
                    "credit": entry["credit"] if by == "thomas" else "",
                },
            }
        )

    async def change(request: web.Request) -> web.Response:
        guard(request)
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            return _fail("Send a JSON object of the choices to change", 400)
        if not isinstance(payload, dict):
            return _fail("Send a JSON object of the choices to change", 400)
        try:
            saved = voice_settings.update(path, payload)
        except ValueError as exc:
            return _fail(str(exc), 400)
        return web.json_response({"ok": True, "settings": saved})

    async def list_voices(request: web.Request) -> web.Response:
        guard(request)
        try:
            found = await voice_studio.voices(voice_settings.load(path)["studio_url"])
        except VoiceStudioError:
            found = []
        return web.json_response({"ok": True, "voices": found})

    async def speak(request: web.Request) -> web.Response:
        guard(request)
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            payload = None
        if not isinstance(payload, dict):
            return _fail("Send JSON with the text to speak", 400)
        text = str(payload.get("text") or "").strip()
        if not text:
            return _fail("There is no text to speak", 400)
        saved = voice_settings.load(path)
        voice = str(payload.get("voice") or saved["voice"])
        try:
            sound, kind = await voice_studio.speak(saved["studio_url"], text, voice)
        except VoiceStudioError as exc:
            return _fail(str(exc), 503)
        return web.Response(body=sound, content_type=kind, headers={"Cache-Control": "no-store"})

    async def transcribe(request: web.Request) -> web.Response:
        guard(request)
        if not str(request.content_type or "").lower().startswith("multipart/"):
            return _fail("Send the recording as multipart/form-data", 400)
        audio, name, kind, language = b"", "speech.webm", "audio/webm", ""
        try:
            reader = await request.multipart()
            while (field := await reader.next()) is not None:
                if field.name == "language":
                    language = (await field.text()).strip()[:32]
                elif field.name == "audio":
                    name = str(field.filename or name)
                    kind = str(field.headers.get("Content-Type", kind) or kind)
                    audio = await field.read(decode=False)
                    if len(audio) > _MAX_UPLOAD:
                        return _fail("The recording is too large", 413)
                else:
                    await field.release()
        except (AssertionError, OSError, RuntimeError, ValueError):
            return _fail("The recording could not be read", 400)
        if not audio:
            return _fail("There is no recording", 400)
        try:
            text = await voice_studio.transcribe(
                voice_settings.load(path)["studio_url"], audio, filename=name, content_type=kind, language=language
            )
        except VoiceStudioError as exc:
            return _fail(str(exc), 503)
        return web.json_response({"ok": True, "text": text})

    async def live(request: web.Request) -> web.StreamResponse:
        """Listen to the page's microphone, Thomas's own ears first, Voice Studio's otherwise, until either side closes."""
        guard(request)
        if request.headers.get("Upgrade", "").lower() != "websocket":
            return _fail("Open this address as a websocket", 400)
        chosen = voice_settings.load(path)["ears"]
        ears = voice_ears.find_model(path, chosen)
        if not voice_ears.why_not(ears, chosen):
            page = web.WebSocketResponse(heartbeat=20.0, max_msg_size=1 << 20)
            await page.prepare(request)
            try:
                await voice_ears.serve(page, ears, chosen)
            except (OSError, RuntimeError, ValueError) as exc:
                if not page.closed:
                    await page.send_json(
                        {"type": "error", "kind": "ears_failed", "message": f"Thomas stopped listening: {exc}"}
                    )
            await page.close()
            return page
        saved = voice_settings.load(path)
        model, why = await voice_studio.live_model(saved["studio_url"])
        page = web.WebSocketResponse(heartbeat=20.0, max_msg_size=1 << 20)
        await page.prepare(request)
        if model is None:
            await page.send_json({"type": "error", "kind": "no_live_model", "message": why})
            await page.close()
            return page
        try:
            async with (
                aiohttp.ClientSession() as http,
                http.ws_connect(voice_studio.live_address(saved["studio_url"], model), heartbeat=20.0) as studio,
            ):
                await page.send_json({"type": "live.started", "model": model})

                async def up() -> None:
                    async for message in page:
                        if message.type == aiohttp.WSMsgType.BINARY:
                            await studio.send_bytes(message.data)
                        elif message.type == aiohttp.WSMsgType.TEXT:
                            await studio.send_str(message.data)
                    await studio.close()

                async def down() -> None:
                    async for message in studio:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await page.send_str(message.data)

                tasks = [asyncio.ensure_future(up()), asyncio.ensure_future(down())]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in tasks:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, aiohttp.ClientError, ConnectionError):
                        await task
        except (aiohttp.ClientError, OSError, VoiceStudioError):
            if not page.closed:
                await page.send_json(
                    {"type": "error", "kind": "studio_gone", "message": "Voice Studio stopped listening"}
                )
        await page.close()
        return page

    async def setup_state(request: web.Request) -> web.Response:
        guard(request)
        return web.json_response({"ok": True, "setup": _setup(path, voice_settings.load(path))})

    async def setup_start(request: web.Request) -> web.Response:
        """Set up the listening model named (it becomes the one Thomas listens with) in the data folder.

        The model has to be named: an empty request starts nothing, so nothing downloads 670 MB by accident.
        """
        guard(request)
        try:
            payload = await request.json() if request.can_read_body else {}
        except (ValueError, UnicodeDecodeError):
            return _fail("Send JSON, or nothing", 400)
        wanted = payload.get("model") if isinstance(payload, dict) else None
        if not wanted:
            return _fail("Name the listening model to set up", 400)
        try:
            saved = voice_settings.update(path, {"ears": wanted})
        except ValueError as exc:
            return _fail(str(exc), 400)
        found = _setup(path, saved)
        if found is not None:
            voice_ears_setup.start(found["model"], voice_ears.model_dir(path, found["model"]))
            found = _setup(path, saved)
        return web.json_response({"ok": True, "setup": found})

    app.router.add_get("/api/voice/status", status)
    app.router.add_get("/api/voice/setup", setup_state)
    app.router.add_post("/api/voice/setup", setup_start)
    app.router.add_get("/api/voice/live", live)
    app.router.add_put("/api/voice/settings", change)
    app.router.add_get("/api/voice/voices", list_voices)
    app.router.add_post("/api/voice/speak", speak)
    app.router.add_post("/api/voice/transcribe", transcribe)


__all__ = ["setup_voice_routes"]
