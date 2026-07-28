import fs from 'node:fs';
import vm from 'node:vm';
const sourcePath = process.argv[2];
const lifecyclePath = process.argv[3];
let adapter = null;
let busy = false;
let fetchHandler = async () => { throw new Error('unexpected fetch'); };
const snapshots = [];
const controls = new Map();
const resizeListeners = new Map();
const preferenceWarnings = [];
let storedDrawerWidth = '';
let failDrawerStorage = false;
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
const panel = { style: { setProperty(_name, value) { panel.width = value; } }, width: '' };
const resizeHandle = {
  attributes: {},
  addEventListener(type, handler) { resizeListeners.set(type, handler); },
  removeEventListener(type, handler) { if (resizeListeners.get(type) === handler) resizeListeners.delete(type); },
  setAttribute(name, value) { this.attributes[name] = String(value); },
  setPointerCapture() {},
};
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
    registerAdapter(_mode, value) { adapter = value; },
  },
  setInterval() { return 0; },
};
globalThis.document = {
  activeElement: null,
  getElementById(id) { return id === 'tc-mode-surface' ? root : control(id); },
  createElement: () => ({ className: '', innerHTML: '', disabled: false, classList: { add() {} }, addEventListener() {} }),
};
globalThis.localStorage = {
  getItem: key => key === 'thomas_code_drawer_width' ? storedDrawerWidth : '',
  setItem(key, value) {
    if (failDrawerStorage) throw new Error('storage unavailable');
    if (key === 'thomas_code_drawer_width') storedDrawerWidth = String(value);
  },
};
const originalWarn = console.warn;
console.warn = (...args) => { preferenceWarnings.push(args.map(String).join(' ')); };
globalThis.fetch = (...args) => fetchHandler(...args);
globalThis.setTimeout = callback => { queueMicrotask(callback); return 0; };
globalThis.EventSource = class {
  constructor(url) { this.url = url; this.closed = false; }
  close() { this.closed = true; }
};
vm.runInThisContext(fs.readFileSync(lifecyclePath, 'utf8'), { filename: lifecyclePath });
const source = fs.readFileSync(sourcePath, 'utf8');
const instrumented = source.replace(
  /\n\}\)\(\);\s*$/,
  '\n  window.__ThomasCodeModeTest = { state, activate: () => { adapterActive = true; }, approvePending, changeAction, elapsedLabel, eventHtml, failureSummary, finishRun, handleStreamError, loadConversation, narrativeActivityHtml, newConversation, pickProject, pushLiveEvent, refresh, render, send, steer, technicalActivityHtml, transcriptEvents, turnHtml };\n})();',
);
if (instrumented === source) throw new Error('could not instrument Code lifecycle adapter');
vm.runInThisContext(instrumented, { filename: sourcePath });
const api = window.__ThomasCodeModeTest;
const state = api.state;
api.activate();

function response(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, async json() { return data; } };
}

function resetState() {
  if (state.source) state.source.close();
  Object.assign(state, {
    conversations: [], activeId: '', conversation: null, liveEvents: [], changes: [], tree: [], treePath: '',
    artifacts: [], filePreview: null, pendingApproval: null, pendingRequest: null, lastContext: {}, running: false,
    runStartedAt: 0, runStatus: 'ready', source: null, finishing: null, approvalBusy: false, steeringBusy: false,
    projectRoot: '', terminalTool: '', contextEpoch: state.contextEpoch + 1, runProof: null,
    runId: '', eventCursor: 0, retryRequest: null,
  });
  busy = false;
  snapshots.length = 0;
  liveChildren.length = 0;
}

