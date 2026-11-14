"""The shipped self-edit UI renders independent run state and truthful activation."""

import subprocess
from pathlib import Path


def test_self_edit_controls_are_bound_to_the_active_task_and_run():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(root / "tests/web_node/self_edit_controls.mjs")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_restart_waits_for_the_new_server_and_shows_what_it_waits_for():
    """The restart has no clock: it follows the server until a new one answers, and the strip says what it waits for.

    You said the menu's restart "just sits there, and all of a sudden, nothing happens". The strip now names the runs
    and checks a restart is draining and how long it has been; the only failure it reports on its own is a server that
    keeps answering as before and says no restart is under way.
    """
    root = Path(__file__).resolve().parents[1]
    driver = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('  async function restart()');
const end = source.indexOf('  // Self-edit Apply', start);
assert(start >= 0 && end > start);
for (const scenario of ['rejected', 'replaced', 'reset', 'draining', 'unchanged', 'no-identity', 'busy', 'unmounted']) {
  let now = 0, reloads = 0, requests = 0, polls = 0;
  const texts = [];
  const label = {}, button = {dataset: {}, querySelector: () => label, setAttribute() {}};
  const node = () => { const n = {dataset: {}, kids: [], setAttribute() {}, append(...k) { n.kids.push(...k); }, querySelector() { return n.kids[0] || n; }}; return n; };
  const textNode = node();
  Object.defineProperty(textNode, 'textContent', { set(v) { texts.push(v); }, get() { return texts[texts.length - 1]; } });
  const strip = node(); strip.kids.push(textNode);
  const ctx = {busy: scenario === 'busy', menu: scenario === 'unmounted' ? null : {}, restartButton: button, strip: null,
    initialPid: scenario === 'no-identity' ? null : 10, initialUptime: 100, initialGeneration: 'g1',
    refreshIdentity: async () => {}, mount() {ctx.menu = {};}, close() {}, NOT_STARTED_MS: 20, POLL_MS: 5,
    Date: {now: () => now}, setTimeout(fn, ms) {now += ms; fn();},
    document: {createElement: (tag) => tag === 'div' ? strip : node(), body: {append() {}}},
    health: async () => {
      polls++;
      if (scenario === 'draining') {
        // Three answers while checks drain, then the new server answers with a new pid.
        if (polls <= 3) return {pid: 10, uptime_s: 101, restart: {restarting: true, generation: 'g1', waiting_for: ['Build run'], checks_running: 2}};
        return {pid: 11, uptime_s: 1, build: {commit: 'abc12345'}, restart: {restarting: false, generation: 'g2'}};
      }
      return {pid: scenario === 'replaced' ? 11 : 10, uptime_s: ['reset', 'unmounted'].includes(scenario) ? 1 : 101,
        restart: {restarting: false, generation: 'g1'}};
    },
    fetch: async () => {requests++; return {ok: scenario !== 'rejected', json: async () => ({ok: scenario !== 'rejected', error: 'Live work is active'})};},
    window: {dispatchEvent() {reloads++;}}, CustomEvent: class {}};
  vm.createContext(ctx); vm.runInContext(source.slice(start, end), ctx);
  const result = await ctx.restart();
  const success = ['replaced', 'reset', 'draining', 'unmounted'].includes(scenario);
  assert.equal(result.ok, success, scenario + ': ' + JSON.stringify(result));
  assert.equal(reloads, success ? 1 : 0, scenario);
  if (['busy', 'no-identity'].includes(scenario)) assert.equal(requests, 0);
  if (scenario === 'rejected') assert.equal(result.error, 'Live work is active');
  if (scenario === 'draining') {
    assert.ok(texts.some(t => t.startsWith('Restarting Thomas: waiting for Build run (2 checks running)')), texts.join(' | '));
    assert.ok(texts.some(t => t.startsWith('Thomas is back on abc12345')), texts.join(' | '));
  }
  if (scenario === 'unchanged') {
    assert.match(result.error, /did not begin/);
    assert.ok(polls >= 4, 'it asked more than once before saying the restart did not begin: ' + polls);
  }
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", driver, str(root / "thomas/server/web/js/shell_context_menu.js")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
