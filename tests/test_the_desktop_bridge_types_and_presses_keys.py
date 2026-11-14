"""The desktop app's agent bridge can type and press keys, so Thomas can be used
without the owner's mouse or keyboard.

Before this, the bridge had clicks and reads only, and it could not reach the
Thomas page itself. These tests run the real desktop/cdp.js under Node with a
stand-in for the page's debugger and check exactly what it would send.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

CDP = Path(__file__).resolve().parents[1] / "desktop" / "cdp.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

DRIVER = r"""
const cdp = require(process.argv[1]);
const sent = [];
const view = { webContents: {
  focus() {},
  debugger: { isAttached: () => true, sendCommand: async (m, p) => { sent.push([m, p]); return {}; } },
} };
(async () => {
  const out = {};
  await cdp.cdpType(view, "hello");
  await cdp.cdpKey(view, "Enter");
  await cdp.cdpKey(view, "a", ["ctrl"]);
  try { await cdp.cdpKey(view, "NotAKey"); out.unknown = "no error"; } catch (e) { out.unknown = String(e.message); }
  out.sent = sent;
  console.log(JSON.stringify(out));
})();
"""


def _run() -> dict:
    result = subprocess.run([NODE, "-e", DRIVER, str(CDP)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_typing_sends_the_text_as_one_insert() -> None:
    sent = _run()["sent"]
    assert ["Input.insertText", {"text": "hello"}] in sent


def test_enter_is_a_key_down_with_a_carriage_return_then_a_key_up() -> None:
    sent = _run()["sent"]
    keys = [params for method, params in sent if method == "Input.dispatchKeyEvent"]
    enter_down, enter_up = keys[0], keys[1]
    assert enter_down["type"] == "keyDown" and enter_down["text"] == "\r" and enter_down["windowsVirtualKeyCode"] == 13
    assert enter_up["type"] == "keyUp" and enter_up["key"] == "Enter"


def test_a_chord_carries_its_modifier_and_types_no_character() -> None:
    sent = _run()["sent"]
    keys = [params for method, params in sent if method == "Input.dispatchKeyEvent"]
    ctrl_a = keys[2]
    assert ctrl_a["modifiers"] == 2 and ctrl_a["type"] == "rawKeyDown" and "text" not in ctrl_a


def test_an_unknown_key_is_refused_and_says_what_is_allowed() -> None:
    message = _run()["unknown"]
    assert "unknown key NotAKey" in message and "Enter" in message


EXTRA = CDP.with_name("bridge_extra.js")

EXTRA_DRIVER = r"""
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const make = require(process.argv[1]);
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "bridge-"));
const chromeView = { webContents: {
  isDestroyed: () => false, getURL: () => "http://x/", getTitle: () => "Thomas Chat", focus() {},
  debugger: { isAttached: () => true, sendCommand: async (m) => (m === "Page.captureScreenshot" ? { data: "AAAA" } : {}) },
} };
const shells = new Map([[1, { id: 1, chromeView }]]);
const extra = make({ shells, tabs: new Map(), currentShell: () => shells.get(1),
  app: { getPath: () => temp }, path, fs });
(async () => {
  const out = {};
  out.chromeNamed = extra.chromeOf("chrome") === chromeView;
  out.chromeDefault = extra.chromeOf(null) === chromeView;
  out.webTabIsNotChrome = extra.chromeOf(7) === null;
  out.listed = extra.chromeTabs().map(t => t.tabId);
  const cmds = extra.commands(() => chromeView, () => chromeView);
  const hostile = path.join("..", "..", "evil.jpg");
  const shot = await cmds.screenshot({ tabId: "chrome", file: hostile });
  out.shotInside = path.dirname(shot.file) === path.join(temp, "thomas-shots");
  out.shotName = path.basename(shot.file);
  out.escaped = fs.existsSync(path.join(temp, "..", "evil.jpg"));
  try { await cmds.screenshot({ tabId: "chrome", file: hostile }); out.second = "overwrote"; }
  catch (e) { out.second = String(e.message); }
  console.log(JSON.stringify(out));
})();
"""


def _run_extra() -> dict:
    result = subprocess.run(
        [NODE, "-e", EXTRA_DRIVER, str(EXTRA)], capture_output=True, text=True, timeout=60, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_chrome_names_the_thomas_page_and_a_tab_number_does_not() -> None:
    out = _run_extra()
    assert out["chromeNamed"] and out["chromeDefault"] and out["webTabIsNotChrome"]
    assert out["listed"] == ["chrome:1"]


def test_a_screenshot_name_cannot_leave_the_screenshot_folder_or_overwrite() -> None:
    out = _run_extra()
    assert out["shotInside"] and out["shotName"] == "evil.jpg" and not out["escaped"]
    assert "already exists" in out["second"]
