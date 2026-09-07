"""The first real Redesign on a free port uses a canned model reply and gives birth
to the overlay with the records of what changed, every paint path carries it,
a second document paints it first, the browser keeps no copy, the base wrote
nothing else, a protected region is refused before any model call, and a
minted entry whose element was replaced is reported instead of applied.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_every_document_applies_the_overlay import ROOT_VAR, SHELL_VAR, SIDEBAR_BG, SIDEBAR_W, App  # noqa: E402
from web_fixtures.thomas_chat_fixture import browser_ok  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

REPO = Path(__file__).resolve().parents[1]
INSTRUCTION = "make the sidebar darker and a bit wider, the accent green everywhere, and call yourself Otto"
CANNED = {
    "ok": True,
    "layout": [{"target_index": 0, "ui_id": "chat.sidebar", "style": {"backgroundColor": "#101a2e"}, "width": 320}],
    "dashboard": {"changed": 0, "applied": []},
    "theme": {"theme": "nebula", "tokens": {"--c-accent": "#2ecc71"}, "identity": {"name": "Otto"}, "rejected": []},
    "unsupported": [],
    "code_thread": None,
}


@pytest.fixture(scope="module")
def app(tmp_path_factory: pytest.TempPathFactory):
    instance = App(tmp_path_factory.mktemp("redesign_app"))
    instance.start()
    try:
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
    # Redesign lives in the composer's plus menu since 2026-09-06 (the owner: the
    # Redesign button next to Canvas is gone); the menu item is the shell's proof
    # that the feature is wired, and start() below is the same call it makes.
    page.wait_for_function(
        "() => window.ThomasRedesign && window.ThomasOverlay && document.querySelector('[data-create-action=\"redesign\"]')",
        timeout=20000,
    )
    return page


def test_one_apply_gives_birth_to_the_overlay_with_the_records_of_what_changed(context, app) -> None:
    assert not app.overlay.exists(), "before the first Redesign there is no overlay"
    page = _home(context, app)
    page.route(
        "**/api/ui/redesign",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(CANNED)),
    )
    # The tab shell hosts the Redesign button inside the profile menu (closed by
    # default); arming through the page's own API is the same start() it calls.
    page.evaluate("() => window.ThomasRedesign.start()")
    page.wait_for_function("() => window.ThomasRedesign.phase() === 'selecting'")
    page.evaluate("() => document.querySelector('[data-ui-id=\"chat.sidebar\"]').click()")
    page.wait_for_function("() => window.ThomasRedesign.selection().length === 1")
    assert page.evaluate("() => window.ThomasRedesign.selection()[0]")["uiId"] == "chat.sidebar"
    page.click('[data-tr="lock"]')
    page.fill(".tr-input", INSTRUCTION)
    page.click('[data-tr="apply"]')
    page.wait_for_selector(".tr-result", timeout=20000)
    result = page.inner_text(".tr-result")
    assert "Changed 3 things" in result, result
    assert "Saved to your overlay (rev 3)" in result and str(app.overlay) in result, result
    assert "Kept in this browser only" not in result

    manifest = json.loads((app.overlay / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["overlay"]["id"].startswith("ovl_") and manifest["overlay"]["created_from"]["thomas_version"]
    records = manifest["records"]
    assert [r["address"] for r in records] == [
        "element:chat:desktop:chat.sidebar",
        "token:nebula:--c-accent",
        "identity:name",
    ]
    assert {r["by"]["actor"] for r in records} == {"redesign"} and records[0]["by"]["instruction"] == INSTRUCTION
    anchor = records[0]["anchor"]
    assert (
        anchor["exact"] is True
        and anchor["fragile"] is False
        and anchor["component"] == "aside"
        and anchor["policy"] == "move resize"
    )
    assert records[0]["value"]["width"] == 320 and records[0]["value"]["style"] == {"backgroundColor": "#101a2e"}
    assert records[1]["value"] == "#2ecc71" and records[1]["stock_value"] and records[2]["value"] == "Otto"
    assert sorted(p.name for p in app.overlay.iterdir()) == [
        ".gitattributes",
        ".gitignore",
        "README.md",
        "manifest.json",
    ]

    assert page.evaluate(SHELL_VAR, "--c-accent") == "#2ecc71", "the writer repainted its own shell"
    assert page.evaluate(SIDEBAR_BG) == "rgb(16, 26, 46)" and page.evaluate(SIDEBAR_W) == "320px"
    # The sidebar wordmark is gone (the owner, 2026-09-06: minimal sidebar), so the
    # identity rename shows where the name still lives: the welcome copy the theme
    # meta carries, swapped by the overlay for every theme.
    welcome = page.evaluate(
        "() => Object.values((window.ThomasChatThemes && window.ThomasChatThemes.THEME_META) || {})"
        ".flatMap((m) => Array.isArray(m.welcome) ? m.welcome : []).join(' | ')"
    )
    assert "Otto" in welcome and "Thomas" not in welcome, welcome
    saved = page.evaluate(
        "() => { const b = JSON.parse(localStorage.getItem('thomas_ui_layout_v2') || '{}'); const w = (b.workspaces || {}).chat || {}; return Object.keys((w.desktop || {}).saved || {}); }"
    )
    assert "chat.sidebar" not in saved, "the browser's own book dropped its copy once the overlay carried it"
    page.close()


def test_every_paint_path_and_a_second_document_carry_the_first_apply(context, app) -> None:
    settings = context.new_page()
    settings.goto(app.base + "/settings?embed=1")
    settings.wait_for_selector("#theme")
    assert settings.evaluate(ROOT_VAR, "--c-accent") == "#2ecc71"
    settings.close()
    page = _home(context, app)
    assert page.evaluate(SHELL_VAR, "--c-accent") == "#2ecc71" and page.evaluate(SIDEBAR_BG) == "rgb(16, 26, 46)"
    page.click('.tc-mode-button[data-thomas-mode="code"]')
    page.wait_for_function("() => document.querySelectorAll('iframe.bt-doc.is-ready').length >= 1", timeout=30000)
    frame = next(f for f in page.frames if "embed=1" in f.url)
    frame.wait_for_function("() => window.ThomasOverlay && document.getElementById('tc-shell')", timeout=20000)
    assert frame.evaluate(SHELL_VAR, "--c-accent") == "#2ecc71"
    frame.wait_for_function(f"() => ({SIDEBAR_BG})() === 'rgb(16, 26, 46)'", timeout=10000)
    assert "Otto" in frame.evaluate("() => document.getElementById('tc-input').placeholder")
    page.close()


def test_reverting_an_overlaid_element_clears_it_from_the_overlay_for_every_document(context, app) -> None:
    page = _home(context, app)
    assert page.evaluate(SIDEBAR_BG) == "rgb(16, 26, 46)"
    before = json.loads(app.get("/api/ui/overlay")[1])["view"]["rev"]
    assert page.evaluate("() => window.ThomasUiLayout.revert('chat.sidebar')") is True
    page.wait_for_function(f"() => window.ThomasOverlay.view.rev === {before + 1}", timeout=10000)
    assert "element:chat:desktop:chat.sidebar" not in page.evaluate("() => window.ThomasOverlay.view.overrides")
    page.wait_for_function(f"() => ({SIDEBAR_BG})() !== 'rgb(16, 26, 46)'", timeout=10000)
    other = context.new_page()
    other.goto(app.base + "/")
    other.wait_for_function("() => window.ThomasOverlay && document.getElementById('tc-shell')", timeout=20000)
    assert other.evaluate(SIDEBAR_BG) != "rgb(16, 26, 46)", "a fresh document no longer carries the cleared entry"
    other.close()
    page.close()


def test_a_protected_region_is_refused_before_any_model_call(context, app) -> None:
    page = _home(context, app)
    calls: list[int] = []

    def intercept(route) -> None:
        calls.append(1)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(CANNED))

    page.route("**/api/ui/redesign", intercept)
    # The tab shell hosts the Redesign button inside the profile menu (closed by
    # default); arming through the page's own API is the same start() it calls.
    page.evaluate("() => window.ThomasRedesign.start()")
    page.wait_for_function("() => window.ThomasRedesign.phase() === 'selecting'")
    page.evaluate("() => document.getElementById('tc-shell').click()")
    page.wait_for_function("() => /is protected/.test(document.body.innerText)")
    assert page.evaluate("() => window.ThomasRedesign.selection().length") == 0
    assert page.evaluate("() => document.querySelector('[data-tr=\"lock\"]').disabled") is True
    assert calls == []
    page.close()


def test_a_minted_entry_whose_element_was_replaced_is_reported_not_applied(context, app) -> None:
    fragile = {
        "exact": False,
        "fragile": True,
        "component": "span",
        "label": "Brand",
        "policy": "move resize",
        "path": "span",
    }
    replaced = dict(fragile, component="button", label="Was a button", path="div")
    current = json.loads(app.get("/api/ui/overlay")[1])["view"]["overlay_id"]
    seeded = app.post(
        "/api/ui/overlay/records",
        {
            "overlay_id": current,
            "action": {"actor": "test", "instruction": "fragile", "targets": []},
            "records": [
                {
                    "op": "set",
                    "kind": "element",
                    "address": "element:chat:desktop:chat.sidebar~~span",
                    "value": {"x": 0, "y": 0, "style": {"color": "#ff00aa"}},
                    "anchor": fragile,
                },
                {
                    "op": "set",
                    "kind": "element",
                    "address": "element:chat:desktop:chat.sidebar~~div",
                    "value": {"x": 0, "y": 0, "style": {"color": "#00ff00"}},
                    "anchor": replaced,
                },
            ],
        },
    )
    assert seeded["ok"] and seeded["rejected"] == [], seeded
    page = _home(context, app)
    page.wait_for_function("() => window.ThomasUiLayout.orphans().includes('chat.sidebar~~div')", timeout=10000)
    assert "chat.sidebar~~span" not in page.evaluate("() => window.ThomasUiLayout.orphans()")
    span_color = page.evaluate(
        "() => getComputedStyle(document.querySelector('[data-ui-id=\"chat.sidebar\"]').querySelector('span')).color"
    )
    div_color = page.evaluate(
        "() => getComputedStyle(document.querySelector('[data-ui-id=\"chat.sidebar\"]').querySelector('div')).color"
    )
    assert span_color == "rgb(255, 0, 170)", "the entry whose anchor still matches is applied"
    assert div_color != "rgb(0, 255, 0)", (
        "the entry whose element is now a different kind is never applied to the replacement"
    )
    page.close()


def test_the_fresh_organic_matrix_survives_live_tabs_bad_clients_and_restart(context, app) -> None:
    errors: list[str] = []

    def home(ctx):
        page = ctx.new_page()
        page.on("pageerror", lambda error: errors.append(f"page: {error}"))
        page.on(
            "console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None
        )
        page.goto(app.base + "/")
        page.wait_for_function("() => window.ThomasOverlay && document.getElementById('tc-shell')", timeout=20000)
        return page

    first, second = home(context), home(context)
    start = json.loads(app.get("/api/ui/overlay")[1])["view"]
    anchor = {
        "exact": True,
        "fragile": False,
        "component": "aside",
        "label": "Chat sidebar",
        "policy": "move resize",
        "path": "",
    }
    element = {
        "op": "set",
        "kind": "element",
        "address": "element:chat:desktop:chat.sidebar",
        "value": {"x": 12, "y": 7, "width": 333, "locked": True, "style": {"backgroundColor": "#123456"}},
        "anchor": anchor,
    }
    records = [
        {
            "op": "set",
            "kind": "theme",
            "address": "theme:organic",
            "value": {
                "label": "Organic",
                "derives_from": "nebula",
                "color_scheme": "dark",
                "meta": {"welcome": ["Old", "Again"]},
            },
        },
        {"op": "set", "kind": "token", "address": "token:organic:--c-bg", "value": "#102030"},
        {"op": "set", "kind": "token", "address": "token:*:--c-text", "value": "#010203"},
        {"op": "set", "kind": "setting", "address": "setting:default_theme", "value": "organic"},
        {"op": "set", "kind": "identity", "address": "identity:name", "value": "Ada"},
        element,
        dict(
            element,
            address="element:chat:desktop:nope.organic",
            value={"x": 0, "style": {"color": "#abcdef"}},
            anchor=dict(anchor, label="Nothing"),
        ),
    ]
    result = first.evaluate(
        "records => window.ThomasOverlay.record({actor:'organic', instruction:'real use', targets:[]}, records)",
        records,
    )
    assert result["ok"] and result["rev"] == start["rev"] + len(records) and result["rejected"] == []
    second.wait_for_function("rev => window.ThomasOverlay.view.rev === rev", arg=result["rev"], timeout=10000)
    for page in (first, second):
        page.evaluate("name => localStorage.setItem('thomas_chat_theme', name)", "organic")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("() => document.getElementById('tc-shell')?.dataset.theme === 'organic'", timeout=20000)
        assert page.evaluate(SHELL_VAR, "--c-bg") == "#102030" and page.evaluate(SHELL_VAR, "--c-text") == "#010203"
        assert "Ada" in page.title() and "Ada" in page.evaluate("() => document.getElementById('tc-input').placeholder")
    assert first.evaluate(SIDEBAR_W) == "333px" and first.evaluate(SIDEBAR_BG) == "rgb(18, 52, 86)"
    assert first.evaluate("() => document.querySelector('[data-ui-id=\"chat.sidebar\"]').dataset.uiLocked") == "true"
    assert "nope.organic" in first.evaluate("() => window.ThomasUiLayout.orphans()")

    empty_context = context.browser.new_context(viewport={"width": 1440, "height": 900})
    empty = home(empty_context)
    assert empty.evaluate("() => document.getElementById('tc-shell').dataset.theme") == "organic"
    assert empty.evaluate(SHELL_VAR, "--c-bg") == "#102030"
    cleared = first.evaluate(
        "() => window.ThomasOverlay.record({actor:'organic',instruction:'restore identity',targets:[]}, [{op:'clear',kind:'identity',address:'identity:name'}])"
    )
    second.wait_for_function("rev => window.ThomasOverlay.view.rev === rev", arg=cleared["rev"], timeout=10000)
    for page in (first, second):
        assert "Thomas" in page.title() and "Thomas" in page.evaluate(
            "() => document.getElementById('tc-input').placeholder"
        )

    before, rev = (app.overlay / "manifest.json").read_bytes(), cleared["rev"]
    duplicate = first.evaluate(
        "record => window.ThomasOverlay.record({actor:'organic',instruction:'duplicate',targets:[]}, [record])", element
    )
    assert (
        duplicate["accepted"] == []
        and duplicate["rev"] == rev
        and "already in effect" in duplicate["rejected"][0]["reason"]
    )
    assert (app.overlay / "manifest.json").read_bytes() == before

    cycle = (
        "records => window.ThomasOverlay.record({actor:'organic',instruction:'dependency cycle',targets:[]}, records)"
    )
    gone = first.evaluate(
        cycle,
        [
            {"op": "clear", "kind": "token", "address": "token:organic:--c-bg"},
            {"op": "set", "kind": "setting", "address": "setting:default_theme", "value": "dark"},
            {"op": "clear", "kind": "theme", "address": "theme:organic"},
        ],
    )
    second.wait_for_function("rev => window.ThomasOverlay.view.rev === rev", arg=gone["rev"], timeout=10000)
    assert all(
        page.evaluate("() => document.getElementById('tc-shell').dataset.theme") == "dark" for page in (first, second)
    )
    back = first.evaluate(
        cycle,
        [
            {
                "op": "set",
                "kind": "theme",
                "address": "theme:organic",
                "value": {
                    "label": "Organic Two",
                    "derives_from": "dark",
                    "color_scheme": "dark",
                    "meta": {"welcome": ["New", "Again"]},
                },
            },
            {"op": "set", "kind": "token", "address": "token:organic:--c-bg", "value": "#203040"},
            {"op": "set", "kind": "setting", "address": "setting:default_theme", "value": "organic"},
        ],
    )
    second.wait_for_function("rev => window.ThomasOverlay.view.rev === rev", arg=back["rev"], timeout=10000)
    assert first.evaluate("() => window.ThomasChatThemes.THEME_META.organic.welcome[0]") == "New"
    final_clear = first.evaluate(
        cycle,
        [
            {"op": "clear", "kind": "token", "address": "token:organic:--c-bg"},
            {"op": "set", "kind": "setting", "address": "setting:default_theme", "value": "nebula"},
            {"op": "clear", "kind": "theme", "address": "theme:organic"},
        ],
    )
    assert final_clear["accepted"] == ["token:organic:--c-bg", "setting:default_theme", "theme:organic"]

    current = json.loads(app.get("/api/ui/overlay")[1])["view"]
    candidate = {
        "action": {"actor": "bad", "instruction": "stale", "targets": []},
        "records": [{"op": "set", "kind": "identity", "address": "identity:title", "value": "Never"}],
    }
    immutable = (app.overlay / "manifest.json").read_bytes()
    encode = lambda body: json.dumps(body).encode()  # noqa: E731 - compact table adapter
    wrong = app.raw_post(encode(dict(candidate, overlay_id="ovl_000000000000")))
    null = app.raw_post(encode(dict(candidate, overlay_id=None)))
    missing = app.raw_post(encode(candidate))
    malformed, oversized = app.raw_post(b"{bad"), app.raw_post(b"x" * 600000)
    chunked = app.raw_post(
        encode(dict(candidate, overlay_id=current["overlay_id"], padding="x" * 600000)), chunked=True
    )
    assert (wrong[0], null[0], missing[0], malformed[0], oversized[0], chunked[0]) == (409, 409, 400, 400, 413, 413)
    assert current["overlay_id"] not in wrong[1]["error"] and chunked[1]["code"] == "too_large"
    assert (app.overlay / "manifest.json").read_bytes() == immutable

    pending = """body => { window.__organicWrite = new Promise(resolve => setTimeout(async () => { const r=await fetch('/api/ui/overlay/records',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); resolve({status:r.status,body:await r.json()}); },150)); return true; }"""
    bodies = [
        dict(
            candidate,
            overlay_id=current["overlay_id"],
            records=[{"op": "set", "kind": "identity", "address": address, "value": value}],
        )
        for address, value in (("identity:title", "Organic Title"), ("identity:placeholder", "Ask Organic"))
    ]
    first.evaluate(pending, bodies[0])
    empty.evaluate(pending, bodies[1])
    concurrent = [first.evaluate("() => window.__organicWrite"), empty.evaluate("() => window.__organicWrite")]
    assert {item["status"] for item in concurrent} == {200}
    assert {item["body"]["rev"] for item in concurrent} == {current["rev"] + 1, current["rev"] + 2}
    manifest = json.loads((app.overlay / "manifest.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in manifest["records"]] == [f"r{i:04d}" for i in range(1, len(manifest["records"]) + 1)]
    assert not list(app.overlay.glob("*.tmp")) and not app.overlay.with_suffix(".lock").exists()
    first.evaluate("() => window.ThomasOverlay.refresh()")
    first.screenshot(path=str(app.root / "organic-overlay.png"))
    assert (app.root / "organic-overlay.png").stat().st_size > 0

    persisted, persisted_view, old_process = (
        (app.overlay / "manifest.json").read_bytes(),
        json.loads(app.get("/api/ui/overlay")[1])["view"],
        app.proc,
    )
    first.close()
    second.close()
    empty.close()
    empty_context.close()
    app.stop()
    assert old_process and old_process.poll() is not None
    app.start()
    assert app.proc and app.proc.pid != old_process.pid and (app.overlay / "manifest.json").read_bytes() == persisted
    restarted = home(context)
    assert restarted.evaluate("() => window.ThomasOverlay.view.overlay_id") == persisted_view["overlay_id"]
    assert restarted.evaluate("() => window.ThomasOverlay.view.rev") == persisted_view["rev"]
    assert restarted.evaluate(SHELL_VAR, "--c-text") == "#010203"
    restarted.close()
    assert errors == []
    print(
        "ORGANIC_EVIDENCE "
        + json.dumps(
            {
                "port": app.port,
                "old_pid": old_process.pid,
                "new_pid": app.proc.pid,
                "rev": persisted_view["rev"],
                "manifest_bytes": len(persisted),
                "screenshot_bytes": (app.root / "organic-overlay.png").stat().st_size,
            },
            sort_keys=True,
        )
    )


def _web_status() -> set[str]:
    status = subprocess.run(
        ["git", "status", "--porcelain", "thomas/server/web"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    return {line for line in status.stdout.splitlines() if line.strip()}


# Snapshotted when this module loads, before its server ever runs: the tree may
# already be dirty from other work, and that is not this feature's doing.
_WEB_STATUS_BEFORE = _web_status()


def test_the_base_wrote_nothing_into_the_repository(app) -> None:
    """A Redesign lives in the overlay under the data dir. Whatever the checkout
    looked like before this module ran, it must look the same afterwards: no
    stock web file newly modified, none newly created."""
    new = _web_status() - _WEB_STATUS_BEFORE
    assert new == set(), f"a Redesign must not touch stock web files: {sorted(new)}"
