"""Exercise the Build status line's running clock and ended time in Node (the line above the composer)."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "thomas/server/web/js"
DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const start = Date.parse('2024-01-01T12:34:00Z');
let now = start, redraws = 0;
const ticks = [];
const realDateNow = Date.now;
Date.now = () => now;
const mount = { ctx: null, querySelector() { return null; } };
globalThis.document = { createElement: () => ({ className: '', dataset: {}, setAttribute() {}, innerHTML: '' }),
  getElementById: id => (id === 'tc-code-composer-extras' ? mount : null) };
globalThis.window = { setInterval: fn => { ticks.push(fn); return ticks.length; }, ThomasCodeViewState: {
  capture: () => ({}), restore() {},
} };
globalThis.EventSource = class { constructor(url) { this.url = url; EventSource.latest = this; } close() { this.closed = true; } };
for (const path of process.argv.slice(1)) vm.runInThisContext(fs.readFileSync(path, 'utf8'), { filename: path });
// The stack above the composer is real markup in the page; here its paint is kept to read.
window.ThomasCodeComposer.render = (root, ctx) => { root.ctx = ctx; return true; };
const state = { running: false, activeId: 'a', runId: 'run-a', runStartedAt: 0, runStatus: 'ready',
  conversation: { turns: [] }, liveEvents: [], artifacts: [], changes: [], tree: [],
  contextEpoch: 1, projectRoot: '/repo', queuedSends: [] };
const transcript = { scrollHeight: 0, clientHeight: 500, scrollTop: 0, insertAdjacentHTML() {} };
const root = {
  _html: '', get innerHTML() { return this._html; },
  set innerHTML(value) { this._html = value; redraws++; },
  querySelector(selector) {
    if (selector === '.tc-code-transcript') return transcript;
    if (selector === '.tc-code-actions') return { insertAdjacentHTML() {} };
    return null;
  }, querySelectorAll() { return []; },
};
const esc = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const deps = new Proxy({ state, adapterActive: true, surface: () => root, transcriptScroller: () => transcript,
  esc, turnHtml: () => '<article class="tc-code-turn">Done</article>',
  progressEvents: () => [], finalReplyEvent: () => null, interleavedActivityHtml: () => '',
  codeResults: () => ({ viewerHtml: () => '', bindViewer() {}, bindDrawerResize() {}, bindArtifactActions() {},
    playtestChatCardHtml: () => '', artifactCardsHtml: () => '', artifactHtml: () => '', publishColumnState() {}, presentNewestResult: async () => {} }),
  codeProjects: () => ({ projectDisplayLabel: () => 'Project', updateProjectButton() {} }),
  historyAskHtml: () => '', emptyStateHtml: () => '', surface: () => root,
  eventType: event => event.type || event.kind, annotateTerminalEvent() {}, flagExpectedProbe() {},
  lifecycle: () => ({ streamUrl: () => '/stream', acceptEvent: () => true, registerRunProof() {},
    runIsDurable: () => true, contextToken: () => ({ id: 'a', epoch: 1 }) }),
  adoptStartedConversation: (cid, path, id) => { state.activeId = cid; state.runId = id; state.running = true;
    state.runStartedAt = Date.now(); state.runStatus = 'working'; },
  refresh: async () => {}, loadConversation: async () => { state.conversation.turns = [{role:'agent'}]; return true; },
  safely: fn => Promise.resolve().then(fn), terminalRunStatus: event => event.ok ? 'completed' : 'failed',
  host: () => ({ setBusy() {} }), render: () => surface.render(),
  eventHtml: () => '<div class="tc-code-live-event">row</div>',
  isActive: () => true, MAX_LIVE_EVENTS: 120, MAX_VISIBLE_PROGRESS_EVENTS: 120,
  scrollTranscriptToNewest() {},
}, { get: (target, name) => name in target ? target[name] : (() => '') });
deps.controls = window.ThomasCodeControls.create(deps);
const surface = window.ThomasCodeSurface.create(deps);
const live = window.ThomasCodeLiveView.create(deps);
Object.assign(deps, { pushLiveEvent: live.pushLiveEvent, appendLiveEvent: live.appendLiveEvent,
  updateRunStatus: live.updateRunStatus });
const stream = window.ThomasCodeRunStream.create(deps);
// The status line above the composer: its words, then the run's clock.
function read() {
  const status = mount.ctx && mount.ctx.status;
  if (!status) return null;
  const clock = typeof status.elapsed === 'number' ? window.ThomasCodeComposer.formatElapsed(status.elapsed) : status.elapsed;
  return { text: `${status.words} ${clock}`, clock, tone: status.tone };
}
function send(event) { EventSource.latest.onmessage({ data: JSON.stringify(event) }); return read(); }
function tick() { ticks.forEach(fn => fn()); return read(); }
(async () => {
  surface.render();
  await stream.acceptStartedRun({ conversation_id: 'a', project_root: '/repo', run_id: 'run-a', run_state: 'running' });
  const starting = read(), drawsBeforeTicks = redraws;
  const clocks = [[0, starting.clock]];
  for (const seconds of [59, 60, 185, 3599, 3600, 3840]) {
    now = start + seconds * 1000;
    clocks.push([seconds, tick().clock]);
  }
  const drawsAfterTicks = redraws;
  const edit = send({ type: 'output', kind: 'tool', name: 'Edit', text: 'src/main.js' });
  const actionStart = state.actionLine.at;
  now += 185000;
  const editLater = tick();
  const drawsBeforeLoss = redraws;
  EventSource.latest.onerror();
  const disconnected = read();
  state.source = EventSource.latest;
  const restored = send({ type: 'output', kind: 'meta', text: 'stream back' });
  const drawsAfterLoss = redraws;
  now += 90000;
  const restoredLater = tick();
  const finishAt = now;
  const finished = send({ type: 'done', ok: true, persistence_confirmed: true, changed_files: ['a', 'b'] });
  const endedAt = state.actionLine.at;
  const endTime = () => new Date(state.actionLine.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const finishTime = endTime(), finishHour = new Date(endedAt).getHours();
  now += 90000;
  const afterTick = tick();
  surface.render();
  const afterRedraw = read();
  await new Promise(resolve => setImmediate(resolve));
  const otherEndTimes = [];
  async function endAnother(data, stopping = false) {
    await stream.acceptStartedRun({ conversation_id: 'a', project_root: '/repo', run_id: 'another', run_state: 'running' });
    state.runStatus = stopping ? 'stopping' : 'working';
    const result = send({ type: 'done', ...data });
    otherEndTimes.push(endTime());
    await new Promise(resolve => setImmediate(resolve));
    return result;
  }
  const stopped = await endAnother({ ok: false, outcome: 'stopped', persistence_confirmed: false }, true);
  const problem = await endAnother({ ok: false, persistence_confirmed: false });
  console.log(JSON.stringify({ starting, clocks, drawsBeforeTicks, drawsAfterTicks, edit, editLater,
    actionStart, disconnected, restored, restoredLater, drawsBeforeLoss, drawsAfterLoss,
    finished, finishAt, endedAt, finishTime, finishHour, afterTick, afterRedraw, stopped, problem, otherEndTimes }));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => { Date.now = realDateNow; });
"""


