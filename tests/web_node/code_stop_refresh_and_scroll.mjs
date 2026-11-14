// Full-stack harness (same shape as unified_code_mode_lifecycle.mjs): loads the
// sibling modules in chat.html order, instruments the Code adapter, and drives
// three lifecycle claims:
//
//   1. stopRun -- the primary button's Stop path -- reloads changes + tree after a
//      confirmed stop, exactly as the post-Keep/Revert path does. Before the
//      fix the FILES panel stayed on "Loading files…" and CHANGED FILES was
//      absent until the user switched away and back.
//   2. The mode-adapter stop() entry point runs the SAME routine: same honest
//      wording, same refresh. There used to be two stop functions with
//      divergent wording and behavior.
//   3. finishRun's durable path scrolls the transcript to the newest turn, so
//      a follow-up run's answer is not left below the fold.
//   4. The LIVE render of a failed run that produced a final answer shows the
//      answer AND the failure note, never only one.
import fs from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const lifecyclePath = process.argv[3];
const siblingPaths = process.argv.slice(4);

let adapter = null;
let busy = false;
let fetchHandler = async () => { throw new Error('unexpected fetch'); };
const snapshots = [];
const controls = new Map();
function control(id = '') {
  if (!controls.has(id)) controls.set(id, {
    id, value: '', dataset: {}, disabled: false,
    addEventListener() {}, focus() {}, setSelectionRange() {},
  });
  return controls.get(id);
}
const transcript = { scrollTop: 0, scrollHeight: 0, clientHeight: 500,
  cardHtml: '', insertAdjacentHTML(_where, html) { this.cardHtml = html; } };
const liveChildren = [];
const liveList = {
  get children() { return liveChildren; },
  get firstElementChild() { return liveChildren[0] || null; },
  get lastElementChild() { return liveChildren.at(-1) || null; },
  closest() { return transcript; },
  insertAdjacentHTML(_where, html) {
    liveChildren.push({
      html,
      remove() { liveChildren.shift(); },
      set outerHTML(value) { this.html = value; },
    });
  },
};
const drawer = { insertAdjacentHTML() {} };
const panel = { style: { setProperty() {} } };
const resizeHandle = { attributes: {}, addEventListener() {}, removeEventListener() {}, setAttribute() {}, setPointerCapture() {} };
const root = {
  get ownerDocument() { return globalThis.document; },
  _html: '',
  get innerHTML() { return this._html; },
  set innerHTML(value) { this._html = value; snapshots.push(value); },
  contains() { return false; },
  querySelector(selector) {
    if (selector === '.tc-code-transcript') return transcript;
    if (selector === '#tc-code-live-events') return liveList;
    if (selector === '.tc-code-actions') return drawer;
    if (selector === '.tc-code-panel') return panel;
    if (selector === '.tc-code-drawer-resize') return resizeHandle;
    if (selector.startsWith('#tc-code-')) return control(selector.slice(1));
    return null;
  },
  querySelectorAll() { return []; },
};
globalThis.window = {
  ThomasUnifiedModes: {
    host: () => ({
      getContext: () => ({}),
      renderHistory() {},
      setBusy(value) { busy = value; },
    }),
    registerAdapter(_mode, value) { adapter = value; },
  },
  setInterval() { return 0; },
};
globalThis.document = {
  activeElement: null,
  getElementById(id) { return id === 'tc-mode-surface' ? root : control(id); },
  createElement: () => ({ className: '', innerHTML: '', disabled: false, classList: { add() {} }, addEventListener() {} }),
};
globalThis.localStorage = { getItem: () => '', setItem() {}, removeItem() {} };
console.warn = () => {};
globalThis.fetch = (...args) => fetchHandler(...args);
globalThis.setTimeout = callback => { queueMicrotask(callback); return 0; };
globalThis.EventSource = class {
  constructor(url) { this.url = url; this.closed = false; }
  close() { this.closed = true; }
};

