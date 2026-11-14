"""An old-style workspace is not shown until it is on the page you asked for (2026-11-09).

You said: "All the extra rendering pages, they're old. Not even supposed to be there behind stuff ... when I click
stuff, I can see other pages load." Office, Channels, Token Economy and Marketplace all open the same old page, which
starts on its own default view and only then switches. The frame is kept out of sight until the old page says it is
showing the one that was asked for, and is shown anyway after a few seconds if it never says so.

You also said: "It says canvas. We removed the canvas thing from Thomas." Canvas is no longer in the sidebar list.

``workspace_shell.js`` runs on both sides, so it is run here in node twice: once as the page that owns the frame and
once as the old page inside it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"
SCRIPT = r"""
const fs = require('fs'), vm = require('vm');
function world(isChild) {
  const handlers = {}, posted = [], timers = [];
  const frame = { dataset: {}, contentWindow: {}, classes: new Set(),
    classList: { add: name => frame.classes.add(name), remove: name => frame.classes.delete(name) } };
  const el = () => ({ dataset: {}, style: {}, textContent: '', setAttribute() {}, getAttribute: () => null,
    appendChild() {}, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false } });
  const document = { readyState: 'loading', documentElement: el(), body: el(), head: el(), createElement: el,
    getElementById: () => null, querySelector: () => null, addEventListener() {},
    querySelectorAll: sel => (sel.includes('is-arriving') && frame.classes.has('is-arriving') ? [frame] : []) };
  const window = { document, location: { origin: 'http://thomas', search: '', pathname: '/classic' },
    localStorage: { getItem: () => null, setItem() {} }, addEventListener: (type, fn) => { handlers[type] = fn; },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimeout() {},
    requestAnimationFrame: fn => fn(), matchMedia: () => ({ matches: false, addEventListener() {} }),
    __thomasRuntimeReady: Promise.resolve(), console, HTMLElement: function () {}, CustomEvent: function () {} };
  window.parent = isChild ? { postMessage: message => posted.push(message) } : window;
  window.window = window;
  vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), vm.createContext(window));
  return { shell: window.ThomasWorkspaceShell, window, handlers, posted, frame, timers };
}
const said = (page, mode, source) => page.handlers.message({ origin: 'http://thomas', source,
  data: { type: 'thomas:workspace:shown', mode } });
(async () => {
  const out = {};
  const owner = world(false);
  owner.shell.arrive(owner.frame, 'office');
  out.hidden = owner.frame.classes.has('is-arriving');
  said(owner, 'channels', owner.frame.contentWindow);
  out.hidden_after_another_page = owner.frame.classes.has('is-arriving');
  said(owner, 'office', {});
  out.hidden_after_another_frame = owner.frame.classes.has('is-arriving');
  owner.handlers.message({ origin: 'http://elsewhere', source: owner.frame.contentWindow,
    data: { type: 'thomas:workspace:shown', mode: 'office' } });
  out.hidden_after_a_stranger = owner.frame.classes.has('is-arriving');
  said(owner, 'office', owner.frame.contentWindow);
  out.shown = !owner.frame.classes.has('is-arriving'); out.remembered = owner.frame.dataset.shownMode;
  owner.shell.arrive(owner.frame, 'office');
  out.same_page_again_is_not_hidden = !owner.frame.classes.has('is-arriving');

  const silent = world(false);
  silent.shell.arrive(silent.frame, 'office');
  silent.timers.forEach(timer => timer.fn());
  out.silent_page_shown_anyway = !silent.frame.classes.has('is-arriving');
  silent.shell.arrive(silent.frame, 'channels');
  silent.timers[0].fn();
  out.an_old_give_up_does_not_reveal_a_newer_request = silent.frame.classes.has('is-arriving');

  const old = world(true);
  old.window.setSidebarNavMode = mode => { old.switched = mode; };
  old.shell.navigateWorkspace('office');
  await new Promise(resolve => setTimeout(resolve, 20));
  out.old_page_switched = old.switched; out.old_page_said = old.posted;
  console.log(JSON.stringify(out));
})();
"""


@pytest.fixture(scope="module")
def seen() -> dict:
    out = subprocess.run(
        ["node", "-e", SCRIPT, str(WEB / "js" / "workspace_shell.js")],
        capture_output=True, check=False, text=True, encoding="utf-8", timeout=60,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_frame_is_hidden_until_its_own_page_says_it_shows_what_was_asked(seen: dict) -> None:
    assert seen["hidden"] is True
    assert seen["hidden_after_another_page"] is True, "saying it shows Channels does not reveal a request for Office"
    assert seen["hidden_after_another_frame"] is True, "another frame's word does not reveal this one"
    assert seen["hidden_after_a_stranger"] is True, "a message from another origin is ignored"
    assert seen["shown"] is True and seen["remembered"] == "office"


def test_going_back_to_the_page_it_already_shows_hides_nothing(seen: dict) -> None:
    assert seen["same_page_again_is_not_hidden"] is True


def test_a_page_that_never_answers_is_shown_anyway(seen: dict) -> None:
    assert seen["silent_page_shown_anyway"] is True
    assert seen["an_old_give_up_does_not_reveal_a_newer_request"] is True


def test_the_old_page_says_so_once_it_has_switched(seen: dict) -> None:
    assert seen["old_page_switched"] == "office"
    assert seen["old_page_said"] == [{"type": "thomas:workspace:shown", "mode": "office"}]


def test_both_ways_of_opening_an_old_workspace_hide_it_first_and_the_style_hides_without_unloading() -> None:
    tabs = (WEB / "js" / "browser_shell.js").read_text("utf-8")
    single = (WEB / "js" / "chat_workspace_navigation.js").read_text("utf-8")
    assert (
        "if (meta.route === CLASSIC_ROUTE && window.ThomasWorkspaceShell) window.ThomasWorkspaceShell.arrive(" in tabs
    )
    assert tabs.index("ThomasWorkspaceShell.arrive(frame, mode)") < tabs.index("frame.src = meta.route;")
    assert (
        "if (route === CLASSIC_WORKSPACE_ROUTE && window.ThomasWorkspaceShell) window.ThomasWorkspaceShell.arrive("
        in single
    )
    css = (WEB / "css" / "chat_shell.css").read_text("utf-8")
    assert ".tc-workspace-frame.is-arriving { visibility: hidden; }" in css


def test_canvas_is_not_in_the_sidebar_list() -> None:
    tabs = (WEB / "js" / "browser_shell.js").read_text("utf-8")
    single = (WEB / "js" / "chat_workspace_navigation.js").read_text("utf-8")
    assert '"Canvas": {' not in tabs and "label: 'Canvas'" not in single
