from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_shared_editor_carries_the_owner_hotkeys_and_live_component_contract() -> None:
    editor = _read(WEB / "js" / "ui_edit_mode.js")
    layout = _read(WEB / "js" / "ui_edit_layout.js")

    assert 'event.key.toLowerCase() === "e" && event.ctrlKey && event.shiftKey' in editor
    assert 'event.key === "Tab" && event.shiftKey' in editor
    assert 'event.key === "Escape"' in editor
    assert '["nw", "n", "ne", "e", "se", "s", "sw", "w"]' in editor
    assert 'event.altKey && p.resize' in editor
    assert 'event.preventDefault(); event.stopImmediatePropagation()' in editor
    assert 'node.style.translate' in layout
    assert "clone(editing ? slot.draft : slot.saved)" in layout
    assert 'BREAKPOINTS = ["desktop", "tablet", "mobile"]' in layout
    assert 'protected: protectedNode' in layout
    assert 'collision: parts.includes("collision=avoid")' in layout
    assert 'return id && key ? `${id}::${key}` : id;' in layout
    assert "L.get(selectedId())" in editor
    assert "const map = currentMap();" in layout
    assert "requestAnimationFrame(() => { applyFrame = 0; applyAll(); })" in layout
    assert 'if (current.locked) { flash("Unlock this region to change it"); return; }' in editor
    assert "Math.min(p.maxWidth, box.width" in editor
    assert "Math.min(p.maxHeight, box.height" in editor
    assert 'flash("That change would overlap another region")' in editor


def test_shared_editor_has_one_persisted_breakpoint_aware_layout_book() -> None:
    layout = _read(WEB / "js" / "ui_edit_layout.js")
    editor = _read(WEB / "js" / "ui_edit_mode.js")

    assert 'const KEY = "thomas_ui_layout_v2"' in layout
    assert 'const LEGACY_KEY = "thomas_ui_layout_v1"' in layout
    assert "book.workspaces[key][point]" in layout
    assert "localStorage.setItem(KEY" in layout
    for capability in ("undo", "redo", "snap", "lock", "reset-view", "export", "front", "back", "cancel", "done"):
        assert f'data-action=\"{capability}\"' in editor
    for capability in ("beginDraft", "commitDraft", "cancelDraft", "restorePrevious", "isDirty"):
        assert capability in layout
    assert "node.style.zIndex" in layout
    assert "Done &amp; Save" in editor
    assert "Discard draft" in editor
    assert "AI edit this region" in editor
    assert "thomas:ui-ai-edit" in editor
    assert 'data-inspector="regions"' in editor


def test_editor_is_hotkey_available_but_chrome_is_absent_from_normal_chat() -> None:
    chat = _read(WEB / "chat.html")
    css = _read(WEB / "css" / "ui_edit_mode.css")

    assert "/static/js/ui_edit_mode.js" in chat
    assert "/static/css/ui_edit_mode.css" in chat
    assert ">Edit UI<" not in chat
    assert ".thomas-ui-edit-entry {" in css
    assert "display: none" in css
    assert "label: 'Canvas'" in chat
    assert "label: 'UI Editor'" not in chat
    assert 'data-ui-id="chat.action.canvas" data-ui-label="Canvas button" data-ui-policy="control"' in chat
    assert 'data-ui-id="chat.action.canvas" data-ui-label="Canvas button" data-ui-policy="control protected"' not in chat


def test_ui_edit_mode_standard_names_every_modernized_workspace_and_gate() -> None:
    standard = _read(ROOT / "docs" / "UI_EDIT_MODE_STANDARD.md")
    plan = _read(ROOT / "plans" / "thomas" / "tasks" / "ui-modernization-20260721" / "PLAN.md")
    combined = f"{standard}\n{plan}"

    for workspace in (
        "Mission Control",
        "Virtual Office",
        "Canvas",
        "Library",
        "Channels",
        "Token Economy",
        "Marketplace",
        "Settings",
    ):
        assert workspace in combined
    for proof in ("survives reload", "breakpoint", "prevents accidental", "accessible focus"):
        assert re.search(proof, combined, re.IGNORECASE)
