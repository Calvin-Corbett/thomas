// Full-stack harness (same shape as unified_code_mode_lifecycle.mjs): loads the
// sibling modules in chat.html order, instruments the Code adapter, and drives
// the queue-affinity, sidebar-loading, and stop-wording claims:
//
//   1. A send with NO conversation on screen while some run is live must NOT
//      queue -- parallel runs are supported, so it starts immediately as its
//      own NEW conversation. Measured 2026-08-05 (w2-code-network +
//      w2-code-tiny): the countdown task queued with cid:'' and was later
//      fired into the Bitcoin conversation, where it OVERWROTE the finished
//      deliverable with a countdown page.
//   2. A queued entry drains ONLY into exactly the conversation it was typed
//      into -- never into whichever conversation is active when a run ends.
//   3. An entry that somehow has no cid becomes its own NEW conversation
//      rather than adopting the active one.
//   4. The queue never drains while a run is live (a drain-then-requeue is
//      where a cid gets rewritten to the wrong conversation).
//   5. The Code sidebar says "Loading" until the first history fetch answers,
//      names a failure, and claims "No code tasks yet." only once an answer
//      confirmed it (~197 real tasks used to render as "No code tasks yet."
//      while the fetch was in flight).
//   6. A user stop is confirmed in plain words, not as a process error --
//      "Stop confirmed (process exit 1)." read as a failure for a clean stop.
import fs from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const lifecyclePath = process.argv[3];
const siblingPaths = process.argv.slice(4);

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
const transcript = { scrollTop: 0, scrollHeight: 0, clientHeight: 500 };
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
    registerAdapter() {},
  },
  setInterval() { return 0; },
};
globalThis.document = {
  activeElement: null,
  getElementById(id) { return id === 'tc-mode-surface' ? root : control(id); },
  createElement: () => ({ type: '', className: '', innerHTML: '', disabled: false, classList: { add() {} }, addEventListener() {} }),
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
  '\n  window.__ThomasCodeQueueTest = { state, activate: () => { adapterActive = true; }, openStream, pushLiveEvent, refresh, render, renderHistory, send, startNextQueued };\n})();',
);
if (instrumented === source) throw new Error('could not instrument Code queue adapter');
vm.runInThisContext(instrumented, { filename: sourcePath });
const api = window.__ThomasCodeQueueTest;
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
    historyLoadState: 'pending', parkedRuns: {},
  });
  busy = false;
  snapshots.length = 0;
  liveChildren.length = 0;
}

// A fetch surface for a send that the server answers with a brand-new running
// conversation, recording every /send body it sees.
function startSurface(sendBodies, newConversationId) {
  return async (url, options) => {
    if (url === '/api/issues') return response({ ok: true });
    if (url.endsWith('/send') && options?.method === 'POST') {
      const body = JSON.parse(options.body);
      sendBodies.push(body);
      const cid = body.conversation_id || newConversationId;
      return response({ ok: true, conversation_id: cid, project_root: `/proj-${cid}`, run_id: `run-${cid}-${sendBodies.length}`, run_state: 'running' });
    }
    if (url.endsWith('/conversations')) return response({ conversations: [] });
    throw new Error(`unexpected start fetch ${url}`);
  };
}

async function settle() {
  for (let waited = 0; waited < 50; waited += 1) {
    await new Promise(resolve => { queueMicrotask(resolve); });
  }
}

const report = {};

// 1. The P0: a new task sent with no conversation on screen while another
//    conversation's run is live. It must START, not queue.
{
  resetState();
  Object.assign(state, {
    running: true, runStatus: 'working', runId: 'run-live', activeId: '', conversation: null,
  });
  const sendBodies = [];
  fetchHandler = startSurface(sendBodies, 'c-new');
  const result = await api.send('Make a countdown page', {});
  report.newTaskStartsOwnConversation = {
    result,
    sendCount: sendBodies.length,
    sentConversationId: sendBodies[0] ? (sendBodies[0].conversation_id ?? null) : 'never-sent',
    activeId: state.activeId,
    queued: (state.queuedSends || []).length,
  };
}

// 2 + 3. A cid-less entry that somehow exists must NEVER adopt the active
//    conversation -- it becomes its own new one.
{
  resetState();
  Object.assign(state, {
    activeId: 'c2', conversation: { id: 'c2', turns: [] }, projectRoot: '/proj-c2',
  });
  state.queuedSends = [{ message: 'orphan countdown', context: {}, cid: '' }];
  const sendBodies = [];
  fetchHandler = startSurface(sendBodies, 'c-fresh');
  api.startNextQueued();
  await settle();
  report.orphanEntryNeverAdopts = {
    sendCount: sendBodies.length,
    sentConversationId: sendBodies[0] ? (sendBodies[0].conversation_id ?? null) : 'never-sent',
    activeId: state.activeId,
    queued: (state.queuedSends || []).length,
  };
}