async function proveApprovalRetry() {
  resetState();
  Object.assign(state, {
    activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] },
    changes: [{ file: 'a.js', diff: '+change' }], pendingApproval: { id: 'approval-1', summary: 'Revert a.js' },
    pendingRequest: { kind: 'change', action: 'revert', file: 'a.js' }, runStatus: 'approval',
  });
  let approveCalls = 0;
  let revertCalls = 0;
  fetchHandler = async url => {
    if (url.endsWith('/approve')) { approveCalls += 1; return response({ ok: true }); }
    if (url.endsWith('/revert')) { revertCalls += 1; return response({ ok: false, error: 'disk busy' }, 500); }
    throw new Error(`unexpected approval fetch ${url}`);
  };
  if (await api.approvePending() !== false) throw new Error('failed approved change reported success');
  if (busy || state.running || state.approvalBusy) throw new Error('approved change failure left Code busy');
  if (!state.pendingApproval || state.pendingRequest.approval_id !== 'approval-1') throw new Error('approved change lost retry receipt');

  fetchHandler = async url => {
    if (url.endsWith('/approve')) throw new Error('retry re-approved an already approved receipt');
    if (url.endsWith('/revert')) { revertCalls += 1; return response({ ok: true }); }
    if (url.includes('/changes?')) return response({ changed: [] });
    throw new Error(`unexpected approval retry fetch ${url}`);
  };
  if (await api.approvePending() !== true) throw new Error('approved change retry did not succeed');
  if (approveCalls !== 1 || revertCalls !== 2 || state.pendingApproval) throw new Error('approved change retry lifecycle was not stable');

  Object.assign(state, { pendingApproval: { id: 'approval-2', summary: 'Run task' }, pendingRequest: { message: 'build it' }, runStatus: 'approval' });
  let runApproveCalls = 0;
  fetchHandler = async url => {
    if (url.endsWith('/approve')) { runApproveCalls += 1; return response({ ok: true }); }
    if (url.endsWith('/send')) return response({ ok: false, error: 'runner unavailable' }, 503);
    throw new Error(`unexpected approved run fetch ${url}`);
  };
  if (await api.approvePending() !== false) throw new Error('failed approved run reported success');
  if (busy || state.running || !state.pendingApproval || state.pendingRequest.approval_id !== 'approval-2') throw new Error('approved run failure lost retry or left Code busy');

  fetchHandler = async url => {
    if (url.endsWith('/approve')) throw new Error('consumed approval retry repeated old approval');
    if (url.endsWith('/send')) return response({ ok: false, error: 'approval was consumed', code: 'approval_required', approval: { id: 'approval-fresh', summary: 'Fresh approval' } }, 409);
    throw new Error(`unexpected consumed approval fetch ${url}`);
  };
  if (await api.approvePending() !== false) throw new Error('consumed approval retry reported success');
  if (busy || state.running || state.pendingApproval.id !== 'approval-fresh' || state.pendingRequest.approval_id) throw new Error('fresh approval receipt did not replace the consumed receipt');

  fetchHandler = async url => {
    if (url.endsWith('/approve')) { runApproveCalls += 1; return response({ ok: true }); }
    if (url.endsWith('/send')) return response({ ok: true, conversation_id: 'c1', project_root: '/repo', run_id: 'run-c1', run_state: 'running' });
    throw new Error(`unexpected fresh approval retry fetch ${url}`);
  };
  if (await api.approvePending() !== true) throw new Error('fresh approval retry did not start');
  if (runApproveCalls !== 2 || !busy || !state.running || state.pendingApproval) throw new Error('fresh approval retry lifecycle was not stable');
}

