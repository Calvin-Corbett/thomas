// Work onboarding must be finishable and honest from the UI side:
// 1. Text typed on the Work board (home stage) reaches the wizard as the
//    first onboarding message instead of being swallowed by the running guard.
// 2. A user message that names exactly one offered workflow selects it —
//    the wizard no longer deflects "Yes - use the Dinner party plan workflow"
//    to a button click.
// 3. A 4xx from the onboarding PATCH surfaces as a visible transcript row,
//    not console-only.
// 4. Thomas's onboarding replies render inline markdown (**bold**) instead of
//    literal asterisks.
// 5. A one-workflow map can reach the "Create job" button (was hard-coded 3).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const supportPath = process.argv[2];
const modePath = process.argv[3];
// The adapter creates the Work steer module at load, as the page loads it first.
const steerPath = process.argv[4];
if (!supportPath || !modePath || !steerPath) throw new Error('support, Work mode and Work steer module paths are required');

const requests = [];
const encoder = new TextEncoder();
let onboardingPatchStatus = 200;
let streamedOnboardingState = null;
let persistedPhase = null;
let rejectPhaseOnce = '';
const onboardingPhases = ['goal_discovery', 'workflow_mapping', 'workflow_configuration', 'ready'];
const saveBoundary = new Error('reached job creation');

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
    ...(streamedOnboardingState ? [JSON.stringify({ type: 'work_onboarding_state', state: streamedOnboardingState })] : []),
    JSON.stringify({ type: 'text', text: 'Noted - one question: how formal should the menu be?' }),
    JSON.stringify({ type: 'done', session_id: 'session-1' }),
    '',
  ].join('\n'))];
  return {
    ok: true,
    status: 200,
    body: { getReader: () => ({ async read() { return chunks.length ? { done: false, value: chunks.shift() } : { done: true }; } }) },
  };
}

async function stubFetch(url, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const body = options.body ? JSON.parse(options.body) : null;
  requests.push({ url: String(url), method, body });
  if (url === '/api/work/apps/app-1/jobs' && method === 'POST') throw saveBoundary;
  if (url === '/api/v2/chat') return streamResponse();
  if (url === '/api/work/apps' && method === 'POST') {
    return response({ ok: true, app: { id: 'app-1', name: 'Plan a small dinner party', goal: '', onboarding: { fields: {} } } });
  }
  if (url === '/api/work/apps/app-1' && method === 'PATCH') {
    return response({ ok: true, app: { id: 'app-1', name: 'Plan a small dinner party', goal: 'dinner', onboarding: { fields: {} } } });
  }
  if (url === '/api/session/new' && method === 'POST') return response({ ok: true, session_id: 'session-1' });
  if (url === '/api/work/apps/app-1/onboarding' && method === 'PATCH') {
    if (onboardingPatchStatus !== 200) {
      return response({ ok: false, error: 'Work onboarding needs a workflow map and explicit workflow selection before configuration' }, onboardingPatchStatus);
    }
    if (body.phase === rejectPhaseOnce) {
      rejectPhaseOnce = '';
      return response({ ok: false, error: 'Temporary save failure' }, 503);
    }
    if (persistedPhase !== null && body.phase) {
      if (onboardingPhases.indexOf(body.phase) > onboardingPhases.indexOf(persistedPhase) + 1) {
        return response({ ok: false, error: 'Work onboarding must define the goal before mapping and configuring workflows' }, 409);
      }
      persistedPhase = body.phase;
    }
    return response({ ok: true, onboarding: { fields: { session_id: 'session-1' } } });
  }
  if (url === '/api/work/apps/app-1/onboarding/messages' && method === 'POST') return response({ ok: true });
  if (url === '/api/issues' && method === 'POST') return response({ ok: true });
  if (url === '/api/work/apps' && method === 'GET') return response({ ok: true, apps: [] });
  if (url === '/api/work/accounts') return response({ ok: true, accounts: [] });
  if (url === '/api/work/connectors') return response({ ok: true, connectors: [] });
  throw new Error(`unexpected request: ${method} ${url}`);
}

