"""The voice routes with a stand-in for Voice Studio that answers the way its OpenAI-style audio calls do.

Proves ``thomas.server.routes.voice_routes`` (through ``thomas.server.rows.voice``), ``thomas.server.voice_studio``,
``thomas.server.voice_settings`` and ``thomas.server.voice_fast_model``. The stand-in copies what was read in Voice
Studio's own code: ``GET /health``, ``GET /v1/audio/voices`` answering ``{"voices": [{"voice_id", "name"}]}``,
``POST /v1/audio/speech`` taking ``{"input", "voice", "response_format"}`` and ``POST /v1/audio/transcriptions`` taking a
``file`` field and answering ``{"text"}``, and ``WS /v1/audio/transcriptions/stream`` (``?model=&sr=&pcm=1``) answering
``session.started``, then ``error`` for a model whose licence is not accepted or ``status`` ready, then ``partial`` and
``final`` for the sound it hears. The live line was run against Voice Studio 0.5.7 on 2026-11-06: a model whose licence
was not accepted answered ``{"type": "error", "message": "Licence not accepted for ..."}`` right after ``session.started``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from aiohttp import FormData, WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture
from thomas.models.catalog_rules import writes_text
from thomas.server import app_core, voice_ears, voice_fast_model, voice_settings, voice_studio
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

SOUND = b"RIFF....WAVEfmt fake"
WEBM = b"\x1aE\xdf\xa3webm"


@pytest.fixture(autouse=True)
def _no_installed_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """These are about Voice Studio, so Thomas's own model must not be found in the install folder of this checkout."""
    monkeypatch.setattr(voice_ears, "INSTALL_DIR", tmp_path / "no-install" / voice_ears.MODEL_NAME)


def _stand_in(calls: list[tuple[str, Any]]) -> web.Application:
    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def voices(_request: web.Request) -> web.Response:
        calls.append(("voices", None))
        return web.json_response(
            {"voices": [{"voice_id": "alloy", "name": "Alloy"}, {"voice_id": "p1", "name": "Mine"}]}
        )

    async def speech(request: web.Request) -> web.Response:
        body = await request.json()
        calls.append(("speech", body))
        if body["input"] == "slow":
            await asyncio.sleep(120)
        if body["input"] == "refuse":
            return web.json_response({"error": {"message": "no engine installed"}}, status=400)
        return web.Response(body=SOUND, content_type="audio/wav")

    async def transcriptions(request: web.Request) -> web.Response:
        form = await request.post()
        upload = form["file"]
        calls.append(("transcriptions", (upload.filename, upload.file.read(), form.get("language"))))
        return web.json_response({"text": " hello there "})

    async def stream(request: web.Request) -> web.WebSocketResponse:
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        model = request.query.get("model", "")
        calls.append(("live", dict(request.query)))
        await socket.send_json({"type": "session.started", "protocol": "voicestudio.speech.v1"})
        if model == voice_studio.LIVE_MODELS[0] or "locked-all" in calls:
            await socket.send_json({"type": "error", "message": f"Licence not accepted for {model}."})
            await socket.close()
            return socket
        await socket.send_json({"type": "status", "stage": "ready"})
        heard = 0
        async for message in socket:
            if message.type == WSMsgType.BINARY:
                heard += len(message.data)
                calls.append(("sound", len(message.data)))
                if heard >= 3200:
                    await socket.send_json({"type": "partial", "text": "hello"})
                    await socket.send_json({"type": "final", "text": "Hello there.", "final_kind": "utterance"})
                    heard = -(10**9)
        return socket

    app = web.Application()
    app.router.add_get("/v1/audio/transcriptions/stream", stream)
    app.router.add_get("/health", health)
    app.router.add_get("/v1/audio/voices", voices)
    app.router.add_post("/v1/audio/speech", speech)
    app.router.add_post("/v1/audio/transcriptions", transcriptions)
    return app


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: Callable[..., Awaitable[Any]], *, up: bool = True
) -> Any:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    calls: list[tuple[str, Any]] = []

    async def main() -> Any:
        studio = TestServer(_stand_in(calls))
        await studio.start_server()
        address = f"http://127.0.0.1:{studio.port}" if up else "http://127.0.0.1:9"
        try:
            async with TestClient(TestServer(app_core.create_app(plugin_view_fixture.config_in(tmp_path)))) as client:
                assert (await client.put("/api/voice/settings", json={"studio_url": address})).status == 200
                return await scenario(client, calls)
        finally:
            await studio.close()

    return asyncio.run(main())


