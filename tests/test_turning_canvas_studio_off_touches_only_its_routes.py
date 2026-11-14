"""The canvas_studio row, off: its five routes answer 404, a server started that way never loads them, and the workspace
helpers that save a Canvas layout for an agent go on working.

The routes save a layout to ``.thomas/canvas`` under the project Thomas runs from, load it, turn it into code, and ask a
model for a layout from a prompt or from a sketch. The Canvas page in the sidebar works out its code in the browser, so
off costs it only its save button, its AI Template button and its sketch import. The helpers share one folder with the
routes through ``thomas/server/canvas_studio_shared.py`` and not through the routes, which is what these tests hold.

Each sentence of the row's words was also checked once in a browser against a real server, with this row pressed off and
on. A test here cannot hold what a page paints.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, ROWS
from thomas.server import app_core
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = (
    "POST /api/canvas/spec",
    "GET /api/canvas/spec/missing",
    "POST /api/canvas/codegen",
    "POST /api/canvas/template",
    "POST /api/canvas/spec-from-sketch",
)
OWN_CODE = (
    "thomas.server.rows.canvas_studio",
    "thomas.server.routes.canvas_studio_routes",
    "thomas.server.routes.canvas_studio_specgen",
)
IMPORTING = r"import[^\n]*canvas_studio_routes|canvas_studio_routes import"
# aiohttp lists a HEAD beside each GET.
LISTED = {
    "POST /api/canvas/spec",
    "GET /api/canvas/spec/{id}",
    "HEAD /api/canvas/spec/{id}",
    "POST /api/canvas/codegen",
    "POST /api/canvas/template",
    "POST /api/canvas/spec-from-sketch",
}
# What each route says to an empty body on a store with nothing in it. The saved-layout read answers 404 itself for an id
# that is not there, so only the list of routes the row added (``live_on``) tells it from the row being off.
EMPTY_BODY = {
    "POST /api/canvas/spec": 400,
    "GET /api/canvas/spec/missing": 404,
    "POST /api/canvas/codegen": 400,
    "POST /api/canvas/template": 400,
    "POST /api/canvas/spec-from-sketch": 400,
}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("canvas-off")
    started, found = start_with_one_row_off("canvas_studio", list(ROUTES), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("canvas-remote")
    started, found = ask_as_a_remote_caller("canvas_studio", list(ROUTES), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder that counts as the project Thomas runs from, so a saved layout lands here and not in the checkout."""
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "canvas_studio"}
    assert seen["rows"]["canvas_studio"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES, 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_five_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == EMPTY_BODY


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES, 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES, 401)
    assert remote["with_token"] == EMPTY_BODY


def test_a_layout_saved_before_off_is_still_there_and_the_helpers_use_the_same_folder(
    project: Path, own_data_dir: Path, tmp_path: Path
) -> None:
    """The words tell you saved layouts stay and that Thomas's own helpers go on saving and reading them with this off."""
    from thomas.server.canvas_studio_shared import _read_spec, _write_spec

    spec = {"id": "home", "root": {"type": "frame", "children": []}}

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            saved = await client.post("/api/canvas/spec", json={"spec": spec})
            assert (saved.status, (await saved.json())["id"]) == (200, "home")
            assert (project / ".thomas" / "canvas" / "home.json").is_file()

            assert (await client.post("/api/plugins/thomas/canvas_studio/off")).status == 200
            assert (await client.get("/api/canvas/spec/home")).status == 404
            assert _read_spec(project, "home") == spec  # the helpers read it with the routes gone
            assert _write_spec(project, {"id": "from-agent", "root": {"type": "frame"}}) == "from-agent"

            assert (await client.post("/api/plugins/thomas/canvas_studio/on")).status == 200
            loaded = await client.get("/api/canvas/spec/from-agent")  # and the routes read what the helper wrote
            assert (loaded.status, (await loaded.json())["spec"]["root"]) == (200, {"type": "frame"})
            assert (await client.get("/api/canvas/spec/home")).status == 200

    asyncio.run(scenario())


def test_the_routes_work_on_a_real_body_through_the_live_table(
    project: Path, own_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codegen is deterministic. The two model routes are asked with a stand-in model, because a real one is not here."""
    from thomas.server.routes import canvas_studio_routes as routes

    class Model:
        def __init__(self, text: str) -> None:
            self.text = text

        async def chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
            return {"text": self.text}

    layout = {"root": {"type": "frame", "children": [{"type": "text", "text": "hi"}]}}
    spec = {"name": "demo", **layout}
    image = {"image_data_url": "data:image/png;base64,AA"}

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            code = await (await client.post("/api/canvas/codegen", json={"spec": spec})).json()
            assert code["ok"] is True and "App.jsx" in code["files"] and "tokens.css" in code["files"]

            monkeypatch.setattr(routes, "_build_llm", lambda root, profile: Model(json.dumps(layout)))
            made = await client.post("/api/canvas/template", json={"prompt": "a page", "profile": "local"})
            assert (made.status, (await made.json())["spec"]) == (200, layout)
            sketched = await client.post("/api/canvas/spec-from-sketch", json=image)
            assert (sketched.status, (await sketched.json())["spec"]) == (200, layout)
            plain = await client.post("/api/canvas/spec-from-sketch", json={"image_data_url": "https://x/y.png"})
            assert plain.status == 400

            monkeypatch.setattr(routes, "_build_llm", lambda root, profile: Model("not json"))
            assert (await client.post("/api/canvas/template", json={"prompt": "a page"})).status == 502
            monkeypatch.setattr(routes, "_build_llm", lambda root, profile: None)
            assert (await client.post("/api/canvas/template", json={"prompt": "a page"})).status == 503

    asyncio.run(scenario())


def test_only_the_row_imports_the_routes_module() -> None:
    """Anything else that imports it loads it on a server started with this row off, and off could not unload it."""
    package = ROOT / "thomas"
    naming = sorted(
        path.relative_to(package).as_posix()
        for path in package.rglob("*.py")
        if re.search(IMPORTING, path.read_text(encoding="utf-8"))
    )
    assert naming == ["server/rows/canvas_studio.py"]


def test_the_canvas_page_asks_these_routes_only_when_you_press_a_button() -> None:
    """The row's words tell you nothing asks again on its own. If the page starts asking on load or on a timer, this
    fails and those words have to change."""
    web = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
    script = (web / "048_ui_studio_canvas.js").read_text(encoding="utf-8")
    asking = [line for line in script.splitlines() if "postJson(api.apiBase" in line]
    assert len(asking) == 4, asking
    for name in ("function generateCode()", "function saveToServer()", "function aiTemplate()", "function handleDrop"):
        assert name in script
    assert "setInterval(function () { postJson" not in script


def test_the_row_has_words_for_stop_now() -> None:
    row = next(row for row in ROWS if row.id == "canvas_studio")
    assert row.config["words"]["stop_now"]


@pytest.mark.parametrize(
    "changed", ["thomas/server/rows/canvas_studio.py", "thomas/server/routes/canvas_studio_routes.py"]
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_canvas_studio_off_touches_only_its_routes.py" in chosen
    assert "tests/test_canvas_studio_routes.py" in chosen
