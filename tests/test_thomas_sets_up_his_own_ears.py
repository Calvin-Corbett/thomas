"""Setting up Thomas's own ears for someone who has just downloaded him: one click, and he does the rest.

You asked for the product, not this computer: "this is a product. That other users need to use. So how are they going
to use it? When they download Thomas." Then: "make it as easy as possible. And do all the work as possible we can", with
a list that can grow ("make it able to expand to different ones") and a default. The model's files are never in the
repository; voice_ears_setup downloads them from their makers (voice_ears_models lists each with its size and SHA-256),
checks every one, and installs the speech engine first when it is missing. These hold that to what it does, with a
stand-in for the internet, and the routes the page uses (GET and POST /api/voice/setup, and ``setup`` in the status).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import time
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture
from thomas.server import app_core, voice_ears, voice_ears_models, voice_ears_setup, voice_settings

PIECES = {"enc.onnx": b"encoder" * 400_000, "dec.onnx": b"decoder" * 1000, "tokens.txt": b"a 0\nb 1\n"}
SOURCE = "https://models.example/pinned/"


def _entry(pieces: dict[str, bytes] = PIECES, model_id: str = "tiny-test") -> dict[str, Any]:
    return {
        "id": model_id,
        "label": "Tiny, on this computer",
        "name": "Tiny Test Model",
        "about": "A model made of a few bytes.",
        "licence": "MIT",
        "credit": "Tiny Test Model (MIT)",
        "source": SOURCE,
        "kind": "transducer",
        "roles": {"encoder": "enc.onnx", "decoder": "dec.onnx", "joiner": "enc.onnx", "tokens": "tokens.txt"},
        "files": {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in pieces.items()},
    }


class _Internet:
    """Answers each file's address with what is published there, and counts what was asked for."""

    def __init__(self, published: dict[str, bytes]) -> None:
        self.published = published
        self.asked: list[str] = []

    def __call__(self, request: Any, timeout: float) -> io.BytesIO:
        url = request.full_url
        self.asked.append(url)
        assert request.get_header("User-agent") == "Thomas"
        return io.BytesIO(self.published[url.removeprefix(SOURCE)])


