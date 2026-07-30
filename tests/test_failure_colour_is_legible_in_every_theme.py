"""Whatever marks a failure must be readable in every theme.

`#ff9a9a` is a DARK-theme red. It was hard-coded into the failed-verdict rail,
the failure icon and (as of this session) the Revert control. Measured live
against each world's own surface::

    nebula     9.47:1  Revert     9.78:1  verdict icon
    light      2.03:1             2.03:1
    sandstone  1.89:1             1.89:1

So on two of the five themes the mark that says a run FAILED, and the control
that permanently discards a file, were both close to invisible -- the two things
in the surface that most need to be seen.

Checked as CONTRAST, not as a hex string. A guard that pins `#b3261e` would go
red the moment someone tunes the palette, and would pass if a future theme
shipped an unreadable colour of its own. This computes the WCAG ratio from each
theme's own tokens, so it keeps meaning something whatever the palette becomes.
"""

from __future__ import annotations

import re
from pathlib import Path

CHAT_HTML = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "chat.html"

# 4.5:1 is the AA floor for body text. The verdict text and the run summary use
# this colour, not just the icon, so the stricter figure is the right one.
MINIMUM_RATIO = 4.5


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


def _themes() -> dict[str, dict[str, str]]:
    """Each theme's token map, read from the THEMES object in chat.html."""

    text = CHAT_HTML.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    for match in re.finditer(r"^\s*(\w+): \{ name:.*?\n\s*vars: \{(.*?)\} \},", text, re.S | re.M):
        name, body = match.group(1), match.group(2)
        out[name] = dict(re.findall(r"'(--[\w-]+)':\s*'([^']+)'", body))
    return out


def test_every_theme_defines_a_failure_colour() -> None:
    themes = _themes()
    assert themes, "no themes could be read from chat.html"
    assert len(themes) >= 5, f"expected the five worlds, found {sorted(themes)}"

    for token in ("--c-danger", "--c-warn"):
        missing = [name for name, tokens in themes.items() if not tokens.get(token)]
        assert not missing, (
            f"these themes have no {token}, so that state falls back to a dark-theme "
            f"literal: {missing}"
        )


def test_the_failure_colour_is_readable_on_its_own_background() -> None:
    bad: list[str] = []
    for name, tokens in _themes().items():
        background = tokens.get("--c-bg")
        if not background or not background.startswith("#"):
            continue
        for token in ("--c-danger", "--c-warn"):
            value = tokens.get(token)
            if not value or not value.startswith("#"):
                continue
            ratio = _ratio(value, background)
            if ratio < MINIMUM_RATIO:
                bad.append(f"{name} {token}: {value} on {background} = {ratio:.2f}:1")

    assert not bad, (
        "a failure mark nobody can see is the same as no failure mark; these are "
        f"below {MINIMUM_RATIO}:1 -> " + "; ".join(bad)
    )


CODE_CSS = [
    Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "css" / name
    for name in ("unified_code_activity.css", "unified_code_mode.css", "unified_code_results.css")
]

# The dark-theme literals that were hard-coded across Code mode before the
# tokens. The ambers matter as much as the reds: the WARN verdict measured
# 1.68:1 on sandstone and the stream-disconnected message 1.27:1, so "passed,
# with things to look at" and "the connection dropped" were both unreadable
# there.
DARK_REDS = ("#ff9a9a", "#ffaaaa", "#ffb0b0", "#ff7777")
DARK_AMBERS = ("#e2b25f", "#f2b35f", "#f7ce91", "#d79a45")
STATE_LITERALS = DARK_REDS + DARK_AMBERS


def test_code_mode_never_hard_codes_a_failure_red() -> None:
    """A new hard-coded red is invisible on light and sandstone all over again.

    Allowed only as the FALLBACK inside `var(--c-danger, ...)`, which is what the
    themed token degrades to. Comments are stripped first -- several of them
    quote `#ff9a9a` while explaining this very fix, and a naive scan matches its
    own documentation.
    """

    offenders: list[str] = []
    for path in CODE_CSS:
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        # Remove every legitimate use, then anything left is a bare literal.
        stripped = re.sub(r"var\(\s*--c-(?:danger|warn)\s*,[^)]*\)", "", css, flags=re.I)
        for literal in STATE_LITERALS:
            if literal in stripped.lower():
                offenders.append(f"{path.name}: {literal}")

    assert not offenders, (
        "these are hard-coded dark-theme state colours and measure between 1.27:1 "
        "and 2:1 on the light worlds; use var(--c-danger, ...) or "
        "var(--c-warn, ...) -> " + "; ".join(offenders)
    )


def test_the_light_worlds_do_not_reuse_the_dark_red() -> None:
    """The specific regression: #ff9a9a shipped to light and sandstone."""

    themes = _themes()
    for name in ("light", "sandstone"):
        tokens = themes.get(name) or {}
        assert tokens.get("--c-danger", "").lower() != "#ff9a9a", (
            f"{name} is back on the dark-theme red, which measured about 2:1 there"
        )
