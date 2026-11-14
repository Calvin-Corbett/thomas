"""Build's project chooser opens on the reading column, not off to the right.

The panel is `position:absolute; left:0` inside `#tc-code-project-wrap`, and
that wrap is the third control in the composer's button row. `left:0` is
therefore the folder button's left edge -- about 140px in from the composer
card -- while the panel's CSS width is up to 760px. So it is sized to the
reading column but started a third of the way across it, which is what "the
project folder renders off to the right rather than centered" looks like on
screen. It degrades from there rather than staying put: in Build's viewer
layout the column is narrow and the panel lies across the viewer beside it,
and at phone widths its right edge leaves the screen.

Three tests, because no one of them is enough on its own:

* `test_the_chooser_is_centred_on_the_reading_column` drives the real
  chat.html in headless Chromium -- clicks Build, clicks the folder button,
  measures the painted boxes. The bug was a layout fact, so a layout
  measurement is the honest test. It skips where Chromium cannot launch.
  The library read is fulfilled with six projects, so the panel measured is
  the shelf a person picks from rather than the fixture's failed-read
  message, and the page's own error log is asserted clean alongside the
  geometry.
  It also leaves a before/after screenshot pair per viewport: the fixed
  panel, and the same open panel with the shipped markup's `left:0` anchor
  put back, which is the reported layout. Set THOMAS_CHOOSER_SHOTS to a
  folder to collect that pair somewhere you can open it.
  Everything after the Build click happens inside the Build TAB: the shell
  answers that click by opening a second chat.html in an `iframe.bt-doc`
  that covers the whole window, so the chooser a person sees is the one in
  that document, not the one in the page that was clicked.
* `test_the_trigger_is_not_the_columns_centre` measures the gap the fix
  closes, so the test above cannot pass by coincidence.
* `test_the_positioning_arithmetic_survives_every_build_layout` runs the
  shipped `positionLibraryMenu` against measured rail/trigger boxes for
  Build's normal, activity, viewer and narrow layouts, plus the
  narrow-then-wide sequence that a stale width would fail. Those states need
  a live Build run to reach in a browser; the arithmetic does not, and Node
  is available in places Chromium is not. Two of its cases exist to make the
  edge clamps BIND -- a rail beginning left of the window, and a rail pushed
  right by the viewer in a small one -- because every other case is answered
  by centring alone, and the 16px margin that keeps a phone-width chooser on
  screen would otherwise be the one part of the fix nothing could fail on.
  It also drives `toggleLibraryMenu`
  itself, so the OPEN path -- the one every person takes -- is covered by the
  check that runs everywhere and not only by the browser test above, which
  skips where Chromium cannot launch. And it pins the two non-layouts this
  code is still called in -- a document with no composer rail, and a rail
  with no box yet -- where the requirement is that nothing is written rather
  than that something is centred.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "thomas/server/web/js/chat_composer_panels.js"
HARNESS = ROOT / "tests/web_node/build_project_chooser_position.mjs"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok, open_shell  # noqa: E402

# Subpixel rounding only; anything larger is the panel sitting off the column.
TOLERANCE = 1.0
# The same edge margin positionLibraryMenu clamps to.
EDGE_MARGIN = 16.0
DESKTOP = {"width": 1440, "height": 900}

MEASURE = """
() => {
  const menu = document.getElementById('tc-code-library-menu');
  const rail = document.getElementById('tc-composer-rail');
  const wrap = document.getElementById('tc-code-project-wrap');
  if (!menu || !rail || !wrap) return null;
  const m = menu.getBoundingClientRect();
  const r = rail.getBoundingClientRect();
  const w = wrap.getBoundingClientRect();
  return {
    display: getComputedStyle(menu).display,
    menuLeft: m.left, menuRight: m.right, menuWidth: m.width,
    menuCentre: m.left + m.width / 2,
    railLeft: r.left, railRight: r.right, railWidth: r.width,
    railCentre: r.left + r.width / 2,
    triggerLeft: w.left,
    viewport: window.innerWidth,
  };
}
"""

# The shipped markup's own anchor, put back on an already-open panel: `left:0`
# is the folder button's left edge, and clearing the width returns the CSS
# `min(760px, 100vw - 48px)`. Those are the two inline writes the fix makes, so
# taking them off is the reported layout -- photographed beside the fixed one
# rather than described.
UNFIXED = """
() => {
  const menu = document.getElementById('tc-code-library-menu');
  if (!menu) return null;
  menu.style.left = '0px';
  menu.style.width = '';
  return menu.getBoundingClientRect().left;
}
"""

NO_MOTION = "*{transition:none !important; animation:none !important}"
# The Build tab's document, once the shell has it on screen. `.bt-doc` frames
# are `visibility:hidden` until they are both active and ready, so the classes
# are the wait -- attached is not enough, and Playwright's own visibility check
# would pass on an iframe whose document is still booting.
BUILD_DOC = 'iframe.bt-doc.is-active.is-ready[src*="tab_mode=code"]'

# The library the chooser is opened onto.
#
# The fixture answers /api/local/projects with `{"projects": []}` and no `ok`,
# and loadLibraryProjects() requires `data.ok` -- so without this the panel
# under measurement is the "Thomas could not read your library just now." one.
# It would still prove the geometry, because the fix writes width and left
# regardless of content, but the report was about choosing a project, and a
# screenshot of an error message is not a picture of that. Fulfil the read.
#
# No project carries an `artifact_url`, so every card rests on its monogram
# and mountLibraryPreviews() mounts no preview iframe: a populated shelf that
# costs no further request and holds no preview grant.
LIBRARY = {
    "ok": True,
    "projects": [
        {
            "root_path": f"C:/Users/you/Thomas/projects/p{n}",
            "name": f"p{n}",
            "request_title": title,
            "entry_path": "index.html",
            "updated_at": f"2026-09-{10 + n:02d}T09:00:00Z",
        }
        for n, title in enumerate(
            (
                "Recipe box",
                "Garage inventory",
                "Trip planner",
                "Bird log",
                "Invoice tracker",
                "Reading list",
            ),
            start=1,
        )
    ],
}


@pytest.fixture(scope="module")
def shell():
    with open_shell() as s:
        yield s


def _shot_dir(tmp_path: Path) -> Path:
    """Where the before/after pair lands.

    A passing test writes its screenshots into pytest's temp folder and then
    says nothing, because only the failure message names the path -- so the
    evidence exists and nobody can find it. The report here was about what a
    screen looks like, so the answer should be lookable: THOMAS_CHOOSER_SHOTS
    points the pair at a folder of your choosing. Unset, the temp folder is
    still the default, and nothing is written into the repository either way.
    """
    named = os.environ.get("THOMAS_CHOOSER_SHOTS", "").strip()
    if not named:
        return tmp_path
    out = Path(named).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    return out


def _build_frame(shell, timeout: float = 20.0):
    """The Build tab's frame object, once Playwright is reporting its URL.

    BUILD_DOC proves the IFRAME is on screen. The frame OBJECT behind it is a
    separate arrival -- `page.frames` carries it from attachment, with the URL
    it will navigate to landing a beat later -- and `shell.docs()` selects on
    that URL. Taking the first match unconditionally therefore fails as a bare
    StopIteration from inside a fixture, which names neither the tab nor the
    wait. Poll for it, and if it never comes say which documents did.
    """
    deadline = time.monotonic() + timeout
    while True:
        for frame in shell.docs():
            if "tab_mode=code" in frame.url:
                return frame
        if time.monotonic() >= deadline:
            seen = ", ".join(f.url for f in shell.docs()) or "none"
            raise AssertionError(f"the Build tab never reported its document (tab documents: {seen})")
        shell.page.wait_for_timeout(100)


@pytest.fixture(scope="module")
def build(shell):
    """Build, reached the way anyone reaching this panel reaches it.

    Clicking Build does not put the page that was clicked into Build.
    browser_shell_docs.js takes that click in the capture phase and opens a
    Build TAB instead -- a second chat.html at `?embed=1&browser=0&tab_mode=code`
    in an `iframe.bt-doc`, absolutely positioned over the whole row, sidebar
    included. So the chooser on screen belongs to that document, and the one
    left behind in the parent page is both in Chat mode and underneath an
    iframe. This yields the tab document; every click and measurement below
    goes through it.

    Opened once, at desktop width: the mode switch is in the composer's
    control row, which phone widths crowd, and nobody picks a project by
    starting in a 390px window. Narrowing happens afterwards, on a tab that
    is already in Build.
    """
    page = shell.page
    page.set_viewport_size(DESKTOP)
    # Registered after the fixture's own catch-all, so it wins for this one URL
    # (Playwright tries handlers newest first) and every other request still
    # goes to the fixture server. Page routes cover the page's child frames, so
    # the Build tab's read is answered too.
    page.route(
        "**/api/local/projects",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(LIBRARY)),
    )
    page.click('.tc-mode-button[data-thomas-mode="code"]')
    page.wait_for_selector(BUILD_DOC, state="attached", timeout=20000)
    frame = _build_frame(shell)
    # modeChanged() reveals the wrap before the Code adapter enters, and the
    # adapter's own work is fire-and-forget, so this does not wait on the API.
    frame.wait_for_selector("#tc-code-project-wrap", state="visible", timeout=20000)
    frame.add_style_tag(content=NO_MOTION)
    return frame


def _close_chooser(frame) -> None:
    """Escape, the panel's own close (chat_shell_bindings.js).

    Pressed on the tab document rather than on the shell around it: a
    keystroke reaches the document that has focus, and the listener that
    closes this panel is that document's. Re-clicking Build would not do it
    -- Build is already the open tab, so the shell just focuses it again.
    """
    frame.press("body", "Escape")
    frame.wait_for_selector("#tc-code-library-menu", state="hidden", timeout=10000)


def _open_chooser(frame) -> dict:
    """Click the selected-project button and measure what was painted."""
    # The tab is shared by every case here, and this button toggles: a chooser
    # an earlier case left open would be CLOSED by the click below. Start from
    # a known state instead of from whatever the last case ended in.
    _close_chooser(frame)
    frame.click("#tc-code-project-btn")
    frame.wait_for_selector("#tc-code-library-menu", state="visible", timeout=10000)
    # Settle on the shelf of projects, not on the panel's loading frame: the
    # library read is fulfilled above, so a card is what an open chooser becomes.
    # Measuring and photographing after it means the panel in evidence is the one
    # a person opens, and a read that stopped arriving fails here by name instead
    # of quietly leaving a thinner panel in the screenshots.
    frame.wait_for_selector("[data-lib-card]", state="visible", timeout=10000)
    box = frame.evaluate(MEASURE)
    assert box is not None, "the chooser, the rail and the trigger must all be laid out"
    assert box["display"] == "flex", "the chooser must be open before it is measured"
    return box


@pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")
@pytest.mark.parametrize(("width", "height"), [(1440, 900), (1100, 820), (390, 780)])
def test_the_chooser_is_centred_on_the_reading_column(shell, build, tmp_path, width, height) -> None:
    page = shell.page
    shots = _shot_dir(tmp_path)
    try:
        page.set_viewport_size({"width": width, "height": height})
        # The tab document is `inset: 0` on the shell's row, so the shell's
        # resize is its resize -- but a child frame learns its new width on the
        # next rendering lifecycle, not inside set_viewport_size. Give that one
        # beat and then force layout, so the chooser is positioned against the
        # width the tab actually has rather than the one it is leaving.
        page.wait_for_timeout(150)
        build.evaluate("() => document.body.offsetWidth")
        box = _open_chooser(build)
        # Evidence as a pair, from the real chooser in a real Build tab. The
        # "before" is this same open panel with the fix's two inline writes
        # taken back off -- nothing else on the page moves between the shots,
        # so the difference between them is the fix and nothing else. The next
        # open recomputes both properties, so this does not leak into the cases
        # after it.
        page.screenshot(path=str(shots / f"after-{width}x{height}.png"))
        unfixed_left = build.evaluate(UNFIXED)
        page.screenshot(path=str(shots / f"before-{width}x{height}.png"))
        assert unfixed_left is not None, "the chooser must still be on the page to photograph"
        print(f"chooser evidence {width}x{height}: before/after in {shots}")

        off = box["menuCentre"] - box["railCentre"]
        assert abs(off) <= TOLERANCE, (
            f"at {width}x{height} the chooser centre is {off:.1f}px from the reading"
            f" column's centre (chooser {box['menuLeft']:.0f}..{box['menuRight']:.0f},"
            f" rail {box['railLeft']:.0f}..{box['railRight']:.0f});"
            f" before/after screenshots in {shots}"
        )
        assert box["menuLeft"] >= EDGE_MARGIN - TOLERANCE, (
            f"at {width}x{height} the chooser starts {box['menuLeft']:.1f}px from the left edge"
        )
        assert box["menuRight"] <= box["viewport"] - EDGE_MARGIN + TOLERANCE, (
            f"at {width}x{height} the chooser reaches {box['menuRight']:.1f}px of a {box['viewport']:.0f}px viewport"
        )
        assert box["menuWidth"] <= box["railWidth"] + TOLERANCE, (
            "the chooser must not be wider than the column it is centred on"
        )
        # A panel can be measured in the right place by code that threw on the
        # way there. positionLibraryMenu() now runs on resize and on the rail's
        # ResizeObserver -- both reached in this test -- so the page's own error
        # log is part of the result, as it is in every browser test here.
        assert not shell.errors, shell.errors
    finally:
        _close_chooser(build)
        page.set_viewport_size(DESKTOP)


@pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")
def test_the_trigger_is_not_the_columns_centre(shell, build) -> None:
    """The measurement that makes the test above able to fail.

    `left:0` -- the markup's own anchor, and what shipped -- puts the panel's
    left edge on the folder button. If that happened to coincide with the
    column's centre the assertions above would pass with no fix present, so
    name the gap the fix closes rather than assuming it.
    """
    page = shell.page
    try:
        page.set_viewport_size(DESKTOP)
        page.wait_for_timeout(150)
        box = _open_chooser(build)
        unfixed_centre = box["triggerLeft"] + box["menuWidth"] / 2
        off = unfixed_centre - box["railCentre"]
        assert abs(off) > TOLERANCE, (
            "anchoring the chooser at the trigger would already be centred here;"
            " this fixture no longer reproduces the reported layout"
        )
        assert not shell.errors, shell.errors
    finally:
        _close_chooser(build)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for the browser JS harness")
def test_the_positioning_arithmetic_survives_every_build_layout() -> None:
    result = subprocess.run(
        ["node", str(HARNESS), str(JS)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    for variant in (
        "Build project selected",
        "Build activity open",
        "Build viewer open",
        "Build narrow",
        "Build reopened wide",
        "Clamped at the left edge",
        "Clamped at the right edge",
        "Opening the chooser",
        "Degenerate states",
    ):
        assert variant in result.stdout
