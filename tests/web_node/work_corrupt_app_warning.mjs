import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const modePath = process.argv[2];
if (!modePath) throw new Error('Work mode module path required');
const requests = [];
const root = {
  innerHTML: '',
  insertAdjacentHTML(position, html) { assert.equal(position, 'afterbegin'); this.innerHTML = html + this.innerHTML; },
  querySelectorAll() { return []; },
  querySelector() { return null; },
};
const warning = {
  app_id: 'app-75c180040a34', job_id: 'once-stock-proof-0007',
  workflow_id: 'stock', reason: 'scheduled workflow cannot use a manual trigger',
};
const responses = {
  '/api/work/apps': { apps: [{ id: 'healthy' }], warnings: [warning] },
  '/api/work/accounts': { accounts: [] },
  '/api/work/connectors': { connectors: [] },
  '/api/work/lane-proposals': { proposals: [] },
};
let adapter;
const context = {
  window: {
    ThomasUnifiedModes: {
      registerAdapter(name, value) { assert.equal(name, 'work'); adapter = value; },
      host: () => ({ renderHistory() {} }),
    },
    ThomasWorkSupport: { create: () => ({ homeHtml: () => '<div>Healthy Work</div>' }) },
    ThomasWorkModeSteer: { create: () => ({ paintKeepingSteerDrafts(node, paint) { paint(); } }) },
  },
  document: { getElementById: () => root },
  fetch: async url => {
    requests.push(url);
    assert.ok(responses[url], `unexpected request: ${url}`);
    return { ok: true, status: 200, json: async () => responses[url] };
  },
  requestAnimationFrame: () => {},
  setTimeout: () => 1,
  clearTimeout: () => {},
};
// Instrument only the private state used to verify that a stale selection is discarded.
const source = fs.readFileSync(modePath, 'utf8');
const instrumented = source.replace(/\n\}\)\(\);\s*$/, '\n  window.__workState = state;\n})();');
assert.notEqual(source, instrumented);
vm.createContext(context);
vm.runInContext(instrumented, context, { filename: modePath });
assert.ok(adapter, 'the Work adapter was not registered');
await adapter.enter();
context.window.__workState.activeApp = { id: warning.app_id };
context.window.__workState.activeJob = { id: warning.job_id };
await adapter.refresh();
assert.equal(context.window.__workState.activeApp, null);
assert.equal(context.window.__workState.activeJob, null);
assert.equal(context.window.__workState.stage, 'home');
assert.ok(root.innerHTML.includes('Healthy Work'));
for (const value of Object.values(warning)) assert.ok(root.innerHTML.includes(value), value);
assert.ok(root.innerHTML.includes('their stored data is preserved'));
assert.deepEqual(requests, Object.keys(responses));
console.log('Work warning rendered and stale selection cleared');
