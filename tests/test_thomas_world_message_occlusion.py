from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORLD_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "thomas_world.css"
WORLD_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "thomas_world.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_living_world_decoration_cannot_cover_chat_message_text() -> None:
    css = _read(WORLD_CSS)
    js = _read(WORLD_JS)

    for world in ("nebula", "dark", "light", "aurora", "sandstone"):
        assert f'body.tcw-on[data-tcw-world="{world}"]' in css

    assert "#tcw-bg { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }" in css
    assert "body.tcw-on #app, body.tcw-on .app-layout { position: relative; z-index: 1;" in css
    assert "body.tcw-on .message-row .message-content {\n  isolation: isolate;\n}" in css
    assert "body.tcw-on .message-row .message-content::after {" in css
    assert "z-index: -1;" in css
    assert "background: var(--c-bg);" in css
    assert "pointer-events: none;" in css
    assert "body.tcw-on .message-row.is-user .message-content::after {" in css
    assert "linear-gradient(var(--c-user-bg), var(--c-user-bg))," in css

    assert "bg.setAttribute('aria-hidden', 'true');" in js
    assert "document.body.insertBefore(bg, document.body.firstChild);" in js