async def _status(client: TestClient, _calls: list) -> dict:
    return await (await client.get("/api/voice/status")).json()


def test_status_says_voice_studio_will_speak_when_it_is_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _run(tmp_path, monkeypatch, _status)
    assert body["studio"]["running"] is True
    assert (body["speaker"], body["listener"]) == ("voicestudio", "voicestudio")
    assert body["settings"]["voice"] == "default"  # the one saved default


def test_status_falls_back_to_the_browser_when_voice_studio_is_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _run(tmp_path, monkeypatch, _status, up=False)
    assert body["studio"]["running"] is False
    assert (body["speaker"], body["listener"]) == ("browser", "browser")


def test_the_browser_engine_is_never_overridden_by_a_running_voice_studio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient, calls: list) -> dict:
        await client.put("/api/voice/settings", json={"engine": "browser"})
        return await _status(client, calls)

    assert _run(tmp_path, monkeypatch, scenario)["speaker"] == "browser"


def test_speak_returns_voice_studios_sound_with_the_saved_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient, calls: list) -> tuple[int, bytes, str, list]:
        await client.put("/api/voice/settings", json={"voice": "alloy"})
        answer = await client.post("/api/voice/speak", json={"text": "Hello"})
        return answer.status, await answer.read(), answer.content_type, calls

    status, sound, kind, calls = _run(tmp_path, monkeypatch, scenario)
    assert (status, sound, kind) == (200, SOUND, "audio/wav")
    assert calls == [("speech", {"input": "Hello", "voice": "alloy", "response_format": "wav", "speed": 1.0})]


def test_speak_answers_503_with_the_reason_when_voice_studio_is_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient, _calls: list) -> tuple[int, dict]:
        answer = await client.post("/api/voice/speak", json={"text": "Hello"})
        return answer.status, await answer.json()

    status, body = _run(tmp_path, monkeypatch, scenario, up=False)
    assert (status, body) == (503, {"ok": False, "error": "Voice Studio is not running"})


def test_speak_passes_on_voice_studios_own_reason_when_it_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient, _calls: list) -> tuple[int, dict]:
        answer = await client.post("/api/voice/speak", json={"text": "refuse"})
        return answer.status, await answer.json()

    status, body = _run(tmp_path, monkeypatch, scenario)
    assert status == 503
    assert body["error"] == "Voice Studio could not speak (400): no engine installed"


def test_transcribe_sends_the_recording_to_voice_studio_and_returns_the_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient, calls: list) -> tuple[int, dict, list]:
        form = FormData()
        form.add_field("audio", WEBM, filename="speech.webm", content_type="audio/webm")
        form.add_field("language", "en")
        answer = await client.post("/api/voice/transcribe", data=form)
        return answer.status, await answer.json(), calls

    status, body, calls = _run(tmp_path, monkeypatch, scenario)
    assert (status, body) == (200, {"ok": True, "text": "hello there"})
    assert calls == [("transcriptions", ("speech.webm", WEBM, "en"))]


def test_transcribe_answers_503_when_voice_studio_is_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient, _calls: list) -> int:
        form = FormData()
        form.add_field("audio", b"x", filename="speech.webm", content_type="audio/webm")
        return (await client.post("/api/voice/transcribe", data=form)).status

    assert _run(tmp_path, monkeypatch, scenario, up=False) == 503