async function proveScopedSwitch() {
  resetState();
  const oldSource = { closed: false, close() { this.closed = true; } };
  Object.assign(state, {
    activeId: 'old', projectRoot: '/old', conversation: { id: 'old', turns: [] }, running: true, source: oldSource,
    pendingApproval: { id: 'old-approval' }, pendingRequest: { message: 'old' }, artifacts: [{ file: 'old.html' }],
    filePreview: { path: 'old.js', content: 'old' }, terminalTool: 'shell', changes: [{ file: 'old.js' }], tree: [{ name: 'old.js' }],
  });
  let contextCalls = 0;
  fetchHandler = async url => {
    if (url === '/api/issues') return response({ ok: true });
    contextCalls += 1;
    throw new Error('switch fetched before run identity was available');
  };
  if (await api.loadConversation('new') !== false || contextCalls) throw new Error('conversation switch was not blocked before the run could be parked');
  if (state.activeId !== 'old' || oldSource.closed) throw new Error('blocked switch mutated the live context');

  state.runId = 'run-old';
  state.liveEvents = [];
  fetchHandler = async url => {
    if (url.endsWith('/conversations/new')) return response({ ok: true, conversation: { id: 'new', project_root: '/new', turns: [] } });
    if (url.includes('/changes?')) return response({ changed: [{ file: 'new.js' }] });
    if (url.includes('/tree')) return response({ ok: true, entries: [{ name: 'new.js', kind: 'file', path: 'new.js' }], path: '' });
    if (url.includes('/status?conversation_id=new')) return response({ ok: true, running: false });
    throw new Error(`unexpected switch fetch ${url}`);
  };
  if (await api.loadConversation('new') !== true) throw new Error('identified running conversation was not parked and switched');
  if (!oldSource.closed || state.parkedRuns?.old?.runId !== 'run-old') throw new Error('running conversation was not parked with its run identity');
  if (state.activeId !== 'new' || state.projectRoot !== '/new' || state.running || busy) throw new Error('conversation switch did not adopt the new idle context');
  if (state.pendingApproval || state.artifacts.length || state.filePreview || state.terminalTool) throw new Error('conversation switch leaked prior run state');
  if (state.changes[0].file !== 'new.js' || state.tree[0].name !== 'new.js') throw new Error('conversation switch did not scope loaded state');

  Object.assign(state, { pendingApproval: { id: 'stale' }, pendingRequest: { message: 'stale' }, artifacts: [{ file: 'stale.html' }], filePreview: { path: 'stale.js' }, terminalTool: 'shell', changes: [{ file: 'stale.js' }], tree: [{ name: 'stale.js' }] });
  fetchHandler = async (url, options) => {
    if (url.endsWith('/conversations/new') && options && options.method === 'POST') return response({ ok: true, conversation: { id: 'project-two', project_root: '/project-two', turns: [] } });
    if (url.endsWith('/conversations')) return response({ conversations: [] });
    if (url.includes('/tree')) return response({ ok: true, entries: [{ name: 'package.json', kind: 'file', path: 'package.json' }], path: '' });
    throw new Error(`unexpected project switch fetch ${url}`);
  };
  if (await api.newConversation('/project-two') !== true) throw new Error('project switch did not create a scoped conversation');
  if (state.activeId !== 'project-two' || state.projectRoot !== '/project-two' || state.pendingApproval || state.artifacts.length || state.filePreview || state.terminalTool || state.changes.length) throw new Error('project switch leaked prior conversation state');
  if (state.tree[0].name !== 'package.json') throw new Error('project switch did not load the selected project tree');
}

async function proveSteeringConfirmation() {
  resetState();
  const oldSource = { closed: false, close() { this.closed = true; } };
  Object.assign(state, { activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] }, running: true, runStatus: 'working', source: oldSource, liveEvents: [{ type: 'say', kind: 'say', text: 'kept progress' }] });
  let sendCalls = 0;
  fetchHandler = async url => {
    if (url.endsWith('/steer')) return response({ ok: true });
    if (url.includes('/status')) return response({ ok: true, running: true });
    if (url.endsWith('/send')) { sendCalls += 1; return response({ ok: true }); }
    throw new Error(`unexpected steering timeout fetch ${url}`);
  };
  let timeoutError = null;
  try { await api.steer('keep the API'); } catch (error) { timeoutError = error; }
  if (!timeoutError || sendCalls || !state.running || oldSource.closed) throw new Error('steering restarted without a confirmed stop');
  if (!state.liveEvents.some(event => event.text === 'kept progress')) throw new Error('steering timeout discarded progress');

  fetchHandler = async url => {
    if (url.endsWith('/steer')) return response({ ok: true });
    if (url.includes('/status')) return response({ ok: true, running: false });
    if (url.endsWith('/send')) { sendCalls += 1; return response({ ok: true, conversation_id: 'c1', project_root: '/repo', run_id: 'run-c1', run_state: 'running' }); }
    if (url.endsWith('/conversations')) return response({ conversations: [] });
    throw new Error(`unexpected steering restart fetch ${url}`);
  };
  if (await api.steer('keep the API') !== true || sendCalls !== 1) throw new Error('confirmed steering did not restart exactly once');
  if (!oldSource.closed || !state.running || !busy) throw new Error('confirmed steering did not transfer to the restarted run');
  if (!state.liveEvents.some(event => event.text === 'kept progress')) throw new Error('confirmed steering discarded prior progress');
}

