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


def test_runtime_copy_keeps_simple_then_expandable_shell() -> None:
    runtime_init = _read_text("thomas/server/web/js/src/runtime_modules/008_init.js")
    fallback_init = _read_text("thomas/server/web/js/app_parts/part-004b.js")
    suggestion_runtime = _read_text("thomas/server/web/js/src/runtime_modules/005_capped.js")
    task_part = _read_text("thomas/server/web/js/app_parts/part-002b.js")
    sidebar_search_part = _read_text("thomas/server/web/js/app_parts/part-030.js")
    index_html = _read_text("thomas/server/web/index.html")
    app_loader = _read_text("thomas/server/web/js/app.js")
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
    assert "Ask {{agent}} anything or describe a task" in runtime_init
    assert "welcomeReadinessStatus" in fallback_init
    assert "welcomeReadinessPills" in fallback_init
    assert "welcomeRepairBtn" in fallback_init
    assert "updateWelcomeSupportRail(loadStoredBuilderMode());" in fallback_init
    assert "Easy Setup is still required before Thomas unlocks memory, tools, and automation." in fallback_init
    assert "Everyday path is ready. Active connection:" in fallback_init
    assert "Builder Controls" in fallback_init
    assert "Everyday Defaults" in fallback_init
    assert "Setup And Repair" in fallback_init
    assert "settingsRepairSetupBtn" in fallback_init
    assert "Connection And Defaults" in fallback_init
    assert "Use Easy Setup" in fallback_init
    assert "Speed Vs Quality" in fallback_init
    assert "Find past chats" in fallback_init
    assert "Find messages in this chat" in fallback_init
    assert "Current Task" in fallback_init
    assert "Ask {{agent}} anything or describe a task" in fallback_init
    assert "Try asking" in suggestion_runtime
    assert "Needs help" in task_part
    assert "Task status is unavailable right now." in task_part
    assert "Thomas will show progress and blockers here when a task is running." in task_part
    assert "Try asking" in task_part
    assert "Find past chats" in sidebar_search_part
    assert "Find office activity" in sidebar_search_part
    assert "Find missions" in sidebar_search_part
    assert "Find content" in sidebar_search_part
    assert "Find past chats" in index_html
    assert "Find messages in this chat" in index_html
    assert "Current Task" in index_html
    assert "Try asking" in index_html
    assert "Ask {{agent}} anything or describe a task" in index_html
    assert "Loading primary app runtime" in app_loader
    assert "./app_runtime_primary.mjs" in app_loader
    assert "generated/app_runtime_joined.mjs" not in app_loader
    assert "app_parts/" not in app_loader
    model_setup_part = _read_text("thomas/server/web/js/app_parts/part-031.js")
    assert "ChatGPT / Codex" in model_setup_part
    assert "Local Ollama" in model_setup_part
    assert "Provider API key" in model_setup_part


def test_settings_respect_stored_builder_mode() -> None:
    appearance_runtime = _read_text("thomas/server/web/js/src/runtime_modules/061_appearance.js")
    assert "loadStoredBuilderMode" in appearance_runtime
    assert "settingsSuite.classList.toggle('advanced-mode', builderModeEnabled);" in appearance_runtime


def test_dashboard_description_matches_default_mode_story() -> None:
    runtime_init = _read_text("thomas/server/web/js/src/runtime_modules/008_init.js")
    assert "Start with what matters now. Open deeper control surfaces only when you need them." in runtime_init
