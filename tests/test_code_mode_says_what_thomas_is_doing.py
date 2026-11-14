"""A Build conversation keeps its current action visible in the status line above the composer."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "thomas/server/web/js"
CSS = ROOT / "thomas/server/web/css/unified_code_mode.css"
DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let now = 100000, redraws = 0;
const timers = [];
const realDateNow = Date.now;
Date.now = () => now;
const mount = { ctx: null, querySelector() { return null; } };
globalThis.document = { createElement: () => ({ className: '', dataset: {}, setAttribute() {}, innerHTML: '' }),
  getElementById: id => (id === 'tc-code-composer-extras' ? mount : null) };
globalThis.window = { setInterval: fn => { timers.push(fn); return timers.length; }, ThomasCodeViewState: {
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
  _html: '', get innerHTML() { return this._html; }, set innerHTML(value) { this._html = value; redraws++; },
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
  return { text: `${status.words} ${clock}`, clock, tone: status.tone,
    html: root.innerHTML + window.ThomasCodeComposer.extrasHtml(mount.ctx) };
}
function send(event) { EventSource.latest.onmessage({ data: JSON.stringify(event) }); return read(); }
(async () => {
  surface.render();
  const empty = read();
  await stream.acceptStartedRun({ conversation_id: 'a', project_root: '/repo', run_id: 'run-a', run_state: 'running' });
  const starting = read();
  const tool = (name, text = '') => send({ type: 'output', kind: 'tool', name, text });
  const edit = tool('Edit', 'src/main.js');
  const afterResult = send({type: 'output', kind: 'tool_result', text: 'ok'});
  const bashTest = tool('Bash', 'python -m pytest tests/test_app.py');
  const bashCommand = tool('Bash', 'git status');
  const reading = tool('Read', 'src/main.js');
  const shellTest = tool('shell.exec', 'pytest -q');
  const fileRead = tool('fs.read_file', 'src/main.js');
  const planning = send({type:'output', kind:'planning', text:'thinking'});
  const say = send({type:'output', kind:'say', text:'working'});
  const check = tool('run', 'checks');
  const search = tool('Grep', 'needle');
  const steer = send({type:'steering', text:'go left'});
  const reason = send({type:'output', kind:'reason', text:'why'});
  const note = send({type:'output', kind:'meta', text:'metadata'});
  const script = tool('Edit', '<script>globalThis.injected=true</script>');
  const safe = { ...script, hasScriptElement: /<script\b/i.test(root.innerHTML), injected: !!globalThis.injected };
  // Your steer is acknowledged at once, before the lead has read it.
  state.steers = [{ runId: state.runId, state: 'sending' }];
  window.ThomasCodeLiveView.paintExtras(state);
  const acknowledging = read();
  state.steers = [];
  window.ThomasCodeLiveView.paintExtras(state);
  const drawsBeforeTick = redraws;
  now += 5000; timers.forEach(fn => fn());
  const later = read(), drawsAfterTick = redraws;
  EventSource.latest.onerror();
  const disconnected = read();
  state.source = EventSource.latest;
  const reconnectedNote = send({type:'output', kind:'meta', text:'stream back'});
  const resumed = tool('Read', 'src/next.js');
  send({type:'done', ok:true, persistence_confirmed:true, changed_files:['a','b']});
  const done = read();
  await new Promise(resolve => setImmediate(resolve));
  const afterReplacement = read();
  async function ending(data, stopPending = false) {
    state.runStatus = stopPending ? 'stopping' : 'working';
    await stream.acceptStartedRun({ conversation_id: 'a', project_root: '/repo', run_id: 'another', run_state: 'running' });
    state.runStatus = stopPending ? 'stopping' : 'working';
    send({ type: 'done', ...data });
    const result = read();
    await new Promise(resolve => setImmediate(resolve));
    return result;
  }
  const noop = await ending({ ok: true, noop: true, persistence_confirmed: true, changed_files: [] });
  const stopped = await ending({ ok: false, outcome: 'stopped', persistence_confirmed: false });
  const failed = await ending({ ok: false, persistence_confirmed: false });
  const clickedStop = await ending({ ok: false, persistence_confirmed: false }, true);
  state.activeId = 'other'; state.running = false; state.liveEvents = []; state.conversation = {turns:[]};
  surface.render();
  const other = read();
  state.activeId = 'a'; state.running = true; state.runStatus = 'working';
  surface.render();
  stream.openStream();
  const reattached = read();
  const reattachedFirstEvent = send({type:'output', kind:'tool', name:'Read', text:'src/next.js'});
  globalThis.fetch = async () => ({ok:true, status:200, json:async () => ({ok:true, running:false, recording:false})});
  EventSource.latest.onerror();
  await new Promise(resolve => setImmediate(resolve));
  const lostRun = read(), lostRunEnded = state.actionLine?.ended;
  state.running = false;
  await stream.acceptStartedRun({conversation_id:'a', project_root:'/repo', run_id:'replay',
    run_state:'completed', ok:true, persistence_confirmed:true, changed_files:['one','two']});
  const replay = read(), replayEnded = state.actionLine?.ended;
  console.log(JSON.stringify({empty, starting, edit, afterResult, bashTest, bashCommand, reading,
    shellTest, fileRead, planning, say, check, search, steer, reason, note, safe, acknowledging,
    later, drawsBeforeTick, drawsAfterTick, disconnected, reconnectedNote, resumed, done, afterReplacement,
    noop, stopped, failed, clickedStop, other, reattached, reattachedFirstEvent, lostRun, lostRunEnded, replay, replayEnded}));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => { Date.now = realDateNow; });
"""


