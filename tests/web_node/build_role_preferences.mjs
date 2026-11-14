import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// A behavioral DOM with native-like select/value semantics. Execute the whole
// shipped factory, including its real event listeners and network requests.
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.style = {}; this.attrs = {};
    this.listeners = new Map(); this.textContent = ''; this.disabled = false; this._value = '';
  }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  get value() {
    if (this.tagName !== 'select') return this._value;
    return this.children.some(option => option.value === this._value) ? this._value : '';
  }
  set value(value) { this._value = String(value); }
  get selectedIndex() { return this.children.findIndex(option => option.value === this._value); }
  change(value) { this.value = value; return this.listeners.get('change')(); }
}
const all = node => [node, ...node.children.flatMap(all)];
const select = (root, label) => all(root).find(node => node.attrs['aria-label'] === `Model for ${label}`);
const status = (root, role) => all(root).find(node => node.id === `tc-role-${role}-status`);
const encoded = (profile, model) => `${profile}\u0000${model}`;
const clone = value => JSON.parse(JSON.stringify(value));
const model = (id, available = true) => ({ id, display_name: id, available });
const profiles = [
  { name: 'openai_codex', provider: 'openai_codex', models: [model('gpt-5.6-sol'), model('gpt-5.6-luna'), model('gpt-unavailable', false), model('not-gpt')] },
  { name: 'other-account', provider: 'openai_codex', models: [model('gpt-other-account')] },
  { name: 'openai', provider: 'openai', models: [model('gpt-api-key')] },
  { name: 'anthropic', provider: 'anthropic', models: [model('claude-sonnet')] },
];
let prefs = { role_profiles: { research: 'anthropic' }, role_model_ids: { research: 'claude-sonnet' } };
let nextFailure = '', releaseReadback;
const calls = [];
const context = {
  window: {}, console, Error,
  document: { createElement: tag => new Element(tag), getElementById: () => null },
  fetch: async (url, options = {}) => {
    calls.push({ url, options });
    assert.equal(url, '/api/preferences');
    if (options.method === 'PATCH') {
      if (nextFailure === 'patch') return { ok: false, status: 503 };
      if (nextFailure === 'network') throw new Error('Connection unavailable');
      const incoming = JSON.parse(options.body).advanced.model;
      for (const field of ['role_profiles', 'role_model_ids']) {
        for (const [role, value] of Object.entries(incoming[field])) {
          if (value === null) delete prefs[field][role]; else prefs[field][role] = value;
        }
      }
      return { ok: true };
    }
    assert.equal(options.cache, 'no-store');
    if (nextFailure === 'get') return { ok: false, status: 503 };
    if (nextFailure === 'mismatch') return { ok: true, json: async () => ({ advanced: { model: { role_profiles: {}, role_model_ids: {} } } }) };
    if (nextFailure === 'defer') await new Promise(resolve => { releaseReadback = resolve; });
    return { ok: true, json: async () => ({ advanced: { model: clone(prefs) } }) };
  },
};
vm.createContext(context);
const source = process.argv[2] || 'thomas/server/web/js/chat_model_accounts.js';
vm.runInContext(fs.readFileSync(source, 'utf8'), context, { filename: source });
const state = { profile: 'openai_codex', modelId: 'gpt-5.6-sol',
  roleProfiles: clone(prefs.role_profiles), roleModelIds: clone(prefs.role_model_ids) };
const deps = { state, profilesData: profiles, profileIsUsable: () => true,
  profileModelOptions: profile => profile.models };
const accounts = context.window.ThomasChatModelAccounts.create(deps);
const render = () => { const root = new Element('div'); accounts.renderSpecialistModels(root); return root; };
let root = render();
const labels = all(root).filter(node => node.tagName === 'select').map(node => node.attrs['aria-label']).filter(label => label.startsWith('Model for'));
assert.deepEqual(labels, ['Reasoning', 'Coding', 'Research', 'Tools', 'Writing', 'Data', 'Build builders', 'Build reviewers'].map(label => `Model for ${label}`));
assert.ok(all(root).some(node => node.textContent.includes('Task manager uses the model chosen in Models. Saved defaults for new Build runs.')));
for (const label of ['Build builders', 'Build reviewers']) {
  assert.equal(select(root, label).children[0].textContent, 'Use the default');
}
// Builders run only connected GPT models; reviewers may use any connected one.
assert.deepEqual(select(root, 'Build builders').children.map(option => option.value), ['', encoded('openai_codex', 'gpt-5.6-sol'), encoded('openai_codex', 'gpt-5.6-luna')]);
assert.ok(select(root, 'Build reviewers').children.some(option => option.value === encoded('anthropic', 'claude-sonnet')));
assert.ok(select(root, 'Research').children.some(option => option.value === encoded('anthropic', 'claude-sonnet')));
assert.equal(select(root, 'Research').children[0].textContent, 'Use the default');