def _finish(model_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    while (found := voice_ears_setup.progress(model_id))["state"] == "working":
        assert time.monotonic() < deadline, found
        time.sleep(0.02)
    return found


@pytest.fixture(autouse=True)
def _tiny_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real list stays as it is for the tests that read it; these use a tiny model and a clean progress table."""
    monkeypatch.setattr(voice_ears_models, "MODELS", (*voice_ears_models.MODELS, _entry()))
    monkeypatch.setattr(voice_ears_setup, "_progress", {})
    monkeypatch.setattr(voice_ears_setup, "engine_ready", lambda: True)


def test_every_listed_model_says_where_it_comes_from_its_licence_and_how_to_check_each_file() -> None:
    assert voice_ears_models.get()["id"] == voice_ears_models.DEFAULT == voice_ears_models.get("default")["id"]
    for entry in voice_ears_models.MODELS[:-1]:  # the real list, without the tiny one added above
        assert re.search(r"/resolve/[0-9a-f]{40}/$", entry["source"]), "the files must be pinned to one revision"
        assert entry["licence"] and entry["credit"] and entry["name"] and entry["about"] and entry["label"]
        assert set(entry["roles"].values()) <= set(entry["files"])
        for size, digest in entry["files"].values():
            assert size > 0 and re.fullmatch(r"[0-9a-f]{64}", digest)
    assert voice_ears_models.size(voice_ears_models.get()) > 600_000_000  # what the window says it downloads
    with pytest.raises(ValueError, match="no listening model called nope"):
        voice_ears_models.get("nope")


def test_setting_up_downloads_each_file_from_its_makers_checks_it_and_puts_it_in_place(tmp_path: Path) -> None:
    internet = _Internet(PIECES)
    started = voice_ears_setup.start("tiny-test", tmp_path / "tiny-test", opener=internet)
    assert started["state"] == "working" and started["total"] == sum(len(d) for d in PIECES.values())

    found = _finish("tiny-test")

    assert found["state"] == "ready", found
    assert found["done"] == found["total"]
    assert sorted(internet.asked) == sorted(SOURCE + name for name in PIECES)
    for name, data in PIECES.items():
        assert (tmp_path / "tiny-test" / name).read_bytes() == data
    assert list((tmp_path / "tiny-test").glob("*.part")) == []
    assert voice_ears.why_not(tmp_path / "tiny-test", "tiny-test") == ""


def test_a_file_that_does_not_match_its_checksum_is_thrown_away_and_the_set_up_says_so(tmp_path: Path) -> None:
    changed = dict(PIECES, **{"dec.onnx": b"Decoder" * 1000})  # same size, other bytes
    voice_ears_setup.start("tiny-test", tmp_path / "tiny-test", opener=_Internet(changed))

    found = _finish("tiny-test")

    assert found["state"] == "failed"
    assert "dec.onnx did not download whole and unchanged" in found["error"]
    assert not (tmp_path / "tiny-test" / "dec.onnx").exists()
    assert list((tmp_path / "tiny-test").glob("*.part")) == []


def test_files_already_in_place_are_not_downloaded_again(tmp_path: Path) -> None:
    folder = tmp_path / "tiny-test"
    folder.mkdir()
    (folder / "enc.onnx").write_bytes(PIECES["enc.onnx"])
    internet = _Internet(PIECES)
    voice_ears_setup.start("tiny-test", folder, opener=internet)

    assert _finish("tiny-test")["state"] == "ready"
    assert SOURCE + "enc.onnx" not in internet.asked and len(internet.asked) == 2


def test_a_missing_speech_engine_is_installed_first_and_a_failed_install_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    there = {"engine": False}
    monkeypatch.setattr(voice_ears_setup, "engine_ready", lambda: there["engine"])

    def install() -> None:
        there["engine"] = True

    voice_ears_setup.start("tiny-test", tmp_path / "a", opener=_Internet(PIECES), install=install)
    assert _finish("tiny-test")["state"] == "ready" and there["engine"]

    there["engine"] = False
    monkeypatch.setattr(voice_ears_setup, "_progress", {})

    def refused() -> None:
        raise OSError("Thomas could not install his speech engine: no permission")

    voice_ears_setup.start("tiny-test", tmp_path / "b", opener=_Internet(PIECES), install=refused)
    found = _finish("tiny-test")
    assert found["state"] == "failed" and "no permission" in found["error"]
    assert not (tmp_path / "b").exists()  # nothing was downloaded without the engine to run it


def test_the_engine_install_is_the_pinned_sherpa_onnx_into_thomas_s_own_python_with_no_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[tuple[list[str], dict[str, Any]]] = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(voice_ears_setup.subprocess, "run", lambda command, **how: ran.append((command, how)) or Done())
    voice_ears_setup.install_engine()

    command, how = ran[0]
    assert command == [voice_ears_setup.sys.executable, "-m", "pip", "install", "--quiet", voice_ears_models.ENGINE]
    assert voice_ears_models.ENGINE == "sherpa-onnx==1.13.6"
    assert how["creationflags"] == voice_ears_setup._NO_WINDOW and how["capture_output"] is True


def test_the_listening_model_is_a_saved_choice_with_a_default(tmp_path: Path) -> None:
    path = tmp_path / "voice.json"
    assert voice_settings.load(path)["ears"] == "default"
    assert voice_settings.update(path, {"ears": "tiny-test"})["ears"] == "tiny-test"
    with pytest.raises(ValueError, match="no listening model called"):
        voice_settings.update(path, {"ears": "made-up"})


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario) -> Any:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(voice_ears, "INSTALL_DIR", tmp_path / "no-install" / voice_ears.MODEL_NAME)
    config = plugin_view_fixture.config_in(tmp_path)

    async def main() -> Any:
        async with TestClient(TestServer(app_core.create_app(config))) as client:
            assert (await client.put("/api/voice/settings", json={"studio_url": "http://127.0.0.1:9"})).status == 200
            return await scenario(client, Path(config.memory.root_path) / ".thomas" / "voice.json")

    return asyncio.run(main())


def test_status_says_what_setting_up_would_download_until_thomas_can_listen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(client: TestClient, settings: Path) -> tuple[dict, dict, dict]:
        before = await (await client.get("/api/voice/status")).json()
        asked = await (await client.get("/api/voice/setup")).json()
        folder = voice_ears.model_dir(settings)
        folder.mkdir(parents=True)
        for name in voice_ears.FILES:
            (folder / name).write_bytes(b"x")
        after = await (await client.get("/api/voice/status")).json()
        return before, asked, after

    before, asked, after = _app(tmp_path, monkeypatch, scenario)

    setup = before["setup"]
    assert setup["model"] == voice_ears_models.DEFAULT and setup["licence"] == "CC-BY-4.0"
    assert setup["bytes"] == voice_ears_models.size(voice_ears_models.get()) and setup["engine"] is True
    assert setup["progress"]["state"] == "idle"
    assert asked == {"ok": True, "setup": setup}
    assert before["live"]["model"] is None
    assert after["setup"] is None and after["live"]["by"] == "thomas"


def test_set_up_now_starts_the_named_model_into_the_data_folder_and_refuses_one_not_named_or_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[tuple[str, Path]] = []

    def start(model_id: str, folder: Path, **_how: Any) -> dict:
        started.append((model_id, folder))
        voice_ears_setup._progress[model_id] = {"state": "working", "done": 1, "total": 9, "step": "model", "error": ""}
        return voice_ears_setup.progress(model_id)

    monkeypatch.setattr(voice_ears_setup, "start", start)

    async def scenario(client: TestClient, settings: Path) -> tuple[dict, dict, int, int, Path]:
        unnamed = await client.post("/api/voice/setup")
        default = await (await client.post("/api/voice/setup", json={"model": voice_ears_models.DEFAULT})).json()
        chosen = await (await client.post("/api/voice/setup", json={"model": "tiny-test"})).json()
        refused = await client.post("/api/voice/setup", json={"model": "made-up"})
        return default, chosen, refused.status, unnamed.status, settings

    default, chosen, refused, unnamed, settings = _app(tmp_path, monkeypatch, scenario)
    assert unnamed == 400  # an empty request starts nothing

    assert started == [
        (voice_ears_models.DEFAULT, voice_ears.model_dir(settings)),
        ("tiny-test", voice_ears.model_dir(settings, "tiny-test")),
    ]
    assert default["setup"]["progress"]["state"] == "working"
    assert chosen["setup"]["model"] == "tiny-test"
    assert voice_settings.load(settings)["ears"] == "tiny-test"  # setting one up makes it the one Thomas listens with
    assert refused == 400
