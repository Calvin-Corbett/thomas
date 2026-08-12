"""Client-side contracts for point-at-anything redesign.

Two of these encode bugs found by driving a real browser, not by reading code:

* Undoing a style must RESTORE the author's inline value, not blank the
  property. chat.html styles most of the shell inline, so clearing font-size
  on the welcome heading deleted its authored clamp() and shrank it for good.
* Styles must be written with !important, or a shell rule that carries
  !important silently wins and the change lands in the style attribute
  without ever appearing on screen.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"


def _read(name: str) -> str:
    return (WEB / "js" / name).read_text(encoding="utf-8", errors="replace")


def test_undoing_a_style_restores_the_authored_inline_value() -> None:
    layout = _read("ui_edit_layout.js")

    assert "const styleBases = new WeakMap()" in layout
    assert "function rememberStyle(" in layout
    assert "function restoreStyle(" in layout
    # The old implementation blanked the property. If this reappears, an
    # author's inline font-size/clamp() is destroyed by a reset.
    assert 'applied.forEach((prop) => { node.style[prop] = ""; })' not in layout
    assert "restoreStyle(node, prop)" in layout
    assert "node.style.getPropertyPriority(name)" in layout


def test_styles_are_written_important_so_they_actually_show() -> None:
    layout = _read("ui_edit_layout.js")

    assert 'node.style.setProperty(kebab(prop), value, "important")' in layout
    assert "function kebab(" in layout
    # hidden must go through the same path, or hiding a .hv-* control fails.
    assert 'writeStyle(node, "display", "none")' in layout


def test_any_element_can_be_addressed_by_a_minted_identity() -> None:
    target = _read("ui_redesign_target.js")
    layout = _read("ui_edit_layout.js")

    assert "const SYNTH = '~~'" in target
    assert "const minted =" in target
    # The layout book has to resolve and apply those addresses, and drop the
    # styling again when the entry is removed.
    assert "function resolveSynthetic(" in layout
    assert "function applySyntheticNode(" in layout
    assert "[data-ui-synth]" in layout


def test_a_target_never_borrows_its_containers_identity() -> None:
    target = _read("ui_redesign_target.js")

    # uiId is the element's own id or a minted one — never the ancestor's,
    # which would restyle the whole container instead of what was clicked.
    assert "uiId: exact ? (layout ? layout.identity(node)" in target
    assert "ownerUiId," in target


def test_clicking_inside_a_control_selects_the_control() -> None:
    target = _read("ui_redesign_target.js")

    # The icon inside the Settings button is not independently meaningful;
    # an area guard alone refused to promote it and the click read as
    # "not addressable".
    assert "const ATOMIC = 'button, a, [role=\"button\"], label, summary'" in target
    assert "region.matches(ATOMIC)" in target
    # Containers still need the size guard, or small print in the sidebar
    # would select the whole sidebar.
    assert "area(region) <= area(node) * MAX_PROMOTE_GROWTH" in target


def test_icons_are_their_own_target_not_swallowed_by_the_button() -> None:
    target = _read("ui_redesign_target.js")

    assert "const ICONISH =" in target
    # Checked BEFORE the atomic-control promotion, or the icon becomes the button.
    assert target.index("if (node.matches(ICONISH)) return node;") < target.index("region.matches(ATOMIC)")
    assert "isIcon: isIcon(node)" in target
    assert "icon: iconName(node)" in target


def test_the_icon_vocabulary_is_read_from_the_stylesheet() -> None:
    target = _read("ui_redesign_target.js")

    assert "function iconVocabulary()" in target
    assert "ph-[a-z0-9-]+)::?before" in target
    # In Chrome with CSS nesting every style rule has an (empty) cssRules list,
    # so recursing on its mere presence skipped every rule and found nothing.
    assert "if (rule.cssRules && rule.cssRules.length) walk(rule.cssRules);" in target
    assert "const selector = String(rule.selectorText || '');" in target


def test_an_icon_that_does_not_render_is_rolled_back_and_reported() -> None:
    target = _read("ui_redesign_target.js")
    select = _read("ui_redesign_select.js")

    # chat_shell.css maps .ph-<name> to a literal glyph; an unknown name falls
    # through to the bullet and looks like a broken button rather than an error.
    assert "function iconRendersAsFallback(" in target
    assert "=== '\\u2022'" in target or "text === '•'" in target
    assert "iconRendersAsFallback(element)" in select
    assert "is not in Thomas's icon set" in select


def test_every_change_records_a_version_that_can_be_reverted() -> None:
    layout = _read("ui_edit_layout.js")
    select = _read("ui_redesign_select.js")

    assert "function pushVersion(" in layout
    assert "function revert(" in layout
    assert "function versionCount(" in layout
    # normalizeSlot rebuilds the slot from a fixed field list; omitting
    # `versions` silently wiped the undo stack on the next ensureSlot call.
    assert "versions: slot.versions && typeof slot.versions === \"object\"" in layout
    assert "layout.pushVersion(uiId)" in select
    # The Revert button only appears when something selected can actually move.
    assert "function editedPicks()" in select
    assert 'data-tr="revert"' in select
    assert "Nothing to roll back" in select


def test_redesign_mode_looks_like_build_mode() -> None:
    css = (WEB / "css" / "ui_redesign.css").read_text(encoding="utf-8", errors="replace")
    select = _read("ui_redesign_select.js")

    # A hammer, so it is obvious you are building — especially when Thomas
    # turned the mode on and you did not press the button yourself.
    assert "html.tr-selecting" in css
    assert "image/svg+xml" in css
    assert ".tr-banner" in css
    assert 'class="tr-banner" role="status"' in select
    assert "Redesign mode" in select


def test_thomas_can_arm_redesign_mode_through_a_structured_capability() -> None:
    html = (WEB / "chat.html").read_text(encoding="utf-8", errors="replace")

    # Natural-language UI control was removed on purpose; the shell must act on
    # the tool NAME from the stream, never on anything Thomas says in prose.
    assert "evt.name === 'ui.redesign'" in html
    assert "window.ThomasRedesign.start()" in html


def test_the_selector_reports_rather_than_guesses() -> None:
    select = _read("ui_redesign_select.js")

    assert "function applyLayout(" in select
    # Counts come from a real diff, not from what the model proposed.
    assert "if (JSON.stringify(merged) === before) return;" in select
    assert "Thomas returned no edit for this one" in select
    assert "Nothing changed." in select
