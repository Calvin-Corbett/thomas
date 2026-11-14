"""The Library replaces a quick partial catalogue without waiting to open."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "thomas/server/web/static"


def test_library_loads_followup_after_its_existing_renderer() -> None:
    html = (STATIC / "my_stuff.html").read_text(encoding="utf-8-sig")
    assert html.index("my_stuff.script01.js") < html.index("library_catalogue_followup.js")


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js required to exercise browser JavaScript")
def test_partial_catalogue_retries_then_uses_library_refresh() -> None:
    source = STATIC / "library_catalogue_followup.js"
    script = r"""
const fs = require('fs');
const vm = require('vm');
const timers = [];
const responses = [true, false];
let clicks = 0;
let requests = 0;
const sandbox = {
  window: { addEventListener(name, callback) {
    if (name !== 'DOMContentLoaded') throw new Error('unexpected event');
    callback();
  } },
  document: { getElementById(name) {
    if (name !== 'refreshButton') throw new Error('unexpected element');
    return { click() { clicks++; } };
  } },
  setTimeout(fn) { timers.push(fn); },
  fetch: async () => ({ ok: true, json: async () => ({ refreshing: responses[requests++] }) }),
};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
async function tick() {
  const next = timers.shift();
  if (!next) throw new Error('no retry scheduled');
  await next();
  await new Promise(resolve => setImmediate(resolve));
}
(async () => {
  await tick();
  if (clicks !== 0 || requests !== 1) throw new Error('partial response must not refresh yet');
  await tick();
  if (clicks !== 1 || requests !== 2 || timers.length) throw new Error('complete response must refresh once');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(["node", "-e", script, str(source)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js required to exercise browser JavaScript")
def test_a_turned_off_list_is_asked_for_once_and_not_again() -> None:
    """With the workspace row off the list answers 404. The page asked again every second for as long as it stayed open."""
    source = STATIC / "library_catalogue_followup.js"
    script = r"""
const fs = require('fs');
const vm = require('vm');
const timers = [];
let requests = 0;
const sandbox = {
  window: { addEventListener(name, callback) { callback(); } },
  document: { getElementById() { return { click() { throw new Error('nothing to refresh'); } }; } },
  setTimeout(fn) { timers.push(fn); },
  fetch: async () => { requests++; return { ok: false, status: 404 }; },
};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
(async () => {
  await timers.shift()();
  await new Promise(resolve => setImmediate(resolve));
  if (requests !== 1 || timers.length) throw new Error('asked ' + requests + ' times, ' + timers.length + ' more waiting');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(["node", "-e", script, str(source)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
