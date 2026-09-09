"""tokens.css is the single source for status colour, scrollbars and controls.

The audit found the same meanings hand-painted per page: mission invented
--c-positive/#47d7ac, settings invented --c-danger/#ff7a86, Code mode carried
var(--c-danger, #ff9a9a) fallbacks against tokens that existed only inside
chat.html's THEMES JS map. Meanwhile the global scrollbar in tokens.css was a
dark-theme literal, so the two light worlds got dark scrollbars.

These tests pin the fix at the source:

* every theme block in tokens.css defines --c-danger/--c-warn/--c-success and
  --c-scroll-track/--c-scroll-thumb;
* the status colours are legible on their own theme's background (contrast,
  not a hex pin -- retuning the palette must not go red, an unreadable colour
  must);
* the global scrollbar rules consume the tokens and the old dark literals are
  gone from tokens.css;
* the .t-btn standard is the REAL Chat profile (filled accent, 38px, radius
  10, Manrope 12-13/650-700), not the dead "skinny" outline that had exactly
  one consumer product-wide;
* the audited winner components (.status-pill, .empty-state, .loading-state,
  .t-input) live once, in shared_components.css, reached from tokens.css;
* the generic .thomas-modal core lives in modals.css, not in a file named
  chat-game-animations.css.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"
TOKENS = WEB / "css" / "tokens.css"
SHARED = WEB / "css" / "shared_components.css"
MODALS = WEB / "css" / "modals.css"
GAME_ANIMATIONS = WEB / "css" / "component_styles" / "chat-game-animations.css"

STATUS_TOKENS = ("--c-danger", "--c-warn", "--c-success")
SCROLL_TOKENS = ("--c-scroll-track", "--c-scroll-thumb")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _theme_blocks() -> dict[str, str]:
    """Every tokens.css block that carries a palette (defines --c-bg).

    The first :root block is the canonical Nebula palette; the legacy-bridge
    :root defines no --c-bg and is excluded, which is the point -- status
    tokens belong in the THEME blocks, not only in a bridge.
    """

    css = _strip_comments(TOKENS.read_text(encoding="utf-8"))
    blocks: dict[str, str] = {}
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector = " ".join(match.group(1).split())
        body = match.group(2)
        if "--c-bg:" in body:
            blocks[selector] = body
    return blocks


def _declarations(body: str) -> dict[str, str]:
    return {
        prop.strip(): value.strip()
        for prop, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)
    }


def _luminance(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    adjusted = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]


def _ratio(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# ── (1) semantic status + scrollbar tokens in every theme ────────────────────


def test_every_theme_block_defines_the_status_tokens() -> None:
    blocks = _theme_blocks()
    assert len(blocks) >= 5, f"expected the five theme palettes, found {sorted(blocks)}"

    missing: list[str] = []
    for selector, body in blocks.items():
        tokens = _declarations(body)
        for token in STATUS_TOKENS + SCROLL_TOKENS:
            if token not in tokens:
                missing.append(f"{selector}: {token}")
    assert not missing, (
        "a theme without its own status/scrollbar tokens silently inherits "
        "another theme's colours: " + "; ".join(missing)
    )


def test_the_status_colours_are_legible_on_their_own_background() -> None:
    bad: list[str] = []
    for selector, body in _theme_blocks().items():
        tokens = _declarations(body)
        background = tokens.get("--c-bg", "")
        if not background.startswith("#"):
            continue
        for token in STATUS_TOKENS:
            value = tokens.get(token, "")
            if not value.startswith("#"):
                continue
            ratio = _ratio(value, background)
            if ratio < 4.5:
                bad.append(f"{selector} {token}: {value} on {background} = {ratio:.2f}:1")
    assert not bad, (
        "a status colour nobody can read is the same as no status colour; "
        "below 4.5:1 -> " + "; ".join(bad)
    )


def test_the_warning_alias_bridges_the_old_name() -> None:
    css = _strip_comments(TOKENS.read_text(encoding="utf-8"))
    assert re.search(r"--c-warning\s*:\s*var\(\s*--c-warn\s*\)", css), (
        "--c-warning must alias var(--c-warn) during migration -- pages still "
        "using the long name would otherwise go colourless"
    )


# ── (2) scrollbars come from the tokens, not dark literals ───────────────────


def test_the_global_scrollbar_consumes_the_theme_tokens() -> None:
    css = _strip_comments(TOKENS.read_text(encoding="utf-8"))

    match = re.search(r"scrollbar-color\s*:\s*([^;]+);", css)
    assert match, "tokens.css lost its global scrollbar-color rule"
    assert "var(--c-scroll-thumb)" in match.group(1) and "var(--c-scroll-track)" in match.group(1), (
        f"scrollbar-color is not driven by the theme tokens: {match.group(1).strip()}"
    )

    track = re.search(r"::-webkit-scrollbar-track\s*\{([^}]*)\}", css)
    assert track and "var(--c-scroll-track)" in track.group(1), (
        "the webkit scrollbar track does not consume --c-scroll-track"
    )
    thumb = re.search(r"::-webkit-scrollbar-thumb\s*\{([^}]*)\}", css)
    assert thumb and "var(--c-scroll-thumb)" in thumb.group(1), (
        "the webkit scrollbar thumb does not consume --c-scroll-thumb"
    )


def test_the_dark_scrollbar_literals_are_gone_from_the_rules() -> None:
    """rgba(17,20,26,...) / rgba(173,179,194,...) were the dark-theme scrollbar.

    They may survive only as the VALUES of the dark themes' own scroll tokens,
    never inside a rule -- that is exactly what painted dark scrollbars onto
    the light worlds.
    """

    css = _strip_comments(TOKENS.read_text(encoding="utf-8"))
    # Drop custom-property declarations; what remains are real rule declarations.
    rules_only = re.sub(r"--[\w-]+\s*:\s*[^;]+;", "", css)
    flat = re.sub(r"\s+", "", rules_only)
    for literal in ("rgba(17,20,26", "rgba(173,179,194"):
        assert literal not in flat, (
            f"{literal}… is hard-coded in a rule again; light themes get dark "
            "scrollbars. Route it through --c-scroll-track/--c-scroll-thumb."
        )


# ── (3) the .t-btn standard is the Chat profile ──────────────────────────────


def _t_btn_body() -> str:
    css = _strip_comments(TOKENS.read_text(encoding="utf-8"))
    match = re.search(r"(?:^|\s)\.t-btn\s*\{([^}]*)\}", css)
    assert match, "tokens.css no longer defines .t-btn"
    return match.group(1)


def _resolved(body: str, prop: str) -> str:
    """A .t-btn declaration, following one level of var() into :root tokens."""

    match = re.search(rf"{prop}\s*:\s*([^;]+);", body)
    assert match, f".t-btn has no {prop}"
    value = match.group(1).strip()
    var = re.fullmatch(r"var\(\s*(--[\w-]+)\s*\)", value)
    if var:
        css = _strip_comments(TOKENS.read_text(encoding="utf-8"))
        token = re.search(rf"{var.group(1)}\s*:\s*([^;]+);", css)
        assert token, f".t-btn {prop} references undefined {var.group(1)}"
        value = token.group(1).strip()
    return value


def _raw(body: str, prop: str) -> str:
    match = re.search(rf"{prop}\s*:\s*([^;]+);", body)
    assert match, f".t-btn has no {prop}"
    return match.group(1).strip()


def test_t_btn_is_the_filled_chat_profile() -> None:
    body = _t_btn_body()
    assert _raw(body, "background") == "var(--c-accent)", (
        ".t-btn must be the FILLED accent button the Chat surface ships, "
        "not an outline"
    )
    assert _raw(body, "color") == "var(--c-accent-ink)", (
        ".t-btn text must be --c-accent-ink on the accent fill"
    )


def test_t_btn_pins_the_chat_numbers() -> None:
    body = _t_btn_body()

    min_height = float(_resolved(body, "min-height").rstrip("px"))
    assert min_height == 38, f".t-btn min-height is {min_height}px, the Chat standard is 38px"

    radius = float(_resolved(body, "border-radius").rstrip("px"))
    assert radius in (9, 10), f".t-btn radius is {radius}px, the Chat standard is 9-10px"

    size = float(_resolved(body, "font-size").rstrip("px"))
    assert 12 <= size <= 13, f".t-btn font-size is {size}px, the Chat standard is 12-13px"

    weight = float(_resolved(body, "font-weight"))
    assert 650 <= weight <= 700, f".t-btn weight is {weight}, the Chat standard is 650-700"

    assert "Manrope" in _resolved(body, "font-family"), ".t-btn must speak Manrope"


def test_t_btn_quiet_is_transparent_with_the_hairline_border() -> None:
    css = _strip_comments(TOKENS.read_text(encoding="utf-8"))
    match = re.search(r"\.t-btn-quiet[^{]*\{([^}]*)\}", css)
    assert match, "the quiet variant (.t-btn-quiet) is missing"
    body = match.group(1)
    assert re.search(r"background\s*:\s*transparent", body), ".t-btn-quiet must be transparent"
    assert "var(--c-border)" in body, ".t-btn-quiet must use the --c-border hairline"


# ── (4) the audited winners live once, reachable from tokens.css ─────────────


def test_tokens_css_pulls_in_the_shared_components() -> None:
    css = TOKENS.read_text(encoding="utf-8")
    assert re.search(r"@import\s+url\(\s*['\"]?\./shared_components\.css", css), (
        "tokens.css must @import shared_components.css so every page that "
        "links tokens gets the shared classes with no HTML edits"
    )
    assert SHARED.exists(), "shared_components.css does not exist"


def test_the_shared_components_carry_the_audited_winners() -> None:
    css = _strip_comments(SHARED.read_text(encoding="utf-8"))

    for cls in (".status-pill", ".empty-state", ".loading-state", ".t-input"):
        assert re.search(rf"{re.escape(cls)}[^{{}}]*\{{", css), f"{cls} is not defined"

    pill = re.search(r"\.status-pill[^{}]*\{([^}]*)\}", css)
    assert pill and "999px" in pill.group(1), ".status-pill lost its pill radius"
    for state in ("is-success", "is-warning", "is-danger"):
        assert state in css, f".status-pill.{state} state is missing"
    for token in STATUS_TOKENS:
        assert f"var({token})" in css, f"the pill states must consume {token}"

    empty = re.search(r"\.empty-state[^{}]*\{([^}]*)\}", css)
    assert empty and "dashed" in empty.group(1), (
        ".empty-state lost the dashed border that marks 'nothing here yet'"
    )

    t_input = re.search(r"\.t-input[^{}]*\{([^}]*)\}", css)
    assert t_input, ".t-input is not defined"
    body = t_input.group(1)
    assert re.search(r"border-radius\s*:\s*9px", body), ".t-input radius is pinned at 9px"
    assert "var(--c-composer-bg)" in body, ".t-input background is --c-composer-bg"
    assert "var(--c-border-2)" in body, ".t-input border is --c-border-2"
    assert re.search(r"font-size\s*:\s*13px", body), ".t-input font-size is pinned at 13px"


# ── (5) the generic modal lives in modals.css ────────────────────────────────


def test_the_modal_core_moved_out_of_the_game_animations_file() -> None:
    game = _strip_comments(GAME_ANIMATIONS.read_text(encoding="utf-8"))
    for selector in (".thomas-modal", ".modal-content", ".modal-header", ".modal-backdrop"):
        assert not re.search(rf"{re.escape(selector)}[^{{}}]*\{{", game), (
            f"{selector} is still defined in chat-game-animations.css -- the "
            "generic modal is not a game animation; it belongs in modals.css"
        )

    modals = _strip_comments(MODALS.read_text(encoding="utf-8"))
    for selector in (".thomas-modal", ".modal-backdrop", ".modal-content", ".modal-header"):
        assert re.search(rf"{re.escape(selector)}[^{{}}]*\{{", modals), (
            f"modals.css does not define {selector}"
        )

    content = re.search(r"\.modal-content\s*\{([^}]*)\}", modals)
    assert content and "max-height" in content.group(1), (
        "the viewport containment (max-height on .modal-content) was lost in "
        "the move -- footers become unreachable on laptop heights again"
    )
