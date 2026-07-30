"""An icon name with no glyph is invisible, not broken.

Thomas's icons are not the Phosphor webfont — they are a hand-written glyph map
in ``chat_shell.css``, so the shell boots offline and deterministically. The map
opens with a catch-all::

    .ph::before { content: "\\2022"; }

so a class the markup uses but the map never defines silently renders a bullet.
The element is present, the class is right, the layout is correct and every test
passes. Only looking at the screen shows a row of meaningless dots.

Measured on the Code surface before this test existed: **17 distinct names** were
used and unmapped, including ``ph-robot`` — Thomas's own avatar, drawn on every
message he sends and in the empty state — and ``ph-check-circle``, which alone
appeared 18 times in a single transcript's activity log.

This is the cheap, deterministic half of that check: every ``ph-`` class the Code
surface asks for must have a glyph. It cannot prove the glyph is a *good* symbol
— only a person looking at it can — but it does prove none of them are dots.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB = REPO_ROOT / "thomas" / "server" / "web"
GLYPH_MAP = WEB / "css" / "chat_shell.css"

# The surfaces this test speaks for. Code, and the shell it is drawn inside.
CODE_SOURCES = (
    WEB / "chat.html",
    WEB / "js" / "unified_code_mode.js",
    WEB / "js" / "unified_code_results.js",
    WEB / "js" / "unified_code_lifecycle.js",
    WEB / "js" / "unified_code_projects.js",
    WEB / "css" / "unified_code_activity.css",
    WEB / "css" / "unified_code_mode.css",
    WEB / "css" / "unified_code_results.css",
)

_USE_RE = re.compile(r"\bph-[a-z0-9]+(?:-[a-z0-9]+)*")
_DEF_RE = re.compile(r"\.(ph-[a-z0-9]+(?:-[a-z0-9]+)*)\s*::before")


def _mapped_names() -> set[str]:
    return set(_DEF_RE.findall(GLYPH_MAP.read_text(encoding="utf-8")))


def _used_names() -> dict[str, str]:
    """Every ``ph-`` name the Code surface references, and where.

    Classes assembled at runtime are skipped -- ``ph-caret-${up|down}`` reads as
    the fragment ``ph-caret``, which is not a name anyone can map. Both halves it
    can produce are real names in their own right and are checked on their own
    merits wherever they appear literally.
    """
    used: dict[str, str] = {}
    for path in CODE_SOURCES:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for match in _USE_RE.finditer(text):
            if text[match.end() : match.end() + 2] in ("${", "-$"):
                continue
            used.setdefault(match.group(0), path.name)
    return used


def test_the_glyph_map_has_a_catch_all_that_hides_mistakes() -> None:
    """The premise. If this ever stops being true, an unmapped name would show
    as nothing at all rather than a bullet, and this test's reason changes."""
    text = GLYPH_MAP.read_text(encoding="utf-8")

    assert ".ph::before" in text
    assert "2022" in text.split(".ph::before", 1)[1][:80]


def test_every_icon_the_code_surface_uses_has_a_glyph() -> None:
    mapped = _mapped_names()
    used = _used_names()

    assert used, "no ph- classes found; the sources moved and this test is now blind"

    missing = {
        name: where
        for name, where in used.items()
        # `ph-caret-` and friends come from template strings that build a class
        # at runtime (`ph-caret-${dir}`); they are not real names.
        if name not in mapped and not name.endswith("-")
    }

    assert not missing, (
        "these render as a bullet, not an icon — add a glyph in "
        f"css/chat_shell.css: {sorted(missing.items())}"
    )


def test_thomas_has_a_face() -> None:
    """The one that started it. His avatar is on every message he sends."""
    assert "ph-robot" in _mapped_names()