async function proveEvidenceAndRefresh() {
  resetState();
  const raw = api.eventHtml({ type: 'output', text: 'opaque runner bytes' }, false);
  if (!raw.includes('tc-code-technical') || raw.includes('tc-code-event')) throw new Error('untyped output was presented as narrative');
  const reasoning = api.eventHtml({ type: 'output', kind: 'reason', text: 'private implementation reasoning' }, false);
  if (!reasoning.includes('tc-code-technical') || reasoning.includes('tc-code-event')) throw new Error('reasoning was presented as a conversational milestone');
  const rawError = api.eventHtml({ type: 'error', text: 'HTTP 400: {"secret":"raw detail"}' }, false);
  if (!rawError.includes('tc-code-technical') || rawError.includes('tc-code-event')) throw new Error('raw error was presented as a conversational blob');
  const conciseError = api.failureSummary({ ok: false }, [{ type: 'error', text: 'HTTP 400: {"secret":"raw detail"}' }]);
  if (conciseError.includes('HTTP 400') || conciseError.includes('secret')) throw new Error('raw failure detail leaked into the concise reply');
  const protocolSpew = api.narrativeActivityHtml([{ kind: 'say', text: '{"tool_uses":[{"recipient_name":"functions.fs_read_file"}]}' }], true);
  if (protocolSpew.includes('tc-code-event')) throw new Error('tool protocol spew was presented as a conversational update');
  const grouped = api.technicalActivityHtml([
    { type: 'output', kind: 'tool_result', text: 'same check' },
    { type: 'output', kind: 'tool_result', text: 'same check' },
    { type: 'output', kind: 'tool', name: 'fs.read_file', text: 'read source' },
  ], false);
  if (!grouped.includes('Worked through 1 tool run · 2 checks') || !grouped.includes('×2')) throw new Error('technical evidence was not summarized and deduplicated');
  if ((grouped.match(/tc-code-saved-activity/g) || []).length !== 1 || grouped.includes('<details class="tc-code-technical')) throw new Error('technical evidence created nested activity blobs');
  const groupedError = api.technicalActivityHtml([{ type: 'error', text: 'request failed' }], false);
  if (!groupedError.includes('Worked through 1 issue') || groupedError.includes('1 detail')) throw new Error('technical error was not summarized as an issue');
  state.running = true;
  state.runStartedAt = Date.now() - 65000;
  const timed = api.technicalActivityHtml([{ type: 'output', kind: 'tool_result', text: 'same check' }], false);
  if (!timed.includes('data-code-elapsed') || !timed.includes('Working · 1m')) throw new Error('live technical summary did not show elapsed progress');
  state.running = false;
  const persisted = api.transcriptEvents({ transcript: [
    '{"fc":"say","text":"Inspecting.","delta":true}',
    '{"fc":"say","text":" Building.","delta":true}',
    '{"fc":"tool_result","text":"same check"}',
    '{"fc":"tool_result","text":"same check"}',
    '{"fc":"say","text":"Inspecting. Building."}',
  ].join('\n') });
  const replay = api.technicalActivityHtml(persisted.filter(event => event.kind === 'tool_result'), true);
  if (!replay.includes('×2') || persisted.filter(event => event.kind === 'say').length !== 1) throw new Error('persisted replay lost counts or duplicated progress');
  // Owner contract (Calvin, 2026-07-18): the running action feed shows EVERY
  // progress note inline, Codex-style. Collapse only engages past the
  // live-event ring bound (MAX_VISIBLE_PROGRESS_EVENTS = 120).
  const fullFeed = api.narrativeActivityHtml(Array.from({ length: 7 }, (_value, index) => ({ kind: 'say', text: `progress-${index}` })), true);
  if (fullFeed.includes('<details class="tc-code-progress-history">')) throw new Error('a short progress feed must not be collapsed');
  if (!fullFeed.includes('progress-0') || !fullFeed.includes('progress-6')) throw new Error('full progress feed lost notes');
  const hugeFeed = api.narrativeActivityHtml(Array.from({ length: 130 }, (_value, index) => ({ kind: 'say', text: `progress-${index}` })), true);
  if (!hugeFeed.includes('<details class="tc-code-progress-history">')) throw new Error('an extreme progress feed past the ring bound was not collapsed');
  const longProgress = api.narrativeActivityHtml([{ kind: 'say', text: 'x'.repeat(500) }], true);
  if (!longProgress.includes('Show full update') || longProgress.split('x').length < 500) throw new Error('long progress was not compacted with a full disclosure');
  const completedTurn = api.turnHtml({
    role: 'agent', ok: true, reason: '3 file(s) changed', changed_files: ['a.js'],
    transcript: [
      '{"fc":"say","text":"Inspecting the project."}',
      '{"fc":"tool_result","text":"tests passed"}',
      '{"fc":"final","text":"Built the game and verified Start, Pause, and Resume."}',
    ].join('\n'),
  });
  const progressAt = completedTurn.indexOf('Inspecting the project.');
  const evidenceAt = completedTurn.indexOf('tc-code-saved-activity');
  const finalAt = completedTurn.indexOf('Built the game and verified Start, Pause, and Resume.');
  if (!(progressAt >= 0 && evidenceAt > progressAt && finalAt > evidenceAt)) throw new Error('completed turn did not render progress, evidence, then final reply');
  if (completedTurn.indexOf('3 file(s) changed') >= 0 || (completedTurn.match(/Built the game/g) || []).length !== 1) throw new Error('machine receipt replaced or duplicated the final reply');
  const failedTurn = api.turnHtml({
    role: 'agent', ok: false,
    transcript: [
      '{"fc":"final","text":"I cannot continue because the review budget forbids another tool call."}',
      '{"fc":"error","text":"verification failed (exit 1) after fix attempts"}',
    ].join('\n'),
  });
  if (!failedTurn.includes('final verification still failed after its repair attempts') || failedTurn.includes('review budget forbids')) throw new Error('failed turn exposed the model budget excuse instead of the authoritative verification result');
  const verifiedAfterLimitTurn = api.turnHtml({
    role: 'agent', ok: true, changed_files: ['pause-controls.js'],
    transcript: [
      '{"fc":"final","text":"I could not apply the fix because the execution review prohibited further tool calls, so no files were changed and verification has not been claimed."}',
      '{"fc":"tool_result","text":"BROWSER_SMOKE_OK: pause and resume","is_error":false}',
      '{"fc":"meta","text":"engine checks passed","is_error":false}',
    ].join('\n'),
  });
  if (!verifiedAfterLimitTurn.includes('passed Thomas’s verification') || verifiedAfterLimitTurn.includes('could not apply')) throw new Error('authoritative engine success did not replace the stale review-limit reply');
  const filteredReceipt = api.turnHtml({
    role: 'agent', ok: true, changed_files: ['.thomas/evolve/agent/conversations/run.json', 'game.js'],
    artifacts: [{ file: '.thomas/evolve/agent/conversations/run.json', kind: 'data' }, { file: 'game.html', kind: 'html' }],
    transcript: '{"fc":"final","text":"Finished."}',
  });
  // The point of this case is that Thomas's OWN bookkeeping file, written into
  // .thomas/evolve/..., must not be counted as work the owner did or delivered.
  // It used to be checked by asserting the reply said "1 result ready"; that
  // wording is gone on purpose -- a count is not a delivery, and results are now
  // named cards you can open. So the same guarantee is asserted against what the
  // receipt actually says now: the real file is named, the internal one is not.
  if (!filteredReceipt.includes('1 file changed') || filteredReceipt.includes('2 files changed')) throw new Error('internal Thomas bookkeeping inflated the changed-file count');
  if (!filteredReceipt.includes('game.html')) throw new Error('the delivered result was not named in the saved turn receipt');
  if (filteredReceipt.includes('run.json') || filteredReceipt.includes('.thomas/evolve')) throw new Error('internal Thomas bookkeeping was offered to the owner as a result');
  for (let index = 0; index < 140; index += 1) api.pushLiveEvent({ type: 'output', text: `raw-${index}` });
  if (state.liveEvents.length !== 120) throw new Error('live evidence was not capped');

  Object.assign(state, {
    conversation: { id: 'c1', turns: [{ role: 'agent', artifacts: [{ file: '.thomas/evolve/agent/conversations/run.json', kind: 'data' }, { file: 'game.html', kind: 'html' }] }] },
    changes: [{ file: '.thomas/evolve/agent/conversations/run.json', diff: '+internal' }, { file: 'game.js', diff: '+public' }],
    artifacts: [],
    liveEvents: [],
  });
  api.render();
  if (root.innerHTML.includes('.thomas/evolve/agent') || !root.innerHTML.includes('game.html') || !root.innerHTML.includes('game.js')) throw new Error('internal Thomas bookkeeping leaked into Code results');

  state.conversations = [{ id: 'prior' }];
  fetchHandler = async () => response({ error: 'history unavailable' }, 503);
  if (await api.refresh() !== false || state.conversations[0].id !== 'prior') throw new Error('failed refresh erased prior history');
  if (!state.liveEvents.some(event => event.type === 'error' && event.text.includes('history unavailable'))) throw new Error('failed refresh was silent');
}

