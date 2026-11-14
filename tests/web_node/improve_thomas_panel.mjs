/* "Improve Thomas" talks to /api/self/projects: the dials it sends, and the list it shows. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context = { window: {} };
vm.createContext(context);
vm.runInContext(fs.readFileSync('thomas/server/web/js/self_edit_controls.js', 'utf8'), context);
const { settings, showProjects } = context.window.ThomasSelfEdit;

// Every key must be one POST /api/self/projects accepts; it refuses any other by name. This is
// self_project_routes.SETTINGS_KEYS.
const ACCEPTED = new Set(['engine', 'model', 'model_id', 'reasoning_effort', 'autonomy_level', 'file_access', 'memory', 'guardrails', 'token_economy', 'build_roles']);

// No Build surface open yet: defaults only, and nothing the route would reject.
let sent = settings();
assert.deepEqual(Object.keys(sent).filter(k => !ACCEPTED.has(k)), []);
assert.equal(sent.autonomy_level, 3);
assert.equal(sent.guardrails, 'guarded');
assert.equal(sent.model, undefined, 'an empty model must not become a Claude pick');
assert.equal(sent.build_roles, undefined, 'no role picked: send no build_roles rather than empty ones');

// The dials a person actually set in Build ride along. The route calls the guardrail dial `guardrails`
// where a Build run request calls it `thomas_guardrails`; sending the run-request name is refused by name.
context.window.ThomasUnifiedModes = {
  host: () => ({ getContext: () => ({
    modelId: 'gpt-5.6',
    dials: { effort: 'xhigh', autonomy: 5, fileAccess: 'project', memory: false, guardrails: 'unguarded', tokenEconomy: 'generous' },
    roleModelIds: { build_builder: 'gpt-5.6-terra' },
  }) }),
};
sent = settings();
assert.deepEqual(Object.keys(sent).filter(k => !ACCEPTED.has(k)), []);
assert.equal(sent.model, 'gpt-5.6');
assert.equal(sent.model_id, 'gpt-5.6');
assert.equal(sent.reasoning_effort, 'xhigh');
assert.equal(sent.autonomy_level, 5);
assert.equal(sent.memory, false);
assert.equal(sent.guardrails, 'unguarded');
assert.ok(!('thomas_guardrails' in sent));
// The builder and reviewer picks, shaped as ForgeCodeSettings.from_payload takes them. Without these a
// project started from this panel ignored a model choice Build itself honours.
// Through JSON on purpose: `settings()` runs inside the vm context, so the object it returns has THAT
// context's Object.prototype, and node:assert/strict compares prototypes -- it reported "Values have same
// structure but are not reference-equal" for a value that was right. JSON is also what the panel actually
// sends (`JSON.stringify({ request, settings: settings() })`), so this compares what the route receives.
assert.deepEqual(JSON.parse(JSON.stringify(sent.build_roles)), { builder: { profile: '', model_id: 'gpt-5.6-terra' }, reviewer: null });

// The list GET /api/self/projects answers, which no page read before this one.
const host = { innerHTML: '' };
const dialog = { querySelector: () => host };
let asked = '';
context.fetch = url => {
  asked = url;
  return Promise.resolve({
    ok: true,
    json: async () => ({
      ok: true,
      projects: [
        { conversation_id: 'c1', title: 'Make the Send button blue', state: 'running', detail: 'a Build run is going', changed_files: ['thomas/a.py', 'thomas/b.py'] },
        { conversation_id: 'c2', title: '<script>x</script>', state: 'stopped', detail: 'no Build run is going', changed_files: [] },
      ],
    }),
  });
};
await showProjects(dialog);
assert.equal(asked, '/api/self/projects');
assert.match(host.innerHTML, /Thomas projects right now/);
assert.match(host.innerHTML, /Make the Send button blue/);
assert.match(host.innerHTML, /a Build run is going/);
assert.match(host.innerHTML, /thomas\/a\.py, thomas\/b\.py/);
assert.match(host.innerHTML, /stopped/);
assert.ok(!host.innerHTML.includes('<script>x</script>'), 'a project title is escaped before it is shown');

// Nothing going says so, rather than showing an empty box.
context.fetch = () => Promise.resolve({ ok: true, json: async () => ({ ok: true, projects: [] }) });
await showProjects(dialog);
assert.match(host.innerHTML, /No Thomas project is going right now/);

context.fetch = () => Promise.resolve({ ok: true, json: async () => ({
  ok: true, projects: [], unreadable: ['green/work could not be read (PermissionError: Access is denied)'],
}) });
await showProjects(dialog);
assert.match(host.innerHTML, /could not be read, so this list may be missing some/);
assert.match(host.innerHTML, /Access is denied/);
assert.ok(!host.innerHTML.includes('No Thomas project is going right now'));

// A refusal is shown in the route's own words, and never throws out of the panel.
context.fetch = () => Promise.resolve({ ok: false, json: async () => ({ ok: false, error: 'loopback only' }) });
await showProjects(dialog);
assert.match(host.innerHTML, /loopback only/);
context.fetch = () => Promise.reject(new Error('the server is not answering'));
await showProjects(dialog);
assert.match(host.innerHTML, /the server is not answering/);

console.log('Improve Thomas panel: settings contract and project list checks passed');
