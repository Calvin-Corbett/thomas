"""Thomas listens live by himself: no Voice Studio, no licence click, his own speech model in his own process.

You asked that Thomas not need Voice Studio's licence click: "your suppose to reverse enbginerr whatebvr it is and him, not
need it". The click was Voice Studio's own rule; the model, NVIDIA Parakeet TDT 0.6B v3, is CC-BY-4.0 and runs here with
sherpa-onnx (thomas/server/voice_ears.py). These walk the cut between what you said and your pauses, the status the
page reads, the live websocket through Thomas's real app, and, when the model is installed, the real model on a real
recording.
"""

from __future__ import annotations

import asyncio
import glob
import os
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture
from thomas.server import app_core, voice_ears

RATE = voice_ears.RATE


def _tone(seconds: float, loudness: float = 0.2) -> bytes:
    t = np.arange(int(RATE * seconds)) / RATE
    return (np.sin(2 * np.pi * 220 * t) * loudness * 32767).astype("<i2").tobytes()


def _quiet(seconds: float, hiss: float = 0.001) -> bytes:
    noise = np.random.default_rng(7).normal(0, hiss, int(RATE * seconds))
    return (noise * 32767).astype("<i2").tobytes()


def _frames(pcm: bytes, size: int = 3200):
    for start in range(0, len(pcm), size):
        yield pcm[start : start + size]


def _cut(pcm: bytes) -> list[tuple[str, float]]:
    cut = voice_ears.Segmenter()
    out = []
    for frame in _frames(pcm):
        out += [(kind, len(samples) / RATE) for kind, samples in cut.feed(frame)]
    return out + [(kind, len(samples) / RATE) for kind, samples in cut.flush()]


def test_a_sentence_then_a_pause_is_one_final_with_the_words_shown_while_it_is_said() -> None:
    got = _cut(_quiet(1.0) + _tone(2.0) + _quiet(1.0))

    finals = [seconds for kind, seconds in got if kind == "final"]
    assert len(finals) == 1
    assert 2.0 <= finals[0] <= 3.1  # the speech, the bit kept from before it, and the pause that ended it
    assert any(kind == "partial" for kind, _ in got[: got.index(("final", finals[0]))])


def test_two_sentences_with_a_pause_between_are_two_turns() -> None:
    got = _cut(_quiet(0.5) + _tone(1.0) + _quiet(1.0) + _tone(1.0) + _quiet(1.0))

    assert [kind for kind, _ in got if kind == "final"] == ["final", "final"]


@pytest.mark.parametrize(
    "pcm",
    [_quiet(3.0), _quiet(3.0, hiss=0.004), _quiet(1.0) + _tone(0.1) + _quiet(1.0)],
    ids=["silence", "a steady hum the room makes", "a click"],
)
def test_quiet_a_hum_or_a_click_is_never_a_turn(pcm: bytes) -> None:
    assert [kind for kind, _ in _cut(pcm) if kind == "final"] == []


def test_stopping_the_microphone_mid_sentence_still_sends_what_was_said() -> None:
    cut = voice_ears.Segmenter()
    for frame in _frames(_quiet(0.5) + _tone(1.5)):
        cut.feed(frame)

    assert [kind for kind, _ in cut.flush()] == ["final"]


def test_a_long_speech_with_no_pause_is_still_written_down() -> None:
    got = _cut(_quiet(0.5) + _tone(27.0) + _quiet(1.0))

    assert [kind for kind, _ in got if kind == "final"][:1] == ["final"]


def test_why_not_names_what_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "not in" in voice_ears.why_not(tmp_path) and "encoder.int8.onnx" in voice_ears.why_not(tmp_path)
    for name in voice_ears.FILES:
        (tmp_path / name).write_bytes(b"x")
    assert voice_ears.why_not(tmp_path) == ""
    monkeypatch.setattr(voice_ears.importlib.util, "find_spec", lambda name: None)
    assert "sherpa-onnx" in voice_ears.why_not(tmp_path)


@pytest.fixture(autouse=True)
def _no_installed_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(voice_ears, "INSTALL_DIR", tmp_path / "no-install" / voice_ears.MODEL_NAME)