def test_the_voice_list_is_voice_studios_and_empty_when_it_is_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient, _calls: list) -> list:
        return (await (await client.get("/api/voice/voices")).json())["voices"]

    assert _run(tmp_path, monkeypatch, scenario) == [{"id": "alloy", "name": "Alloy"}, {"id": "p1", "name": "Mine"}]
    assert _run(tmp_path / "again", monkeypatch, scenario, up=False) == []


@pytest.mark.parametrize(
    "address",
    [
        "http://example.com:3900",
        "https://127.0.0.1:3900",
        "http://127.0.0.1:3900/x",
        "http://user@127.0.0.1:3900",
        "ftp://localhost",
    ],
)
def test_the_saved_address_can_only_be_on_this_computer(address: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="studio_url"):
        voice_settings.update(tmp_path / "voice.json", {"studio_url": address})
    assert voice_studio.local_url(address) is None


def test_one_default_voice_is_saved_and_a_change_replaces_it(tmp_path: Path) -> None:
    path = tmp_path / "voice.json"
    assert voice_settings.load(path)["voice"] == "default"
    assert voice_settings.update(path, {"voice": "Nova"})["voice"] == "Nova"
    assert voice_settings.load(path)["voice"] == "Nova"
    assert voice_settings.update(path, {"voice": ""})["voice"] == "default"


def test_a_bad_choice_is_refused_and_leaves_the_saved_file_alone(tmp_path: Path) -> None:
    path = tmp_path / "voice.json"
    voice_settings.update(path, {"voice": "Nova"})
    for bad in ({"engine": "loud"}, {"fast_model": "gpt"}, {"nope": 1}):
        with pytest.raises(ValueError):
            voice_settings.update(path, bad)
    assert voice_settings.load(path)["voice"] == "Nova"


ROWS = [
    {"profile": "big", "id": "gpt-5.5", "available": True, "family": "openai"},
    {"profile": "claude", "id": "claude-haiku-4-5", "available": True, "family": "anthropic", "display_name": "Haiku"},
    {"profile": "oa", "id": "gpt-5.4-mini", "available": True, "family": "openai"},
    {"profile": "oa", "id": "gpt-5-nano", "available": False, "family": "openai"},
    {"profile": "", "id": "gpt-5.1-codex-mini", "available": True, "family": "openai"},
    {"profile": "loc", "id": "tiny-llama", "available": True, "family": "ollama", "hidden": True},
]


def test_the_smallest_ready_model_is_picked_by_its_size_word() -> None:
    # nano is not ready, tiny is hidden and codex-mini has no profile, so haiku outranks mini.
    assert voice_fast_model.pick(ROWS) == {"profile": "claude", "id": "claude-haiku-4-5", "label": "Haiku"}


def test_with_no_small_model_ready_nothing_is_picked_and_the_turn_keeps_your_model() -> None:
    assert voice_fast_model.pick([ROWS[0]]) is None


def test_code_is_held_to_the_families_it_runs() -> None:
    rows = [{"profile": "loc", "id": "tiny-llama", "available": True, "family": "ollama"}, ROWS[2]]
    assert voice_fast_model.pick(rows)["id"] == "tiny-llama"
    assert voice_fast_model.pick(rows, surface="code")["id"] == "gpt-5.4-mini"


def test_a_named_model_is_used_only_while_it_is_ready() -> None:
    assert voice_fast_model.chosen("oa|gpt-5.4-mini", ROWS)["id"] == "gpt-5.4-mini"
    assert voice_fast_model.chosen("oa|gpt-5-nano", ROWS) is None


