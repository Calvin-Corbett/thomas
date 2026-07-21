"""Focused contract for the modernized standalone Library workspace."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "thomas/server/web/static/my_stuff.html"
CSS_PATH = ROOT / "thomas/server/web/static/my_stuff.style01.css"
JS_PATH = ROOT / "thomas/server/web/static/my_stuff.script01.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_my_stuff_uses_current_thomas_identity_without_copying_chat_themes() -> None:
    html = _read(HTML_PATH)
    css = _read(CSS_PATH)

    assert 'data-theme="nebula"' in html
    assert 'data-stuff-brand' in html
    assert 'class="thomas-eyes-mark"' in html
    assert ".stuff-eyes-mark" not in css
    assert '<span class="stuff-brand-name">Thomas</span>' in html
    assert '<span class="stuff-brand-space">Library</span>' in html

    assert ':root.is-embedded .stuff-brand { display: none; }' in css
    assert "--stuff-primary: var(--c-accent)" in css
    assert "--stuff-font: var(--font-sans)" in css
    assert "--radius-card: max(6px, calc(var(--r-card) - 6px))" in css
    assert ':root[data-theme=' not in css
    assert "--c-bg:" not in css
    assert "body::before" not in css


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
    assert len(js.splitlines()) < 1600


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

    for card_id in (
        "my-stuff.library.project-card.",
        "my-stuff.library.installed-app-card.",
        "my-stuff.library.forge-build-card.",
        "my-stuff.board.project-card.",
    ):
        assert card_id in js
    assert js.count('data-ui-instance-key="') >= 3
    assert 'data-ui-policy="protected"' in html
    assert "preserve-confirmation-flow" in js
    assert "data-open-workspace-chat" in js
    assert "thomas:workspace-chat:open" in js


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
        "stuffSearch",
        "libraryTitle",
        "librarySummary",
        "itemDetail",
        "itemDetailContent",
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
    ):
        assert endpoint in js

    assert "fetch('/api/v2/chat'" not in js
    assert "mode: 'my_stuff'" in js

    assert "var installedPromise = refreshInstalledPlugins();" in js
    assert "var buildsPromise = loadForgeBuilds({ deferRender: true });" in js
    assert js.index("var buildsPromise = loadForgeBuilds") < js.index("fetchJson('/api/local/projects')")
    assert "await installedPromise;" in js
    assert "await buildsPromise;" in js


def test_my_stuff_is_a_searchable_hybrid_library_with_real_item_details() -> None:
    html = _read(HTML_PATH)
    js = _read(JS_PATH)

    for label in ("All Stuff", "Apps", "Projects", "Creations", "Recent"):
        assert label in html
    for contract in (
        'data-library-filter="all"',
        'data-view-mode="library"',
        'data-view-mode="arrange"',
        'data-ui-id="my-stuff.library.search"',
        'data-ui-id="my-stuff.library.collections"',
        'data-ui-id="my-stuff.item-detail"',
    ):
        assert contract in html
    assert "function libraryItems()" in js
    assert "function openLibraryItemDetails(key)" in js
    assert "Installed marketplace registry" in js
    assert "Thomas Code deliverables registry" in js
    assert "project && project.generated" in js
    assert "project.artifact_url" in js
    assert "New Thomas creations will appear automatically when a canonical source records them." in js


def test_my_stuff_board_uses_live_width_and_preserves_rightward_positions() -> None:
    js = _read(JS_PATH)

    assert "function boardColumnCount()" in js
    assert "elements.board.clientWidth" in js
    assert "Math.min(columns - 1" in js
    assert "columns: 5" not in js
    assert "elements.board.addEventListener('pointercancel'" in js
    assert "Math.round(boardRect.width - SNAP.tileWidth - 24)" in js
    assert "'/layout'" in js


def test_owner_facing_library_is_dense_and_defers_to_the_shared_world_backdrop() -> None:
    html = _read(HTML_PATH)
    css = _read(CSS_PATH)
    js = _read(JS_PATH)

    assert "<title>Thomas · Library</title>" in html
    assert "<h1>Library</h1>" in html
    assert "Apps · Projects · Creations" in html
    assert "Everything you make with Thomas" not in html
    assert "A living home for your apps" not in html
    assert "My Stuff" not in html
    assert "My Stuff" not in js
    assert ":root.is-embedded, :root.is-embedded body { background: transparent !important; }" in css
    assert ".stuff-header h1 { margin: 0; font-size: 1.15rem" in css
    assert "min-height: calc(100vh - 136px)" in css
    assert "repeat(auto-fill, minmax(184px, 1fr))" in css
    assert "min-height: 112px" in css
    assert "box-shadow: none;" in css
