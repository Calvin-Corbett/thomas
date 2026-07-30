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


# `\bph-` followed by a template hole: `ph-${...}`. The suffix is decided at
# runtime, so no static scan can know which name is asked for.
_RUNTIME_ASSEMBLED_RE = re.compile(r"\bph-\$\{")


def test_no_icon_name_is_assembled_at_runtime() -> None:
    """The hole this file used to have, closed by forbidding the shape.

    `_used_names` deliberately skips `ph-${...}`, on the reasoning that the names
    such a template can produce "are checked on their own merits wherever they
    appear literally". That reasoning did not hold. Of the seven names reachable
    only through those templates, **five never appeared literally anywhere in
    these sources** -- including `ph-check-circle`, the very icon this file's
    docstring cites as appearing 18 times in one transcript. The guard written
    because of check-circle could not see check-circle.

    Proved by injecting `ph-${ok ? 'totally-not-a-real-glyph' : 'warning'}` into
    `reportRow`: the three tests above stayed green while the live page rendered
    `content: "•"` on every "Check passed" row of every run report.

    Making the scanner cleverer was the wrong fix -- it would have to tell a
    value-side literal from a condition-side one, in
    `tone === 'is-bad' ? 'warning-circle' : ...`, and get that right forever.
    Forbidding the un-analysable shape is smaller and total: write the whole
    class name (`${ok ? 'ph-check-circle' : 'ph-warning'}`) and every name is a
    literal the scan above already covers.
    """
    offenders: dict[str, list[str]] = {}
    for path in CODE_SOURCES:
        if not path.is_file():
            continue
        hits = [
            line.strip()[:110]
            for line in path.read_text(encoding="utf-8").splitlines()
            if _RUNTIME_ASSEMBLED_RE.search(line)
        ]
        if hits:
            offenders[path.name] = hits

    assert not offenders, (
        "icon class names built at runtime cannot be checked for a missing glyph, "
        "and a missing glyph renders as a bullet. Interpolate the WHOLE class name "
        f"instead: {offenders}"
    )
