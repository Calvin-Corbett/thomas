"""Every served page carries the overlay hook, and serving pages never creates the overlay.

The four page handlers in app_middleware_helpers (/, /classic, /settings,
/companion) and mission_support's versioned page (/mission) all splice the
overlay's view script and runtime tag before </head>; the stylesheet appears
only when an overlay exists. Requesting every page with the overlay absent
must leave it absent: the base never writes it. The index handler keeps
exactly one web_dir page name so the deep-links test's rule still holds.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from aiohttp.test_utils import make_mocked_request

from thomas import __version__ as THOMAS_VERSION
from thomas.server import app_middleware_helpers as helpers
from thomas.server.overlay import manifest as m
from thomas.server.overlay import render, stock_tokens
from thomas.server.routes import mission_support

PAGES = ("chat.html", "index.html", "settings.html", "companion.html")
STAMP = "stampstampst"
TOKEN = {"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#2ecc71"}
ACTION = {"actor": "test", "instruction": "inject", "targets": []}
BASE = {"thomas_version": THOMAS_VERSION, "git": None, "web_build": None, "tokens_sha1": "0" * 40}


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "web"
    directory.mkdir()
    for name in PAGES:
        directory.joinpath(name).write_text(
            f"<!doctype html><html><head><title>{name}</title></head><body>__THOMAS_WEB_BUILD__ __THOMAS_VERSION__</body></html>",
            encoding="utf-8",
        )
    return directory


@pytest.fixture
def overlay_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "overlay"
    monkeypatch.setenv("THOMAS_OVERLAY_DIR", str(directory))
    render.invalidate()
    return directory


def _serve_all(web_dir: Path) -> dict[str, str]:
    handlers = helpers.build_page_handlers(web_dir, lambda *names: STAMP)

    async def go() -> dict[str, str]:
        out = {}
        for name, handler in handlers.items():
            response = await handler(make_mocked_request("GET", "/"))
            out[name] = response.text
        return out

    return asyncio.run(go())


def test_every_page_carries_the_view_and_the_runtime_and_the_overlay_stays_absent(web_dir: Path, overlay_dir: Path) -> None:
    pages = _serve_all(web_dir)
    assert set(pages) >= {"index", "classic", "settings", "companion"}
    for name, html in pages.items():
        head = html.split("</head>", 1)[0]
        assert 'id="thomas-overlay-view"' in head and '"present":false' in head, name
        assert f'src="/static/js/overlay_runtime.js?v={STAMP}" defer' in head, name
        assert 'id="thomas-overlay-css"' not in head, name
        assert "__THOMAS_WEB_BUILD__" not in html and "__THOMAS_VERSION__" not in html, name
    assert not overlay_dir.exists(), "serving every page must not create the overlay"


def test_an_existing_overlay_is_a_stylesheet_in_every_page(web_dir: Path, overlay_dir: Path) -> None:
    m.append([TOKEN], ACTION, BASE, path=overlay_dir / "manifest.json", stock=stock_tokens.load_stock())
    render.invalidate()
    for name, html in _serve_all(web_dir).items():
        head = html.split("</head>", 1)[0]
        assert ':root{--c-accent:#2ecc71;}' in head, name
        assert head.index('id="thomas-overlay-css"') < head.index('id="thomas-overlay-view"'), name
    assert sorted(p.name for p in overlay_dir.iterdir()) == [".gitattributes", ".gitignore", "README.md", "manifest.json"]


def test_the_mission_page_is_covered_with_its_own_stamp_token(tmp_path: Path, overlay_dir: Path) -> None:
    page = tmp_path / "mission.html"
    page.write_text("<html><head></head><body>__THOMAS_VERSION__</body></html>", encoding="utf-8")
    response = mission_support._serve_versioned_page(page)
    html = response.text
    assert 'id="thomas-overlay-view"' in html
    assert f'src="/static/js/overlay_runtime.js?v={THOMAS_VERSION}" defer' in html
    assert not overlay_dir.exists()


def test_a_broken_overlay_still_serves_stock_pages(web_dir: Path, overlay_dir: Path) -> None:
    overlay_dir.mkdir()
    (overlay_dir / "manifest.json").write_text("{broken", encoding="utf-8")
    render.invalidate()
    for name, html in _serve_all(web_dir).items():
        assert 'id="thomas-overlay-css"' not in html, name
        assert '"present":false' in html and "manifest.json" in html, name
    assert (overlay_dir / "manifest.json").read_text(encoding="utf-8") == "{broken"


def test_a_page_that_already_carries_the_hook_is_not_given_a_second_one(web_dir: Path, overlay_dir: Path) -> None:
    pages = _serve_all(web_dir)
    for name, html in pages.items():
        again = render.inject(html, "__THOMAS_WEB_BUILD__")
        assert again == html, name
        assert html.count('id="thomas-overlay-view"') == 1 and html.count("overlay_runtime.js") == 1, name


def test_the_index_handler_still_names_exactly_one_page_for_the_deep_links_rule() -> None:
    source = Path(helpers.__file__).read_text(encoding="utf-8")
    body = source.split("async def index(", 1)[1].split("async def ", 1)[0]
    assert set(re.findall(r'web_dir\s*/\s*"([^"]+\.html)"', body)) == {"chat.html"}
    assert body.count("inject_overlay(") == 1
