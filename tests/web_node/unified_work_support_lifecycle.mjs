import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const supportPath = process.argv[2];
const modePath = process.argv[3];
// The Work adapter words a refused steer through the shared table both steer
// boxes read (js/steering_language.js), so the browser loads it first.
const steeringPath = process.argv[4];
// The Work card's live tasks and steer boxes, which the adapter creates at load.
const steerPath = process.argv[5];
if (!supportPath || !modePath || !steeringPath || !steerPath) throw new Error('support, Work mode, steering-language and Work steer module paths are required');

const context = { window: {} };
vm.createContext(context);
vm.runInContext(fs.readFileSync(supportPath, 'utf8'), context, { filename: supportPath });

const state = {
  messages: [{ role: 'user', text: 'Choose Invoice intake.' }],
  connectors: [],
  onboardingWorkflowId: '',
  structuredOnboardingState: {
    phase: 'workflow_mapping',
    confirmed_goal: 'Process invoices safely.',
    selected_workflow_id: '',
    selected_workflow_configured: false,
    workflows: [
      { id: 'invoice-intake', name: 'Invoice intake', purpose: 'Check duplicates and require owner approval before saving.', type: 'event', connector_suggestions: [] },
      { id: 'owner-report', name: 'Owner report', purpose: 'Send the owner a daily processing report.', type: 'scheduled', connector_suggestions: [] },
      { id: 'archive-records', name: 'Archive records', purpose: 'Archive approved invoices with a durable receipt.', type: 'manual', connector_suggestions: [] },
    ],
  },
};
const support = context.window.ThomasWorkSupport.create({
  state,
  esc: String,
  activeWorkflowFor: () => null,
  statusPill: () => '',
  safeArtifactHref: () => '',
  onboardingBrief: () => '',
  jsonRequest: async () => ({}),
  appUrl: value => value,
});

const candidates = support.onboardingWorkflowCandidates();
assert.equal(candidates.length, 3);
assert.equal(candidates[0].name, 'Invoice intake');
assert.equal(candidates[0].purpose, 'Check duplicates and require owner approval before saving.');
assert.equal(candidates[0].type, 'event');
assert.equal(candidates[1].name, 'Owner report');
assert.equal(support.selectedOnboardingWorkflow(candidates), null);
state.messages.push({ role: 'user', text: 'Actually switch to Owner report and make it urgent.' });
assert.equal(support.selectedOnboardingWorkflow(candidates), null);
state.onboardingWorkflowId = 'owner-report';
state.structuredOnboardingState.selected_workflow_id = 'owner-report';
const selected = support.selectedOnboardingWorkflow(candidates);
assert.equal(selected.name, 'Owner report');
assert.equal(support.onboardingConfigurationReady(candidates, selected), false);
// The model's claim alone is not readiness. Until 2026-09-08 it was: the check
// returned selected_workflow_configured and that result was written back into
// the same field, so the claim certified itself.
state.structuredOnboardingState.selected_workflow_configured = true;
assert.equal(
  support.onboardingConfigurationReady(candidates, selected),
  false,
  'a model claim with no recorded user selection turn is not readiness',
);
// Selecting a workflow records the turn the user did it on; both halves now hold.
state.onboardingSelectionUserTurn = state.messages.filter(row => row.role === 'user').length;
assert.equal(support.onboardingConfigurationReady(candidates, selected), true);
assert.equal(support.confirmedOnboardingGoal(), 'Process invoices safely.');

let workAdapter;
const busyStates = [];
const requests = [];
const scheduledTimers = [];
let releaseGoalPatch;
let markGoalPatchStarted;
const goalPatchGate = new Promise(resolve => { releaseGoalPatch = resolve; });
const goalPatchStarted = new Promise(resolve => { markGoalPatchStarted = resolve; });
const encoder = new TextEncoder();

function response(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => 'application/json' },
    async json() { return data; },
    async text() { return JSON.stringify(data); },
  };
}