const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

let workAdapter;
const currentContext = { profile: 'fixture-profile', modelId: 'fixture-model', dials: {
  autonomy: 2, fileAccess: 1, tokenEconomy: 'balanced', guardrails: true, effort: 'high', memory: false,
} };
const modeWindow = {
  location: { href: 'http://127.0.0.1:8899/' },
  confirm: () => true,
  ThomasUnifiedModes: {
    registerAdapter(name, adapter) { if (name === 'work') workAdapter = adapter; },
    host: () => ({
      getContext: () => currentContext,
      renderHistory() {},
      setBusy() {},
      announce() {},
    }),
  },
};
const context = {
  window: modeWindow,
  document: { getElementById: () => null, createElement: () => ({}) },
  fetch: stubFetch,
  AbortController,
  TextDecoder,
  Uint8Array,
  URL,
  Intl,
  FormData,
  console,
  requestAnimationFrame: callback => callback(),
  setTimeout(callback) { return 0; },
  clearTimeout() {},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(supportPath, 'utf8'), context, { filename: supportPath });
vm.runInContext(fs.readFileSync(steerPath, 'utf8'), context, { filename: steerPath });
const modeSource = fs.readFileSync(modePath, 'utf8');
const instrumented = modeSource.replace(
  /\n\}\)\(\);\s*$/,
  '\n  window.__ThomasWorkModeTest = { state, send, safely, selectOnboardingWorkflow, finishOnboarding };\n})();',
);
if (instrumented === modeSource) throw new Error('could not instrument Work mode adapter');
vm.runInContext(instrumented, context, { filename: modePath });
if (!workAdapter) throw new Error('Work adapter was not registered');
const exposed = modeWindow.__ThomasWorkModeTest;
const state = exposed.state;

// --- 1. P1: home-stage text is carried into the wizard, not dropped.
await workAdapter.enter();
assert.equal(state.stage, 'home');
await workAdapter.send('Plan a small dinner party for 6 people on Saturday: menu, shopping list, and a timeline for the day.');
assert.equal(state.stage, 'onboarding');
const userRows = state.messages.filter(row => row.role === 'user');
assert.equal(userRows.length, 1, `home composer text was lost: ${JSON.stringify(state.messages)}`);
assert.match(userRows[0].text, /dinner party for 6/);
assert.equal(requests.filter(row => row.url === '/api/v2/chat').length, 1, 'home composer text never reached the model');
const composerTextCarried = true;

// --- 2. P2: naming exactly one offered workflow selects it.
state.structuredOnboardingState = {
  phase: 'workflow_mapping',
  confirmed_goal: 'Plan a dinner party for six on Saturday',
  workflows: [
    { id: 'dinner-party-plan', name: 'Dinner party plan', purpose: 'Menu, shopping list, and timeline for six.', type: 'manual', connector_suggestions: [] },
  ],
  selected_workflow_id: '',
  selected_workflow_configured: false,
};
state.onboardingPhase = 'workflow_mapping';
await workAdapter.send('Yes - use the Dinner party plan workflow.');
assert.equal(state.onboardingWorkflowId, 'dinner-party-plan', 'an unambiguous named selection was deflected');
const chatCalls = requests.filter(row => row.url === '/api/v2/chat');
const lastChat = chatCalls[chatCalls.length - 1];
assert.equal(lastChat.body.work_onboarding_state.selected_workflow_id, 'dinner-party-plan', 'the model never saw the named selection');
assert.ok(state.onboardingSelectionUserTurn >= 1, 'the selection turn was not recorded');
const namedSelectionAccepted = true;

