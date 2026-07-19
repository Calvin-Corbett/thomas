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
  messages: [
    {
      role: 'thomas',
      text: [
        'Workflow: Invoice intake | Purpose: Save every invoice without checking duplicates. | Type: manual',
        'Workflow: Owner report | Purpose: Send the owner a daily processing report. | Type: scheduled',
        'Workflow: Archive records | Purpose: Archive approved invoices with a durable receipt. | Type: manual',
      ].join('\n'),
    },
    { role: 'user', text: 'Revise invoice intake so it is safe.' },
    {
      role: 'thomas',
      text: 'Workflow: Invoice intake | Purpose: Check duplicates and require owner approval before saving. | Type: event',
    },
  ],
  connectors: [],
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

state.messages.push({
  role: 'thomas',
  text: [
    'Workflow: Mail triage | Purpose: Classify every new customer message safely. | Type: event',
    'Workflow: Escalation review | Purpose: Route urgent messages for owner approval. | Type: manual',
    'Workflow: Daily summary | Purpose: Deliver a verified daily operations summary. | Type: scheduled',
  ].join('\n'),
});
const replacedMap = support.onboardingWorkflowCandidates();
assert.deepEqual(Array.from(replacedMap, row => row.name), ['Mail triage', 'Escalation review', 'Daily summary']);

state.messages = [
  {
    role: 'thomas',
    text: [
      'Workflow: Invoice intake | Purpose: Validate and save every incoming invoice. | Type: event',
      'Workflow: Owner report | Purpose: Deliver a verified daily processing report. | Type: scheduled',
      'Workflow: Archive records | Purpose: Archive approved invoices with a durable receipt. | Type: manual',
    ].join('\n'),
  },
  { role: 'user', text: 'Choose Invoice intake.' },
];
let selectionCandidates = support.onboardingWorkflowCandidates();
assert.equal(support.selectedOnboardingWorkflow(selectionCandidates).name, 'Invoice intake');
state.messages.push({ role: 'thomas', text: 'Which mailbox should this workflow read from?' });
state.messages.push({ role: 'user', text: 'Actually switch from Invoice intake to Owner report.' });
selectionCandidates = support.onboardingWorkflowCandidates();
const switched = support.selectedOnboardingWorkflow(selectionCandidates);
assert.equal(switched.name, 'Owner report');
assert.equal(support.onboardingConfigurationReady(selectionCandidates, switched), false);
state.messages.push({ role: 'thomas', text: 'What time should the report arrive?' });
state.messages.push({ role: 'user', text: 'Send it at 8 AM Central on weekdays.' });
assert.equal(support.onboardingConfigurationReady(selectionCandidates, switched), true);

state.messages = [{
  role: 'thomas',
  text: Array.from({ length: 7 }, (_, index) => `Workflow: Flow ${index + 1} | Purpose: Complete distinct outcome number ${index + 1} safely. | Type: manual`).join('\n'),
}];
assert.equal(support.onboardingWorkflowCandidates().length, 7);

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
  latestWorkflowWins: true,
  latestMapReplaces: true,
  switchTargetsDestination: true,
  configurationAnswerRequired: true,
  overflowPreserved: true,
  firstTurnHiddenCompletion: true,
  reconciliationExecuted: true,
  activeDraftRequeued: true,
}));
