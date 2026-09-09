"""Every document applies the user overlay before it paints, and a write reaches every open one.

Driven against the REAL app on a free port (never your live :8899) with
THOMAS_OVERLAY_DIR at a scratch directory seeded through the overlay route, in
headless Chromium. Computed styles only: a value read from the DOM of a hidden
surface proves nothing (the hidden-DOM trap), so the shell's inline palette and
the settings page's cascade are both asserted, never one alone.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

SIDEBAR_ANCHOR = {"exact": True, "fragile": False, "component": "aside", "label": "Chat sidebar", "policy": "move resize", "path": ""}
SEED = [
    {"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#2ecc71"},
    {"op": "set", "kind": "token", "address": "token:*:--c-text", "value": "#010203"},
    {"op": "set", "kind": "token", "address": "token:dark:--c-text", "value": "#040506"},
    {"op": "set", "kind": "theme", "address": "theme:ember",
     "value": {"label": "Ember", "tagline": "Warm dark", "derives_from": "nebula", "color_scheme": "dark",
               "swatches": ["#140a06", "#2a1408", "#ff7a1a"], "world": "nebula", "meta": {"menuBg": "#1c0f08"}}},
    {"op": "set", "kind": "token", "address": "token:ember:--c-bg", "value": "#140a06"},
    {"op": "set", "kind": "identity", "address": "identity:name", "value": "Otto"},
    {"op": "set", "kind": "element", "address": "element:chat:desktop:chat.sidebar",
     "value": {"x": 0, "y": 0, "width": 320, "style": {"backgroundColor": "#101a2e"}}, "anchor": SIDEBAR_ANCHOR},
    {"op": "set", "kind": "element", "address": "element:chat:desktop:nope.id",
     "value": {"x": 0, "y": 0, "style": {"backgroundColor": "#000000"}}, "anchor": dict(SIDEBAR_ANCHOR, label="Nothing")},
]
SHELL_VAR = "(name) => getComputedStyle(document.getElementById('tc-shell')).getPropertyValue(name).trim()"
ROOT_VAR = "(name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()"
SIDEBAR_BG = "() => getComputedStyle(document.querySelector('[data-ui-id=\"chat.sidebar\"]')).backgroundColor"
SIDEBAR_W = "() => document.querySelector('[data-ui-id=\"chat.sidebar\"]').style.width"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class App:
    def __init__(self, root: Path) -> None:
        self.root, self.port = root, _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.overlay = root / "overlay"
        self.proc: subprocess.Popen[bytes] | None = None
        self.log = None

    def start(self) -> None:
        data = self.root / "data"
        data.mkdir(exist_ok=True)
        env = dict(os.environ, THOMAS_DATA_DIR=str(data), THOMAS_OVERLAY_DIR=str(self.overlay), PYTHONDONTWRITEBYTECODE="1")
        self.log = open(self.root / "server.log", "ab")
        self.proc = subprocess.Popen([sys.executable, "-m", "thomas.server", "--host", "127.0.0.1", "--port", str(self.port)],
                                     env=env, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(240):
            try:
                if self.get("/")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"the app did not come up on {self.base}; see {self.root / 'server.log'}")

    def get(self, path: str) -> tuple[int, str]:
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")

    def post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.base + path, method="POST", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def raw_post(self, body: bytes, *, chunked: bool = False) -> tuple[int, dict]:
        import http.client

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        payload = (body[i:i + 65536] for i in range(0, len(body), 65536)) if chunked else body
        connection.request("POST", "/api/ui/overlay/records", body=payload,
                           headers={"Content-Type": "application/json"}, encode_chunked=chunked)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.log:
            self.log.close()
        self.proc = None
        self.log = None


@pytest.fixture(scope="module")
def app(tmp_path_factory: pytest.TempPathFactory):
    instance = App(tmp_path_factory.mktemp("overlay_app"))
    instance.start()
    try:
        assert not instance.overlay.exists(), "serving the first page must not create the overlay"
        seeded = instance.post("/api/ui/overlay/records", {"overlay_id": None, "action": {"actor": "test", "instruction": "seed", "targets": []}, "records": SEED})
        assert seeded["ok"] and seeded["created"] and seeded["rejected"] == [], seeded
        yield instance
    finally:
        instance.stop()


@pytest.fixture(scope="module")
def context(app):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        yield ctx
        browser.close()


def _home(context, app):
    page = context.new_page()
    page.goto(app.base + "/")
    page.wait_for_function("() => window.ThomasOverlay && window.ThomasOverlay.view.present && document.getElementById('tc-shell')", timeout=20000)
    return page


def test_the_home_shell_and_the_settings_root_both_carry_the_token(context, app) -> None:
    page = _home(context, app)
    assert page.evaluate(SHELL_VAR, "--c-accent") == "#2ecc71", "the shell's inline palette (chat.html paints THEMES) carries the token"
    settings = context.new_page()
    settings.goto(app.base + "/settings?embed=1")
    settings.wait_for_selector("#theme")
    assert settings.evaluate(ROOT_VAR, "--c-accent") == "#2ecc71", "the settings page gets it through the cascade"
    assert settings.evaluate("() => Array.from(document.getElementById('theme').options).some((o) => o.value === 'ember' && o.textContent === 'Ember')")
    settings.close()
    page.close()


def test_a_wildcard_token_paints_stock_and_overlay_themes_while_specific_wins(context, app) -> None:
    page = _home(context, app)
    for theme, expected in (("light", "#010203"), ("dark", "#040506"), ("sandstone", "#010203"), ("ember", "#010203")):
        page.evaluate("theme => localStorage.setItem('thomas_chat_theme', theme)", theme)
        page.reload()
        page.wait_for_function("theme => document.getElementById('tc-shell')?.dataset.theme === theme", arg=theme, timeout=20000)
        assert page.evaluate(SHELL_VAR, "--c-text") == expected
    page.evaluate("() => localStorage.setItem('thomas_chat_theme', 'nebula')")
    page.close()


def test_the_identity_is_renamed_on_its_surfaces_and_nowhere_else(context, app) -> None:
    page = _home(context, app)
    brand = page.evaluate("() => Array.from(document.querySelectorAll('[data-ui-id=\"chat.sidebar\"] span')).map((s) => s.textContent.trim())")
    assert "Otto" in brand and "Thomas" not in brand
    assert "Otto" in page.evaluate("() => document.getElementById('tc-input').placeholder")
    assert "Otto" in page.title() and "Thomas" not in page.title()
    assert "Otto" in page.evaluate("() => document.getElementById('tc-welcome-sub').textContent")
    assert "Thomas Canvas" in page.content(), "prose that names the product stays stock"
    page.close()


def test_a_later_rename_and_a_cleared_identity_move_every_surface_deterministically(context, app) -> None:
    page = _home(context, app)
    brand = "() => Array.from(document.querySelectorAll('[data-ui-id=\"chat.sidebar\"] span')).map((s) => s.textContent.trim()).filter((t) => t)"
    assert "Otto" in page.evaluate(brand)
    page.evaluate("() => window.ThomasOverlay.adopt(Object.assign({}, window.ThomasOverlay.view, { identity: { name: 'Ada' } }))")
    assert "Ada" in page.evaluate(brand) and "Otto" not in page.evaluate(brand)
    assert "Ada" in page.title() and "Otto" not in page.title()
    assert "Ada" in page.evaluate("() => document.getElementById('tc-input').placeholder")
    assert "Ada" in page.evaluate("() => document.getElementById('tc-welcome-sub').textContent")
    page.evaluate("() => window.ThomasOverlay.adopt(Object.assign({}, window.ThomasOverlay.view, { identity: {} }))")
    assert "Thomas" in page.evaluate(brand) and "Ada" not in page.evaluate(brand)
    assert "Thomas" in page.title() and "Ada" not in page.title()
    assert "Thomas" in page.evaluate("() => document.getElementById('tc-input').placeholder")
    assert "Thomas" in page.evaluate("() => document.getElementById('tc-welcome-sub').textContent")
    page.evaluate("() => window.ThomasOverlay.adopt(Object.assign({}, window.ThomasOverlay.view, { identity: { name: 'Otto' } }))")
    assert "Otto" in page.evaluate(brand)
    page.close()


def test_the_element_layer_applies_without_a_local_copy_and_reports_its_orphans(context, app) -> None:
    page = _home(context, app)
    page.wait_for_function(f"() => ({SIDEBAR_BG})() === 'rgb(16, 26, 46)'", timeout=10000)
    assert page.evaluate(SIDEBAR_W) == "320px"
    saved = page.evaluate("() => { const b = JSON.parse(localStorage.getItem('thomas_ui_layout_v2') || '{}'); const w = (b.workspaces || {}).chat || {}; return Object.keys((w.desktop || {}).saved || {}); }")
    assert "chat.sidebar" not in saved, "the overlay's entry is not copied into the browser's own book"
    orphans = page.evaluate("() => window.ThomasUiLayout.orphans()")
    assert "nope.id" in orphans and "chat.sidebar" not in orphans
    assert page.evaluate("() => window.ThomasUiLayout.overlaidKeys()") == ["chat.sidebar", "nope.id"]
    page.close()


def test_an_overlay_theme_survives_a_reload_and_paints_its_own_tokens(context, app) -> None:
    page = _home(context, app)
    assert page.evaluate("() => window.ThomasChatThemes.THEMES.ember.name") == "Ember"
    assert page.evaluate("() => Object.keys(window.ThomasChatThemes.THEMES)") == ["nebula", "dark", "light", "aurora", "sandstone", "ember"]
    page.evaluate("() => localStorage.setItem('thomas_chat_theme', 'ember')")
    page.reload()
    page.wait_for_function("() => document.getElementById('tc-shell') && document.getElementById('tc-shell').dataset.theme === 'ember'", timeout=20000)
    assert page.evaluate(SHELL_VAR, "--c-bg") == "#140a06"
    assert page.evaluate(SHELL_VAR, "--c-accent") == "#2ecc71", "the parent's override flows into the derived theme"
    assert page.evaluate("() => document.documentElement.dataset.thomasTheme") == "ember"
    assert page.evaluate("() => document.documentElement.style.colorScheme") == "dark"
    page.evaluate("() => localStorage.setItem('thomas_chat_theme', 'nebula')")
    page.close()


def test_a_second_document_paints_the_overlay_first_and_adopts_a_later_write_without_reload(context, app) -> None:
    page = _home(context, app)
    page.click('.tc-mode-button[data-thomas-mode="code"]')
    page.wait_for_function("() => document.querySelectorAll('iframe.bt-doc.is-ready').length >= 1", timeout=30000)
    frame = next(f for f in page.frames if "embed=1" in f.url)
    frame.wait_for_function("() => window.ThomasOverlay && document.getElementById('tc-shell')", timeout=20000)
    assert frame.evaluate(SHELL_VAR, "--c-accent") == "#2ecc71", "a tab document carries the overlay at parse"
    frame.wait_for_function(f"() => ({SIDEBAR_BG})() === 'rgb(16, 26, 46)'", timeout=10000)
    before = page.evaluate("() => window.ThomasOverlay.view.rev")
    result = page.evaluate("() => window.ThomasOverlay.record({actor: 'test', instruction: 'redder', targets: []}, [{op: 'set', kind: 'token', address: 'token:nebula:--c-accent', value: '#ff0000'}])")
    assert result["ok"] and result["rev"] == before + 1, result
    assert page.evaluate(SHELL_VAR, "--c-accent") == "#ff0000", "the writer repaints itself"
    frame.wait_for_function(f"() => ({SHELL_VAR})('--c-accent') === '#ff0000'", timeout=10000)
    assert frame.evaluate("() => window.ThomasOverlay.view.rev") == before + 1, "the other document adopted the write over the channel"
    page.close()


def test_a_set_clear_set_clear_cycle_is_visible_every_time_and_a_fresh_tab_agrees(context, app) -> None:
    from thomas.server.overlay import stock_tokens

    page = _home(context, app)
    stock_accent = stock_tokens.load_stock()["nebula"]["--c-accent"]
    page.evaluate("() => localStorage.setItem('thomas_chat_theme', 'nebula')")
    page.reload()
    page.wait_for_function("() => window.ThomasOverlay && document.getElementById('tc-shell')", timeout=20000)
    record = "(records) => window.ThomasOverlay.record({actor: 'test', instruction: 'cycle', targets: []}, records)"
    set_accent = [{"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#ff0000"}]
    clear_accent = [{"op": "clear", "kind": "token", "address": "token:nebula:--c-accent"}]
    for _ in range(2):
        assert page.evaluate(record, set_accent)["ok"]
        page.wait_for_function(f"() => ({SHELL_VAR})('--c-accent') === '#ff0000'", timeout=5000)
        assert page.evaluate(record, clear_accent)["ok"]
        page.wait_for_function(f"() => ({SHELL_VAR})('--c-accent') !== '#ff0000'", timeout=5000)
        assert page.evaluate("() => window.ThomasChatThemes.THEMES.nebula.vars['--c-accent']") != "#ff0000"
    # fonts chat.html sets inline come back too
    assert page.evaluate(record, [{"op": "set", "kind": "token", "address": "token:nebula:--font-mono", "value": "monospace"}])["ok"]
    page.wait_for_function(f"() => ({SHELL_VAR})('--font-mono') === 'monospace'", timeout=5000)
    assert page.evaluate(record, [{"op": "clear", "kind": "token", "address": "token:nebula:--font-mono"}])["ok"]
    page.wait_for_function(f"() => ({SHELL_VAR})('--font-mono') !== 'monospace'", timeout=5000)
    # a cleared theme leaves the known list and the document it was showing
    page.evaluate("() => localStorage.setItem('thomas_chat_theme', 'ember')")
    page.reload()
    page.wait_for_function("() => document.getElementById('tc-shell') && document.getElementById('tc-shell').dataset.theme === 'ember'", timeout=20000)
    cleared = page.evaluate(record, [
        {"op": "clear", "kind": "token", "address": "token:ember:--c-bg"},
        {"op": "clear", "kind": "theme", "address": "theme:ember"},
    ])
    assert cleared["ok"] and cleared["accepted"] == ["token:ember:--c-bg", "theme:ember"]
    page.wait_for_function("() => document.getElementById('tc-shell').dataset.theme === 'nebula'", timeout=5000)
    assert "ember" not in page.evaluate("() => Object.keys(window.ThomasChatThemes.THEMES)")
    assert "ember" not in page.evaluate("() => window.ThomasWorkspaceShell.knownThemes()")
    assert page.evaluate("() => localStorage.getItem('thomas_chat_theme')") == "nebula"
    fresh = context.new_page()
    fresh.goto(app.base + "/")
    fresh.wait_for_function("() => window.ThomasOverlay && document.getElementById('tc-shell')", timeout=20000)
    assert fresh.evaluate("() => Object.keys(window.ThomasChatThemes.THEMES)") == ["nebula", "dark", "light", "aurora", "sandstone"]
    assert fresh.evaluate(SHELL_VAR, "--c-accent") == page.evaluate(SHELL_VAR, "--c-accent") == stock_accent.strip()
    fresh.close()
    page.close()


def test_the_base_wrote_nothing_beyond_the_four_files(app) -> None:
    assert sorted(p.name for p in app.overlay.iterdir()) == [".gitattributes", ".gitignore", "README.md", "manifest.json"]
    status, body = app.get("/api/ui/overlay")
    assert status == 200 and json.loads(body)["view"]["rev"] >= len(SEED) + 1
