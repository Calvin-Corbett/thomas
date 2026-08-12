// Drives one finished Code run down BOTH client routes and reports the status
// each one lands on, plus the words that end up in the activity bar.
//
//   watched  -- /send starts the run, the SSE `done` frame ends it
//   finished -- /send hands back a run that had already finished (a replayed
//               idempotency receipt)
//
// Both are fed the SAME dict the server builds once in
// evolve_agent_runtime._record_run_outcome, because that is exactly how it is
// shipped: `{"type": "done", **persistence}` on the stream and
// `{**response, **persistence, "run_state": ...}` on the replay.
//
// Prints JSON: { "<outcome>": { "watched": {...}, "finished": {...} }, ... }
import fs from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const lifecyclePath = process.argv[3];
const siblingPaths = process.argv.slice(4);

let busy = false;
let fetchHandler = async () => { throw new Error('unexpected fetch'); };
const controls = new Map();
function control(id = '') {
  if (!controls.has(id)) {
    controls.set(id, {
      id, value: '', dataset: {}, disabled: false,
      addEventListener() {}, focus() {}, setSelectionRange() {},
    });
  }
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
    liveChildren.push({ html, remove() { liveChildren.shift(); }, set outerHTML(value) { this.html = value; } });
  },
};
const panel = { style: { setProperty(_name, value) { panel.width = value; } }, width: '' };
const resizeHandle = {
  attributes: {},
  addEventListener() {}, removeEventListener() {},
  setAttribute(name, value) { this.attributes[name] = String(value); },
  setPointerCapture() {},
};
// The real status badge, so the assertion can read the WORDS on screen rather
// than infer them from state.
const badge = { className: '', textContent: '' };
const root = {
  _html: '',
  get innerHTML() { return this._html; },
  set innerHTML(value) { this._html = value; },
  contains() { return false; },
  querySelector(selector) {
    if (selector === '.tc-mode-status') return badge;
    if (selector === '.tc-code-transcript') return transcript;
    if (selector === '#tc-code-live-events') return liveList;
    if (selector === '.tc-code-actions') return { insertAdjacentHTML() {} };
    if (selector === '.tc-code-panel') return panel;
    if (selector === '.tc-code-drawer-resize') return resizeHandle;
    if (selector.startsWith('#tc-code-')) return control(selector.slice(1));
    return null;
  },
  querySelectorAll() { return []; },
};
globalThis.window = {
  ThomasUnifiedModes: {
    host: () => ({ getContext: () => ({}), renderHistory() {}, setBusy(value) { busy = value; } }),
    registerAdapter() {},
  },
  setInterval() { return 0; },
};
globalThis.document = {
  activeElement: null,
  getElementById(id) { return id === 'tc-mode-surface' ? root : control(id); },
  createElement: () => ({ className: '', innerHTML: '', disabled: false, classList: { add() {} }, addEventListener() {} }),
};
globalThis.localStorage = { getItem: () => '', setItem() {} };
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
  '\n  window.__ThomasCodeTerminalStatusTest = { state, activate: () => { adapterActive = true; }, send, updateRunStatus };\n})();',
);
if (instrumented === source) throw new Error('could not instrument Code lifecycle adapter');
vm.runInThisContext(instrumented, { filename: sourcePath });
const api = window.__ThomasCodeTerminalStatusTest;
const state = api.state;
api.activate();

function response(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, async json() { return data; } };
}

function resetState(cid) {
  if (state.source) state.source.close();
  Object.assign(state, {
    conversations: [], activeId: cid, conversation: { id: cid, turns: [] }, liveEvents: [], changes: [], tree: [],
    treePath: '', artifacts: [], filePreview: null, pendingApproval: null, pendingRequest: null, lastContext: {},
    running: false, runStartedAt: 0, runStatus: 'ready', source: null, finishing: null, approvalBusy: false,
    steeringBusy: false, projectRoot: '/repo', terminalTool: '', contextEpoch: (state.contextEpoch || 0) + 1,
    runProof: null, runId: '', eventCursor: 0, retryRequest: null, pendingUserText: '', queuedSends: [],
  });
  busy = false;
  liveChildren.length = 0;
  badge.className = '';
  badge.textContent = '';
}

// _record_run_outcome's dict, verbatim. `conversation` is the run that ANSWERED
// without editing anything -- ok, no changed files, reason "Thomas replied
// without changing files".
function persistence(outcome) {
  return {
    persistence_confirmed: true,
    returncode: 0,
    changed_files: outcome === 'completed' ? ['index.html'] : [],
    artifacts: [],
    ok: outcome === 'completed' || outcome === 'conversation',
    noop: outcome === 'noop',
    outcome,
  };
}

const finishedConversation = cid => ({
  ok: true,
  conversation: {
    id: cid,
    project_root: '/repo',
    turns: [{
      role: 'agent',
      run_id: `run-${cid}`,
      transcript: '{"fc":"final","text":"It is a Vite app with three routes."}',
    }],
  },
});

function routes(cid, sendBody) {
  return async (url, options) => {
    if (url.endsWith('/send') && options?.method === 'POST') return response(sendBody);
    if (url.endsWith(`/conversations/${cid}`)) return response(finishedConversation(cid));
    if (url.includes('/changes?')) return response({ changed: [] });
    if (url.includes('/tree')) return response({ ok: true, entries: [], path: '' });
    if (url.endsWith('/conversations')) return response({ conversations: [] });
    if (url === '/api/issues') return response({ ok: true });
    throw new Error(`unexpected fetch ${url}`);
  };
}

function reading() {
  api.updateRunStatus();
  return { status: state.runStatus, label: badge.textContent, css: badge.className };
}

// The run you are WATCHING: /send starts it, the SSE `done` frame ends it.
async function watched(outcome) {
  const cid = `live-${outcome}`;
  resetState(cid);
  fetchHandler = routes(cid, {
    ok: true, conversation_id: cid, project_root: '/repo', run_id: `run-${cid}`, run_state: 'running',
  });
  await api.send('what does this project do?', {});
  state.source.onmessage({
    data: JSON.stringify({ type: 'done', run_id: `run-${cid}`, event_seq: 1, ...persistence(outcome) }),
  });
  await new Promise(resolve => queueMicrotask(() => queueMicrotask(resolve)));
  return reading();
}

// The SAME run, already FINISHED when /send answered (a replayed receipt).
async function alreadyFinished(outcome) {
  const cid = `replay-${outcome}`;
  resetState(cid);
  fetchHandler = routes(cid, {
    ok: true, conversation_id: cid, project_root: '/repo', run_id: `run-${cid}`,
    replayed: true, run_state: 'completed', ...persistence(outcome),
  });
  await api.send('what does this project do?', {});
  return reading();
}

const report = {};
// Only ok-true outcomes are exercised end to end. The replay body merges
// persistence OVER the envelope, so `ok` becomes the RUN's ok -- a replayed
// noop/failed receipt is rejected by send() before it can reach this branch at
// all, and asserting on it would be asserting on the rejection, not the status.
for (const outcome of ['completed', 'conversation']) {
  report[outcome] = { watched: await watched(outcome), finished: await alreadyFinished(outcome) };
}
process.stdout.write(JSON.stringify(report));
