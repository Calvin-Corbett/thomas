from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "thomas" / "server" / "web"
TOKEN_JS = WEB_ROOT / "js" / "token_economy.js"
SPACE_JS = WEB_ROOT / "js" / "token_economy_space.js"
TOKEN_CSS = WEB_ROOT / "css" / "token_economy_widget.css"
COMPONENT_CSS = WEB_ROOT / "css" / "token_economy_components.css"
THEME_CSS = WEB_ROOT / "css" / "token_economy_space_theme.css"
WORKSPACE_SHELL_CSS = WEB_ROOT / "css" / "workspace_shell.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_token_economy_consumes_the_immutable_five_theme_shell() -> None:
    css = "\n".join((_read(TOKEN_CSS), _read(COMPONENT_CSS), _read(THEME_CSS)))
    shell = _read(WORKSPACE_SHELL_CSS)

    for theme in ("nebula", "dark", "light", "aurora", "sandstone"):
        assert f'data-thomas-theme="{theme}"' in shell or theme == "nebula"

    for token in (
        "--c-bg",
        "--c-surface",
        "--c-surface-2",
        "--c-border",
        "--c-border-2",
        "--c-text",
        "--c-dim",
        "--c-muted",
        "--c-accent",
        "--c-accent-ink",
        "--c-accent-soft",
        "--c-accent-line",
        "--c-shadow",
    ):
        assert f"var({token}" in css or f"var({token}" in shell
        assert f"{token}:" not in css

    assert "te-theme-light" not in css
    assert "te-theme-dark" not in css
    assert "body.te-" not in css
    assert "\n.main-content" not in css
    assert ".sidebar" not in css
    assert "#settings" not in css
    assert "var(--r-card" in css
    assert "--c-r-card" not in css


def test_token_economy_uses_the_shared_eyes_mark_and_no_editor_chrome() -> None:
    js = _read(TOKEN_JS)

    assert 'class="thomas-eyes-mark"' in js
    assert '<strong class="te-topbar-title">Token Economy</strong>' in js
    assert 'class="te-overview-rail"' in js
    assert "See token use, budgets, and runtime policy in one place." not in js
    assert 'class="te-panel-copy"' not in js
    assert "thomas-ui-editor" not in js
    assert "thomas-ui-edit-toolbar" not in js
    assert ">Edit UI<" not in js


def test_token_economy_registers_stable_edit_mode_regions_and_protections() -> None:
    js = _read(TOKEN_JS)

    for region in (
        "token-economy.header",
        "token-economy.overview",
        "token-economy.summary",
        "token-economy.history",
        "token-economy.ledger",
        "token-economy.policy",
        "token-economy.models",
        "token-economy.profile-matrix",
    ):
        assert f'data-ui-id="{region}"' in js

    assert 'data-ui-id="token-economy.policy" data-ui-label="Economy policy controls" data-ui-policy="protected"' in js
    assert 'data-ui-id="token-economy.economy-mode"' in js
    assert 'data-ui-group-policy="protected-controls"' in js
    assert 'data-ui-policy="protected"' in js
    assert 'data-ui-constraints="minWidth=280' in js

    for dynamic_region in (
        "token-economy.metric",
        "token-economy.model-share",
        "token-economy.model-ledger-row",
        "token-economy.history-day",
        "token-economy.profile",
        "token-economy.ledger-event",
    ):
        marker = f'data-ui-id="{dynamic_region}"'
        assert marker in js
        dynamic_markup = js[js.index(marker) : js.index(marker) + 500]
        assert "data-ui-instance-key=" in dynamic_markup
        assert "data-ui-group=" in dynamic_markup
        assert "data-ui-group-policy=" in dynamic_markup


def test_token_economy_preserves_live_api_and_module_contracts() -> None:
    js = _read(TOKEN_JS)

    for endpoint in (
        "/api/spend/today",
        "/api/spend/session",
        "/api/spend/history?days=",
        "/api/spend/pricing",
        "/api/runtime/profile",
        "/api/runtime/matrix",
        "/api/preferences",
        "/api/spend/stream",
        "/api/spend/export.csv?days=",
    ):
        assert endpoint in js

    assert "method: 'PATCH'" in js
    assert "default_token_economy: mode" in js
    assert "window.__moduleBackgrounds['token_economy']" in js
    assert "window.__tokenEconomy = { mount, unmount, refresh" in js


def test_token_economy_background_and_live_work_are_active_only() -> None:
    js = _read(TOKEN_JS)
    space = _read(SPACE_JS)
    combined = js + "\n" + space

    for forbidden in (
        "requestAnimationFrame",
        "cancelAnimationFrame",
        "MutationObserver",
        "createElement('canvas')",
        "createElement(\"canvas\")",
        "_startSpaceAnimation",
        "_watchForIframes",
        "floaterStart",
        "screensaver",
    ):
        assert forbidden not in combined

    assert "function workspaceActive()" in js
    assert "if (_s.sse || !workspaceActive()) return;" in js
    assert "document.addEventListener('visibilitychange', onVisibilityChange);" in js
    assert "document.removeEventListener('visibilitychange', onVisibilityChange);" in js
    assert "sseOff();" in js
    assert "clockStop();" in js
    assert "removeSpaceBg();" in js
    assert "window.__teSpace = (function tokenEconomySurfaceAdapter()" in space
    assert "if (!workspace || !workspace.isConnected) return false;" in space


def test_token_economy_component_css_is_lazy_and_all_sources_fit_limits() -> None:
    js = _read(TOKEN_JS)

    assert "function ensureComponentStyles()" in js
    assert "token_economy_components.css" in js
    assert "new URL(source.href, window.location.href).search" in js
    assert js.index("ensureComponentStyles();") < js.index("container.innerHTML = shell();")

    limits = {
        TOKEN_JS: 800,
        SPACE_JS: 800,
        TOKEN_CSS: 600,
        COMPONENT_CSS: 600,
        THEME_CSS: 600,
    }
    for path, limit in limits.items():
        assert len(_read(path).splitlines()) <= limit, f"{path.name} exceeds {limit} lines"


def test_token_economy_respects_reduced_motion() -> None:
    css = "\n".join((_read(TOKEN_CSS), _read(COMPONENT_CSS), _read(THEME_CSS)))
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "animation: none !important" in css
    assert "transition-duration: .01ms !important" in css


def test_token_economy_is_a_dense_tool_without_the_legacy_space_backdrop() -> None:
    widget = _read(TOKEN_CSS)
    components = _read(COMPONENT_CSS)
    theme = _read(THEME_CSS)

    assert '#moduleWorkspace[data-mode="token_economy"]::before' in widget
    assert '#moduleWorkspace[data-mode="token_economy"]::after' in widget
    assert "display: none !important" in widget
    assert "content: none !important" in widget
    assert "background: none !important" in widget
    assert "html.tcw-embed [data-te-container]" in widget
    assert "html.tcw-embed:has([data-te-container] .te-v3.is-active) #moduleWorkspace" in widget
    assert "html.tcw-embed:has([data-te-container] .te-v3.is-active)" in widget
    assert "color-scheme: normal !important" in widget
    assert "body:has([data-te-container] .te-v3.is-active) .main-content" in widget
    assert "body:has([data-te-container] .te-v3.is-active) .main-content::before" in widget
    assert "body:has([data-te-container] .te-v3.is-active) .main-content::after" in widget
    assert ".te-overview-rail" in widget
    assert "min-height: 46px" in widget
    assert "min-height: 84px" in widget
    assert "min-height: 220px" in components
    assert "radial-gradient" not in theme
