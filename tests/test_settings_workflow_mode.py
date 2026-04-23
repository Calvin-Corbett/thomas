from __future__ import annotations

from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_settings_page_exposes_workflow_mode() -> None:
    html = (_root() / "thomas" / "server" / "web" / "settings.html").read_text(encoding="utf-8")
    script = (_root() / "thomas" / "server" / "web" / "settings.script01.js").read_text(encoding="utf-8")

    assert "Workflow Mode" in html
    assert "workflowMode" in html
    assert "Guided workflow (Recommended)" in html
    assert "workflowMode: 'guided'" in script
    assert "workflow_mode: mergedLegacy.workflowMode || defaults.workflowMode" in script
