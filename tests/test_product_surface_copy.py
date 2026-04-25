from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_surfaces_user_first_story() -> None:
    readme = _read_text("README.md")
    assert readme.startswith("# Thomas")
    assert "Fresh install: download the Windows installer above." in readme
    assert "ThomasSetup_0.14.63.exe" in readme
    assert "## Everyday Use" in readme
    assert "## Grow Into Advanced Thomas Safely" in readme


def test_runtime_copy_keeps_simple_then_expandable_shell() -> None:
    runtime_init = _read_text("thomas/server/web/js/src/runtime_modules/008_init.js")
    suggestion_runtime = _read_text("thomas/server/web/js/src/runtime_modules/005_capped.js")
    message_runtime = _read_text("thomas/server/web/js/src/runtime_modules/004_message.js")
    index_html = _read_text("thomas/server/web/index.html")
    app_loader = _read_text("thomas/server/web/js/app.js")
    model_setup_runtime = _read_text("thomas/server/web/js/runtime/045_model_setup_settings_06.js")
    assert "Build And Extend" in runtime_init
    assert "Start with chat. Add memory, tools, and automation when you are ready." in runtime_init
    assert "Ready for everyday use" in runtime_init
    assert "Grow safely" in runtime_init
    assert "Show Builder Controls" in runtime_init
    assert "Run Easy Setup" in runtime_init
    assert "Repair Setup" in runtime_init
    assert "thomas.builder_mode.enabled" in runtime_init
    assert "Setup is not finished yet. Thomas is staying in guarded mode until verification passes." in runtime_init
    assert "Easy Setup is still required before Thomas unlocks memory, tools, and automation." in runtime_init
    assert "Everyday path is ready. Active connection:" in runtime_init
    assert "Builder Controls" in runtime_init
    assert "Everyday Defaults" in runtime_init
    assert "Setup And Repair" in runtime_init
    assert "Continue Easy Setup" in runtime_init
    assert "Connection And Defaults" in runtime_init
    assert "Use Easy Setup" in runtime_init
    assert "Speed Vs Quality" in runtime_init
    assert "Find past chats" in runtime_init
    assert "Find messages in this chat" in runtime_init
    assert "Current Task" in runtime_init
    assert "data-agent-placeholder-template" in runtime_init
    assert "welcomeReadinessStatus" in runtime_init
    assert "welcomeReadinessPills" in runtime_init
    assert "welcomeRepairBtn" in runtime_init
    assert "updateWelcomeSupportRail(loadStoredBuilderMode());" in runtime_init
    assert "Easy Setup is still required before Thomas unlocks memory, tools, and automation." in runtime_init
    assert "Everyday path is ready. Active connection:" in runtime_init
    assert "Builder Controls" in runtime_init
    assert "Everyday Defaults" in runtime_init
    assert "Setup And Repair" in runtime_init
    assert "settingsRepairSetupBtn" in runtime_init
    assert "Connection And Defaults" in runtime_init
    assert "Use Easy Setup" in runtime_init
    assert "Speed Vs Quality" in runtime_init
    assert "Find past chats" in runtime_init
    assert "Find messages in this chat" in runtime_init
    assert "Current Task" in runtime_init
    assert "data-agent-placeholder-template" in runtime_init
    assert "Try asking" in suggestion_runtime
    assert "Needs help" in message_runtime
    assert "Thomas will show progress and blockers here when a task is running." in runtime_init
    assert "Find past chats" in index_html
    assert "Find messages in this chat" in index_html
    assert "Current Task" in index_html
    assert "Try asking" in index_html
    assert "Ask {{agent}} anything or describe a task" in index_html
    assert "window.__thomasRuntimeReady" in app_loader
    assert "await window.__thomasRuntimeReady" in app_loader
    assert "app_runtime_loader.js" in app_loader
    assert "generated/app_runtime_joined.mjs" not in app_loader
    assert "app_parts/" not in app_loader
    assert "ChatGPT / Codex" in model_setup_runtime
    assert "Local Ollama" in model_setup_runtime
    assert "Provider API key" in model_setup_runtime


def test_settings_respect_stored_builder_mode() -> None:
    appearance_runtime = _read_text("thomas/server/web/js/src/runtime_modules/061_appearance.js")
    assert "loadStoredBuilderMode" in appearance_runtime
    assert "settingsSuite.classList.toggle('advanced-mode', builderModeEnabled);" in appearance_runtime


def test_dashboard_description_matches_default_mode_story() -> None:
    runtime_init = _read_text("thomas/server/web/js/src/runtime_modules/008_init.js")
    assert "Start with what matters now. Open deeper control surfaces only when you need them." in runtime_init
