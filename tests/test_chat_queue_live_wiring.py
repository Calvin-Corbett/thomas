"""Exercise the real chat shell's dependency wiring, not a copied binding."""

import subprocess
from pathlib import Path

DRIVER = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = process.argv[1];
const html = fs.readFileSync(root + '/thomas/server/web/chat.html', 'utf8');
const inline = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).filter(Boolean).at(-1);
assert.ok(inline, 'the live chat shell has an inline entry point');
const calls = { session: null, view: null, restores: [] };
const noop = () => {};
const standin = new Proxy(noop, { get: (_, key) => key === 'then' ? undefined : standin,
  apply: () => standin, set: () => true });
const element = () => ({style: {setProperty: noop}, classList: {add: noop, remove: noop,
  toggle: noop, contains: () => false}, addEventListener: noop, appendChild: noop,
  setAttribute: noop, getAttribute: () => null, querySelector: () => null,
  querySelectorAll: () => [], value: '', innerHTML: ''});
const doc = {getElementById: () => element(), querySelector: () => element(),
  querySelectorAll: () => [], createElement: element, addEventListener: noop};
const storage = {getItem: () => null, setItem: noop, removeItem: noop};
const queue = {restoreQueued: () => calls.restores.push('restored'), drainQueued: noop};
const win = new Proxy({addEventListener: noop, location: {search: ''}, parent: {},
  ThomasChatTurnFlow: {createSessionProvider: () => noop, create: () => queue},
  ThomasChatMessageView: {create(deps) { calls.view = deps; return standin; }},
  ThomasChatSessionRestore: {create(deps) { calls.session = deps; return standin; }}},
  {get(target, key) { return key in target ? target[key] : standin; }});
const ctx = {window: win, document: doc, localStorage: storage, fetch: async () => ({}),
  console, setTimeout: noop, clearTimeout: noop, setInterval: noop,
  requestAnimationFrame: noop,
  navigator: {}, URLSearchParams, Promise};
vm.createContext(ctx);
vm.runInContext(inline, ctx, {filename: 'chat.html', timeout: 2000});
assert.ok(calls.session, 'the live shell creates the session module');
assert.ok(calls.view, 'the live shell creates the message view');
assert.equal(calls.session.turnFlow, queue, 'session restore receives the live queue');
assert.equal(calls.view.turnFlow, queue, 'message redraw receives the live queue');
calls.session.turnFlow.restoreQueued(); calls.view.turnFlow.restoreQueued();
assert.equal(calls.restores.length, 2);
console.log('live chat shell gives redraw modules their queued-message flow: passed');
"""


def test_live_chat_shell_passes_its_queue_to_both_redraw_modules():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "-e", DRIVER, str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
