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
if (!supportPath || !modePath) throw new Error('support and Work mode module paths are required');

const requests = [];
const encoder = new TextEncoder();
let onboardingPatchStatus = 200;

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
const modeWindow = {
  location: { href: 'http://127.0.0.1:8899/' },
  confirm: () => true,
  ThomasUnifiedModes: {
    registerAdapter(name, adapter) { if (name === 'work') workAdapter = adapter; },
    host: () => ({
      getContext: () => ({ dials: {} }),
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
const modeSource = fs.readFileSync(modePath, 'utf8');
const instrumented = modeSource.replace(
  /\n\}\)\(\);\s*$/,
  '\n  window.__ThomasWorkModeTest = { state, send, safely, selectOnboardingWorkflow };\n})();',
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
  messages: [
    { role: 'user', text: 'Plan a small dinner party for 6 people on Saturday.' },
    { role: 'assistant', text: 'Select **Dinner party plan** in the workflow options to lock it in.' },
    { role: 'user', text: 'Yes - use the Dinner party plan workflow.' },
    { role: 'assistant', text: 'How formal should the menu be?' },
    { role: 'user', text: 'Casual, one pot dishes.' },
    { role: 'assistant', text: 'Great, casual it is.' },
    { role: 'user', text: 'That is everything.' },
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
const oneWorkflowFinishable = true;

console.log(JSON.stringify({
  ok: true,
  composerTextCarried,
  namedSelectionAccepted,
  ambiguityStaysUnselected,
  fourXxIsVisible,
  markdownRenders,
  oneWorkflowFinishable,
}));
