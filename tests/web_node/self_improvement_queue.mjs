/* The existing Improve Thomas dialog shows queue provenance and controls its planner. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('thomas/server/web/js/self_edit_controls.js', 'utf8');
const requests = [];
let host;
const dialog = {
  style: {},
  setAttribute() {},
  showModal() {},
  close() {},
  addEventListener() {},
  querySelector(selector) {
    if (selector === '[data-self-queue]') return host;
    if (selector === '[data-cancel]') return { onclick: null };
    if (selector === 'form') return { onsubmit: null };
    return null;
  },
  querySelectorAll() { return []; },
};
const document = {
  getElementById() { return null; },
  createElement() { return dialog; },
  body: { append() {} },
};
const fetch = async (url, options) => {
  requests.push({ url, options });
  if (options?.method === 'PUT') return { ok: true, json: async () => ({ ok: true, planner: { enabled: false } }) };
  if (url.endsWith('/planner')) return { ok: true, json: async () => ({ ok: true, planner: { enabled: true } }) };
  if (url.endsWith('/queue')) return { ok: true, json: async () => ({ ok: true, capacity: { running: 5, starting: 1, blocked_by: 'Not enough disk <free>' }, queued: [
    { origin: 'pytest', source_id: 'tests/example.py::failed', request: 'Fix example', last_reason: 'temporary launch failure', failed_at: 1700000001 },
  ], given_up: [
    { request: 'Newest refusal', last_reason: '<invalid guardrails>', failed_at: 1700000000 },
    ...Array.from({ length: 11 }, (_, index) => ({ request: `Older refusal ${index}`, reason: 'old failure' })),
  ] }) };
  return { ok: true, json: async () => ({ ok: true, projects: [] }) };
};
const context = { window: {}, document, fetch, console };
vm.createContext(context);
vm.runInContext(source, context);
host = {
  innerHTML: '',
  querySelector(selector) {
    if (selector === '[data-planner-enabled]') return toggle;
    if (selector === '[data-planner-error]') return { textContent: '' };
    return null;
  },
};
const toggle = { checked: true, disabled: false };
context.window.ThomasSelfEdit.open();
await new Promise(resolve => setTimeout(resolve, 0));
assert.match(dialog.innerHTML, /data-self-queue/);
assert.match(host.innerHTML, /tests\/example\.py::failed/);
assert.match(host.innerHTML, /Fix example/);
assert.match(host.innerHTML, /5 running, 1 starting; 1 queued/);
assert.match(host.innerHTML, /More cannot start: Not enough disk &lt;free&gt;/);
assert.match(host.innerHTML, /Origin: pytest/);
assert.match(host.innerHTML, /data-planner-enabled/);
assert.match(host.innerHTML, /Could not start/);
assert.match(host.innerHTML, /Newest refusal/);
assert.ok(host.innerHTML.includes(`<time>${new Date(1700000000 * 1000).toLocaleString()}</time>`));
assert.doesNotMatch(host.innerHTML, /Older refusal 10/);
assert.match(host.innerHTML, /temporary launch failure \(will retry\) · <time>[^<]+<\/time>/);
assert.match(host.innerHTML, /will retry/);
assert.match(host.innerHTML, /&lt;invalid guardrails&gt;/);
toggle.checked = false;
await toggle.onchange();
assert.equal(requests.at(-1).url, '/api/self/projects/queue/planner');
assert.equal(requests.at(-1).options.method, 'PUT');
assert.equal(JSON.parse(requests.at(-1).options.body).enabled, false);
console.log('Self-improvement queue provenance and planner switch OK');
