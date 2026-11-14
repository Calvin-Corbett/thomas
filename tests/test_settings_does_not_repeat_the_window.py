"""Settings inside Thomas has no second header and no "Chat" button over it (2026-11-10).

You said: "Settings looks really dumb because it says Thomas, even though like it says Thomas again, controller
workspace, that's dumb ... There's a thing that says chat at the top right. That's not supposed to be there."
"""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"


def test_the_brand_block_is_hidden_when_settings_is_inside_thomas() -> None:
    css = (WEB / "css" / "settings_plugins.css").read_text("utf-8")
    assert "html.is-embedded .settings-brand, body.is-embedded .settings-brand { display: none !important; }" in css
    assert 'class="settings-brand"' in (WEB / "settings.html").read_text("utf-8"), "opened on its own, it keeps it"


def test_the_top_right_button_is_not_shown_over_a_workspace() -> None:
    drawer = (WEB / "js" / "workspace_chat_drawer.js").read_text("utf-8")
    assert "button.style.display = 'none';" in drawer
    assert "button.style.display = current ? 'flex' : 'none';" not in drawer