vm.runInThisContext(fs.readFileSync(lifecyclePath, 'utf8'), { filename: lifecyclePath });
for (const siblingPath of siblingPaths) {
  vm.runInThisContext(fs.readFileSync(siblingPath, 'utf8'), { filename: siblingPath });
}
const source = fs.readFileSync(sourcePath, 'utf8');
const instrumented = source.replace(
  /\n\}\)\(\);\s*$/,
  '\n  window.__ThomasCodeStopTest = { state, activate: () => { adapterActive = true; }, finishRun, pushLiveEvent, render, stopRun, steer };\n})();',
);
if (instrumented === source) throw new Error('could not instrument Code stop adapter');
vm.runInThisContext(instrumented, { filename: sourcePath });
const api = window.__ThomasCodeStopTest;
const state = api.state;
api.activate();

function response(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, async json() { return data; } };
}

function resetState() {
  if (state.source) state.source.close();
  Object.assign(state, {
    conversations: [], activeId: '', conversation: null, liveEvents: [], changes: [], tree: [], treeLoaded: false,
    treePath: '', artifacts: [], filePreview: null, pendingApproval: null, pendingRequest: null, lastContext: {},
    running: false, runStartedAt: 0, runStatus: 'ready', source: null, finishing: null, approvalBusy: false,
    steeringBusy: false, projectRoot: '', terminalTool: '', contextEpoch: state.contextEpoch + 1, runProof: null,
    runId: '', eventCursor: 0, retryRequest: null, pendingUserText: '', queuedSends: [],
  });
  busy = false;
  snapshots.length = 0;
  liveChildren.length = 0;
  transcript.scrollTop = 0;
  transcript.scrollHeight = 0;
}

// The fetch surface a confirmed stop needs: the stop itself, the status poll
// that confirms termination, and the changes + tree the drawer must reload.
function stopFetchSurface(counts) {
  return async url => {
    if (url === '/api/issues') return response({ ok: true });
    if (url.endsWith('/stop')) { counts.stop += 1; return response({ ok: true, stopped: true, termination_confirmed: true, returncode: -15 }); }
    if (url.includes('/status')) return response({ ok: true, running: false, recording: false });
    if (url.includes('/changes?')) { counts.changes += 1; return response({ changed: [{ file: 'app.js', diff: '+partial work' }] }); }
    if (url.includes('/tree')) { counts.tree += 1; return response({ ok: true, entries: [{ name: 'app.js', kind: 'file', path: 'app.js' }], path: '' }); }
    throw new Error(`unexpected stop fetch ${url}`);
  };
}

function runningState() {
  const source = { closed: false, close() { this.closed = true; } };
  Object.assign(state, {
    activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] },
    running: true, runStatus: 'working', runId: 'run-c1', source,
    // The mid-run drawer truth this bug leaves frozen: no changes loaded yet,
    // tree never fetched (so the panel reads "Loading files…").
    changes: [], tree: [], treeLoaded: false,
  });
}

function stopOutcome(counts) {
  const stoppedEvent = state.liveEvents.filter(event => event.type === 'stopped').at(-1);
  return {
    wording: stoppedEvent ? String(stoppedEvent.text || '') : '',
    status: state.runStatus,
    running: state.running,
    changes: state.changes.map(change => change.file),
    treeLoaded: state.treeLoaded,
    tree: state.tree.map(row => row.name),
    fetched: { ...counts },
  };
}

const report = {};

// A native stop reloads the durable candidate result and its recovery controls.
{
  resetState();
  runningState();
  state.conversation.self_edit = true;
  const counts = { stop: 0, changes: 0, tree: 0, conversation: 0 };
  const ordinaryFetch = stopFetchSurface(counts);
  fetchHandler = async url => {
    if (url === '/api/evolve/agent/conversations/c1') {
      counts.conversation += 1;
      return response({ ok: true, conversation: { id: 'c1', self_edit: true, project_root: '/repo', turns: [
        { role: 'agent', run_id: 'run-c1', report: { self_edit: { status: 'failed', reason: 'Stopped safely' } } },
      ] } });
    }
    return ordinaryFetch(url);
  };
  if (await api.stopRun() !== true) throw new Error('native stop failed');
  report.nativeStop = { ...stopOutcome(counts), selfEdit: state.conversation.turns.at(-1)?.report?.self_edit, cardHtml: transcript.cardHtml };
}

// 1. The drawer Stop button path.
{
  resetState();
  runningState();
  const counts = { stop: 0, changes: 0, tree: 0 };
  fetchHandler = stopFetchSurface(counts);
  if (await api.stopRun() !== true) throw new Error('confirmed stop reported failure');
  report.drawerStop = stopOutcome(counts);
}

