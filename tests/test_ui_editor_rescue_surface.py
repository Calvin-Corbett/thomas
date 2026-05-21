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


def test_ui_editor_now_has_inspector_and_stable_targets() -> None:
    editor_core = _read_text("thomas/server/web/js/modules/063_module_studio_comfy_style_id_helpers.js")
    editor_shell = _read_text("thomas/server/web/js/modules/063_module_studio_comfy_style_id_workspace.js")
    assert "function moduleUiEditorIsElement" in editor_core
    assert "type: 'url'" in editor_core
    assert "url: '/'" in editor_core
    assert "overridesById" in editor_core
    assert "notesById" in editor_core
    assert "moduleUiEditorBuildThomasShellDocument" not in editor_core
    assert "thomas_shell" not in editor_core
    assert "Thomas UI Shell" not in editor_core
    assert "Inspect the live Thomas UI" in editor_core
    assert "Selected Element" in editor_core
    assert "Visible Layers" in editor_core
    assert "Export Snapshot" in editor_core
    assert '[data-ui-editor-target-key="' in editor_core
    assert "Live Thomas UI" in editor_shell
    assert "thomas_shell" not in editor_shell
    assert "selected_key" in editor_shell
    assert "overrides_by_target" in editor_shell
    assert "notes_by_target" in editor_shell
    assert "applySelectionFields" in editor_shell
    assert "resetSelectionOverride" in editor_shell
    assert "persistProjects()" in editor_shell
    assert "Selected layer could not be rebound to the live DOM." in editor_shell
    assert "frameSandboxValue" in editor_shell
    assert "applyFrameSandbox" in editor_shell
    assert "if (trustedProject) {" in editor_shell
    assert "frame.removeAttribute('sandbox');" in editor_shell
    assert "loadProject(true);" in editor_shell


def test_ui_editor_rescue_loader_is_wired_into_app_boot() -> None:
    app_loader = _read_text("thomas/server/web/js/app.js")
    rescue_loader = _read_text("thomas/server/web/js/ui_editor_rescue.js")
    runtime_module_core = _read_text(
        "thomas/server/web/js/src/runtime_modules/063_module_studio_comfy_style_id_helpers.js"
    )
    runtime_module_shell = _read_text(
        "thomas/server/web/js/src/runtime_modules/063_module_studio_comfy_style_id_workspace.js"
    )
    runtime_editor = _read_many(
        [
            "thomas/server/web/js/src/runtime_modules/063_module_studio_comfy_style_id_bootstrap.js",
            "thomas/server/web/js/src/runtime_modules/063_module_studio_comfy_style_id_helpers.js",
            "thomas/server/web/js/src/runtime_modules/063_module_studio_comfy_style_id_workspace.js",
        ]
    )
    runtime_surface = _read_text("thomas/server/web/js/runtime/044_model_setup_settings_05.js")
    marketplace_html = _read_text("thomas/server/web/static/plugin_marketplace.html")
    marketplace_script = _read_text("thomas/server/web/static/plugin_marketplace.script01.js")
    assert "window.__thomasRuntimeReady" in app_loader
    assert "await window.__thomasRuntimeReady" in app_loader
    assert "startUiEditorRescueMode" in app_loader
    assert "ui_editor_rescue.js" in app_loader
    assert "generated/app_runtime_joined.mjs" not in app_loader
    assert "app_parts/" not in app_loader
    assert "Loading UI editor rescue mode" in app_loader
    assert "function moduleRenderWorkbenchAppBuilder" in runtime_editor
    assert "Live Thomas UI" in runtime_surface
    assert "Visible Layers" in runtime_surface
    assert "Export Snapshot" in runtime_surface
    assert "./modules/063_module_studio_comfy_style_id_helpers.js" in rescue_loader
    assert "./modules/063_module_studio_comfy_style_id_workspace.js" in rescue_loader
    assert "allow-scripts allow-forms allow-popups allow-modals" in runtime_surface
    assert "/static/static/plugin_marketplace.html" not in runtime_surface
    assert "Store Health" not in runtime_surface
    assert "Store Activity" not in runtime_surface
    assert "Feature Inventory" not in runtime_surface
    assert "Recent Store Activity" not in runtime_surface
    assert "thomas_shell" not in runtime_editor
    assert "moduleUiEditorBuildThomasShellDocument" not in runtime_editor
    assert "moduleUiEditorBuildThomasShellDocument" not in runtime_module_core
    assert "allow-scripts allow-same-origin allow-forms allow-popups allow-modals" not in runtime_module_core
    assert "thomas_shell" not in runtime_module_core
    assert "allow-scripts allow-same-origin allow-forms allow-popups allow-modals" not in runtime_module_shell
    assert "thomas_shell" not in runtime_module_shell
    assert "Thomas Companion" not in marketplace_html
    assert "/api/marketplace/plugins" in marketplace_script
    assert "/api/companion/v1/app-store" not in marketplace_script
    assert "startUiEditorRescueMode" in rescue_loader
    assert "UI Editor rescue mode is active." in rescue_loader
    assert "moduleRenderWorkbenchStudioOss" in rescue_loader
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
