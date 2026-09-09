"""No icon in the glyph map may be an emoji-presentation codepoint.

The icons are a hand-written map in chat_shell.css: one Unicode codepoint per
`ph-*` name, drawn through `::before`. Some codepoints are *emoji presentation by
default*, so the browser paints them with the colour-emoji font and CSS `color`
is ignored entirely.

`ph-check-circle` was `\\2705`. The stylesheet says
`.tc-code-technical > i { color: var(--c-accent) }` and got a bright green
sticker instead -- 43 times in a single Code transcript, next to three-word grey
rows on a muted surface, and again on the run-report card where the state rail
was violet and the tick beside it green. Measured in situ before the fix: css
colour rgb(139,140,255), 156 of 570 lit pixels green-dominant. `ph-lightning`
(`\\26A1`) and `ph-paperclip` (`\\1F4CE`) had the same problem, found by
rendering all 108 glyphs at a known colour and reading the pixels back.

This is the sibling of the bug `test_every_icon_the_ui_asks_for_is_drawn.py`
already guards. That one catches a name with no glyph, which renders as a bullet.
This one catches a name whose glyph refuses to be styled -- both are "the
stylesheet said something and the screen did something else", and neither shows
up in the DOM.

Ranges are Emoji_Presentation=Yes from Unicode emoji-data.txt. A codepoint in
that set defaults to emoji rendering with no text variation sequence available,
so there is no way to make it obey `color`.
"""

from __future__ import annotations

import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "css" / "chat_shell.css"
RULE = re.compile(r"^([^{\n]*?)::before\s*\{\s*content:\s*\"([^\"]*)\"", re.M)

EMOJI_PRESENTATION_RANGES: tuple[tuple[int, int], ...] = (
    (0x231A, 0x231B), (0x23E9, 0x23EC), (0x23F0, 0x23F0), (0x23F3, 0x23F3),
    (0x25FD, 0x25FE), (0x2614, 0x2615), (0x2648, 0x2653), (0x267F, 0x267F),
    (0x2693, 0x2693), (0x26A1, 0x26A1), (0x26AA, 0x26AB), (0x26BD, 0x26BE),
    (0x26C4, 0x26C5), (0x26CE, 0x26CE), (0x26D4, 0x26D4), (0x26EA, 0x26EA),
    (0x26F2, 0x26F3), (0x26F5, 0x26F5), (0x26FA, 0x26FA), (0x26FD, 0x26FD),
    (0x2705, 0x2705), (0x270A, 0x270B), (0x2728, 0x2728), (0x274C, 0x274C),
    (0x274E, 0x274E), (0x2753, 0x2755), (0x2757, 0x2757), (0x2795, 0x2797),
    (0x27B0, 0x27B0), (0x27BF, 0x27BF), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x1F004, 0x1F004), (0x1F0CF, 0x1F0CF), (0x1F18E, 0x1F18E),
    (0x1F191, 0x1F19A), (0x1F1E6, 0x1F1FF), (0x1F201, 0x1F201),
    (0x1F21A, 0x1F21A), (0x1F22F, 0x1F22F), (0x1F232, 0x1F236),
    (0x1F238, 0x1F23A), (0x1F250, 0x1F251), (0x1F300, 0x1F320),
    (0x1F32D, 0x1F335), (0x1F337, 0x1F37C), (0x1F37E, 0x1F393),
    (0x1F3A0, 0x1F3CA), (0x1F3CF, 0x1F3D3), (0x1F3E0, 0x1F3F0),
    (0x1F3F4, 0x1F3F4), (0x1F3F8, 0x1F43E), (0x1F440, 0x1F440),
    (0x1F442, 0x1F4FC), (0x1F4FF, 0x1F53D), (0x1F54B, 0x1F54E),
    (0x1F550, 0x1F567), (0x1F57A, 0x1F57A), (0x1F595, 0x1F596),
    (0x1F5A4, 0x1F5A4), (0x1F5FB, 0x1F64F), (0x1F680, 0x1F6C5),
    (0x1F6CC, 0x1F6CC), (0x1F6D0, 0x1F6D2), (0x1F6D5, 0x1F6D7),
    (0x1F6DC, 0x1F6DF), (0x1F6EB, 0x1F6EC), (0x1F6F4, 0x1F6FC),
    (0x1F7E0, 0x1F7EB), (0x1F7F0, 0x1F7F0), (0x1F90C, 0x1F93A),
    (0x1F93C, 0x1F945), (0x1F947, 0x1F9FF), (0x1FA70, 0x1FA7C),
    (0x1FA80, 0x1FA88), (0x1FA90, 0x1FABD), (0x1FABF, 0x1FAC5),
    (0x1FACE, 0x1FADB), (0x1FAE0, 0x1FAE8), (0x1FAF0, 0x1FAF8),
)


def _is_emoji_presentation(codepoint: int) -> bool:
    return any(lo <= codepoint <= hi for lo, hi in EMOJI_PRESENTATION_RANGES)


def _glyph_map() -> dict[str, str]:
    """name -> the character the CSS draws.

    CSS escapes are HEX. Decoding them with Python's `unicode_escape` reads
    `\\26A1` as the OCTAL escape `\\26` followed by the letters "A1", which
    reported U+26A1 as U+0016 and made an earlier version of this audit useless.
    """
    out: dict[str, str] = {}
    for selectors, content in RULE.findall(CSS.read_text(encoding="utf-8")):
        char = re.sub(r"\\([0-9A-Fa-f]{1,6})\s?", lambda m: chr(int(m.group(1), 16)), content)
        if not char:
            continue
        for selector in selectors.split(","):
            selector = selector.strip()
            if selector.startswith(".ph-"):
                out[selector[1:]] = char
    return out


def test_the_map_was_actually_parsed() -> None:
    """Without this, every assertion below passes vacuously on an empty dict --
    which is the exact failure shape this whole file exists to catch."""
    icons = _glyph_map()

    assert len(icons) > 80, f"only parsed {len(icons)} glyphs; the CSS format changed"
    assert icons.get("ph-check-circle"), "ph-check-circle is missing from the map"


def test_no_glyph_is_an_emoji_presentation_codepoint() -> None:
    offenders = {
        name: f"U+{ord(char[0]):04X} {char[0]!r}"
        for name, char in _glyph_map().items()
        if _is_emoji_presentation(ord(char[0]))
    }

    assert not offenders, (
        "these icons render through the colour-emoji font and ignore CSS `color`, "
        f"so the theme cannot style them: {offenders}"
    )


def test_the_detector_recognises_the_codepoints_that_were_actually_wrong() -> None:
    """Pins the detector itself. An always-false check would make the test above
    pass forever."""
    for codepoint in (0x2705, 0x26A1, 0x1F4CE):
        assert _is_emoji_presentation(codepoint), f"U+{codepoint:04X} should be flagged"
    # And the text-presentation replacements actually chosen must not be flagged.
    for codepoint in (0x2713, 0x2607, 0x1F587, 0x26A0, 0x2139):
        assert not _is_emoji_presentation(codepoint), f"U+{codepoint:04X} wrongly flagged"