// 2b. The exact-affinity control: an entry stamped for the active conversation
//     drains into exactly that conversation.
{
  resetState();
  Object.assign(state, {
    activeId: 'c1', conversation: { id: 'c1', turns: [] }, projectRoot: '/proj-c1',
  });
  state.queuedSends = [{ message: 'follow-up for c1', context: {}, cid: 'c1' }];
  const sendBodies = [];
  fetchHandler = startSurface(sendBodies, 'unused');
  api.startNextQueued();
  await settle();
  report.exactCidDrains = {
    sendCount: sendBodies.length,
    sentConversationId: sendBodies[0] ? (sendBodies[0].conversation_id ?? null) : 'never-sent',
    queued: (state.queuedSends || []).length,
  };
}

// 2c. An entry stamped for a PARKED conversation waits: it must not fire into
//     the active conversation and must not be dropped.
{
  resetState();
  Object.assign(state, {
    activeId: 'c2', conversation: { id: 'c2', turns: [] },
  });
  state.queuedSends = [{ message: 'follow-up for parked c1', context: {}, cid: 'c1' }];
  const sendBodies = [];
  fetchHandler = startSurface(sendBodies, 'unused');
  api.startNextQueued();
  await settle();
  report.parkedCidWaits = {
    sendCount: sendBodies.length,
    queued: (state.queuedSends || []).length,
    queuedCid: state.queuedSends?.[0]?.cid ?? null,
  };
}

// 4. No draining while a run is live: a drain-then-requeue is where a cid can
//    be rewritten to the wrong conversation.
{
  resetState();
  Object.assign(state, {
    activeId: 'c1', conversation: { id: 'c1', turns: [] }, running: true, runStatus: 'working', runId: 'run-c1',
  });
  state.queuedSends = [{ message: 'wait for the live run', context: {}, cid: 'c1' }];
  const sendBodies = [];
  fetchHandler = startSurface(sendBodies, 'unused');
  api.startNextQueued();
  await settle();
  report.noDrainWhileRunning = {
    sendCount: sendBodies.length,
    queued: (state.queuedSends || []).length,
    announcedStart: state.liveEvents.some(event => String(event.text || '').includes('Starting your queued task')),
  };
}

// 5. Sidebar history loading states.
{
  resetState();
  const historyRoot = {
    children: [],
    _html: '',
    get innerHTML() { return this._html; },
    set innerHTML(value) { this._html = String(value); if (this._html === '') this.children = []; },
    appendChild(el) { this.children.push(el); return el; },
  };
  const renderEmptyText = () => {
    api.renderHistory(historyRoot, '');
    return historyRoot.innerHTML;
  };
  state.conversations = [];
  state.historyLoadState = 'pending';
  const pendingText = renderEmptyText();
  state.historyLoadState = 'error';
  const errorText = renderEmptyText();
  state.historyLoadState = 'loaded';
  const loadedText = renderEmptyText();

  state.historyLoadState = 'pending';
  fetchHandler = async url => {
    if (url.endsWith('/conversations')) return response({ conversations: [{ id: 'c1', title: 'A task', turn_count: 2 }] });
    throw new Error(`unexpected history fetch ${url}`);
  };
  const refreshOk = await api.refresh();
  const stateAfterSuccess = state.historyLoadState;

  state.historyLoadState = 'pending';
  fetchHandler = async url => {
    if (url === '/api/issues') return response({ ok: true });
    if (url.endsWith('/conversations')) return response({ error: 'history unavailable' }, 503);
    throw new Error(`unexpected history fetch ${url}`);
  };
  const refreshFailed = await api.refresh();
  const stateAfterFailure = state.historyLoadState;

  report.sidebar = {
    pendingText, errorText, loadedText,
    refreshOk, stateAfterSuccess,
    refreshFailed, stateAfterFailure,
  };
}

// 6. A user stop is confirmed in plain words, not as a process error.
{
  resetState();
  Object.assign(state, {
    activeId: 'c1', conversation: { id: 'c1', turns: [] }, projectRoot: '/repo',
    running: true, runStatus: 'stopping', steeringBusy: true, runId: 'run-1',
  });
  fetchHandler = async url => {
    if (url === '/api/issues') return response({ ok: true });
    throw new Error(`unexpected stop-stream fetch ${url}`);
  };
  api.openStream();
  state.source.onmessage({
    data: JSON.stringify({ type: 'done', run_id: 'run-1', event_seq: 1, ok: false, persistence_confirmed: true, returncode: 1, artifacts: [] }),
  });
  await settle();
  const stoppedEvent = state.liveEvents.filter(event => event.type === 'stopped').at(-1);
  report.stopWording = {
    status: state.runStatus,
    text: stoppedEvent ? String(stoppedEvent.text || '') : '',
  };
}

process.stdout.write(JSON.stringify(report));
