"""Focused contract for the modernized standalone My Stuff workspace."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "thomas/server/web/static/my_stuff.html"
CSS_PATH = ROOT / "thomas/server/web/static/my_stuff.style01.css"
JS_PATH = ROOT / "thomas/server/web/static/my_stuff.script01.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_my_stuff_uses_current_thomas_identity_and_all_five_themes() -> None:
    html = _read(HTML_PATH)
    css = _read(CSS_PATH)

    assert 'data-theme="nebula"' in html
    assert 'data-stuff-brand' in html
    assert 'class="thomas-eyes-mark"' in html
    assert ".stuff-eyes-mark" not in css
    assert '<span class="stuff-brand-name">Thomas</span>' in html
    assert '<span class="stuff-brand-space">My Stuff</span>' in html

    for theme in ("nebula", "dark", "light", "aurora", "sandstone"):
        assert f':root[data-theme="{theme}"]' in css

    assert ':root.is-embedded .stuff-brand { display: none; }' in css
    assert "--stuff-primary: var(--c-accent)" in css
    assert '--stuff-font: var(--font-sans, "Manrope", system-ui, sans-serif)' in css


def test_my_stuff_theme_bridge_supports_initial_message_and_storage_updates() -> None:
    html = _read(HTML_PATH)
    js = _read(JS_PATH)

    assets = (
        "/static/css/workspace_shell.css",
        "/static/css/ui_edit_mode.css",
        "/static/js/workspace_shell.js",
        "/static/js/ui_edit_layout.js",
        "/static/js/ui_edit_mode.js",
        "/static/static/my_stuff.script01.js",
    )
    positions = [html.index(asset) for asset in assets]
    assert positions == sorted(positions)
    assert 'data-ui-workspace="my_stuff"' in html
    assert "window.addEventListener('storage'" in js
    assert "event.key !== 'thomas_chat_theme'" in js
    assert "window.ThomasWorkspaceShell.applyTheme(event.newValue, { persist: false })" in js
    assert len(js.splitlines()) < 1500


def test_my_stuff_route_replaces_the_shared_build_fingerprint() -> None:
    routes = _read(ROOT / "thomas/server/app_routes_init.py")
    middleware = _read(ROOT / "thomas/server/app_middleware_handlers.py")

    assert '"_web_build_fingerprint": _web_build_fingerprint' in middleware
    assert '"static/my_stuff.style01.css"' in routes
    assert 'html.replace("__THOMAS_WEB_BUILD__", web_build)' in routes
    assert 'headers={"Cache-Control": "no-store"}' in routes


def test_my_stuff_exposes_stable_shared_editor_contracts() -> None:
    html = _read(HTML_PATH)
    js = _read(JS_PATH)

    static_ids = re.findall(r'data-ui-id="([^"]+)"', html)
    assert static_ids
    assert len(static_ids) == len(set(static_ids))
    assert 'data-ui-id="my-stuff.shell"' in html
    assert 'data-ui-component="workspace-shell"' in html
    assert 'data-ui-constraints="preserve-runtime-ids,preserve-handlers"' in html
    assert 'data-ui-component="repeating-card-group"' in html
    assert "items-runtime-owned,reposition-allow,resize-deny,add-deny,remove-deny" in html
    assert 'data-ui-component="privileged-action"' in html

    for card_id in ("my-stuff.project-card.", "my-stuff.installed-app-card.", "my-stuff.forge-build-card."):
        assert f'data-ui-id="{card_id}' in js
    assert js.count('data-ui-instance-key="') >= 6
    assert 'data-ui-policy="protected"' in js
    assert "preserve-confirmation-flow" in js
    assert ".composer\" data-ui-component=\"composer\"" in js


def test_my_stuff_preserves_runtime_ids_and_real_data_paths() -> None:
    html = _read(HTML_PATH)
    js = _read(JS_PATH)

    for element_id in (
        "refreshButton",
        "openImportButton",
        "installedAppsShelf",
        "installedAppsList",
        "boardView",
        "board",
        "forgeBuilds",
        "forgeBuildsGrid",
        "detailView",
        "detailShell",
        "importSheet",
        "dropzone",
        "pickFolderButton",
        "submitImportButton",
    ):
        assert f'id="{element_id}"' in html

    for endpoint in (
        "/api/local/projects",
        "/api/local/projects/import",
        "/api/local/projects/pick-folder",
        "/api/evolve/agent/deliverables",
        "/api/v2/chat",
    ):
        assert endpoint in js

    # refresh() owns the boot-time deliverables refresh; do not issue a second
    # parallel request from the script footer.
    assert js.count("void loadForgeBuilds();") == 1