async function proveTransientStreamFailure() {
  resetState();
  const source = { closed: false, close() { this.closed = true; } };
  Object.assign(state, { activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] }, running: true, runStatus: 'working', source, runId: 'run-c1', runProof: { conversationId: 'c1', runId: 'run-c1' }, liveEvents: [{ type: 'say', kind: 'say', text: 'streamed progress' }] });
  busy = true;
  fetchHandler = async url => {
    if (url.endsWith('/status')) return response({ ok: true, running: true, recording: false });
    throw new Error(`unexpected stream recovery fetch ${url}`);
  };
  if (await api.handleStreamError(source) !== true) throw new Error('transient stream failure did not recover');
  if (!source.closed || !state.source || state.source === source) throw new Error('transient stream failure did not reconnect');
  if (!state.running || !busy || state.runStatus !== 'working') throw new Error('transient stream failure released the live run');
  if (!state.liveEvents.some(event => event.text === 'streamed progress')) throw new Error('transient stream failure discarded progress');
}

async function proveTerminalDedup() {
  resetState();
  Object.assign(state, { activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] }, running: true, runStatus: 'completed', runId: 'run-c1', runProof: { conversationId: 'c1', runId: 'run-c1' }, liveEvents: [{ type: 'say', kind: 'say', text: 'unique-progress' }], artifacts: [{ file: 'partial.html' }] });
  fetchHandler = async url => {
    if (url.endsWith('/conversations/c1')) return response({ ok: true, conversation: { id: 'c1', project_root: '/repo', turns: [{ role: 'agent', run_id: 'run-c1', reason: 'Finished', transcript: '{"fc":"say","text":"unique-progress"}' }] } });
    if (url.includes('/changes?')) return response({ changed: [] });
    if (url.includes('/tree')) return response({ ok: true, entries: [], path: '' });
    if (url.endsWith('/conversations')) return response({ conversations: [] });
    throw new Error(`unexpected terminal refresh fetch ${url}`);
  };
  snapshots.length = 0;
  await api.finishRun();
  const finalHtml = snapshots.at(-1) || '';
  if (state.liveEvents.length || state.artifacts.length) throw new Error('terminal refresh retained duplicate live state');
  if (snapshots.length !== 1 || finalHtml.split('unique-progress').length - 1 !== 1) throw new Error('terminal refresh transiently duplicated saved and live activity');
}

