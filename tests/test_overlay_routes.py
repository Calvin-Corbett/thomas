"""The overlay's routes: reading never creates, one POST is the only writer, and failures say why.

Every scenario runs an aiohttp test client against a bare application with
only the overlay routes mounted and THOMAS_OVERLAY_DIR pointed at a scratch
directory, so what is asserted is the route contract and nothing else.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.overlay import render
from thomas.server.routes.ui_overlay_routes import setup_overlay_routes

ELEMENT = {
    "op": "set", "kind": "element", "address": "element:chat:desktop:chat.sidebar",
    "value": {"x": 0, "y": 0, "width": 320, "style": {"backgroundColor": "#101a2e"}},
    "anchor": {"exact": True, "fragile": False, "component": "aside", "label": "Chat sidebar", "policy": "move resize", "path": ""},
}
ACTION = {"actor": "redesign", "instruction": "make the sidebar darker", "targets": ["chat.sidebar"]}


def _app(guard=None) -> web.Application:
    app = web.Application()
    setup_overlay_routes(app, require_api_access=guard or (lambda request: None))
    return app


def run(scenario) -> None:
    asyncio.run(scenario())


@pytest.fixture
def overlay_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "overlay"
    monkeypatch.setenv("THOMAS_OVERLAY_DIR", str(directory))
    render.invalidate()
    return directory


def test_reading_an_absent_overlay_never_creates_it(overlay_dir: Path) -> None:
    async def scenario() -> None:
        async with TestClient(TestServer(_app())) as client:
            resp = await client.get("/api/ui/overlay")
            data = await resp.json()
            assert resp.status == 200 and data["ok"] and data["view"]["present"] is False and data["css"] == ""
            assert resp.headers["Cache-Control"] == "no-store"
            resp = await client.get("/api/ui/overlay/manifest")
            assert (await resp.json())["present"] is False
        assert not overlay_dir.exists()

    run(scenario)


def test_the_first_write_gives_birth_and_the_reply_says_what_landed(overlay_dir: Path) -> None:
    async def scenario() -> None:
        async with TestClient(TestServer(_app())) as client:
            resp = await client.post("/api/ui/overlay/records", json={"overlay_id": None, "action": ACTION, "records": [ELEMENT]})
            data = await resp.json()
            assert resp.status == 200, data
            assert data["created"] is True and data["rev"] == 1 and data["overlay_id"].startswith("ovl_")
            assert (overlay_dir / ".gitignore").read_text(encoding="utf-8") == "*.tmp\n"
            assert data["accepted"] == ["element:chat:desktop:chat.sidebar"] and data["rejected"] == []
            assert data["view"]["present"] is True and data["view"]["elements"]["chat"]["desktop"]["chat.sidebar"]["width"] == 320
            assert sorted(p.name for p in overlay_dir.iterdir()) == [".gitattributes", ".gitignore", "README.md", "manifest.json"]
            manifest = await (await client.get("/api/ui/overlay/manifest")).json()
            assert manifest["present"] is True and manifest["records"][0]["by"]["actor"] == "redesign"
            assert manifest["overlay"]["created_from"]["thomas_version"]

    run(scenario)


def test_a_foreign_overlay_id_is_a_409_and_changes_nothing(overlay_dir: Path) -> None:
    async def scenario() -> None:
        async with TestClient(TestServer(_app())) as client:
            first = await (await client.post("/api/ui/overlay/records", json={"overlay_id": None, "action": ACTION, "records": [ELEMENT]})).json()
            before = (overlay_dir / "manifest.json").read_bytes()
            resp = await client.post("/api/ui/overlay/records",
                                     json={"overlay_id": "ovl_000000000000", "action": ACTION, "records": [ELEMENT]})
            refused = await resp.json()
            assert resp.status == 409 and refused["code"] == "overlay_mismatch"
            assert first["overlay_id"] not in refused["error"], "a stale caller must not learn the current id from its refusal"
            assert (overlay_dir / "manifest.json").read_bytes() == before
            again = await (await client.post("/api/ui/overlay/records",
                                             json={"overlay_id": first["overlay_id"], "action": ACTION, "records": [ELEMENT]})).json()
            assert again["rev"] == 1 and again["created"] is False and again["accepted"] == []
            assert "already in effect" in again["rejected"][0]["reason"]

    run(scenario)


def test_a_protected_target_comes_back_rejected_with_its_reason(overlay_dir: Path) -> None:
    async def scenario() -> None:
        protected = dict(ELEMENT, address="element:chat:desktop:chat.shell",
                         anchor=dict(ELEMENT["anchor"], label="Chat shell", policy="root protected"))
        async with TestClient(TestServer(_app())) as client:
            resp = await client.post("/api/ui/overlay/records", json={"overlay_id": None, "action": ACTION, "records": [protected, ELEMENT]})
            data = await resp.json()
            assert resp.status == 200
            assert data["accepted"] == ["element:chat:desktop:chat.sidebar"]
            assert data["rejected"] == [{"address": "element:chat:desktop:chat.shell", "reason": "this region is protected"}]

    run(scenario)


def test_a_broken_manifest_is_a_named_500_and_its_bytes_are_untouched(overlay_dir: Path) -> None:
    async def scenario() -> None:
        async with TestClient(TestServer(_app())) as client:
            born = await (await client.post("/api/ui/overlay/records", json={"overlay_id": None, "action": ACTION, "records": [ELEMENT]})).json()
            (overlay_dir / "manifest.json").write_text("{broken", encoding="utf-8")
            render.invalidate()
            view = await (await client.get("/api/ui/overlay")).json()
            assert view["view"]["present"] is False and any("manifest.json" in n for n in view["view"]["notes"])
            resp = await client.post("/api/ui/overlay/records", json={"overlay_id": born["overlay_id"], "action": ACTION, "records": [ELEMENT]})
            assert resp.status == 500 and (await resp.json())["code"] == "overlay_broken" and "manifest.json" in (await resp.json())["error"]
            assert (overlay_dir / "manifest.json").read_text(encoding="utf-8") == "{broken"
            resp = await client.get("/api/ui/overlay/manifest")
            assert resp.status == 500

    run(scenario)


def test_the_overlay_id_is_a_strict_precondition_with_stable_codes(overlay_dir: Path) -> None:
    async def scenario() -> None:
        async with TestClient(TestServer(_app())) as client:
            resp = await client.post("/api/ui/overlay/records", json={"action": ACTION, "records": [ELEMENT]})
            assert resp.status == 400 and (await resp.json())["code"] == "bad_body", "the key must be present"
            resp = await client.post("/api/ui/overlay/records", json={"overlay_id": 7, "action": ACTION, "records": [ELEMENT]})
            assert resp.status == 400 and (await resp.json())["code"] == "bad_body"
            resp = await client.post("/api/ui/overlay/records", json={"overlay_id": "ovl_000000000000", "action": ACTION, "records": [ELEMENT]})
            assert resp.status == 409 and (await resp.json())["code"] == "overlay_mismatch"
            resp = await client.post("/api/ui/overlay/records", json={"overlay_id": "", "action": ACTION, "records": [ELEMENT]})
            assert resp.status == 409 and (await resp.json())["code"] == "overlay_mismatch", "only a literal null means absent"
            assert not overlay_dir.exists(), "a stale id before birth writes nothing"
            resp = await client.post("/api/ui/overlay/records", data=b'{"overlay_id": null, "overlay_id": null, "action": {}, "records": []}', headers={"Content-Type": "application/json"})
            assert resp.status == 400 and (await resp.json())["code"] == "bad_body", "duplicate keys are refused"
            born = await (await client.post("/api/ui/overlay/records", json={"overlay_id": None, "action": ACTION, "records": [ELEMENT]})).json()
            assert born["created"] is True
            resp = await client.post("/api/ui/overlay/records", json={"overlay_id": born["overlay_id"], "action": {"actor": "x" * 81, "targets": [1]}, "records": [ELEMENT]})
            body = await resp.json()
            assert resp.status == 400 and body["code"] == "bad_body" and "action:" in body["error"]
            assert (await (await client.get("/api/ui/overlay")).json())["view"]["rev"] == 1, "a bad envelope wrote nothing and the manifest still loads"
            resp = await client.post("/api/ui/overlay/records", json={"overlay_id": None, "action": ACTION, "records": [ELEMENT]})
            assert resp.status == 409 and (await resp.json())["code"] == "overlay_mismatch", "null once an overlay exists is stale"
            resp = await client.post("/api/ui/overlay/records", json={"overlay_id": born["overlay_id"], "action": ACTION, "records": [ELEMENT]})
            repeated = await resp.json()
            assert resp.status == 200 and repeated["rev"] == 1 and repeated["accepted"] == []
            assert "already in effect" in repeated["rejected"][0]["reason"]

    run(scenario)


def test_a_chunked_body_is_refused_by_the_bytes_actually_read(overlay_dir: Path) -> None:
    async def scenario() -> None:
        payload = json.dumps({"overlay_id": None, "action": ACTION, "records": [dict(ELEMENT, value={"x": 0, "y": 0, "style": {"color": "#000"}, "pad": "x" * 600_000})]}).encode("utf-8")

        async def chunks():
            for i in range(0, len(payload), 65536):
                yield payload[i:i + 65536]

        async with TestClient(TestServer(_app())) as client:
            resp = await client.post("/api/ui/overlay/records", data=chunks(), headers={"Content-Type": "application/json"})
            assert resp.status == 413 and (await resp.json())["code"] == "too_large"
        assert not overlay_dir.exists()

    run(scenario)


def test_a_malformed_body_is_a_400_and_the_guard_is_honoured(overlay_dir: Path) -> None:
    async def scenario() -> None:
        async with TestClient(TestServer(_app())) as client:
            resp = await client.post("/api/ui/overlay/records", data="not json", headers={"Content-Type": "application/json"})
            assert resp.status == 400
            resp = await client.post("/api/ui/overlay/records", json={"records": "nope"})
            assert resp.status == 400
            resp = await client.post("/api/ui/overlay/records", json={"overlay_id": None, "action": ACTION, "records": [ELEMENT] * 201})
            assert resp.status == 400
        assert not overlay_dir.exists()

        def deny(request: web.Request) -> web.Response:
            return web.json_response({"ok": False, "error": "no"}, status=401)

        async with TestClient(TestServer(_app(deny))) as client:
            assert (await client.get("/api/ui/overlay")).status == 401
            assert (await client.post("/api/ui/overlay/records", json={"overlay_id": None, "action": ACTION, "records": [ELEMENT]})).status == 401
        assert not overlay_dir.exists()

        async def raise_guard(request: web.Request) -> None:
            raise web.HTTPForbidden(text=json.dumps({"ok": False}))

        async with TestClient(TestServer(_app(raise_guard))) as client:
            assert (await client.get("/api/ui/overlay")).status == 403

    run(scenario)
