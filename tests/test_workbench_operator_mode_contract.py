from pathlib import Path

from tests.web_ui_source import read_app_js_source


def test_agents_startup_includes_workbench_operator_protocol():
    text = Path("AGENTS.md").read_text(encoding="utf-8")
    assert "docs/WORKBENCH_OPERATOR_PROTOCOL.md" in text
    assert "tabs are AI-first operator control surfaces" in text


def test_workbench_operator_mode_copy_present_in_web_ui_runtime():
    text = read_app_js_source()
    assert "MODULE_WORKBENCH_OPERATOR_COPY" in text
    assert "Operator Mode" in text
    assert "Thomas executes the work in the background." in text


def test_workbench_operator_protocol_doc_exists_with_future_tab_baseline():
    text = Path("docs/WORKBENCH_OPERATOR_PROTOCOL.md").read_text(encoding="utf-8")
    assert "Future tab baseline" in text
    assert "user-created tabs" in text
    assert "Thomas performs the execution work." in text