async function proveMissingPersistedTurn() {
  resetState();
  Object.assign(state, { activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] }, running: true, runStatus: 'completed', runId: 'run-c1', runProof: { conversationId: 'c1', runId: 'run-c1' }, liveEvents: [{ type: 'say', kind: 'say', text: 'evidence-to-preserve' }], artifacts: [{ file: 'result.html' }] });
  fetchHandler = async url => {
    if (url.endsWith('/conversations/c1')) return response({ ok: true, conversation: { id: 'c1', project_root: '/repo', turns: [{ role: 'user', text: 'build it' }] } });
    if (url.includes('/changes?')) return response({ changed: [] });
    if (url.includes('/tree')) return response({ ok: true, entries: [], path: '' });
    if (url.endsWith('/conversations')) return response({ conversations: [] });
    throw new Error(`unexpected persistence-gap fetch ${url}`);
  };
  await api.finishRun();
  if (!state.liveEvents.some(event => event.text === 'evidence-to-preserve') || state.artifacts.length !== 1) throw new Error('persistence gap discarded live evidence');
  if (!state.runProof || !state.liveEvents.some(event => event.type === 'error' && event.text.includes('durable history'))) throw new Error('persistence gap was not surfaced truthfully');
}

async function proveCompletedReplayDurability() {
  resetState();
  Object.assign(state, { activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] } });
  fetchHandler = async (url, options) => {
    if (url.endsWith('/send') && options?.method === 'POST') return response({ ok: true, conversation_id: 'c1', project_root: '/repo', run_id: 'run-fast', run_state: 'completed', persistence_confirmed: true, outcome: 'completed' });
    if (url.endsWith('/conversations/c1')) return response({ ok: true, conversation: { id: 'c1', project_root: '/repo', turns: [{ role: 'agent', run_id: 'run-fast', transcript: '{"fc":"final","text":"Durable reply"}' }] } });
    if (url.includes('/changes?')) return response({ changed: [] });
    if (url.includes('/tree')) return response({ ok: true, entries: [], path: '' });
    if (url.endsWith('/conversations')) return response({ conversations: [] });
    throw new Error(`unexpected completed replay fetch ${url}`);
  };
  if (await api.send('finish immediately', {}) !== true) throw new Error('durable completed replay reported failure');
  if (state.running || busy || state.liveEvents.length || state.runProof) throw new Error('durable completed replay retained a ghost live turn');
  if (!state.conversation?.turns?.some(turn => turn.run_id === 'run-fast')) throw new Error('durable completed replay lost its final turn');

  resetState();
  Object.assign(state, { activeId: 'c2', projectRoot: '/repo', conversation: { id: 'c2', turns: [] } });
  fetchHandler = async (url, options) => {
    if (url.endsWith('/send') && options?.method === 'POST') return response({ ok: true, conversation_id: 'c2', project_root: '/repo', run_id: 'run-gap', run_state: 'completed', persistence_confirmed: true, outcome: 'completed' });
    if (url.endsWith('/conversations/c2')) return response({ ok: false, error: 'history unavailable' }, 503);
    if (url.endsWith('/conversations')) return response({ conversations: [] });
    throw new Error(`unexpected persistence failure fetch ${url}`);
  };
  if (await api.send('finish with missing history', {}) !== false) throw new Error('unconfirmed completed replay reported success');
  if (state.running || busy || state.runStatus !== 'failed' || !state.runProof) throw new Error('unconfirmed completed replay did not preserve failure proof');
  if (!state.liveEvents.some(event => event.type === 'error' && event.text.includes('durable Code reply'))) throw new Error('unconfirmed completed replay hid its persistence failure');
}

