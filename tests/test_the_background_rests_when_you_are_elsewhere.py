"""The animated background rests while you are using another window, and wakes when you come back.

Measured 2026-11-09 on the desktop app, 15 seconds each: the window took 5.8% of a 16-core PC with its 14 never-ending
animations running, 2.5% with them paused, and 4.9% running again. Almost all of the difference was the graphics
process. Those animations are the decorative world behind the page; they ran all day whether or not Thomas was the
window in use. A dot that shows work going on is not part of the world and keeps moving, so nothing looks stuck.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORLDS = ROOT / "thomas/server/web/js/chat_worlds.js"
CSS = ROOT / "thomas/server/web/css/chat_shell.css"

DRIVER = r"""
const fs = require('fs'); const vm = require('vm');
const listeners = {}; const classes = new Set();
const state = { hidden: false, focused: true, search: process.argv[3] || '' };
const shell = { querySelector: () => null, insertAdjacentHTML: () => {}, classList: { toggle: (n, on) => { on ? classes.add(n) : classes.delete(n); } } };
const document = { get hidden() { return state.hidden; }, hasFocus: () => state.focused, addEventListener: (n, f) => { (listeners['d:' + n] = listeners['d:' + n] || []).push(f); } };
const window = { location: { get search() { return state.search; } }, addEventListener: (n, f) => { (listeners['w:' + n] = listeners['w:' + n] || []).push(f); }, setTimeout: (f) => f() };
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), { window, document, setTimeout: (f) => f(), URLSearchParams });
window.ThomasChatWorlds.mount(shell);
const fire = (k) => (listeners[k] || []).forEach((f) => f());
const seen = {};
seen.at_start = classes.has('is-resting');
state.focused = false; fire('w:blur'); seen.after_blur = classes.has('is-resting');
state.focused = true; fire('w:focus'); seen.after_focus = classes.has('is-resting');
state.hidden = true; fire('d:visibilitychange'); seen.when_hidden = classes.has('is-resting');
state.hidden = false; fire('d:visibilitychange'); seen.when_shown = classes.has('is-resting');
// Clicking into an embedded workspace blurs the top window, but the document still has focus.
state.focused = true; fire('w:blur'); seen.focus_in_a_panel = classes.has('is-resting');
console.log(JSON.stringify(seen));
"""


def _run(tmp_path: Path, search: str = "") -> dict[str, bool]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    driver = tmp_path / "driver.js"
    driver.write_text(DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(driver), str(WORLDS), search], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_it_rests_when_the_window_loses_you_and_wakes_when_you_return(tmp_path: Path) -> None:
    seen = _run(tmp_path)
    assert seen == {
        "at_start": False,
        "after_blur": True,
        "after_focus": False,
        "when_hidden": True,
        "when_shown": False,
        "focus_in_a_panel": False,
    }


def test_asking_for_motion_keeps_it_moving(tmp_path: Path) -> None:
    seen = _run(tmp_path, "?motion=1")
    assert not any(seen.values())


def test_only_the_world_behind_the_page_is_paused() -> None:
    css = CSS.read_text(encoding="utf-8")
    rule = next((line for line in css.splitlines() if "is-resting" in line), "")
    assert ".tc-shell.is-resting .tc-world" in rule and "animation-play-state: paused" in rule
    assert rule.count("{") == 1, "one rule, for the world alone"
    before = rule.split("{")[0]
    assert all(".tc-world" in part for part in before.split(",")), "nothing outside the world may be paused"
