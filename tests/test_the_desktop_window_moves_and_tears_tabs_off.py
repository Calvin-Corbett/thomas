"""The desktop window moves like a browser's, and a tab can leave it.

You wrote: "i cant drago a thomas tab like you cna in google chrome or drag the app
around at all its like locked to my screne ... a user should be able to make
multiple sessiosn like one per screen or mroe ... and drag like a tagb off the main
thing and it make s anew ione just like browsers do".

The frameless window had one native drag region, and the tab strip (almost the
whole bar) opted out of it, so there was nothing to grab. The bar now moves the
window itself, tabs reorder, a tab pulled off the strip becomes a window, and a
window can be opened on its own. The arithmetic (``desktop/window_geometry.js``) and
the in-page gestures (``browser_shell_tearoff.js``) are run in Node here; the real
Electron run is in the change's description.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = ROOT / "desktop" / "window_geometry.js"
TEAROFF = ROOT / "thomas" / "server" / "web" / "js" / "browser_shell_tearoff.js"
HARNESS = ROOT / "tests" / "web_node" / "browser_shell_tearoff.mjs"
MAIN_JS = ROOT / "desktop" / "main.js"
PRELOAD = ROOT / "desktop" / "preload.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

WORK = {"x": 0, "y": 0, "width": 2000, "height": 1000}


def _geometry(expression: str) -> object:
    program = f"const g = require({json.dumps(str(GEOMETRY))}); console.log(JSON.stringify({expression}));"
    done = subprocess.run(  # noqa: S603 - node on a literal snippet
        [NODE, "-e", program], capture_output=True, check=False, text=True, timeout=30
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def gestures() -> dict:
    done = subprocess.run(  # noqa: S603
        [NODE, str(HARNESS), str(TEAROFF)], capture_output=True, check=False, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_window_moves_exactly_as_far_as_the_pointer_and_keeps_its_size() -> None:
    out = _geometry("g.dragBounds({x:100,y:50,width:1440,height:900},{x:500,y:20},{x:620,y:90})")
    assert out == {"x": 220, "y": 120, "width": 1440, "height": 900}


def test_a_maximized_window_is_restored_under_the_pointer() -> None:
    out = _geometry(
        "g.restoreUnderPointer({x:0,y:0,width:1000,height:700},{x:0,y:0,width:2000,height:1000},{x:1500,y:10})"
    )
    assert out["width"] == 1000 and out["height"] == 700
    assert out["x"] == 750  # the pointer stays at three quarters along the bar


def test_the_screen_edges_snap_a_released_window() -> None:
    assert _geometry(f"g.snapZone({{x:900,y:3}},{json.dumps(WORK)})") == "maximize"
    assert _geometry(f"g.snapZone({{x:2,y:400}},{json.dumps(WORK)})") == "left"
    assert _geometry(f"g.snapZone({{x:1998,y:400}},{json.dumps(WORK)})") == "right"
    assert _geometry(f"g.snapZone({{x:900,y:400}},{json.dumps(WORK)})") is None
    assert _geometry(f"g.snapBounds('left',{json.dumps(WORK)})") == {"x": 0, "y": 0, "width": 1000, "height": 1000}


def test_a_tab_dropped_on_another_windows_strip_joins_it_and_never_its_own() -> None:
    windows = json.dumps(
        [
            {"id": 3, "bounds": {"x": 100, "y": 100, "width": 800, "height": 600}},
            {"id": 1, "bounds": {"x": 0, "y": 0, "width": 800, "height": 600}},
        ]
    )
    assert _geometry(f"g.stripUnder({{x:150,y:120}},{windows},3)") is None  # window 1's body, not its strip
    assert _geometry(f"g.stripUnder({{x:150,y:20}},{windows},3)") == 1
    assert _geometry(f"g.stripUnder({{x:150,y:120}},{windows},1)") == 3
    assert _geometry(f"g.stripUnder({{x:150,y:120}},{windows},3)") is None  # never onto itself


def test_a_torn_off_window_opens_under_the_pointer_and_is_brought_back_into_reach() -> None:
    placed = _geometry(f"g.tearOffBounds({{x:934,y:563}},{{width:1440,height:900}},{json.dumps(WORK)})")
    assert (placed["x"], placed["y"]) == (844, 545)  # follows the pointer, even partly off screen
    kept = _geometry(f"g.keepReachable({{x:1990,y:5000,width:1440,height:900}},{json.dumps(WORK)})")
    assert kept["x"] <= WORK["width"] - 100 and kept["y"] <= WORK["height"] - 60


def test_a_new_window_cascades_off_the_one_in_front() -> None:
    out = _geometry(f"g.cascadeBounds({{x:100,y:100,width:1440,height:500}},{json.dumps(WORK)})")
    assert (out["x"], out["y"]) == (132, 132)


def test_pressing_empty_bar_space_drags_the_window_and_a_button_or_tab_does_not(gestures) -> None:
    assert gestures["window_drag"] == ["start:500:20", "move:540:50", "end:540:50"]
    assert gestures["button_press_drags_window"] is False
    assert gestures["tab_press_drags_window"] is False
    assert gestures["double_click"] == ["max"]


def test_a_tab_dragged_along_the_strip_reorders_and_the_home_tab_keeps_first_place(gestures) -> None:
    assert gestures["order_after_drag_right"] == [1, 3, 2]
    assert gestures["order_after_drag_far_left"] == [1, 3, 2]
    assert gestures["reorder_never_tears"] is False
    assert gestures["plain_order"] == [1, 3, 2]  # a plain browser reorders too, and nothing leaves


def test_a_click_still_selects_the_tab_without_starting_a_drag(gestures) -> None:
    assert gestures["click_calls"] == ["activate:2"]
    assert gestures["click_released_capture"] is True


def test_a_tab_pulled_off_the_strip_detaches_follows_and_lets_go(gestures) -> None:
    assert gestures["tear_calls"] == [
        "dragTab:detach:web:205:90",
        "release:2",
        "dragTab:move::260:300",
        "dragTab:end::300:320",
    ]
    assert gestures["tear_flags"] == {"dragging_cleared": True, "capture_released": True}


def test_a_tab_that_cannot_leave_stays_on_its_strip(gestures) -> None:
    assert gestures["no_spec_calls"] == ["activate:2"]


def test_a_received_tab_reaches_the_shell_and_the_strip_marks_the_drop_target(gestures) -> None:
    assert gestures["adopted"] == ["doc:Moved"]
    assert gestures["hover_on"] is True and gestures["hover_off"] is True


def test_the_pure_helpers_give_the_slots_and_tear_distances_the_strip_uses(gestures) -> None:
    assert gestures["slots"] == [0, 1, 3]
    assert gestures["tear_out"] == [False, True, True]


def test_the_title_bar_no_longer_depends_on_a_native_drag_region() -> None:
    css = (ROOT / "thomas" / "server" / "web" / "css" / "browser_shell.css").read_text(encoding="utf-8")
    assert "-webkit-app-region: drag" not in css


def test_the_app_keeps_one_shell_per_window_and_the_page_can_reach_every_gesture() -> None:
    main = MAIN_JS.read_text(encoding="utf-8")
    preload = PRELOAD.read_text(encoding="utf-8")
    for needle in ('"bt:window-drag"', '"bt:tab-drag"', "function openWindow", "function moveTab", '"second-instance"'):
        assert needle in main, needle
    for needle in ("dragWindow", "dragTab", "newWindow", "onAdopt", "onStripHover", "browser_shell_tearoff.js"):
        assert needle in preload, needle
    shell = (ROOT / "thomas" / "server" / "web" / "js" / "workspace_shell.js").read_text(encoding="utf-8")
    assert "browser_shell_tearoff.js" in shell