async function proveFinishingQueuesRapidResend() {
  resetState();
  Object.assign(state, { activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] }, running: true, runStatus: 'completed', runId: 'run-old', runProof: { conversationId: 'c1', runId: 'run-old' }, liveEvents: [{ type: 'say', text: 'old progress' }], artifacts: [{ file: 'old.html' }] });
  busy = true;
  let releaseHistory;
  const historyGate = new Promise(resolve => { releaseHistory = resolve; });
  let sendCalls = 0;
  fetchHandler = async (url, options) => {
    if (url.endsWith('/send') && options?.method === 'POST') { sendCalls += 1; return response({ ok: true }); }
    if (url.endsWith('/conversations/c1')) { await historyGate; return response({ ok: true, conversation: { id: 'c1', project_root: '/repo', turns: [{ role: 'agent', run_id: 'run-old' }] } }); }
    if (url.includes('/changes?')) return response({ changed: [] });
    if (url.includes('/tree')) return response({ ok: true, entries: [], path: '' });
    if (url.endsWith('/conversations')) return response({ conversations: [] });
    throw new Error(`unexpected finishing fetch ${url}`);
  };
  const finishing = api.finishRun();
  await Promise.resolve();
  if (await api.send('next queued task', {}) !== true) throw new Error('rapid resend was not accepted into the Code queue');
  if (sendCalls || !state.running || !busy || state.queuedSends?.[0]?.message !== 'next queued task') {
    throw new Error('rapid resend bypassed or was lost from the durable-finish queue');
  }

  Object.assign(state, { runId: 'run-new', runProof: { conversationId: 'c1', runId: 'run-new' }, liveEvents: [{ type: 'say', text: 'new progress' }], artifacts: [{ file: 'new.html' }] });
  releaseHistory();
  await finishing;
  if (!state.running || !busy || state.runProof?.runId !== 'run-new') throw new Error('old finisher released the newer run');
  if (state.liveEvents[0]?.text !== 'new progress' || state.artifacts[0]?.file !== 'new.html') throw new Error('old finisher erased the newer run evidence');
  if (sendCalls || state.queuedSends?.[0]?.message !== 'next queued task') throw new Error('old finisher misdelivered the queued task into the newer run');
}

async function proveLostSendRetryAndCursor() {
  resetState();
  const bodies = [];
  fetchHandler = async (_url, options) => { bodies.push(JSON.parse(options.body)); throw new Error('lost response'); };
  if (await api.send('build once', {}) !== false) throw new Error('lost response reported success');
  fetchHandler = async (_url, options) => { bodies.push(JSON.parse(options.body)); return response({ ok: false, code: 'approval_required', error: 'approve', approval: { id: 'approval-run' } }, 409); };
  await api.send('build once', {});
  if (!bodies[0].request_id || bodies[0].request_id !== bodies[1].request_id || state.pendingRequest.request_id !== bodies[0].request_id) throw new Error('lost response retry changed request identity');
  Object.assign(state, { runId: 'run-cursor', eventCursor: 2 });
  const lifecycle = window.ThomasCodeLifecycle;
  if (lifecycle.acceptEvent(state, { run_id: 'run-cursor', event_seq: 2 }) || lifecycle.acceptEvent(state, { run_id: 'other', event_seq: 3 }) || !lifecycle.acceptEvent(state, { run_id: 'run-cursor', event_seq: 3 })) throw new Error('run-scoped event dedupe failed');
  if (!lifecycle.streamUrl(state).includes('run_id=run-cursor') || !lifecycle.streamUrl(state).includes('cursor=3')) throw new Error('reconnect cursor was not retained');
}

