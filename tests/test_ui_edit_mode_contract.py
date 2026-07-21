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
    assert "clone(ensureMap(read(), currentPoint()))" in layout
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

    assert 'const KEY = "thomas_ui_layout_v1"' in layout
    assert "book.workspaces[workspace()][currentPoint()]" in layout
    assert "localStorage.setItem(KEY" in layout
    for capability in ("undo", "redo", "snap", "lock", "reset-view", "export"):
        assert f'data-action=\"{capability}\"' in editor


def test_editor_chrome_is_absent_from_normal_chat() -> None:
    chat = _read(WEB / "chat.html")

    assert "/static/js/ui_edit_mode.js" not in chat
    assert "/static/css/ui_edit_mode.css" not in chat
    assert ">Edit UI<" not in chat
    assert "label: 'Canvas'" in chat
    assert "label: 'UI Editor'" not in chat


def test_ui_edit_mode_standard_names_every_modernized_workspace_and_gate() -> None:
    standard = _read(ROOT / "docs" / "UI_EDIT_MODE_STANDARD.md")
    plan = _read(ROOT / "plans" / "thomas" / "tasks" / "ui-modernization-20260721" / "PLAN.md")
    combined = f"{standard}\n{plan}"

    for workspace in (
        "Mission Control",
        "Virtual Office",
        "Canvas",
        "My Stuff",
        "Channels",
        "Token Economy",
        "Marketplace",
        "Settings",
    ):
        assert workspace in combined
    for proof in ("survives reload", "breakpoint", "prevents accidental", "accessible focus"):
        assert re.search(proof, combined, re.IGNORECASE)