// 2. The mode-adapter stop entry point. It is fire-and-forget (`void safely`),
// so completion is observed on state rather than awaited.
{
  resetState();
  runningState();
  const counts = { stop: 0, changes: 0, tree: 0 };
  fetchHandler = stopFetchSurface(counts);
  adapter.stop();
  for (let waited = 0; waited < 200 && (state.running || state.steeringBusy); waited += 1) {
    await new Promise(resolve => { queueMicrotask(resolve); });
  }
  report.adapterStop = stopOutcome(counts);
}

// 3. finishRun durable path scrolls to the newest turn. The transcript has
// unscrolled overflow (the shape measured live: the new answer below the fold).
{
  resetState();
  Object.assign(state, {
    activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] },
    running: true, runStatus: 'completed', runId: 'run-c1',
    runProof: { conversationId: 'c1', runId: 'run-c1' },
    liveEvents: [{ type: 'say', kind: 'say', text: 'follow-up progress' }],
  });
  transcript.scrollHeight = 2400;
  transcript.scrollTop = 37;
  fetchHandler = async url => {
    if (url.endsWith('/conversations/c1')) return response({ ok: true, conversation: { id: 'c1', project_root: '/repo', turns: [{ role: 'agent', run_id: 'run-c1', reason: 'Finished', transcript: '{"fc":"final","text":"the follow-up answer"}' }] } });
    if (url.includes('/changes?')) return response({ changed: [] });
    if (url.includes('/tree')) return response({ ok: true, entries: [], path: '' });
    if (url.split('?')[0].endsWith('/conversations')) return response({ conversations: [] });
    throw new Error(`unexpected durable finish fetch ${url}`);
  };
  await api.finishRun();
  report.durableScroll = { scrollTop: transcript.scrollTop, scrollHeight: transcript.scrollHeight };
}

// 4. Live render of a failed run that nevertheless produced a final answer.
{
  resetState();
  Object.assign(state, {
    activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] },
    running: false, runStatus: 'failed',
    liveEvents: [
      { type: 'error', text: 'agent loop exited 1' },
      { kind: 'final', text: 'LIVE-PRODUCED-ANSWER despite the exit' },
    ],
  });
  snapshots.length = 0;
  api.render();
  report.liveFailedWithAnswer = snapshots.at(-1) || '';
}

// A steer is a continuation in the SAME conversation, never a queued new task.
{
  resetState();
  runningState();
  const requests = [];
  fetchHandler = async (url, options) => {
    if (url === '/api/evolve/agent/steer') {
      requests.push({ url, body: JSON.parse(options.body) });
      return response({ ok: true, stop_requested: true, restart_required: true }, 202);
    }
    if (url.includes('/status')) return response({ ok: true, running: false, recording: false });
    if (url === '/api/evolve/agent/send') {
      requests.push({ url, body: JSON.parse(options.body) });
      return response({ ok: true, run_id: 'run-continued', conversation_id: 'c1', project_root: '/repo' });
    }
    if (url.split('?')[0].endsWith('/conversations')) return response({ conversations: [] });
    throw new Error(`unexpected steering fetch ${url}`);
  };
  const applied = await api.steer('Use a clear status');
  report.steer = { applied, requests, runId: state.runId, status: state.runStatus,
    events: state.liveEvents.filter(event => event.type === 'steering').map(event => event.text) };
}

// If continuation is refused, never tell the reader the update was applied.
{
  resetState();
  runningState();
  fetchHandler = async url => {
    if (url === '/api/evolve/agent/steer') return response({ ok: true }, 202);
    if (url.includes('/status')) return response({ ok: true, running: false, recording: false });
    if (url === '/api/evolve/agent/send') return response({ ok: false, error: 'Continuation rejected' }, 409);
    if (url === '/api/issues') return response({ ok: true });
    throw new Error(`unexpected failed steering fetch ${url}`);
  };
  report.steerFailure = { applied: await api.steer('Keep this task'), status: state.runStatus,
    messages: state.liveEvents.map(event => event.text) };
}

process.stdout.write(JSON.stringify(report));