def test_the_model_is_found_in_the_install_folder_when_the_data_folder_cannot_hold_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caged server's data folder is in its own Windows account; the install folder is the one that is shared."""
    settings = tmp_path / "cage" / ".thomas" / "voice.json"
    installed = tmp_path / "install" / ".thomas" / "models" / voice_ears.MODEL_NAME
    monkeypatch.setattr(voice_ears, "INSTALL_DIR", installed)
    assert voice_ears.find_model(settings) == voice_ears.model_dir(settings)  # nowhere yet: say where it belongs
    installed.mkdir(parents=True)
    for name in voice_ears.FILES:
        (installed / name).write_bytes(b"x")
    assert voice_ears.find_model(settings) == installed
    voice_ears.model_dir(settings).mkdir(parents=True)
    for name in voice_ears.FILES:
        (voice_ears.model_dir(settings) / name).write_bytes(b"x")
    assert voice_ears.find_model(settings) == voice_ears.model_dir(settings)  # its own data folder comes first


def _app_with_ears(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario) -> Any:
    """Thomas's real app, with its model folder filled and a stand-in model that says how long each piece was."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    config = plugin_view_fixture.config_in(tmp_path)
    folder = voice_ears.model_dir(Path(config.memory.root_path) / ".thomas" / "voice.json")
    folder.mkdir(parents=True)
    for name in voice_ears.FILES:
        (folder / name).write_bytes(b"x")
    monkeypatch.setattr(voice_ears, "recognizer", lambda _folder, _model=None: ("stand-in", None))
    monkeypatch.setattr(voice_ears, "transcribe", lambda _loaded, samples: f"{len(samples) / RATE:.1f} seconds")

    async def main() -> Any:
        async with TestClient(TestServer(app_core.create_app(config))) as client:
            assert (await client.put("/api/voice/settings", json={"studio_url": "http://127.0.0.1:9"})).status == 200
            return await scenario(client)

    return asyncio.run(main())


def test_status_says_thomas_listens_himself_with_credit_even_when_voice_studio_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient) -> dict:
        return await (await client.get("/api/voice/status")).json()

    body = _app_with_ears(tmp_path, monkeypatch, scenario)

    assert body["studio"]["running"] is False
    assert body["live"] == {"model": voice_ears.LABEL, "why": "", "by": "thomas", "credit": voice_ears.CREDIT}
    assert "CC-BY-4.0" in body["live"]["credit"]


def test_the_live_line_hears_through_thomas_with_no_voice_studio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient) -> list[dict]:
        got: list[dict] = []
        async with client.ws_connect("/api/voice/live") as socket:
            got.append(await socket.receive_json(timeout=10))
            for frame in _frames(_quiet(0.5) + _tone(1.5) + _quiet(1.0)):
                await socket.send_bytes(frame)
            while not got or got[-1].get("type") != "final":
                got.append(await socket.receive_json(timeout=10))
            await socket.send_json({"type": "input_audio.end"})
        return got

    got = _app_with_ears(tmp_path, monkeypatch, scenario)

    assert got[0] == {"type": "live.started", "model": voice_ears.LABEL}
    assert any(event["type"] == "partial" for event in got[1:-1])
    assert got[-1]["type"] == "final" and got[-1]["final_kind"] == "utterance"
    assert got[-1]["text"].endswith("seconds")


def _installed_model() -> Path | None:
    for candidate in [
        os.environ.get("THOMAS_TEST_PARAKEET_DIR", ""),
        *glob.glob(r"F:\VoiceStudio\models\models--csukuangfj--sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8\snapshots\*"),
    ]:
        if candidate and not voice_ears.why_not(Path(candidate)):
            return Path(candidate)
    return None


@pytest.mark.skipif(_installed_model() is None, reason="the Parakeet v3 model is not on this computer")
def test_the_real_model_writes_down_a_real_recording_cut_at_its_pause() -> None:
    folder = _installed_model()
    with wave.open(str(folder / "test_wavs" / "en.wav")) as recording:
        speech = recording.readframes(recording.getnframes())
    loaded = voice_ears.recognizer(folder)
    cut = voice_ears.Segmenter()
    finals = []
    for frame in _frames(_quiet(0.5) + speech + _quiet(1.0)):
        finals += [voice_ears.transcribe(loaded, s) for kind, s in cut.feed(frame) if kind == "final"]

    assert len(finals) == 1
    assert "what you can do for your country" in finals[0].lower()