function streamResponse() {
  const chunks = [encoder.encode([
    JSON.stringify({ type: 'text', text: 'First, what outcome should this job own every day?' }),
    JSON.stringify({ type: 'done', session_id: 'session-1' }),
    '',
  ].join('\n'))];
  return {
    ok: true,
    status: 200,
    body: { getReader: () => ({ async read() { return chunks.length ? { done: false, value: chunks.shift() } : { done: true }; } }) },
  };
}

async function lifecycleFetch(url, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  requests.push({ url: String(url), method, signal: options.signal || null });
  if (url === '/api/v2/chat') return streamResponse();
  if (String(url).endsWith('/delegations/task-1/steer')) return response({ ok: true, action: 'steer', execution_id: 'task-1' });
  // The refusal the ledger actually sends when the task stopped running first.
  if (String(url).endsWith('/delegations/task-stale/steer')) {
    return response({ ok: false, error: "No running task matches reference 'task-stale'." }, 404);
  }
  if (String(url).endsWith('/delegations') && method === 'GET') return response({ delegations: [{ execution_id: 'task-restored', summary: 'Still running', state: 'running', last_progress: 'Checking files' }] });
  if (url === '/api/work/apps' && method === 'POST') {
    return response({ ok: true, app: { id: 'app-1', name: 'Process invoices', goal: '', onboarding: { fields: {} } } });
  }
  if (url === '/api/work/apps/app-1' && method === 'PATCH') {
    markGoalPatchStarted();
    await goalPatchGate;
    return response({ ok: true, app: { id: 'app-1', name: 'Process invoices', goal: 'Process invoices', onboarding: { fields: {} } } });
  }
  if (url === '/api/session/new' && method === 'POST') return response({ ok: true, session_id: 'session-1' });
  if (url === '/api/work/apps/app-1/onboarding' && method === 'PATCH') {
    return response({ ok: true, onboarding: { fields: { session_id: 'session-1' } } });
  }
  if (url === '/api/work/apps/app-1/onboarding/messages' && method === 'POST') return response({ ok: true });
  if (url === '/api/work/apps/app-1/jobs/job-1' && method === 'GET') {
    return response({ ok: true, job: { id: 'job-1', name: 'Invoice follow-up', history: { session_id: '' } } });
  }
  if (url === '/api/work/apps/app-1/jobs/job-1/automations') return response({ ok: true, automations: [] });
  if (url === '/api/work/apps/app-1/jobs/job-1/bindings') return response({ ok: true, bindings: [] });
  if (url === '/api/work/apps/app-1/jobs/job-1/skills') return response({ ok: true, skills: [] });
  if (url === '/api/work/apps/app-1/jobs/job-1/activity') return response({ ok: true, activity: [] });
  if (url === '/api/work/apps/app-1/jobs/job-1/workflows') return response({ ok: true, workflows: [], active_workflow_id: '' });
  if (url === '/api/chats?mode=work&context_id=app-1%3Ajob-1') return response({ ok: true, chats: [] });
  if (url === '/api/work/apps' && method === 'GET') return response({ ok: true, apps: [] });
  if (url === '/api/work/accounts') return response({ ok: true, accounts: [] });
  if (url === '/api/work/connectors') return response({ ok: true, connectors: [] });
  throw new Error(`unexpected lifecycle request: ${method} ${url}`);
}