def exercise(zone="UTC"):
    paths = [
        JS / f"unified_code_{part}.js"
        for part in ("composer", "surface", "live_view", "run_stream", "questions", "controls")
    ]
    result = subprocess.run(
        ["node", "-e", DRIVER, *map(str, paths)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "TZ": zone},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_running_ticks_and_new_action_start_without_redrawing():
    """The clock is the run's (design 3a: "Step 4 of 5 · 1m 12s"), ticking in
    place; a new action changes the words, never the clock or the transcript."""
    seen = exercise()
    assert seen["clocks"] == [
        [0, "0s"],
        [59, "59s"],
        [60, "1m 0s"],
        [185, "3m 5s"],
        [3599, "59m 59s"],
        [3600, "1h 00m"],
        [3840, "1h 04m"],
    ]
    assert seen["drawsAfterTicks"] == seen["drawsBeforeTicks"]
    assert seen["edit"]["text"] == "Thomas is editing 1h 04m"
    assert seen["editLater"]["clock"] == "1h 07m"
    assert seen["starting"]["text"] == "Thomas is starting 0s"
    assert seen["starting"]["tone"] == "working"


def test_reconnect_restores_previous_action_words():
    seen = exercise()
    assert seen["disconnected"]["text"] == "Reconnecting 1h 07m"
    assert seen["restored"]["text"] == "Thomas is editing 1h 07m"
    assert seen["restoredLater"]["clock"] == "1h 08m"
    assert seen["drawsAfterLoss"] == seen["drawsBeforeLoss"] + 1


@pytest.mark.parametrize("zone, hour", [("UTC", 13), ("Asia/Tokyo", 22)])
def test_end_time_in_viewers_zone_survives_tick_and_redraw(zone, hour):
    seen = exercise(zone)
    # 12:34 UTC + 1 h 04 min + 3 min 05 s + 90 s = 13:42 UTC.
    assert seen["endedAt"] == seen["finishAt"]
    assert seen["finishHour"] == hour
    # Once a run has ended the line goes away: no "ended at" clock anywhere.
    for ended in ("finished", "afterTick", "afterRedraw", "stopped", "problem"):
        assert seen[ended] is None, ended