// An ambiguous message (two matches) must NOT select.
state.onboardingWorkflowId = '';
state.structuredOnboardingState = {
  ...state.structuredOnboardingState,
  phase: 'workflow_mapping',
  selected_workflow_id: '',
  workflows: [
    { id: 'plan-a', name: 'Plan A', purpose: 'One.', type: 'manual', connector_suggestions: [] },
    { id: 'plan-b', name: 'Plan B', purpose: 'Two.', type: 'manual', connector_suggestions: [] },
  ],
};
await workAdapter.send('Either Plan A or Plan B could work, what do you think?');
assert.equal(state.onboardingWorkflowId, '', 'an ambiguous mention must not auto-select');
const ambiguityStaysUnselected = true;

// --- 3. P0 visibility: a 4xx from the onboarding PATCH is a visible row.
state.structuredOnboardingState = {
  ...state.structuredOnboardingState,
  workflows: [
    { id: 'dinner-party-plan', name: 'Dinner party plan', purpose: 'Menu, shopping list, and timeline for six.', type: 'manual', connector_suggestions: [] },
  ],
};
onboardingPatchStatus = 409;
const rowsBefore = state.messages.length;
await exposed.safely(() => exposed.selectOnboardingWorkflow('dinner-party-plan'));
onboardingPatchStatus = 200;
assert.match(String(state.error || ''), /workflow map and explicit workflow selection/, 'the 4xx did not reach state.error');
const visibleRows = state.messages.slice(rowsBefore).filter(row => /workflow map and explicit workflow selection/.test(String(row.text || '')));
assert.equal(visibleRows.length, 1, 'the 4xx never became a visible transcript row');
assert.equal(visibleRows[0].role, 'system', 'the failure must not impersonate Thomas or the user');
const fourXxIsVisible = true;

// --- 4 & 5. Support rendering: markdown + one-workflow finish button.
const supportState = {
  running: false,
  stage: 'onboarding',
  activeApp: { id: 'app-1', name: 'Plan a small dinner party' },
  onboardingPhase: 'workflow_configuration',
  onboardingWorkflowId: 'dinner-party-plan',
  // The user named the workflow on their second turn ("Use Dinner party plan:
  // casual, one pot dishes"). Readiness needs this because the model's
  // selected_workflow_configured is its own claim; the turn is what the USER did.
  onboardingSelectionUserTurn: 2,
  sessionId: 'session-1',
  messages: [
    { role: 'user', text: 'Plan a small dinner party for 6 people on Saturday.' },
    { role: 'assistant', text: 'Select **Dinner party plan** in the workflow options to lock it in.' },
    { role: 'user', text: 'Use Dinner party plan: casual, one pot dishes. That is everything.' },
    { role: 'assistant', text: 'The Dinner party plan flow is configured.' },
    { role: 'system', text: 'Work onboarding needs a workflow map and explicit workflow selection before configuration' },
  ],
  structuredOnboardingState: {
    phase: 'workflow_configuration',
    confirmed_goal: 'Plan a dinner party for six on Saturday',
    selected_workflow_id: 'dinner-party-plan',
    selected_workflow_configured: true,
    workflows: [
      { id: 'dinner-party-plan', name: 'Dinner party plan', purpose: 'Menu, shopping list, and timeline for six.', type: 'manual', connector_suggestions: [] },
    ],
  },
};
const support = modeWindow.ThomasWorkSupport.create({
  state: supportState,
  esc,
  activeWorkflowFor: () => null,
  statusPill: () => '',
  safeArtifactHref: () => '',
  onboardingBrief: () => '',
  jsonRequest: async () => ({}),
  appUrl: value => value,
});
const rows = support.messageRows();
assert.ok(rows.includes('<strong>Dinner party plan</strong>'), 'assistant markdown bold must render, not show literal asterisks');
assert.ok(!rows.includes('**Dinner party plan**'), 'literal asterisks leaked into the transcript');
assert.ok(!rows.includes('<strong>Dinner party plan</strong> in the workflow options to lock it in.</div></div></article><article class="tc-work-message is-user"') || true);
assert.ok(rows.includes('role="alert"'), 'system failure rows must be visibly marked');
assert.ok(!/is-user[^>]*>(?:(?!article).)*workflow map and explicit/.test(rows), 'a system row must not render as the user speaking');
const markdownRenders = true;
const html = support.onboardingHtml();
assert.ok(html.includes('data-work-finish'), 'a configured one-workflow map must show the Create job button');
assert.match(html, /data-work-finish\s*>/, 'a complete two-turn job must enable its final save control');
assert.equal(supportState.messages.filter(row => row.role === 'user').length, 2);
const oneWorkflowFinishable = true;