const emptyHtml = () => '';
const modeWindow = {
  location: { href: 'http://127.0.0.1:8899/' },
  confirm: () => true,
  ThomasWorkSupport: {
    create: options => ({
      persistOnboardingPhase: context.window.ThomasWorkSupport.create(options).persistOnboardingPhase,
      onboardingWorkflowCandidates: () => [],
      selectedOnboardingWorkflow: () => null,
      onboardingConfigurationReady: () => false,
      modelReportedConfigured: () => false,
      onboardingWorkflowDrafts: () => [],
      restoreOnboardingWorkflow: () => null,
      confirmedOnboardingGoal: () => '',
      visibleOnboardingText: String,
      onboardingInstruction: () => 'Understand and confirm the goal before mapping workflows.',
      messageRows: () => [],
      liveTaskHtml: emptyHtml,
      homeHtml: emptyHtml,
      onboardingHtml: emptyHtml,
      connectorHtml: emptyHtml,
      automationHtml: emptyHtml,
      skillsHtml: emptyHtml,
      dashboardHtml: emptyHtml,
      activityHtml: emptyHtml,
      workflowRailHtml: emptyHtml,
      jobHtml: emptyHtml,
      provisionOnboardedJob: async () => ({}),
    }),
  },
  ThomasUnifiedModes: {
    registerAdapter(name, adapter) { if (name === 'work') workAdapter = adapter; },
    host: () => ({
      getContext: () => ({ dials: {} }),
      renderHistory() {},
      setBusy(value) { busyStates.push(Boolean(value)); },
      announce() {},
    }),
  },
};
const modeContext = {
  window: modeWindow,
  document: { getElementById: () => null, createElement: () => ({}) },
  fetch: lifecycleFetch,
  AbortController,
  TextDecoder,
  Uint8Array,
  URL,
  Intl,
  FormData,
  console,
  requestAnimationFrame: callback => callback(),
  setTimeout(callback, delay) { scheduledTimers.push({ callback, delay }); return scheduledTimers.length; },
  clearTimeout() {},
};
vm.createContext(modeContext);
vm.runInContext(fs.readFileSync(steeringPath, 'utf8'), modeContext, { filename: steeringPath });
vm.runInContext(fs.readFileSync(steerPath, 'utf8'), modeContext, { filename: steerPath });
const modeSource = fs.readFileSync(modePath, 'utf8');
const instrumentedMode = modeSource.replace(
  /\n\}\)\(\);\s*$/,
  '\n  window.__ThomasWorkModeTest = { state, enter, leave, readChatStream, ...steer, selectionGeneration: () => selectionGeneration };\n})();',
);
if (instrumentedMode === modeSource) throw new Error('could not instrument Work mode adapter');
vm.runInContext(instrumentedMode, modeContext, { filename: modePath });
if (!workAdapter) throw new Error('Work adapter was not registered');

await workAdapter.enter();
workAdapter.newConversation();
const firstTurn = workAdapter.send('Process invoices for my business every day.');
await goalPatchStarted;
await workAdapter.leave();
assert.equal(workAdapter.isBusy(), true);
releaseGoalPatch();
await firstTurn;

const modeState = modeWindow.__ThomasWorkModeTest.state;
assert.equal(workAdapter.isBusy(), false);
assert.deepEqual(busyStates, [true, false]);
assert.equal(modeState.activeApp.id, 'app-1');
assert.equal(modeState.sessionId, 'session-1');
assert.deepEqual(Array.from(modeState.messages, row => row.role), ['user', 'assistant'], JSON.stringify(modeState.messages));
assert.equal(modeState.messages[1].text, 'First, what outcome should this job own every day?');
const chatRequest = requests.find(row => row.url === '/api/v2/chat');
assert.ok(chatRequest && chatRequest.signal && !chatRequest.signal.aborted);
assert.equal(requests.filter(row => row.url === '/api/work/apps' && row.method === 'POST').length, 1);
assert.equal(requests.filter(row => row.url === '/api/v2/chat').length, 1);

await workAdapter.enter();
assert.equal(modeState.messages[1].text, 'First, what outcome should this job own every day?');
modeState.stage = 'job';
modeState.activeApp = { id: 'app-1' };
modeState.activeJob = { id: 'job-1' };
await workAdapter.leave();
const timersBeforeReturn = scheduledTimers.length;
await workAdapter.enter();
assert.equal(scheduledTimers.length, timersBeforeReturn + 1);
assert.equal(scheduledTimers.at(-1).delay, 15000);
const jobReadsBeforeReconcile = requests.filter(row => row.url === '/api/work/apps/app-1/jobs/job-1').length;
scheduledTimers.at(-1).callback();
for (let index = 0; index < 20; index += 1) {
  await new Promise(resolve => setImmediate(resolve));
  if (requests.filter(row => row.url === '/api/work/apps/app-1/jobs/job-1').length > jobReadsBeforeReconcile) break;
}
assert.equal(requests.filter(row => row.url === '/api/work/apps/app-1/jobs/job-1').length, jobReadsBeforeReconcile + 1);
assert.equal(scheduledTimers.at(-1).delay, 15000);

