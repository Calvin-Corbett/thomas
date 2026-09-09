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


def test_a_protected_region_is_refused_at_pick_with_edit_modes_wording() -> None:
    target = _read("ui_redesign_target.js")
    select = _read("ui_redesign_select.js")

    assert "policy: String(node.dataset.uiPolicy || (owner ? owner.dataset.uiPolicy : '') || '')" in target
    assert "/\\b(protected|no-edit)\\b/.test(String(descriptor.policy || ''))" in select
    assert "is protected`" in select
    assert "const stockSource = /^thomas\\/server\\/web\\//" in select
    assert "&& !stockSource" in select
    # Refused BEFORE the pick lands, so no model call and no local restyle ever happens.
    assert select.index("is protected`") < select.index("state.picks.push({ descriptor, element })")


def test_browser_refresh_is_pointable_when_redesign_will_edit_its_stock_source() -> None:
    browser_shell = (WEB / "js" / "browser_shell.js").read_text(encoding="utf-8")

    assert 'data-ui-id="browser.action.reload"' in browser_shell
    assert 'data-ui-policy="protected source-edit"' in browser_shell
    assert 'data-redesign-source="thomas/server/web/js/browser_shell.js"' in browser_shell


def test_apply_records_what_it_changed_in_the_overlay_and_says_where_it_landed() -> None:
    select = _read("ui_redesign_select.js")

    assert "applyLayout(data.layout, iconRejected, applied)" in select
    assert "overlay.record({ actor: 'redesign', instruction" in select
    assert "kind: 'element', address: `element:${workspace}:${point}:${row.uiId}`" in select
    assert "kind: 'token', address: `token:${themeName}:${key}`" in select
    assert "kind: 'identity', address: `identity:${field}`" in select
    assert "theme: (((document.getElementById('tc-shell') || {}).dataset) || {}).theme || 'nebula'" in select
    # Honest result lines: saved with its revision, or kept in this browser with the reason.
    assert "Saved to your overlay (rev ${reply.rev}) - applies on every tab and every reload" in select
    assert "notApplied('this server predates the overlay endpoint; restart it and Apply again')" in select
    assert "`Kept in this browser only - ${reason}.${themeNote}` : `Not applied - ${reason}.`" in select
    # A rolled-back icon is not recorded, and an accepted element leaves the local book.
    assert "what was rolled back is not recorded" in select
    assert "layout.forgetLocal(address.slice(prefix.length))" in select, (
        "pruning after a save drops the local copy only, never the overlay entry"
    )


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
    assert 'versions: slot.versions && typeof slot.versions === "object"' in layout
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


def test_a_text_record_changes_what_the_element_says_and_a_removed_one_restores_it() -> None:
    """Redesign can change what an element SAYS (2026-09-06).

    You asked that AI Redesign be able to change anything. "Change its label to
    Start a build" turned the button green and left the label alone, because
    nothing carried the words from the plan to the element. The layout runtime
    now applies ``text`` to the element's own text runs, keeps the icon, and
    puts the stock words back exactly when the record goes away.
    """
    import json
    import subprocess

    harness = ROOT / "tests" / "web_node" / "ui_edit_layout_text.mjs"
    out = subprocess.run(
        ["node", str(harness), str(WEB / "js" / "ui_edit_layout.js")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["changed"].strip() == "Start a build"
    assert got["restored"] == "\n  \n  New build\n", got  # every stock run back, whitespace included
    assert got["restoredCount"] == 3
    assert got["bareChanged"] == "New"
    assert got["bareRestored"] == "" and got["bareCount"] == 1, got  # the appended run is gone again


def test_the_redesign_client_carries_text_from_the_plan_to_the_record() -> None:
    select = _read("ui_redesign_select.js")
    assert "merged.text = " in select, (
        "applyLayout drops entry.text, so a planned label change never reaches the overlay"
    )
