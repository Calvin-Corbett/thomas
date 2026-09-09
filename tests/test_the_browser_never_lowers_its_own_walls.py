"""Thomas ships a browser now, and a browser's security posture is not a
preference -- it is the product.

Every one of these invariants was a deliberate decision when the desktop
shell was built (owner direction, 2026-08-25: "We are building a browser; no
weakening these to make something easier"). They are easy to undo by accident
and expensive to notice: flipping `sandbox: false` to make one page work
breaks nothing visibly, and a preload that leaks `ipcRenderer` hands every
site full IPC. Nothing else in the suite would catch either.

These tests read the shipped source rather than a config, because the source
is what runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DESKTOP = REPO / "desktop"
MAIN_JS = DESKTOP / "main.js"
PRELOAD_JS = DESKTOP / "preload.js"
SPIKE_JS = DESKTOP / "spike.js"
PANEL_JS = REPO / "thomas" / "server" / "web" / "js" / "browser_shell_panel.js"

pytestmark = pytest.mark.skipif(not MAIN_JS.exists(), reason="desktop shell is not present in this checkout")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_three_walls_are_up_in_every_desktop_entry_point() -> None:
    """contextIsolation on, sandbox on, nodeIntegration off -- everywhere."""
    for path in (MAIN_JS, SPIKE_JS):
        src = _read(path)
        assert re.search(r"contextIsolation:\s*true", src), f"{path.name}: contextIsolation"
        assert re.search(r"sandbox:\s*true", src), f"{path.name}: sandbox"
        assert re.search(r"nodeIntegration:\s*false", src), f"{path.name}: nodeIntegration"


def test_the_desktop_sources_are_still_text() -> None:
    """A stray NUL byte turns a source file binary to every review tool.

    One got into `main.js` during a scripted edit: a space inside a string
    became `\\x00`. Node parsed it, the app ran, and the only symptom was
    `git` and `grep` calling it a binary file -- which is exactly how a diff
    stops being read. Nothing here is allowed to be un-reviewable.
    """
    for path in sorted(DESKTOP.glob("*.js")) + [PANEL_JS]:
        raw = path.read_bytes()
        assert b"\x00" not in raw, f"{path.name} contains a NUL byte"
        raw.decode("utf-8")  # raises if the file is not valid UTF-8
        stray = [b for b in raw if b < 9 or 13 < b < 32]
        assert not stray, f"{path.name} contains control bytes: {stray[:4]}"


def test_nobody_quietly_lowered_a_wall() -> None:
    """The dangerous spellings must appear nowhere in the desktop sources."""
    forbidden = (
        r"contextIsolation:\s*false",
        r"sandbox:\s*false",
        r"nodeIntegration:\s*true",
        r"webSecurity:\s*false",
        r"allowRunningInsecureContent:\s*true",
        r"experimentalFeatures:\s*true",
    )
    for path in DESKTOP.glob("*.js"):
        src = _read(path)
        for pattern in forbidden:
            assert not re.search(pattern, src), f"{path.name} weakens the shell: {pattern}"


def test_web_content_is_never_given_a_preload() -> None:
    """Only the chrome page gets a bridge; a website must never hold one.

    main.js builds every view from one shared WEB_PREFS object and adds the
    preload for the chrome view alone. If a second `preload:` ever appears,
    someone has handed a renderer more than it should have.
    """
    src = _read(MAIN_JS)
    preloads = re.findall(r"preload:", src)
    assert len(preloads) == 1, f"expected exactly one preload wiring, found {len(preloads)}"
    # ...and it is the chrome view that gets it.
    chrome_block = src[
        src.index("chromeView = new WebContentsView") : src.index("win.contentView.addChildView(chromeView)")
    ]
    assert "preload" in chrome_block


def test_the_agent_bridge_demands_a_token() -> None:
    """The bridge drives real tabs, so an unauthenticated socket is a hole."""
    src = _read(MAIN_JS)
    assert "randomBytes" in src, "bridge token must be random"
    assert 'searchParams.get("token")' in src, "bridge must read a token"
    assert re.search(r"!==\s*token", src), "bridge must reject a wrong token"
    assert 'host: "127.0.0.1"' in src, "bridge must bind loopback only"


def test_the_preload_exposes_named_calls_not_raw_ipc() -> None:
    """A leaked ipcRenderer is a leaked main process."""
    src = _read(PRELOAD_JS)
    assert "contextBridge.exposeInMainWorld" in src
    # Every exposure must be a named function, never the module itself.
    exposed = src[src.index("exposeInMainWorld") :]
    assert not re.search(r"\bipcRenderer\s*[,}]", exposed), "preload leaks ipcRenderer"
    assert not re.search(r":\s*ipcRenderer\b", exposed), "preload leaks ipcRenderer"


def test_navigation_from_the_bridge_is_restricted_to_http() -> None:
    """file:// and friends would turn a tab into a local file reader."""
    src = _read(MAIN_JS)
    assert '["http:", "https:"]' in src, "navigate must allow only http(s)"


def test_page_context_travels_as_data_not_as_prose() -> None:
    """The quick chat must not concatenate page text into the message.

    The server wraps `page_context` as untrusted data. That protection is
    worth nothing if the client glues the page's title into `message`
    instead, so pin the shape here as well.
    """
    src = _read(PANEL_JS)
    assert "page_context: qcPageContext()" in src, "page context must be its own field"
    # The message sent is the user's text, untouched.
    assert re.search(r"message:\s*text\b", src), "message must be the user's text alone"