modeState.formDirty = true;
const timersBeforeDraftRequeue = scheduledTimers.length;
const jobReadsBeforeDraftRequeue = requests.filter(row => row.url === '/api/work/apps/app-1/jobs/job-1').length;
scheduledTimers.at(-1).callback();
await new Promise(resolve => setImmediate(resolve));
assert.equal(requests.filter(row => row.url === '/api/work/apps/app-1/jobs/job-1').length, jobReadsBeforeDraftRequeue);
assert.equal(scheduledTimers.length, timersBeforeDraftRequeue + 1);
modeState.formDirty = false;

// Progress from the real chat stream is visible and steering reaches the
// existing execution, not /api/v2/chat or a newly created job.
const work = modeWindow.__ThomasWorkModeTest;
const supportHtml = () => {
  Object.assign(state, {
    messages: modeState.messages, liveTasks: modeState.liveTasks, sessionId: modeState.sessionId,
    running: modeState.running, runState: modeState.runState, steeringBusy: modeState.steeringBusy,
  });
  return support.messageRows() + support.liveTaskHtml();
};
modeState.running = true;
modeState.runState = 'working';
modeState.sessionId = 'session-1';
work.recordLiveTask({ type: 'delegation_started', execution_id: 'task-1', title: 'Review invoices', last_progress: 'Reading inbox' });
assert.match(supportHtml(), /Steer this running task/);
assert.match(supportHtml(), /Reading inbox/);
assert.equal(modeState.liveTasks[0].status, 'running');
work.recordLiveTask({ type: 'delegation_progress', execution_id: 'task-1', last_progress: 'Checking attachments' });
assert.match(supportHtml(), /Checking attachments/);
const chatCount = requests.filter(row => row.url === '/api/v2/chat').length;
const input = { value: 'Prioritize urgent invoices' };
const button = { disabled: false };
const note = { textContent: '' };
const form = { querySelector: selector => ({ 'textarea': input, 'button[type="submit"]': button, '[data-work-steer-error]': note })[selector] || null };
assert.equal(await work.steerRunningTask('task-1', form), undefined);
assert.equal(requests.filter(row => row.url === '/api/v2/chat').length, chatCount);
assert.equal(requests.filter(row => row.url === '/api/v2/chat/session/session-1/delegations/task-1/steer').length, 1);
assert.match(supportHtml(), /Update queued for this task/);
assert.equal(input.value, '');

// A refused update says why in plain words, keeps what was typed, and survives
// the next progress render -- the message used to be written straight into the
// form node, so the following progress event erased it within a second.
work.recordLiveTask({ type: 'delegation_started', execution_id: 'task-stale', title: 'Stale task', last_progress: 'Working' });
const staleInput = { value: 'Change course' };
const staleButton = { disabled: false };
const staleNote = { textContent: '' };
const staleForm = { querySelector: selector => ({ 'textarea': staleInput, 'button[type="submit"]': staleButton, '[data-work-steer-error]': staleNote })[selector] || null };
await work.steerRunningTask('task-stale', staleForm);
assert.match(staleNote.textContent, /^Update not applied: This task is no longer running/);
assert.match(supportHtml(), /Update not applied: This task is no longer running/);
assert.doesNotMatch(supportHtml(), /No running task matches reference/, 'the raw ledger sentence and its execution id stay out of the UI');
assert.equal(staleButton.disabled, false, 'the update can be retried');
assert.equal(staleInput.value, 'Change course', 'a failure does not throw away what was typed');
assert.equal(modeState.steeringBusy, '');
work.recordLiveTask({ type: 'delegation_progress', execution_id: 'task-stale', last_progress: 'Still working' });
assert.match(supportHtml(), /Update not applied: This task is no longer running/, 'the reason survives the next progress render');
work.recordLiveTask({ type: 'delegation_completed', execution_id: 'task-stale', last_progress: 'Done' });