// Saving does not update the current state until the actual GET readback.
nextFailure = 'defer';
const oldProfiles = state.roleProfiles, oldModels = state.roleModelIds;
const pending = select(root, 'Build builders').change(encoded('openai_codex', 'gpt-5.6-luna'));
await new Promise(resolve => setImmediate(resolve));
assert.equal(state.roleModelIds.build_builder, undefined);
assert.equal(select(root, 'Build builders').disabled, true);
assert.equal(status(root, 'build_builder').textContent, 'Saving…');
assert.equal(calls[0].options.method, 'PATCH');
assert.equal(calls[1].options.method, undefined);
// Reopening the model menu during a save keeps the current row disabled, then
// receives the saved result rather than leaving a detached row as the owner.
root = render();
assert.equal(select(root, 'Build builders').disabled, true);
releaseReadback(); await pending; nextFailure = '';
assert.equal(state.roleModelIds.build_builder, 'gpt-5.6-luna');
assert.notEqual(state.roleProfiles, oldProfiles);
assert.notEqual(state.roleModelIds, oldModels);
assert.equal(oldModels.build_builder, undefined);
assert.equal(status(root, 'build_builder').textContent, 'Saved');
assert.equal(select(root, 'Build builders').value, encoded('openai_codex', 'gpt-5.6-luna'));
assert.equal(select(root, 'Build builders').disabled, false);
assert.equal(state.modelId, 'gpt-5.6-sol', 'A helper preference must not change the task manager');
assert.equal(state.roleModelIds.research, 'claude-sonnet');

for (const failure of ['patch', 'network', 'get', 'mismatch']) {
  nextFailure = failure;
  const confirmed = state.roleModelIds;
  await select(root, 'Build builders').change(encoded('openai_codex', 'gpt-5.6-sol'));
  assert.equal(state.roleModelIds, confirmed, `${failure}: failed confirmation cannot mutate state`);
  assert.equal(select(root, 'Build builders').value, encoded('openai_codex', 'gpt-5.6-luna'));
  assert.notEqual(status(root, 'build_builder').textContent, 'Saved');
  assert.ok(status(root, 'build_builder').textContent.length > 0);
  assert.equal(select(root, 'Build builders').disabled, false);
}
nextFailure = '';
await select(root, 'Build builders').change(encoded('openai_codex', 'gpt-5.6-luna'));
await select(root, 'Build reviewers').change(encoded('openai_codex', 'gpt-5.6-sol'));
assert.equal(state.roleModelIds.build_reviewer, 'gpt-5.6-sol');
assert.equal(state.roleModelIds.build_builder, 'gpt-5.6-luna');
root = render();
assert.equal(select(root, 'Build reviewers').value, encoded('openai_codex', 'gpt-5.6-sol'));
await select(root, 'Build builders').change('');
const clear = JSON.parse(calls.at(-2).options.body).advanced.model;
assert.equal(clear.role_profiles.build_builder, null);
assert.equal(clear.role_model_ids.build_builder, null);
assert.equal(state.roleModelIds.build_builder, undefined);
assert.equal(state.roleModelIds.build_reviewer, 'gpt-5.6-sol');
assert.equal(state.roleModelIds.research, 'claude-sonnet');

// A stale stored override stays visible and clearable, rather than masquerading
// as inheritance. Build rows remain available even with no usable GPT catalog.
state.roleProfiles = { ...state.roleProfiles, build_builder: 'other-account' };
state.roleModelIds = { ...state.roleModelIds, build_builder: 'gpt-other-account' };
deps.profilesData = [];
root = render();
assert.equal(select(root, 'Build builders').value, encoded('other-account', 'gpt-other-account'));
assert.match(select(root, 'Build builders').children.at(-1).textContent, /Unavailable saved model/);
assert.equal(select(root, 'Build builders').children.at(-1).disabled, true);
await select(root, 'Build builders').change('');
assert.equal(state.roleModelIds.build_builder, undefined);
assert.equal(select(root, 'Build builders').value, '');
assert.equal(state.modelId, 'gpt-5.6-sol');
console.log('Build role filtering, confirmed persistence, failure recovery, clear, menu reopen and manager identity passed');

// The Advanced table has no Agent column: the model is the only choice for each job.
{
  const view = render();
  const agentCells = all(view).filter(node => String((node.attrs || {})['aria-label'] || '').startsWith('Agent for'));
  assert.equal(agentCells.length, 0);
  console.log('Advanced table has no agent column passed');
}