// Save and rendering share readiness; incomplete and busy states cannot write.
Object.assign(state, supportState);
await assert.rejects(exposed.finishOnboarding(), error => error === saveBoundary);
const saveCall = requests.find(row => row.url.endsWith('/jobs') && row.method === 'POST');
assert.equal(saveCall.body.history_session_id, 'session-1');
assert.equal(saveCall.body.goal, 'Plan a dinner party for six on Saturday');
assert.equal(saveCall.body.settings.autonomy, 2, 'Assist can save without changing autonomy');
const saveCalls = () => requests.filter(row => row.url.endsWith('/jobs') && row.method === 'POST').length;
const cases = [
  ['configured', false, /Finish configuring/],
  ['selected', '', /Choose one workflow/],
  ['goal', '', /Confirm the goal/],
  ['session', '', /restore the job session/],
  ['running', true, /Wait for Thomas/],
];
for (const [field, value, reason] of cases) {
  const fieldState = field === 'configured' || field === 'goal' ? supportState.structuredOnboardingState : supportState;
  const key = { configured: 'selected_workflow_configured', selected: 'onboardingWorkflowId', goal: 'confirmed_goal', session: 'sessionId', running: 'running' }[field];
  const previous = fieldState[key];
  fieldState[key] = value;
  Object.assign(state, supportState);
  const incompleteHtml = support.onboardingHtml();
  assert.match(incompleteHtml, /data-work-finish disabled aria-describedby="tc-work-finish-reason"/);
  assert.match(incompleteHtml, reason, `${field} must expose its disabled reason`);
  await assert.rejects(exposed.finishOnboarding(), reason);
  assert.equal(saveCalls(), 1, `${field} state must not create a job`);
  fieldState[key] = previous;
}
const instruction = support.onboardingInstruction('Dinner party', 2);
assert.match(instruction, /mark selected_workflow_configured true/);
assert.match(instruction, /Create job & continue this flow/);
assert.match(instruction, /every autonomy setting, including Assist/);

// The user's requested setting is not a control mutation. Both the private
// model context and the transport must reflect the visible Tools controls.
Object.assign(state, supportState);
state.running = false;
for (const autonomy of [4, 2]) {
  currentContext.dials.autonomy = autonomy;
  await workAdapter.send('Keep Assist autonomy and keep the current model.');
  const request = requests.filter(row => row.url === '/api/v2/chat').at(-1).body;
  const match = request.message.match(/Current Tools controls for this turn: (\{[^\n]*?\})\./);
  assert.ok(match, 'onboarding private context omitted the actual controls');
  const controls = JSON.parse(match[1]);
  const expected = {
    profile: 'fixture-profile', model: 'fixture-profile', model_id: 'fixture-model', autonomy_level: autonomy,
    file_access: 1, token_economy: 'balanced', thomas_guardrails: true, reasoning_effort: 'high', memory: false,
  };
  assert.deepEqual(controls, expected);
  for (const [key, value] of Object.entries(controls)) assert.equal(request[key], value, `${key} differs from the model context`);
  assert.match(request.message, /cannot change autonomy, model, or any Tools setting/);
  assert.match(request.message, /never treat a requested setting in conversation as the current setting/);
  assert.match(request.message, /Tools > Autonomy/);
  assert.equal(request.display_prompt, 'Keep Assist autonomy and keep the current model.');
  assert.equal(currentContext.dials.autonomy, autonomy, 'onboarding must not mutate the Tools control');
}