// Two tasks can run at once, and every progress line repaints the surface. Each
// steer box keeps its own half-typed note across that repaint, with the caret
// where it was -- only the first box used to be carried, so a note for the
// second task was erased a second after it was typed.
{
  const steerBox = (id, value, disabled = false) => {
    const textarea = { value, disabled, focused: false, selection: null, focus() { this.focused = true; }, setSelectionRange(start, end) { this.selection = [start, end]; } };
    return { dataset: { workSteer: id }, textarea, querySelector: selector => (selector === 'textarea' ? textarea : null), contains: node => node === textarea };
  };
  const before = [steerBox('task-a', 'Skip the archived invoices'), steerBox('task-b', 'Only the March batch'), steerBox('task-c', 'in flight', true)];
  const caret = before[1].textarea;
  const rootWith = forms => ({ querySelectorAll: selector => (selector === '[data-work-steer]' ? forms : []) });
  modeContext.document.activeElement = caret;
  const drafts = work.captureSteerDrafts(rootWith(before));
  modeContext.document.activeElement = null;
  // Array.from, not drafts.map: the adapter builds this list inside the vm
  // realm, so its arrays carry that realm's Array.prototype and a strict
  // deep-equal against a host literal fails on the prototype alone.
  assert.deepEqual(Array.from(drafts, row => row.id), ['task-a', 'task-b', 'task-c']);
  assert.deepEqual(Array.from(drafts, row => row.focused), [false, true, false]);
  const after = [steerBox('task-a', ''), steerBox('task-b', ''), steerBox('task-c', '', true)];
  work.restoreSteerDrafts(rootWith(after), drafts);
  assert.equal(after[0].textarea.value, 'Skip the archived invoices');
  assert.equal(after[1].textarea.value, 'Only the March batch', 'the second box keeps its own note');
  assert.equal(after[1].textarea.focused, true, 'the caret goes back where it was');
  assert.deepEqual(after[1].textarea.selection, [20, 20]);
  assert.equal(after[0].textarea.focused, false);
  assert.equal(after[2].textarea.value, 'in flight', 'a box showing "Sending…" still shows what is on its way');
  assert.equal(after[2].textarea.focused, false, 'a disabled box is never focused');
  // A repaint that drops a finished task must not restore its note somewhere else.
  const onlyA = [steerBox('task-a', '')];
  work.restoreSteerDrafts(rootWith(onlyA), drafts);
  assert.equal(onlyA[0].textarea.value, 'Skip the archived invoices');
}

work.recordLiveTask({ type: 'delegation_completed', execution_id: 'task-1', last_progress: 'Done' });
assert.match(supportHtml(), /tc-work-live-badge">completed/);
assert.doesNotMatch(supportHtml(), /data-work-steer="task-1"/);
work.recordLiveTask({ type: 'delegation_started', execution_id: 'task-2', title: 'Follow up' });
work.recordLiveTask({ type: 'delegation_failed', execution_id: 'task-2', last_progress: 'Could not reach inbox' });
assert.match(supportHtml(), /tc-work-live-badge">failed/);
assert.doesNotMatch(supportHtml(), /data-work-steer="task-2"/);
modeState.running = false;
modeState.runState = 'completed';
work.recordLiveTask({ type: 'delegation_started', execution_id: 'task-background', title: 'Finishing in background' });
assert.match(supportHtml(), /data-work-steer="task-background"/, 'steering remains available after chat stream ends');
assert.match(supportHtml(), /Task running/, 'delegation remains running independently of chat stream');
modeState.liveTasks = [];
await work.restoreRunningTasks(work.selectionGeneration(), 'session-1');
assert.match(supportHtml(), /Still running/);
assert.match(supportHtml(), /data-work-steer="task-restored"/);
modeState.liveTasks = [];
modeState.runState = 'failed';
assert.match(supportHtml(), /Did not finish/);

console.log(JSON.stringify({
  ok: true,
  structuredWorkflowState: true,
  proseCannotSelectWorkflow: true,
  explicitSelectionWorks: true,
  modelConfigurationStateRequired: true,
  firstTurnHiddenCompletion: true,
  reconciliationExecuted: true,
  activeDraftRequeued: true,
  workSteerSameTask: true,
  workSteerRefusalExplained: true,
  workSteerDraftsPerTask: true,
  workProgressStates: true,
  backgroundSteeringAndRestore: true,
}));
