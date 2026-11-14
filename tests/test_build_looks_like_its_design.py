"""Build wears the look it was designed in (handoff screen 3a).

The design for Build is the Dark palette, solid ground, a 256px sidebar that
speaks of tasks, a 46px header naming the project and the task, a
700px reading column, a 12px composer card with 32px controls and a 34px
primary button, and no chevrons anywhere. Before this, Build drew itself in
whatever theme Chat had last been given -- Nebula's starfield behind the
transcript, purple accents on Build's own controls -- so the screens the design
was drawn against never appeared.

`applyTheme` writes the chosen theme's tokens INLINE on #tc-shell, which is why
the forced palette has to be `!important`: a test that only read the stylesheet
could pass while the inline values won on screen. The browser half below reads
computed values off the real page for that reason.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"
CHAT_HTML = WEB / "chat.html"
TOKENS = WEB / "css" / "tokens.css"

# Section 3 of the build-redesign spec: the design's literal values ARE these.
BUILD_TOKENS = {
    "--c-bg": "#16181c",
    "--c-sidebar": "#101216",
    "--c-surface": "rgba(255, 255, 255, .035)",
    "--c-surface-2": "rgba(255, 255, 255, .07)",
    "--c-hover": "rgba(255, 255, 255, .055)",
    "--c-border": "rgba(255, 255, 255, .09)",
    "--c-border-2": "rgba(255, 255, 255, .15)",
    "--c-text": "#e7e9ee",
    "--c-strong": "#f7f8fa",
    "--c-dim": "rgba(231, 233, 238, .64)",
    "--c-muted": "rgba(231, 233, 238, .40)",
    "--c-accent": "#6e9bff",
    "--c-accent-ink": "#0b1020",
    "--c-accent-soft": "rgba(110, 155, 255, .14)",
    "--c-accent-line": "rgba(110, 155, 255, .42)",
    "--c-user-bg": "#2a2e36",
    "--c-composer-bg": "#1b1e23",
    "--c-menu-bg": "#22252b",
    "--c-success": "#47d7ac",
    "--c-warn": "#e2b25f",
    "--c-danger": "#ff9a9a",
    "--fc-add-ink": "#5fd38a",
    "--fc-add-tint": "rgba(63, 185, 80, .14)",
    "--fc-del-ink": "#f0867a",
    "--fc-del-tint": "rgba(248, 81, 73, .13)",
    "--c-code-bg": "#111316",
}
# The one Dark every page wears unless Light is chosen. It was Build's own block, selected by the mode, until
# 2026-11-10; its type and corners now sit in a second block that holds in Light as well.
BUILD_SELECTOR = ":where(html"


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css: str) -> list[tuple[str, str]]:
    return [
        (" ".join(m.group(1).split()), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_comments(css))
    ]


def _declarations(body: str) -> dict[str, str]:
    return {prop.strip(): value.strip() for prop, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)}


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value)


# -- tokens -----------------------------------------------------------------------


def test_every_palette_carries_the_prose_and_code_ground_tokens() -> None:
    palettes = [(sel, body) for sel, body in _blocks(TOKENS.read_text(encoding="utf-8")) if "--c-bg:" in body]
    assert len(palettes) >= 6, "expected Nebula, Dark, Light, Aurora, Sandstone and the Build block"
    missing = [
        f"{sel}: {token}"
        for sel, body in palettes
        for token in ("--c-strong", "--c-code-bg")
        if token not in _declarations(body)
    ]
    assert not missing, "a theme without its own value silently inherits another's: " + "; ".join(missing)


def test_build_forces_the_dark_palette_over_the_inline_theme() -> None:
    blocks = [(sel, body) for sel, body in _blocks(TOKENS.read_text(encoding="utf-8")) if BUILD_SELECTOR in sel]
    assert blocks, "tokens.css has no Build palette block"
    selector = blocks[0][0]
    tokens = {}
    for _sel, body in blocks:
        tokens.update(_declarations(body))
    wrong = []
    for token, value in BUILD_TOKENS.items():
        got = tokens.get(token, "")
        if not got.endswith("!important"):
            wrong.append(f"{token} is not !important (inline theme values would win): {got!r}")
        elif _squash(got.removesuffix("!important")) != _squash(value):
            wrong.append(f"{token}: {got!r} != {value!r}")
    assert not wrong, "; ".join(wrong)
    # chat_themes.js derives the five theme payloads from rules whose selector
    # starts with :root or names a data-thomas-theme. The Build block must be
    # neither, or Nebula's derived palette would come out Dark.
    assert not selector.startswith(":root"), selector
    assert "data-thomas-theme" not in selector, selector


# -- chat.html markup ---------------------------------------------------------------


def _html() -> str:
    return CHAT_HTML.read_text(encoding="utf-8")


def _tag(html: str, marker: str) -> str:
    start = html.rindex("<", 0, html.index(marker))
    return html[start : html.index(">", start) + 1]


def test_the_header_slot_sits_in_the_top_bar_with_its_two_fields() -> None:
    html = _html()
    bar = html[html.index('data-ui-id="chat.topbar"') : html.index("</header>")]
    assert 'id="tc-code-header"' in bar
    slot = bar[bar.index('id="tc-code-header"') :]
    slot = slot[: slot.index("</div>")]
    for field in ("data-code-header-project", "data-code-header-title"):
        assert field in slot, f"{field} is not inside #tc-code-header"
    # There is no such thing as a branch to show: the chip is gone, not hidden.
    assert "data-code-header-branch" not in html
    assert " hidden" in _tag(html, 'id="tc-code-header"'), "the slot must start hidden: it is Build's alone"
    # Shown and hidden with the mode, like the project chip beside the composer.
    changed = html[html.index("function modeChanged(") :]
    changed = changed[: changed.index("\n    }\n")]
    assert "codeHeader.hidden = nextMode !== 'code'" in changed


def test_the_composer_extras_mount_sits_directly_above_the_rail() -> None:
    html = _html()
    wrapper = html.index('data-ui-id="chat.composer"')
    extras = html.index('id="tc-code-composer-extras"')
    rail = html.index('id="tc-composer-rail"')
    assert wrapper < extras < rail
    between = html[html.index(">", extras) + 1 : html.rindex("<", 0, rail)]
    assert between.strip() == "</div>", f"something sits between the extras mount and the rail: {between!r}"
    assert " hidden" in _tag(html, 'id="tc-code-composer-extras"')


def test_the_new_modules_load_in_the_contract_order() -> None:
    html = _html()

    def at(name: str) -> int:
        return html.index(f"/static/{name}?")

    css = [
        "css/unified_code_results.css",
        "css/thomas_bot.css",
        "css/unified_code_agents.css",
        "css/unified_code_cards.css",
        "css/unified_code_composer.css",
    ]
    assert [at(name) for name in css] == sorted(at(name) for name in css)
    assert at("js/thomas_bot.js") < at("js/chat_theme_controls.js")
    agents, live_view = at("js/unified_code_agents.js"), at("js/unified_code_live_view.js")
    modules = [
        "js/unified_code_roster.js",
        "js/unified_code_drawer.js",
        "js/unified_code_agent_chat.js",
        "js/unified_code_cards.js",
        "js/unified_code_live_diff.js",
        "js/unified_code_composer.js",
    ]
    positions = [at(name) for name in modules]
    assert positions == sorted(positions)
    assert agents < positions[0] and positions[-1] < live_view


def test_no_chevron_and_no_ask_thomas_pill_survive() -> None:
    html = _html()
    for caret in ("ph-caret-down", "ph-caret-up", "tc-history-collapse"):
        assert caret not in html, f"{caret} is still in chat.html"
    shell_js = (WEB / "js" / "browser_shell.js").read_text(encoding="utf-8")
    shell_css = (WEB / "css" / "browser_shell.css").read_text(encoding="utf-8")
    assert "bt-askthomas" not in shell_js and "bt-askthomas" not in shell_css
    assert "Ask Thomas</button>" not in shell_js
    assert "openQuickChat" not in shell_js, "the pill's handler outlived the pill"


def test_the_nav_row_pill_rule_leaves_the_model_menu_alone() -> None:
    # #tc-model-menu sits inside [data-model-switch] and draws its provider and
    # model rows as <button>s with inline padding; an !important rule on every
    # descendant button flattened them in Chat and Work as well as Build.
    shell_css = re.sub(r"/\*.*?\*/", "", (WEB / "css" / "browser_shell.css").read_text(encoding="utf-8"), flags=re.S)
    rules = re.findall(r"([^{}]*\[data-model-switch\][^{}]*)\{([^}]*)\}", shell_css)
    forced = [selector.strip() for selector, body in rules if "!important" in body]
    assert forced, "the nav-row pill rules moved; re-point this test"
    for selector in forced:
        for part in selector.split(","):
            assert re.search(r"\[data-model-switch\]\s*>\s*(?:button|select)\b", part), part


def test_the_plus_menu_reads_in_the_design_order() -> None:
    html = _html()
    menu = html[html.index('id="tc-create-menu"') :]
    menu = menu[: menu.index("</div>")]
    assert re.findall(r'data-create-action="([a-z-]+)"', menu) == ["add-files", "image", "music", "video", "redesign"]
    assert re.findall(r"<span>([^<]+)</span>", menu) == [
        "Add files",
        "Create an image",
        "Make music",
        "Make a video",
        "Redesign with AI",
    ]


def test_the_tools_sheet_is_drawn_by_classes_build_can_restyle() -> None:
    panels = (WEB / "js" / "chat_composer_panels.js").read_text(encoding="utf-8")
    sheet = panels[panels.index("function renderToolsMenu(") : panels.index("function toggleToolsMenu(")]
    assert "cssText" not in sheet and "style.color" not in sheet, "inline styles outrank every rule Build has"
    for name in ("tc-tools-heading", "tc-tools-field", "tc-dial-desc", "tc-tools-memory"):
        assert name in sheet
    assert "setAttribute('aria-expanded'" in sheet
    shell_css = (WEB / "css" / "chat_shell.css").read_text(encoding="utf-8")
    for selector in (".tc-tools-heading", ".tc-tools-field select", ".tc-dial-desc", ".tc-tools-memory input"):
        assert selector in shell_css, f"{selector} lost its rule"


def test_the_sidebar_decorates_without_a_collapse_control() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the sidebar runtime proof")
    completed = subprocess.run(
        [
            node,
            str(ROOT / "tests" / "web_node" / "sidebar_history_without_collapse.mjs"),
            str(WEB / "js" / "sidebar_history.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert '"staleMarkupKeepsTheList":true' in completed.stdout


# -- the real page ---------------------------------------------------------------------

# Only errors raised from the files this look touches count here: other Build
# modules are drawn by other changes, and their failures belong to their tests.
OWN_FILES = (
    "chat.html",
    "sidebar_history.js",
    "chat_composer_panels.js",
    "unified_mode_shell.js",
    "thomas_icons.js",
    "chat_create_menu.js",
)

MEASURE = """() => {
  const q = s => document.querySelector(s);
  const box = s => { const r = q(s).getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; };
  return {
    bg: getComputedStyle(q('#tc-shell')).backgroundColor,
    rootBg: getComputedStyle(document.documentElement).getPropertyValue('--c-bg').trim(),
    worlds: Array.from(document.querySelectorAll('.tc-world')).map(w => getComputedStyle(w).display),
    sidebar: box('.tc-sidebar')[0],
    headerSlot: q('#tc-code-header').hidden,
    placeholder: q('#tc-input').placeholder,
    label: q('#tc-history-label').textContent,
    create: q('#tc-newchat').textContent.trim(),
  };
}"""


def test_build_is_dark_and_measured_and_chat_wears_the_same_dark() -> None:
    from playwright.sync_api import sync_playwright

    from tests.web_fixtures.thomas_chat_fixture import serve

    with serve() as fixture, sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        own_errors: list[str] = []

        def note(error) -> None:
            text = f"{error.message}\n{error.stack or ''}"
            if any(name in text for name in OWN_FILES):
                own_errors.append(text)

        page.on("pageerror", note)
        page.route(
            "**/*", lambda route: route.continue_() if route.request.url.startswith(fixture.url) else route.abort()
        )
        page.goto(fixture.url + "/?browser=0", wait_until="load")
        page.wait_for_timeout(800)

        chat = page.evaluate(MEASURE)
        # 2026-11-10: asked whether Chat should take Build's flat dark look or keep the chosen theme, you said
        # "Flat like Build". Chat used to be held to Nebula (rgb(7, 9, 18)) here. Its sidebar took Build's
        # 256px the same day, when the message box was given one place in every mode.
        assert chat["bg"] == "rgb(22, 24, 28)", "Chat wears the same Dark as Build"
        assert chat["sidebar"] == 256 and chat["headerSlot"] is True

        page.click('.tc-mode-button[data-thomas-mode="code"]')
        page.wait_for_function("() => document.getElementById('tc-shell').dataset.surfaceMode === 'code'")
        page.wait_for_timeout(300)
        build = page.evaluate(MEASURE)
        assert build["bg"] == "rgb(22, 24, 28)", "Build is not on the Dark ground; the inline theme won"
        assert build["rootBg"] == "#16181c", "menus appended to <body> would still wear the Chat theme"
        assert set(build["worlds"]) <= {"none"}, "the living world still shows behind Build"
        assert build["sidebar"] == 256
        assert build["headerSlot"] is False
        assert build["placeholder"] == "Message Thomas…"
        assert (build["label"], build["create"]) == ("Recent tasks", "New task")

        sizes = page.evaluate("""() => {
          const q = s => document.querySelector(s);
          const box = s => { const r = q(s).getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; };
          const header = q('#tc-code-header');
          q('[data-code-header-project]').textContent = 'habit-tracker';
          q('[data-code-header-title]').textContent = 'Habit tracker with streaks';
          // A row the way the integrator draws one: rowHtml plus the state class.
          const probe = document.createElement('div');
          probe.innerHTML = '<button type="button" class="tc-mode-history-row is-active is-running">'
            + window.ThomasSidebarHistory.rowHtml({ title: 'Habit tracker', preview: 'Step 4 of 5 · 3 agents', time: Date.now() })
            + '</button>';
          q('#tc-chats').appendChild(probe);
          const sub = probe.querySelector('.tc-history-sub');
          const out = {
            bar: box('header[data-ui-id="chat.topbar"]')[1],
            project: box('[data-code-header-project]')[1],
            branchChip: !!q('[data-code-header-branch]'),
            titleBorder: getComputedStyle(q('[data-code-header-title]')).borderTopWidth,
            titleLeft: q('[data-code-header-title]').getBoundingClientRect().left - q('[data-code-header-project]').getBoundingClientRect().right,
            card: getComputedStyle(q('.tc-composer-card')).borderRadius,
            send: box('#tc-send'),
            attach: box('#tc-attach-btn'),
            icon: box('.tc-mode-button[data-thomas-mode="code"] svg'),
            rail: box('#tc-composer-rail')[0],
            subHeight: Math.round(sub.getBoundingClientRect().height),
            subText: sub.querySelector('.tc-history-preview').getBoundingClientRect().width > 0,
            mark: getComputedStyle(probe.firstChild, '::before').backgroundColor,
          };
          probe.remove();
          return out;
        }""")
        assert sizes["bar"] == 46 and sizes["project"] == 26
        assert sizes["branchChip"] is False, "the branch chip is gone"
        assert sizes["titleBorder"] == "0px", "the chat name is plain text, with no bubble"
        assert 0 <= sizes["titleLeft"] < 40, "the chat name sits beside the project chip"
        assert sizes["card"] == "12px"
        assert sizes["send"] == [34, 34] and sizes["attach"] == [32, 32]
        assert sizes["icon"] == [18, 18]
        assert sizes["rail"] <= 860
        assert sizes["subHeight"] == 16 and sizes["subText"], "a task row's sub-label collapsed to nothing"
        assert sizes["mark"] == "rgb(110, 155, 255)", "the running task has no pulsing accent dot"

        page.click("#tc-tools-btn")
        tools = page.evaluate("""() => ({
          expanded: document.getElementById('tc-tools-btn').getAttribute('aria-expanded'),
          heading: getComputedStyle(document.querySelector('.tc-tools-heading')).fontFamily,
          radius: getComputedStyle(document.getElementById('tc-tools-menu')).borderRadius,
        })""")
        assert tools["expanded"] == "true" and "JetBrains Mono" not in tools["heading"] and tools["radius"] == "10px"
        page.click("#tc-tools-btn")
        assert page.get_attribute("#tc-tools-btn", "aria-expanded") == "false"

        # Collapsing the narrower Build sidebar must not drag the column off screen.
        page.click("#tc-sidebar-toggle")
        page.wait_for_timeout(400)
        assert page.evaluate("() => Math.round(document.querySelector('main').getBoundingClientRect().left)") == 0
        page.click("#tc-sidebar-toggle")

        page.click('.tc-mode-button[data-thomas-mode="chat"]')
        page.wait_for_function("() => document.getElementById('tc-shell').dataset.surfaceMode === 'chat'")
        page.wait_for_timeout(300)
        back = page.evaluate(MEASURE)
        assert back["bg"] == "rgb(22, 24, 28)" and back["sidebar"] == 256 and back["headerSlot"] is True
        assert not own_errors, own_errors
        browser.close()
