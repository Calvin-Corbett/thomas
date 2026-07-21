"""Tests for the Thomas Canvas API handlers.

Mirrors the evolve-loop route test idiom: build the handlers directly with an
injected ``root_resolver`` pointing at a temp ``.thomas/`` and a no-op auth
guard, then exercise the in-process logic. Only the MVP (no-LLM) routes are
covered here — spec persistence round-trips and deterministic codegen. The
wave-2 LLM routes shell out to a model and are out of scope for unit tests.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from aiohttp import web

from thomas.server.routes.canvas_studio_routes import (
    build_canvas_studio_handlers,
    spec_to_react,
    spec_to_tokens_css,
)


class _FakeRequest:
    def __init__(self, *, query=None, match_info=None, json_body=None):
        self.query = query or {}
        self.match_info = match_info or {}
        self._json = json_body if json_body is not None else {}

    async def json(self):
        return self._json


def _no_auth(_request):
    return None


def _handlers(app, root: Path):
    return build_canvas_studio_handlers(app, require_api_access=_no_auth, root_resolver=lambda: root)


def _body(resp: web.Response) -> dict:
    return json.loads(resp.body)


def _sample_spec(name: str = "Test Layout") -> dict:
    """A minimal-but-realistic UiStudioSpec: a flex root with a card holding a
    title (text) and a button, plus one absolute-positioned shape."""
    return {
        "version": 1,
        "id": "spec_" + uuid.uuid4().hex,
        "name": name,
        "canvas": {"width": 1280, "height": 800, "background": "#0f1723"},
        "grid": {"size": 8, "snap": True},
        "tokens": {
            "color": {"primary": "#2563eb", "surface": "#1f232c", "text": "#ececf1"},
            "space": {"sm": 8, "md": 16},
            "radius": {"sm": 4, "md": 8},
            "font": {"sans": "Manrope, system-ui, sans-serif"},
        },
        "root": {
            "id": "node_root",
            "type": "container",
            "name": "Root",
            "rect": {"x": 0, "y": 0, "w": 1280, "h": 800},
            "layout": {
                "mode": "flex",
                "direction": "col",
                "gap": 16,
                "padding": 16,
                "align": "start",
                "justify": "start",
                "sizing": "fixed",
            },
            "absolute": False,
            "style": {},
            "content": {"text": ""},
            "owner": "user",
            "children": [
                {
                    "id": "node_card",
                    "type": "card",
                    "name": "Card",
                    "rect": {"x": 16, "y": 16, "w": 300, "h": 160},
                    "layout": {"mode": "flex", "direction": "col", "gap": 8, "padding": 8},
                    "absolute": False,
                    "style": {"bg": "color.surface", "border": "#3a3f4b", "radius": 8},
                    "content": {"text": ""},
                    "owner": "user",
                    "children": [
                        {
                            "id": "node_title",
                            "type": "text",
                            "name": "Title",
                            "rect": {"x": 24, "y": 24, "w": 200, "h": 24},
                            "style": {"color": "color.text"},
                            "content": {"text": "Hello & <World>"},
                            "children": [],
                        },
                        {
                            "id": "node_btn",
                            "type": "button",
                            "name": "Go",
                            "rect": {"x": 24, "y": 110, "w": 120, "h": 36},
                            "style": {"bg": "#2563eb", "color": "#ffffff", "radius": 6, "fontWeight": 600},
                            "content": {"text": "Go"},
                            "children": [],
                        },
                    ],
                },
                {
                    "id": "node_badge",
                    "type": "shape",
                    "name": "Badge",
                    "rect": {"x": 340, "y": 16, "w": 48, "h": 48},
                    "absolute": True,
                    "style": {"bg": "#47d7ac", "radius": 24},
                    "content": {},
                    "children": [],
                },
            ],
        },
    }


class TestCanvasStudioPersistence(unittest.IsolatedAsyncioTestCase):
    async def test_current_canvas_api_surface_remains_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            handlers = _handlers(web.Application(), Path(tmp))
            assert set(handlers) == {
                "save_spec",
                "load_spec",
                "codegen",
                "template",
                "spec_from_sketch",
            }

    async def test_spec_round_trips_through_thomas_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = web.Application()
            handlers = _handlers(app, root)
            spec = _sample_spec()
            save_resp = await handlers["save_spec"](_FakeRequest(json_body={"spec": spec}))
            saved = _body(save_resp)
            assert saved["ok"] is True
            spec_id = saved["id"]
            # written atomically to <root>/.thomas/canvas/<id>.json
            on_disk = root / ".thomas" / "canvas" / f"{spec_id}.json"
            assert on_disk.exists()
            disk_spec = json.loads(on_disk.read_text(encoding="utf-8"))
            assert disk_spec["name"] == "Test Layout"
            assert disk_spec["root"]["children"][0]["children"][0]["content"]["text"] == "Hello & <World>"

    async def test_get_returns_saved_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = web.Application()
            handlers = _handlers(app, root)
            spec = _sample_spec("Roundtrip")
            saved = _body(await handlers["save_spec"](_FakeRequest(json_body={"spec": spec})))
            spec_id = saved["id"]
            load_resp = await handlers["load_spec"](_FakeRequest(match_info={"id": spec_id}))
            loaded = _body(load_resp)
            assert loaded["ok"] is True
            assert loaded["spec"]["name"] == "Roundtrip"
            assert loaded["spec"]["id"] == spec_id

    async def test_get_unknown_spec_is_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = web.Application()
            handlers = _handlers(app, Path(tmp))
            resp = await handlers["load_spec"](_FakeRequest(match_info={"id": "spec_doesnotexist"}))
            assert resp.status == 404
            assert _body(resp)["ok"] is False

    async def test_save_rejects_spec_without_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = web.Application()
            handlers = _handlers(app, Path(tmp))
            resp = await handlers["save_spec"](_FakeRequest(json_body={"spec": {"name": "no root"}}))
            assert resp.status == 400
            assert _body(resp)["ok"] is False

    async def test_bare_spec_body_without_wrapper_is_accepted(self):
        # Client may POST the spec directly OR wrapped in {"spec": ...}.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = web.Application()
            handlers = _handlers(app, root)
            spec = _sample_spec("Bare")
            resp = await handlers["save_spec"](_FakeRequest(json_body=spec))
            saved = _body(resp)
            assert saved["ok"] is True
            assert (root / ".thomas" / "canvas" / f"{saved['id']}.json").exists()


class TestCanvasStudioCodegen(unittest.IsolatedAsyncioTestCase):
    async def test_codegen_returns_react_and_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = web.Application()
            handlers = _handlers(app, Path(tmp))
            resp = await handlers["codegen"](_FakeRequest(json_body={"spec": _sample_spec()}))
            payload = _body(resp)
            assert payload["ok"] is True
            react = payload["files"]["App.jsx"]
            tokens = payload["files"]["tokens.css"]
            # flow node -> flex Tailwind classes
            assert "flex flex-col gap-4" in react
            # absolute node -> inset utility + a TODO comment
            assert "left-[340px]" in react and "TODO: absolute" in react
            # token ref resolves to a CSS var, not a hardcoded hex
            assert "var(--color-surface)" in react
            # HTML/JSX text is escaped
            assert "Hello &amp; &lt;World&gt;" in react
            # tokens.css emits the :root custom properties
            assert ":root" in tokens and "--color-primary: #2563eb" in tokens

    async def test_codegen_rejects_missing_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = web.Application()
            handlers = _handlers(app, Path(tmp))
            resp = await handlers["codegen"](_FakeRequest(json_body={"spec": {}}))
            assert resp.status == 400

    def test_codegen_pure_functions_are_deterministic(self):
        spec = _sample_spec()
        assert spec_to_react(spec) == spec_to_react(spec)
        assert spec_to_tokens_css(spec) == spec_to_tokens_css(spec)


if __name__ == "__main__":
    unittest.main()
