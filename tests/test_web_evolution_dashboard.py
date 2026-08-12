"""Web integration test for the Evolution dashboard panel.

Mirrors test_web_evolve_chat_ux.py: asserts the sidebar entry, workspace
section, dispatcher wiring, runtime logic, loader registration, and CSS are all
present and consistent -- so the panel cannot silently fall out of the shell.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"
RUNTIME_DIR = WEB / "js" / "runtime"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _all_runtime_js() -> str:
    parts = sorted(RUNTIME_DIR.glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in parts)


def test_chat_shell_has_unified_code_mode_and_workspace() -> None:
    html = _read(WEB / "chat.html")
    assert 'data-thomas-mode="code"' in html
    assert 'id="tc-mode-surface"' in html
    assert "/static/js/unified_mode_shell.js" in html
    assert "/static/js/unified_code_mode.js" in html
    assert "/static/css/unified_code_mode.css" in html
    assert "/static/css/unified_code_activity.css" in html
    assert "/static/css/unified_code_results.css" in html


def test_dispatcher_treats_evolution_as_first_class_mode() -> None:
    text = _all_runtime_js()
    # nav-mode allow-list accepts 'evolution' (else it is coerced to chat)
    assert "mode === 'evolution'" in text
    # setSidebarNavMode toggles the workspace and calls the lifecycle hooks
    assert "const isEvolution = sidebarNavMode === 'evolution';" in text
    assert "evolutionWorkspace.classList.toggle('hidden', !isEvolution);" in text
    assert "if (typeof evolutionEnterMode === 'function') evolutionEnterMode();" in text
    assert "setSidebarNavMode('evolution');" in text


def test_dom_refs_declared_in_preamble() -> None:
    preamble = _read(RUNTIME_DIR / "001_preamble.js")
    assert "const navEvolutionBtn = document.getElementById('navEvolutionBtn');" in preamble
    assert "const evolutionWorkspace = document.getElementById('evolutionWorkspace');" in preamble


def test_dashboard_runtime_defines_hooks_and_calls_api() -> None:
    text = _all_runtime_js()
    assert "function evolutionEnterMode()" in text
    assert "function evolutionLeaveMode()" in text
    assert "function evolutionRenderBacklog(" in text
    assert "function evolutionRenderPending(" in text
    assert "'/api/evolve/loop/status" in text
    assert "'/api/evolve/loop/start'" in text
    assert "'/api/evolve/loop/plan" in text
    assert 'data-evo-action="approve"' in text


def test_dashboard_runtime_is_registered_in_loader() -> None:
    loader = _read(WEB / "js" / "app_runtime_loader.js")
    assert "'046_evolution_dashboard.js'," in loader
    assert (RUNTIME_DIR / "046_evolution_dashboard.js").exists()


def test_evolution_css_present() -> None:
    css = "\n".join(
        _read(WEB / "css" / name)
        for name in (
            "unified_code_mode.css",
            "unified_code_activity.css",
            "unified_code_results.css",
        )
    )
    assert ".tc-code-panel {" in css
    assert ".tc-code-technical.is-error > i" in css
    assert ".tc-code-technical-log {" in css
    assert ".tc-code-approval {" in css


def test_unified_code_mode_has_conversational_command_bar() -> None:
    text = _read(WEB / "js" / "unified_code_mode.js")
    assert "modes().registerAdapter('code'" in text
    assert 'id="tc-code-steer-form"' in text
    assert "'/api/evolve/agent/send'" in text
    assert "new EventSource(lifecycle().streamUrl(state))" in text


def test_dashboard_unwraps_fetchjsonsafe_envelope() -> None:
    """fetchJsonSafe returns an envelope {ok,status,data,text}; the dashboard must
    unwrap `.data` (a live run showed the panel renders nothing otherwise)."""
    text = _all_runtime_js()
    assert "function _evoUnwrap(" in text
    assert "function evoGet(" in text
    # the live data reads must go through the unwrapping helper, not raw fetchJsonSafe
    assert "await evoGet('/api/evolve/loop/status" in text
    assert "await evoGet('/api/evolve/loop/plan" in text
