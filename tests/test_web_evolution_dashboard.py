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


def test_index_has_evolution_nav_and_workspace() -> None:
    html = _read(WEB / "index.html")
    assert 'id="navEvolutionBtn"' in html
    assert 'data-nav-mode="evolution"' in html
    assert "> Evolution </button>" in html
    assert 'id="evolutionWorkspace"' in html
    assert 'class="evolution-workspace hidden"' in html


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
    css = _read(WEB / "css" / "evolution.css")
    assert ".evolution-workspace {" in css
    assert ".evolution-status-pill.is-running {" in css
    assert ".evo-chip.risk-high {" in css


def test_dashboard_has_conversational_command_bar() -> None:
    text = _all_runtime_js()
    assert 'id="evoChatForm"' in text
    assert "function evolutionChatSend(" in text
    assert "function evolutionChatAppend(" in text
    assert "'/api/evolve/loop/chat'" in text
    css = _read(WEB / "css" / "evolution.css")
    assert ".evo-chat-you {" in css


def test_dashboard_unwraps_fetchjsonsafe_envelope() -> None:
    """fetchJsonSafe returns an envelope {ok,status,data,text}; the dashboard must
    unwrap `.data` (a live run showed the panel renders nothing otherwise)."""
    text = _all_runtime_js()
    assert "function _evoUnwrap(" in text
    assert "function evoGet(" in text
    # the live data reads must go through the unwrapping helper, not raw fetchJsonSafe
    assert "await evoGet('/api/evolve/loop/status" in text
    assert "await evoGet('/api/evolve/loop/plan" in text
