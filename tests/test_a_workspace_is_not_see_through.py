"""A dashboard does not sit directly on the animated background.

thomas_world.css says, deliberately, "let the world show through translucent
surfaces". That reads beautifully on the Chat surface, which is airy and centred.
The workspace iframe is the other case: dense, edge-to-edge dashboards whose cards
are `rgba(255,255,255,.04)` -- 4% opaque, effectively glass. With the frame itself
set to `background: transparent`, the world's discrete sprites showed straight
through both layers and landed on top of text.

Observed at 1920x1080 in Token Economy: a hard-edged white sphere sat over the
"TOKENS OUT" stat label and covered the "UT", so the card read "TOKENS O". The DOM
said "TOKENS OUT" the whole time -- the letters were painted, then covered.

The fix keeps the world (58% tint, not opaque) but blurs it, so it survives as
colour and glow instead of as objects. This pins the two properties that matter:
the frame is no longer fully transparent, and the blur is present. Either one alone
would let the regression back in -- an opaque frame kills the atmosphere the owner
asked for, and blur without a tint does not lift text off a bright sprite.
"""

from __future__ import annotations

import re
from pathlib import Path

CHAT_HTML = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "chat.html"


def _frame_style() -> str:
    html = CHAT_HTML.read_text(encoding="utf-8")
    match = re.search(r'<iframe[^>]*class="tc-workspace-frame"[^>]*>', html)
    assert match, "the workspace iframe is gone; this guard needs rewriting, not deleting"
    return match.group(0)


def test_the_workspace_frame_is_not_fully_transparent() -> None:
    style = _frame_style()

    assert "background: transparent;" not in style, (
        "the workspace frame is see-through again: the world's sprites will land on "
        "dashboard text, because the cards inside are only 4% opaque"
    )
    assert "--c-bg" in style, "the backdrop must come from the theme token, not a hardcoded colour"


def test_the_workspace_backdrop_still_lets_the_world_through() -> None:
    """An opaque frame would fix legibility by deleting the design. Not that."""

    style = _frame_style()
    blur = re.search(r"backdrop-filter:\s*blur\((\d+)px\)", style)

    assert blur, "no backdrop blur: a bright sprite behind glass is still a bright sprite"
    assert int(blur.group(1)) >= 8, f"blur of {blur.group(1)}px is too small to soften a hard edge"

    tint = re.search(r"color-mix\(in srgb, var\(--c-bg\) (\d+)%", style)
    assert tint, "no partial tint: the frame is either transparent or flat, and both were wrong"
    assert 30 <= int(tint.group(1)) <= 85, (
        f"tint of {tint.group(1)}% -- below ~30% text stops lifting off the sprites, "
        "above ~85% the animated world may as well not be there"
    )