def test_stop_now_cuts_off_a_piece_of_speech_still_being_made(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stop waits for the request and Stop now drops it, after which the routes are gone."""

    async def scenario(client: TestClient, calls: list) -> None:
        runtime = client.app[APP_RUNTIME_PLUGINS]
        asking = asyncio.create_task(client.post("/api/voice/speak", json={"text": "slow"}))
        for _ in range(300):
            if calls:
                break
            await asyncio.sleep(0.1)
        assert calls, "Voice Studio's stand-in was never asked"
        stopping = asyncio.create_task(runtime.turn_off("voice"))
        await asyncio.sleep(0.3)
        assert not stopping.done()

        await runtime.turn_off("voice", force=True)
        await asyncio.wait_for(stopping, timeout=30)

        answer = (await asyncio.gather(asking, return_exceptions=True))[0]
        assert isinstance(answer, BaseException) or answer.status != 200, answer
        assert (await client.get("/api/voice/status")).status == 404

    _run(tmp_path, monkeypatch, scenario)


def test_nothing_in_the_voice_code_starts_a_program() -> None:
    """The words say Voice Studio has to be running already, and that Thomas never starts it.

    The one program the voice code starts is pip, putting the pinned speech engine into Thomas's own Python when setting
    up his hearing finds it missing; that is ``install_engine`` in voice_ears_setup.py, and it is the only call there.
    """
    folder = Path(__file__).resolve().parents[1] / "thomas" / "server"
    sources = [folder / "voice_studio.py", folder / "voice_settings.py", folder / "voice_fast_model.py"]
    sources += [folder / "voice_ears.py", folder / "voice_ears_models.py"]
    setup = (folder / "voice_ears_setup.py").read_text(encoding="utf-8")
    assert setup.count("subprocess.run(") == 1 and "Popen" not in setup and "os.system" not in setup
    assert '[sys.executable, "-m", "pip", "install", "--quiet", voice_ears_models.ENGINE]' in setup
    sources.append(folder / "routes" / "voice_routes.py")
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert [
            word for word in ("subprocess", "Popen", "os.system", "startfile", "create_subprocess") if word in text
        ] == []


def test_status_names_the_first_live_model_voice_studio_will_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _run(tmp_path, monkeypatch, _status)
    # The fastest one's licence is not accepted in the stand-in, so the next one is the one that listens.
    assert body["live"] == {"model": voice_studio.LIVE_MODELS[1], "why": "", "by": "voicestudio", "credit": ""}


def test_status_says_why_live_listening_is_not_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario(client: TestClient, calls: list) -> dict:
        calls.append("locked-all")
        return await (await client.get("/api/voice/status?fresh=1")).json()

    body = _run(tmp_path, monkeypatch, scenario)
    assert body["live"]["model"] is None
    assert body["live"]["why"].startswith("Thomas's listening model is not in ")
    assert "; and Voice Studio: Licence not accepted for " + voice_studio.LIVE_MODELS[0] in body["live"]["why"]


def test_the_live_line_passes_the_microphone_to_voice_studio_and_its_words_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient, calls: list) -> tuple[list[dict], list]:
        got: list[dict] = []
        async with client.ws_connect("/api/voice/live") as socket:
            got.append(await socket.receive_json(timeout=10))
            await socket.send_bytes(bytes(3200))  # 100 ms of 16 kHz 16-bit silence
            while len(got) < 3:  # Voice Studio's own session.started and status pass through too; the page skips them
                event = await socket.receive_json(timeout=10)
                if event["type"] in ("partial", "final"):
                    got.append(event)
        return got, calls

    got, calls = _run(tmp_path, monkeypatch, scenario)
    assert got == [
        {"type": "live.started", "model": voice_studio.LIVE_MODELS[1]},
        {"type": "partial", "text": "hello"},
        {"type": "final", "text": "Hello there.", "final_kind": "utterance"},
    ]
    asked = [query for kind, query in calls if kind == "live"]
    assert asked[-1] == {"model": voice_studio.LIVE_MODELS[1], "sr": "16000", "pcm": "1"}
    assert ("sound", 3200) in calls


def test_the_live_line_says_why_when_no_model_can_listen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario(client: TestClient, calls: list) -> list:
        calls.append("locked-all")
        await client.get("/api/voice/status?fresh=1")
        async with client.ws_connect("/api/voice/live") as socket:
            first = await socket.receive_json(timeout=10)
            closing = await socket.receive(timeout=10)
        return [first, closing.type]

    first, closing = _run(tmp_path, monkeypatch, scenario)
    assert first["type"] == "error" and first["kind"] == "no_live_model"
    assert first["message"].startswith("Licence not accepted")
    assert closing in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING)


def test_the_live_line_is_a_websocket_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario(client: TestClient, _calls: list) -> int:
        return (await client.get("/api/voice/live")).status

    assert _run(tmp_path, monkeypatch, scenario) == 400


def test_a_model_that_makes_pictures_is_never_the_one_that_answers_your_voice() -> None:
    # What the model list held on 2026-11-06: DeepInfra lists picture models beside text ones, all marked as chat, and
    # "nano" outranks "lite", so every spoken question went to a picture model.
    rows = [
        {"profile": "di", "id": "google/nano-banana-2-lite", "available": True, "capabilities": {"chat": True}},
        {"profile": "di", "id": "Qwen/Qwen-Image-Max", "available": True},
        {"profile": "di", "id": "inworld-ai/realtime-tts-2", "available": True},
        {"profile": "di", "id": "google/gemini-3.1-flash-lite", "available": True, "capabilities": {"chat": True}},
    ]
    assert voice_fast_model.pick(rows)["id"] == "google/gemini-3.1-flash-lite"
    marked = [dict(rows[3], id="openai/gpt-5-nano", capabilities={"chat": False})]
    assert voice_fast_model.pick(marked) is None


@pytest.mark.parametrize(
    "model_id",
    [
        "google/nano-banana-2-lite",
        "black-forest-labs/FLUX-2-dev",
        "ByteDance/Seedream-4",
        "BAAI/bge-m3",
        "intfloat/multilingual-e5-large-instruct",
        "Wan-AI/Wan2.6-T2V",
        "inworld-ai/realtime-tts-2",
        "PrunaAI/p-image",
    ],
)
def test_the_model_list_stops_calling_picture_sound_and_embedding_models_chat(model_id: str) -> None:
    assert writes_text(model_id) is False


@pytest.mark.parametrize(
    "model_id",
    [
        "google/gemini-3.1-flash-lite",
        "haiku",
        "gpt-4o-mini",
        "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp",
        "gpt-5.5-sol",
        "Qwen/Qwen3.8-Flash",
        "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "mistral-large-latest",
    ],
)
def test_models_that_answer_in_words_are_still_chat(model_id: str) -> None:
    assert writes_text(model_id) is True


# ---- 2026-11-06: Voice Studio takes about 2 s to list its voices, so the line under the message box said
# "Voice: 7444d461" until the names arrived. Thomas keeps the list, and status names the chosen voice. ----


def test_the_voice_list_is_asked_for_once_and_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario(client: TestClient, calls: list) -> tuple[list, list, int]:
        first = (await (await client.get("/api/voice/voices")).json())["voices"]
        second = (await (await client.get("/api/voice/voices")).json())["voices"]
        return first, second, len([call for call in calls if call[0] == "voices"])

    first, second, asked = _run(tmp_path, monkeypatch, scenario)
    assert first == second == [{"id": "alloy", "name": "Alloy"}, {"id": "p1", "name": "Mine"}]
    assert asked == 1


def test_status_names_the_chosen_voice_once_the_list_has_been_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient, calls: list) -> tuple[str, str]:
        assert (await client.put("/api/voice/settings", json={"engine": "voicestudio", "voice": "p1"})).status == 200
        before = (await (await client.get("/api/voice/status")).json())["voice_name"]
        for _ in range(100):  # the first status fetches the list in the background, without waiting for it
            if any(call[0] == "voices" for call in calls):
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
        after = (await (await client.get("/api/voice/status")).json())["voice_name"]
        return before, after

    assert _run(tmp_path, monkeypatch, scenario) == ("", "Mine")
