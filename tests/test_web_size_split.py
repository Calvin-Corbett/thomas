"""The extracted web assets remain reachable from their original pages.

The System Map page is gone, so nothing here checks it any more. A change to ``thomas.server.rows.system_map`` or to
``thomas.server.system_map_routes`` still runs this file, so the extracted assets of the pages that remain keep being
checked beside it.
"""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"


def test_settings_extracted_assets_load_at_the_original_positions() -> None:
    page = (WEB / "settings.html").read_text(encoding="utf-8")
    icons = WEB / "css" / "settings_icons.css"
    autonomy = WEB / "settings.autonomy-panel.js"
    assert icons.is_file() and ".ph-gear::before" in icons.read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/static/css/settings_icons.css">' in page
    assert autonomy.is_file() and 'id="autonomy"' in autonomy.read_text(encoding="utf-8")
    assert 'id="privacy"' in (WEB / "settings.privacy-panel.js").read_text(encoding="utf-8")
    assert 'id="appearance"' in (WEB / "settings.appearance-panel.js").read_text(encoding="utf-8")
    assert page.index("/static/settings.autonomy-panel.js") < page.index("/static/settings.privacy-panel.js")
    assert page.index("/static/settings.privacy-panel.js") < page.index("/static/settings.appearance-panel.js")


def test_chat_settings_loads_advanced_interface_before_main_template() -> None:
    page = (WEB / "index.html").read_text(encoding="utf-8")
    template = (WEB / "js" / "templates" / "tpl_settings.js").read_text(encoding="utf-8")
    interface = (WEB / "js" / "templates" / "tpl_settings_interface.js").read_text(encoding="utf-8")
    assert "Advanced Interface + Developer" in interface
    assert interface.startswith("window.__settingsInterfaceTemplate = `")
    assert "${window.__settingsInterfaceTemplate}" in template
    assert page.index("/static/js/templates/tpl_settings_interface.js") < page.index(
        "/static/js/templates/tpl_settings.js"
    )


def test_extracted_classic_modal_and_runtime_sections_load_in_order() -> None:
    page = (WEB / "index.html").read_text(encoding="utf-8")
    model_setup = (WEB / "js" / "templates" / "tpl_model_setup.js").read_text(encoding="utf-8")
    runtime = (WEB / "js" / "templates" / "tpl_settings_runtime.js").read_text(encoding="utf-8")
    template = (WEB / "js" / "templates" / "tpl_settings.js").read_text(encoding="utf-8")
    assert 'id="modelSetupModal"' in model_setup
    assert template.count("${window.__settingsRuntimeTemplate}") == 1
    assert "Advanced Runtime + Quality" in runtime and "Advanced Memory + Retrieval" in runtime
    assert page.index("/static/js/templates/tpl_model_setup.js") < page.index("/static/js/app_runtime_loader.js")
    assert page.index("/static/js/templates/tpl_settings_runtime.js") < page.index(
        "/static/js/templates/tpl_settings.js"
    )
