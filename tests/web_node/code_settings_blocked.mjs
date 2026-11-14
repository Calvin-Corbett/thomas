import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const [lifecyclePath, modePath, eventsPath] = process.argv.slice(2);
const context = { window: {}, console, Date, URLSearchParams };
vm.createContext(context);
vm.runInContext(fs.readFileSync(lifecyclePath, 'utf8'), context);
const lifecycle = context.window.ThomasCodeLifecycle;
const mode = fs.readFileSync(modePath, 'utf8');
const initial = { modelId: 'gpt-5.6-sol', dials: { autonomy: 2, fileAccess: 'project' } };
let state = { activeId: '', chosenProjectRoot: '', retryRequest: null, liveEvents: [], artifacts: [] };
const message = 'Build a synthetic counter.';
const first = lifecycle.runRequest(state, message, initial);
state.retryRequest = first;
assert.equal(lifecycle.runRequest(state, message, initial).request_id, first.request_id);
state.retryRequest = Object.fromEntries(Object.entries(first).reverse());
assert.equal(lifecycle.runRequest(state, message, initial).request_id, first.request_id, 'key order is immaterial');
for (const changed of [
  { ...initial, dials: { ...initial.dials, autonomy: 3 } },
  { ...initial, dials: { ...initial.dials, fileAccess: 'workspace' } },
  { ...initial, modelId: 'claude-sonnet-4' },
  { ...initial, dials: { ...initial.dials, guardrails: 'fortress' } },
  { ...initial, dials: { ...initial.dials, memory: false } },
  { ...initial, dials: { ...initial.dials, effort: 'high' } },
  { ...initial, dials: { ...initial.dials, tokenEconomy: 'generous' } },
  { ...initial, docs: [{ name: 'input.txt', text: 'Changed input' }] },
  { ...initial, images: [{ name: 'input.png', data_url: 'data:image/png;base64,AAAA' }] },
]) {
  const next = lifecycle.runRequest(state, message, changed);
  assert.notEqual(next.request_id, first.request_id, 'changed request must have a new ID');
  assert.equal(next.autonomy_level, changed.dials.autonomy);
  assert.equal(next.model_id, changed.modelId);
  assert.equal(next.memory, changed.dials.memory !== false, 'Retry must honor the current memory control');
}
const memoryOff = { ...initial, dials: { ...initial.dials, memory: false } };
state.retryRequest = lifecycle.runRequest(state, message, memoryOff);
assert.equal(state.retryRequest.memory, false);
assert.equal(lifecycle.runRequest(state, message, memoryOff).request_id, state.retryRequest.request_id);
assert.equal(lifecycle.runRequest(state, message, initial).memory, true);
assert.notEqual(lifecycle.runRequest(state, message, initial).request_id, state.retryRequest.request_id);
const changedInputs = { ...initial, docs: [{ name: 'input.txt', text: 'First' }] };
state.retryRequest = lifecycle.runRequest(state, message, changedInputs);
const replacedInput = lifecycle.runRequest(state, message, { ...changedInputs, docs: [{ name: 'input.txt', text: 'Second' }] });
assert.notEqual(replacedInput.request_id, state.retryRequest.request_id);

let launches = 0;
let sentBody;
const explanation = 'Build has not started. Build requires Autonomy set to Agent or Full to edit files; it is currently Assist. Change these controls in Tools, then send again.';
Object.assign(context, {
  document: { readyState: 'loading', addEventListener() {}, getElementById() { return null; } },
  localStorage: { getItem() { return ''; }, setItem() {}, removeItem() {} },
  fetch: async (_url, options) => {
    assert.equal(_url, '/api/evolve/agent/send', 'A blocked request must not load a run or project');
    sentBody = JSON.parse(options.body);
    return { ok: false, status: 409, json: async () => ({ ok: false, code: 'execution_settings_blocked', error: explanation }) };
  },
});
context.window.ThomasUnifiedModes = {
  host: () => ({ setBusy() {}, getContext: () => initial }),
  registerAdapter() {},
};
// Load the same factories as the page. The complete mode supplies their actual
// dependency objects, including finishBusy from the extracted stream factory.
const webJs = path.dirname(modePath);
const page = fs.readFileSync(path.join(webJs, '..', 'chat.html'), 'utf8');
const scripts = [...page.matchAll(/<script src="\/static\/js\/(unified_code_[^?"/]+\.js)(?:\?[^"<>]*)?"><\/script>/g)];
const sources = scripts.map(match => fs.readFileSync(path.join(webJs, match[1]), 'utf8'));
assert.ok(scripts.some(match => match[1] === 'unified_code_run_stream.js'));
for (let i = 0; i < scripts.length; i += 1) {
  if (['unified_code_lifecycle.js', 'unified_code_mode.js'].includes(scripts[i][1])) continue;
  vm.runInContext(sources[i], context);
}
const createStream = context.window.ThomasCodeRunStream.create;
context.window.ThomasCodeRunStream.create = deps => {
  const stream = createStream(deps);
  const accept = stream.acceptStartedRun;
  stream.acceptStartedRun = (...args) => { launches += 1; return accept(...args); };
  return stream;
};
vm.runInContext(mode.replace(/\n\}\)\(\);\s*$/, '\n  window.settingsProbe = { state, send };\n})();'), context);
state = context.window.settingsProbe.state;
assert.equal(await context.window.settingsProbe.send(message, initial), false);
assert.equal(launches, 0);
assert.equal(sentBody.autonomy_level, 2);
assert.equal(initial.dials.autonomy, 2, 'UI must not raise autonomy');
assert.equal(state.runStatus, 'blocked');
assert.equal(state.running, false);
assert.equal(state.runStartedAt, 0);
assert.equal(state.pendingUserText, message);
assert.equal(state.retryRequest, null);
assert.equal(state.liveEvents.length, 1);
assert.equal(state.liveEvents[0].type, 'settings');
assert.equal(state.liveEvents[0].text, explanation);
assert.equal(state.artifacts.length, 0);
assert.ok(sources.join('\n').includes("blocked: 'Check Tools'"));

vm.runInContext(fs.readFileSync(eventsPath, 'utf8'), context);
const narrative = mode.match(/const NARRATIVE_EVENT_KINDS = new Set\((\[[^;]+\])\);/);
const kinds = new Set(vm.runInContext(narrative[1], context));
const esc = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const events = context.window.ThomasCodeEvents.create({
  MAX_VISIBLE_PROGRESS_EVENTS: 120, MAX_PROGRESS_EVENT_CHARS: 420,
  NARRATIVE_EVENT_KINDS: kinds, state, esc, codeResults: () => ({}), surface: () => null,
});
const html = events.eventHtml(state.liveEvents[0], false);
assert.match(html, /Build has not started/);
assert.doesNotMatch(html, /Something went wrong|ph-check-circle|dry-run|is-error/);
assert.equal(events.isTechnicalEvent(state.liveEvents[0]), false);
console.log(JSON.stringify({ ok: true, currentSettingsOnRetry: true, unchangedRetryIdempotent: true, settingsBlockVisible: true, noRunOrProofClaim: true }));