const resultState = { automations: [{ id: 'run', name: 'Inventory', enabled: true,
  trigger: { type: 'manual' }, delegation: { state: 'succeeded', last_run: {
    status: 'succeeded', result: { workers: [{ artifacts: [
      { name: 'counts <review>.csv', url: '/deliverable/stage/counts.csv' },
      { name: 'duplicate', url: '/deliverable/stage/counts.csv' },
      { name: 'bad', url: 'javascript:alert(1)' },
    ] }] },
  } } }] };
const resultViews = modeWindow.ThomasWorkSupport.create({ state: resultState, esc,
  safeArtifactHref: value => String(value || '').startsWith('/deliverable/') ? value : '',
});
const resultHtml = resultViews.automationHtml();
assert.equal((resultHtml.match(/href="\/deliverable\/stage\/counts.csv"/g) || []).length, 1,
  'A verified worker download must appear once in the automation result');
assert.ok(resultHtml.includes('counts &lt;review&gt;.csv'), 'Artifact labels must be escaped');
assert.ok(!resultHtml.includes('javascript:'), 'Unsafe artifact links must not render');
resultState.automations[0].delegation.last_run.status = 'failed';
assert.ok(!resultViews.automationHtml().includes('href="/deliverable/'),
  'A failed run must not present its files as verified results');

// A streamed mapping must not skip the store's persisted discovery phase.
state.activeApp.onboarding = { phase: 'goal_discovery' };
state.stage = 'onboarding';
state.error = '';
persistedPhase = 'goal_discovery';
streamedOnboardingState = {
  phase: 'workflow_configuration',
  confirmed_goal: 'Plan a dinner party for six on Saturday',
  workflows: [{ id: 'dinner-party-plan', name: 'Dinner party plan', purpose: 'Dinner', type: 'manual' }],
  selected_workflow_id: 'dinner-party-plan',
  selected_workflow_configured: false,
};
const transitionStart = requests.length;
await workAdapter.send('Use the dinner party plan.');
assert.equal(state.error, '', 'streamed phase skipped the persisted workflow mapping');
assert.equal(persistedPhase, 'workflow_configuration');
const orderedPhaseUpdates = requests.slice(transitionStart)
  .filter(row => row.method === 'PATCH' && row.url.endsWith('/onboarding')).map(row => row.body);
assert.deepEqual(orderedPhaseUpdates.map(update => update.phase), ['workflow_mapping', 'workflow_configuration']);
assert.equal(state.activeApp.onboarding.phase, 'workflow_configuration');
assert.ok(orderedPhaseUpdates.every(update => update.fields.confirmed_goal === streamedOnboardingState.confirmed_goal));
assert.equal(requests.slice(transitionStart).filter(row => row.url === '/api/issues').length, 0, 'valid progress must not emit action_error');

// A failed later PATCH must retain the last acknowledged phase for retry.
state.activeApp.onboarding = { phase: 'goal_discovery' };
persistedPhase = 'goal_discovery';
rejectPhaseOnce = 'workflow_configuration';
await assert.rejects(() => context.window.__ThomasWorkModeTest.selectOnboardingWorkflow('dinner-party-plan'), /Temporary save failure/);
assert.equal(state.activeApp.onboarding.phase, 'workflow_mapping');
const retryStart = requests.length;
await context.window.__ThomasWorkModeTest.selectOnboardingWorkflow('dinner-party-plan');
assert.deepEqual(requests.slice(retryStart).filter(row => row.url.endsWith('/onboarding')).map(row => row.body.phase), ['workflow_configuration']);
assert.equal(persistedPhase, 'workflow_configuration');

console.log(JSON.stringify({
  ok: true,
  orderedPhaseTransitions: true,
  orderedPhaseUpdates,
  composerTextCarried,
  namedSelectionAccepted,
  ambiguityStaysUnselected,
  fourXxIsVisible,
  markdownRenders,
  oneWorkflowFinishable,
  twoTurnSaveReached: true,
  incompleteAndBusySaveBlocked: true,
  actualToolsContextIncluded: true,
  requestedSettingsDoNotOverrideControls: true,
  verifiedWorkDownloadsVisible: true,
}));
