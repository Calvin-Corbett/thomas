from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _exists(relative_path: str) -> bool:
    return (ROOT / relative_path).exists()


def _read_many(relative_paths: list[str]) -> str:
    return "\n".join(_read_text(path) for path in relative_paths)


def _read_all_runtime_js() -> str:
    runtime_dir = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
    if not runtime_dir.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in sorted(runtime_dir.glob("*.js")))


def test_canvas_is_the_authoritative_app_builder_surface() -> None:
    contract = _read_text("thomas/server/web/js/runtime/canvas_workspace_contract.js")
    runtime = _read_text("thomas/server/web/js/runtime/canvas_workspace_runtime.js")
    engine = _read_text("thomas/server/web/js/runtime/048_ui_studio_canvas.js")

    assert "var NAME = 'Canvas';" in contract
    assert "var MODE_ID = 'app_builder';" in contract
    assert "window.ThomasCanvasWorkspaceContract" in contract
    assert "window.ThomasCanvasWorkspaceRuntime" in runtime
    assert "moduleRenderWorkbenchAppBuilderCanvas" in runtime
    assert "workspaceRuntime.install(window.UI_STUDIO)" in engine
    assert "module-ui-editor-shell" not in runtime
    assert "module-ui-editor-shell" not in engine
    assert "Live Thomas UI" not in runtime
    assert "Visible Layers" not in runtime


def test_ui_editor_rescue_loader_is_wired_into_app_boot() -> None:
    app_loader = _read_text("thomas/server/web/js/app.js")
    rescue_loader = _read_text("thomas/server/web/js/ui_editor_rescue.js")
    assert "window.__thomasRuntimeReady" in app_loader
    assert "await window.__thomasRuntimeReady" in app_loader
    assert "startUiEditorRescueMode" in app_loader
    assert "ui_editor_rescue.js" in app_loader
    assert "generated/app_runtime_joined.mjs" not in app_loader
    assert "app_parts/" not in app_loader
    assert "Loading UI editor rescue mode" in app_loader
    ordered_files = [
        "./runtime/canvas_workspace_contract.js",
        "./runtime/canvas_workspace_runtime.js",
        "./runtime/048_ui_studio_canvas.js",
    ]
    positions = [rescue_loader.index(path) for path in ordered_files]
    assert positions == sorted(positions)
    assert "063_" not in rescue_loader
    assert "for (const file of CANVAS_RUNTIME_FILES)" in rescue_loader
    assert "await loadClassicScript(file);" in rescue_loader
    assert "startCanvasRescueMode" in rescue_loader
    assert "startUiEditorRescueMode" in rescue_loader
    assert "Canvas rescue mode is active." in rescue_loader
    assert "UI Editor rescue mode is active." not in rescue_loader
    assert "moduleRenderWorkbenchAppBuilder" in rescue_loader


def test_legacy_joined_runtime_files_are_removed() -> None:
    assert not _exists("thomas/server/web/js/app_runtime_joined.mjs")
    assert not _exists("thomas/server/web/js/generated/app_runtime_joined.mjs")
    assert not _exists("scripts/build_app_runtime_joined.py")


def test_shell_layout_guards_prevent_duplicate_suggestions_and_forced_chat_settings() -> None:
    primary_runtime = _read_all_runtime_js()
    layout_css = _read_text("thomas/server/web/css/layout_parts/layout-app-shell.css")
    suggestion_css = _read_text("thomas/server/web/css/components_parts/easy-setup-ui.css")
    marketplace_css = _read_text("thomas/server/web/static/plugin_marketplace.style01_part01.css")

    open_settings_block = primary_runtime.split("function openSettingsModal()", 1)[1].split(
        "function isSettingsScreenOpen()", 1
    )[0]

    assert "frame.style.height = '980px';" not in primary_runtime
    assert "setSidebarNavMode('chat', { persist: false });" not in open_settings_block
    assert (
        "padding-bottom: calc(max(176px, var(--composer-offset, 176px)) + env(safe-area-inset-bottom) + 10px);"
        in layout_css
    )
    assert "min-height: 100%;" in layout_css
    assert "animation: assistantSuggestionMarquee var(--assistant-scroll-duration) linear infinite;" in suggestion_css
    assert "mask-image: linear-gradient(90deg, transparent 0, #000 8%, #000 92%, transparent 100%);" in suggestion_css
    assert "function renderAssistantAvatarVisual" in primary_runtime
    assert "resolveActiveChatProfileMeta" in primary_runtime
    assert "body::before" in marketplace_css
    assert "animation: thomasMarketGridDrift 16s linear infinite;" in marketplace_css