def exercise():
    paths = [
        JS / f"unified_code_{part}.js"
        for part in ("composer", "surface", "live_view", "run_stream", "questions", "controls")
    ]
    result = subprocess.run(
        ["node", "-e", DRIVER, *map(str, paths)], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_live_action_names_and_elapsed_without_redrawing_turns():
    seen = exercise()
    assert seen["empty"] is None
    assert "Thomas is starting" in seen["starting"]["text"]
    for key, words in {
        "edit": "Thomas is editing",
        "afterResult": "Thomas is editing",
        "bashTest": "Thomas is testing",
        "bashCommand": "Thomas is running",
        "reading": "Thomas is reading",
        "shellTest": "Thomas is testing",
        "fileRead": "Thomas is reading",
        "planning": "Thomas is planning",
        "say": "Thomas is thinking",
        "check": "Thomas is testing",
        "search": "Thomas is searching",
        "steer": "Steering",
        "reason": "Thomas is thinking",
        "note": "Thomas is thinking",
    }.items():
        assert seen[key]["text"].startswith(words + " "), (key, seen[key])
        # A short plain phrase (the last word is the clock), never the event's text.
        assert len(seen[key]["text"].split()) <= 5, (key, seen[key])
    assert seen["acknowledging"]["text"].startswith("Acknowledging your message "), seen["acknowledging"]
    # The event's own text never reaches the line, so nothing in it can be markup.
    assert "<script>" not in seen["safe"]["text"]
    assert not seen["safe"]["hasScriptElement"] and not seen["safe"]["injected"]
    # The clock is the run's (design 3a "Step 4 of 5 · 1m 12s"), and it ticks
    # in place: the transcript is not redrawn for it.
    assert seen["safe"]["clock"] == "0s"
    assert seen["later"]["clock"] == "5s"
    assert seen["drawsAfterTick"] == seen["drawsBeforeTick"]
    assert seen["disconnected"]["text"].startswith("Reconnecting ")
    assert seen["reconnectedNote"]["text"].startswith(seen["safe"]["text"].removesuffix(" 0s"))
    assert seen["reconnectedNote"]["clock"] == "5s"
    assert "Thomas is reading" in seen["resumed"]["text"]
    # A finished run draws no status line at all: it only shows while a run is live or paused.
    for ended in ("done", "afterReplacement", "noop", "stopped", "failed", "clickedStop"):
        assert seen[ended] is None, ended
    assert seen["other"] is None


def test_reattaching_to_the_conversation_restores_its_running_line():
    seen = exercise()
    assert seen["other"] is None
    assert "Thomas is starting" in seen["reattached"]["text"]
    assert "Thomas is reading" in seen["reattachedFirstEvent"]["text"]


def test_stream_loss_with_no_active_run_ends_the_reconnecting_line():
    seen = exercise()
    assert seen["lostRun"] is None
    assert seen["lostRunEnded"] is True


def test_replayed_finished_run_ends_the_starting_line():
    seen = exercise()
    assert seen["replay"] is None
    assert seen["replayEnded"] is True


def test_the_line_sits_above_the_composer_not_in_the_transcript():
    """Design 3a moved the line out of the transcript's sticky top to the stack
    directly above the composer (#tc-code-composer-extras), one line that never
    wraps. The old sticky line and its rule left with it."""
    html = (ROOT / "thomas/server/web/chat.html").read_text(encoding="utf-8")
    assert html.index('id="tc-code-composer-extras"') < html.index('id="tc-composer-rail"')
    assert ".tc-code-action-line" not in CSS.read_text(encoding="utf-8")
    assert "data-code-now" not in (JS / "unified_code_surface.js").read_text(encoding="utf-8")
    composer_css = (ROOT / "thomas/server/web/css/unified_code_composer.css").read_text(encoding="utf-8")
    words = re.search(r"\.tc-code-status-words\s*\{([^}]+)\}", composer_css)
    assert words and re.search(r"(?:white-space\s*:\s*nowrap|text-overflow\s*:\s*ellipsis)", words[1])
