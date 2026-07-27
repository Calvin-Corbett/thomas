import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const supportPath = process.argv[2];
const modePath = process.argv[3];
if (!supportPath || !modePath) throw new Error('support and Work mode module paths are required');

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
state.structuredOnboardingState.selected_workflow_configured = true;
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
    create: () => ({
      onboardingWorkflowCandidates: () => [],
      selectedOnboardingWorkflow: () => null,
      onboardingConfigurationReady: () => false,
      onboardingWorkflowDrafts: () => [],
      restoreOnboardingWorkflow: () => null,
      confirmedOnboardingGoal: () => '',
      visibleOnboardingText: String,
      onboardingInstruction: () => 'Understand and confirm the goal before mapping workflows.',
      messageRows: () => [],
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
const modeSource = fs.readFileSync(modePath, 'utf8');
const instrumentedMode = modeSource.replace(
  /\n\}\)\(\);\s*$/,
  '\n  window.__ThomasWorkModeTest = { state, enter, leave };\n})();',
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

console.log(JSON.stringify({
  ok: true,
  structuredWorkflowState: true,
  proseCannotSelectWorkflow: true,
  explicitSelectionWorks: true,
  modelConfigurationStateRequired: true,
  firstTurnHiddenCompletion: true,
  reconciliationExecuted: true,
  activeDraftRequeued: true,
}));
