"""Free text in Code mode must wrap, whoever wrote it.

`.tc-code-turn.is-user` set `white-space: pre-wrap` and nothing else. pre-wrap
breaks at whitespace and does nothing for a single long token -- a hash, an API
key, a path with no separators -- which is exactly what gets pasted into a build
request.

Every sibling that renders free text already handled it: `.tc-code-reply`,
`.tc-code-event span` and `.tc-code-technical code` all set
`overflow-wrap: anywhere`. So Thomas's messages wrapped and yours did not.

Measured in the browser with a 145-character unbreakable string: the bubble
reported `scrollWidth` 1171 against `clientWidth` 510 and was clipped mid-token,
while the reply beside it wrapped onto two lines from the same string.

The first version of that measurement used a path containing hyphens and
slashes. Those ARE break opportunities under `overflow-wrap: normal`, so it
wrapped and proved nothing -- a check that could not have failed. The string had
to be genuinely unbreakable before it meant anything.
"""

from __future__ import annotations

import re
from pathlib import Path

CSS_DIR = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "css"

# Every selector in Code mode that renders text somebody typed or Thomas wrote.
FREE_TEXT_RULES = (
    ("unified_code_mode.css", r"\.tc-code-turn\.is-user"),
    ("unified_code_mode.css", r"\.tc-code-reply"),
    ("unified_code_activity.css", r"\.tc-code-event span"),
)


def _declaration(css: str, selector_pattern: str, prop: str) -> str:
    """One property from the rule matching a selector, comments stripped first.

    Comments go first because the rule this guards is documented at length
    directly above itself, quoting both the selector and the property -- and a
    scan that reads its own documentation is how three other CSS guards in this
    suite passed against deleted fixes.
    """

    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    block = re.search(selector_pattern + r"\s*\{([^}]*)\}", css)
    if not block:
        return ""
    found = re.search(rf"(?:^|[;{{])\s*{prop}\s*:\s*([^;]+)", block.group(1))
    return found.group(1).strip() if found else ""


def test_every_free_text_surface_can_break_a_long_token() -> None:
    missing: list[str] = []
    for filename, selector in FREE_TEXT_RULES:
        css = (CSS_DIR / filename).read_text(encoding="utf-8")
        value = _declaration(css, selector, "overflow-wrap")
        if value not in {"anywhere", "break-word"}:
            missing.append(f"{filename} {selector} -> {value or 'unset'}")

    assert not missing, (
        "these render free text but cannot break an unbreakable token, so a hash "
        "or a key pasted into them overflows: " + "; ".join(missing)
    )


def test_the_user_bubble_specifically_is_not_left_behind() -> None:
    """The regression that happened: three siblings had it, one did not."""

    css = (CSS_DIR / "unified_code_mode.css").read_text(encoding="utf-8")
    user = _declaration(css, r"\.tc-code-turn\.is-user", "overflow-wrap")
    reply = _declaration(css, r"\.tc-code-reply", "overflow-wrap")

    assert user, "the user bubble has no overflow-wrap; your own message will not wrap"
    assert user == reply, (
        f"your message and Thomas's wrap differently ({user!r} vs {reply!r}); free "
        "text is free text whoever typed it"
    )
