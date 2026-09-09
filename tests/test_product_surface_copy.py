from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_surfaces_user_first_story() -> None:
    readme = _read_text("README.md")
    assert readme.startswith("# Thomas")
    assert "Fresh install: run `run-ui.cmd`" in readme
    assert "## Everyday Use" in readme
    assert "## Grow Into Advanced Thomas Safely" in readme


def _read_all_runtime_js() -> str:
    runtime_dir = ROOT / "thomas/server/web/js/runtime"
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in sorted(runtime_dir.glob("*.js"))
    )


def test_runtime_copy_keeps_simple_then_expandable_shell() -> None:
    # Pinned on the live split runtime (js/runtime/) that index.html actually
    # loads. The old target, js/src/runtime_modules/, was a dead archive whose
    # copy had drifted from what users see; it is deleted.
    runtime = _read_all_runtime_js()
    index_html = _read_text("thomas/server/web/index.html")
    app_loader = _read_text("thomas/server/web/js/app.js")
    model_setup_runtime = _read_text("thomas/server/web/js/runtime/045_model_setup_settings_06.js")
    # Builder Mode was deleted: setBuilderMode() had no caller, and the four
    # elements it drove (welcomeReadinessPills / welcomeSupportCopy /
    # welcomeReadinessStatus / welcomeBuilderModeBtn) exist in no page. The
    # settings "advanced-mode" toggle is driven independently by
    # 039_module_rendering_dispatch_02.js and is unaffected.
    assert "setBuilderMode" not in model_setup_runtime
    assert "welcomeReadinessPills" not in model_setup_runtime
    assert "Run Easy Setup" in runtime
    assert "Current Task" in runtime
    assert "data-agent-placeholder-template" in runtime
    assert "Find past chats" in index_html
    assert "Find messages in this chat" in index_html
    assert "Current Task" in index_html
    assert "Try asking" in index_html
    assert "Message {{agent}}" in index_html
    assert "window.__thomasRuntimeReady" in app_loader
    assert "await window.__thomasRuntimeReady" in app_loader
    assert "app_runtime_loader.js" in app_loader
    assert "generated/app_runtime_joined.mjs" not in app_loader
    assert "app_parts/" not in app_loader
    assert "ChatGPT (OpenAI)" in model_setup_runtime
    assert "Local Ollama" in model_setup_runtime
    assert "Provider API key" in model_setup_runtime


def test_settings_advanced_toggle_drives_advanced_mode() -> None:
    # This used to assert that 045_model_setup_settings_06.js mentioned
    # loadStoredBuilderMode -- a string check over code nothing called. The
    # advanced-mode class is actually applied by the settings toggle handler,
    # which is what this now pins.
    dispatch_runtime = _read_text("thomas/server/web/js/runtime/039_module_rendering_dispatch_02.js")
    assert "settingsSuite.classList.toggle('advanced-mode', settingsAdvancedToggle.checked);" in dispatch_runtime


def test_dashboard_description_matches_default_mode_story() -> None:
    index_html = _read_text("thomas/server/web/index.html")
    assert "One screen that answers what matters right now." in index_html