async function proveAccessibleDrawerAndPickerErrors() {
  resetState();
  state.drawerWidth = 360;
  api.render();
  const keydown = resizeListeners.get('keydown');
  if (!keydown) throw new Error('drawer resize handle has no keyboard control');
  let prevented = false;
  keydown({ key: 'ArrowLeft', preventDefault() { prevented = true; } });
  if (!prevented || state.drawerWidth !== 376 || storedDrawerWidth !== '376') throw new Error('keyboard drawer resize did not persist');
  if (resizeHandle.attributes['aria-valuenow'] !== '376' || panel.width !== '376px') throw new Error('drawer resize did not expose its current value');

  failDrawerStorage = true;
  keydown({ key: 'ArrowRight', preventDefault() {} });
  failDrawerStorage = false;
  if (!preferenceWarnings.some(row => row.includes('activity drawer width could not be saved'))) throw new Error('drawer storage failure was silent');

  const pointerdown = resizeListeners.get('pointerdown');
  if (!pointerdown) throw new Error('drawer resize handle has no pointer control');
  pointerdown({ pointerId: 7, preventDefault() {} });
  const pointercancel = resizeListeners.get('pointercancel');
  if (!pointercancel) throw new Error('drawer resize did not register pointer cancellation');
  pointercancel();
  if (resizeListeners.has('pointermove') || resizeListeners.has('pointerup') || resizeListeners.has('pointercancel')) throw new Error('pointer cancellation leaked resize listeners');

  fetchHandler = async url => {
    if (url === '/api/local/projects/pick-folder') {
      return {
        ok: false,
        status: 409,
        headers: { get: () => 'text/plain; charset=utf-8' },
        async text() { return 'could not open the local folder picker'; },
      };
    }
    throw new Error(`unexpected picker fetch ${url}`);
  };
  let pickerError = '';
  try { await api.pickProject(); } catch (error) { pickerError = String(error.message || error); }
  if (pickerError !== 'could not open the local folder picker') throw new Error(`folder picker lost its backend error: ${pickerError}`);

  fetchHandler = async url => {
    if (url === '/api/local/projects/pick-folder') return response({ ok: true, cancelled: true });
    throw new Error(`cancelled picker continued unexpectedly: ${url}`);
  };
  if (await api.pickProject() !== false) throw new Error('cancelled folder picker did not remain a no-op');

  fetchHandler = async (url, options) => {
    if (url === '/api/local/projects/pick-folder') return response({ ok: true, path: '/picked-project' });
    if (url.endsWith('/conversations/new') && options?.method === 'POST') return response({ ok: true, conversation: { id: 'picked', project_root: '/picked-project', turns: [] } });
    if (url.endsWith('/conversations')) return response({ conversations: [] });
    if (url.includes('/tree')) return response({ ok: true, entries: [], path: '' });
    throw new Error(`unexpected successful picker fetch ${url}`);
  };
  if (await api.pickProject() !== true || state.projectRoot !== '/picked-project') throw new Error('successful folder picker did not adopt its project');

  fetchHandler = async url => {
    if (url === '/api/local/projects/pick-folder') {
      return {
        ok: true,
        status: 200,
        headers: { get: () => 'text/plain; charset=utf-8' },
        async text() { return 'not json'; },
      };
    }
    throw new Error(`unexpected malformed picker fetch ${url}`);
  };
  pickerError = '';
  try { await api.pickProject(); } catch (error) { pickerError = String(error.message || error); }
  if (!pickerError.includes('unreadable folder-picker response (200)')) throw new Error('successful non-JSON picker response failed silently');
}

await proveApprovalRetry();
await proveScopedSwitch();
await proveSteeringConfirmation();
await proveEvidenceAndRefresh();
await proveTransientStreamFailure();
await proveTerminalDedup();
await proveMissingPersistedTurn();
await proveCompletedReplayDurability();
await proveFinishingQueuesRapidResend();
await proveLostSendRetryAndCursor();
await proveAccessibleDrawerAndPickerErrors();
console.warn = originalWarn;
process.stdout.write(JSON.stringify({ approval: true, switch: true, steering: true, evidence: true, stream: true, dedup: true, persistence: true, replay: true, finishing: true, cursor: true, drawer: true, pointercancel: true, picker: true }));
