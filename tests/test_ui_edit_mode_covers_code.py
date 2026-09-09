"""Code mode participates in UI Edit Mode.

`docs/UI_EDIT_MODE_STANDARD.md` binds every meaningful surface to the shared
editor, and Code was the one that never registered: zero `data-ui-id` in
`unified_code_mode.js`, and `#tc-mode-surface` -- the container Code renders
into -- carried no identity either, so in Code mode you could move the box that
holds Code but nothing inside it.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"
CODE_JS = WEB / "js" / "unified_code_mode.js"
CHAT_HTML = WEB / "chat.html"


def _code() -> str:
    return CODE_JS.read_text(encoding="utf-8")


def _regions() -> dict[str, str]:
    text = _code()
    found = {}
    for match in re.finditer(r'data-ui-id="(code\.[a-z.]+)"[^>]*?data-ui-policy="([^"]+)"', text):
        found[match.group(1)] = match.group(2)
    return found


def test_codes_meaningful_regions_are_registered() -> None:
    regions = _regions()

    for identity in ("code.transcript", "code.activity", "code.outputs", "code.files", "code.steer"):
        assert identity in regions, f"{identity} is not registered with the shared editor"


def test_every_registered_region_is_named_for_a_person() -> None:
    """`data-ui-label` is what the region picker shows; an identity alone is a
    slug, and the picker is how a covered region is recovered."""
    text = _code()

    for identity in _regions():
        assert re.search(rf'data-ui-id="{re.escape(identity)}" data-ui-label="[^"]+"', text), identity


def test_destructive_controls_are_protected() -> None:
    """The safety rules require it: Stop kills a running build, Checkpoint
    commits, and Approve authorises. None of them should be drag targets."""
    regions = _regions()

    for identity in ("code.action.stop", "code.action.checkpoint", "code.approval"):
        assert regions.get(identity) == "protected", f"{identity} must be protected"


def test_movable_regions_declare_their_limits() -> None:
    """Without a floor a region can be dragged down to nothing and lost."""
    text = _code()

    for identity, policy in _regions().items():
        if "resize" not in policy:
            continue
        pattern = rf'data-ui-id="{re.escape(identity)}"[^>]*?data-ui-constraints="([^"]+)"'
        match = re.search(pattern, text)
        assert match and "min" in match.group(1), f"{identity} declares no minimum size"


def test_the_container_code_renders_into_has_an_identity() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    surface = next(line for line in html.splitlines() if 'id="tc-mode-surface"' in line)

    assert 'data-ui-id="chat.mode.surface"' in surface


def test_an_ai_edit_from_code_stays_in_code() -> None:
    """`stageUiAiEdit` called showChat() unconditionally, so asking Code to
    change one of its own regions threw you into Chat and handed the request to
    the dispatcher instead of to the surface that builds."""
    html = CHAT_HTML.read_text(encoding="utf-8")
    body = html.split("function stageUiAiEdit", 1)[1].split("\n    window.addEventListener", 1)[0]
    code_only = "\n".join(line for line in body.splitlines() if not line.strip().startswith("//"))

    assert "state.surfaceMode === 'code'" in code_only
    index = code_only.index("state.surfaceMode === 'code'")
    assert "showChat()" not in code_only[:index], "Code must be handled before the fallback to Chat"
