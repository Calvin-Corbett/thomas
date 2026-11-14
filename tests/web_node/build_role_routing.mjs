import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const web = process.argv[2];
const copy = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const prefs = (builder = 'gpt-luna') => ({
  role_profiles: { build_builder: 'openai_codex', build_reviewer: 'openai_codex' },
  role_model_ids: { build_builder: builder, build_reviewer: 'gpt-sol' },
});
const checks = [];
async function check(name, run) { await run(); checks.push(name); }

function fixture(parent) {
  const events = new Map(), state = { profile: 'openai_codex', modelId: 'gpt-sol', dials: {},
    messages: [], docs: [], images: [], input: '', streaming: false };
  const models = [{ name: 'openai_codex', provider: 'openai_codex', models: [{ id: 'gpt-sol', available: true }] }];
  const context = vm.createContext({ console, URLSearchParams, setTimeout, clearTimeout,
    location: { search: '' },
    document: { querySelector: () => null, querySelectorAll: () => [], getElementById: () => null },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    addEventListener(type, fn) { if (!events.has(type)) events.set(type, new Set()); events.get(type).add(fn); },
    removeEventListener(type, fn) { events.get(type)?.delete(fn); },
    dispatchEvent(event) { for (const fn of events.get(event.type) || []) fn(event); },
  });
  context.window = context; context.parent = parent?.context || context;
  function load(name) { vm.runInContext(fs.readFileSync(path.join(web, 'js', name), 'utf8'), context, { filename: name }); }
  load('chat_model_selection.js');
  const bridge = context.ThomasChatModelSelection;
  bridge.connect({ state, getCurrent: () => ({ profile: state.profile, modelId: state.modelId }),
    getProfiles: () => models, profileModelOptions: p => p.models,
    setProfile() {}, renderModelMenu() {},
  });
  return { context, state, models, bridge, load, events };
}

async function composer(f) {
  f.load('unified_mode_shell.js'); f.load('unified_code_lifecycle.js'); f.load('chat_stream_actions.js');
  const contexts = [], requests = [], buildState = { activeId: 'build', projectRoot: '/project' };
  f.context.ThomasUnifiedModes.connect({});
  f.context.ThomasUnifiedModes.registerAdapter('code', {
    send(text, context) {
      contexts.push(context);
      requests.push(f.context.ThomasCodeLifecycle.runRequest(buildState, text, context));
    },
  });
  await f.context.ThomasUnifiedModes.setMode('code');
  const deps = { state: f.state, inputEl: { value: '', setCustomValidity() {} },
    attachmentsReady: () => true, renderAttachments() {}, autosize() {}, syncDynamic() {}, reportFriction() {},
  };
  const actions = f.context.ThomasChatStreamActions.create(deps);
  return { contexts, requests, buildState, send(text) { f.state.input = text; actions.send(); } };
}

await check('unloaded maps are omitted through the real composer and shell', async () => {
  const f = fixture(), c = await composer(f);
  f.state.roleProfiles = {}; f.state.roleModelIds = {};
  c.send('Build a game');
  assert.equal(c.requests.length, 1);
  assert.equal(c.requests[0].build_roles, undefined);
  assert.equal(c.requests[0].model_id, 'gpt-sol');
});

await check('confirmed roles reach requests and a changed choice creates a new retry identity', async () => {
  const f = fixture(); f.bridge.loadRoles(prefs()); const c = await composer(f);
  c.send('Build a game');
  assert.deepEqual(copy(c.requests[0].build_roles), {
    builder: { profile: 'openai_codex', model_id: 'gpt-luna' },
    reviewer: { profile: 'openai_codex', model_id: 'gpt-sol' },
  });
  c.buildState.retryRequest = c.requests[0];
  c.send('Build a game');
  assert.equal(c.requests[1].request_id, c.requests[0].request_id);
  f.bridge.roleSaved('build_builder', 'openai_codex', 'gpt-terra');
  c.send('Build a game');
  assert.notEqual(c.requests[2].request_id, c.requests[0].request_id);
  assert.equal(c.requests[2].build_roles.builder.model_id, 'gpt-terra');
  assert.equal(c.contexts[0].roleModelIds.build_builder, 'gpt-luna', 'A parked/queued context is a copy');
});

await check('saved preferences load before a slow provider catalog', async () => {
  const f = fixture(), metadata = deferred(), catalog = deferred(); f.load('chat_boot.js');
  const work = f.context.ThomasChatBoot.loadModels({ state: f.state, fetch: () => metadata.promise,
    setProfiles() {}, getProfiles: () => f.models, hydrateProfileModels: () => catalog.promise,
    setProfile() {}, renderModelMenu() {},
  });
  assert.deepEqual(copy(f.bridge.roleContext()), {});
  metadata.resolve({ ok: true, json: async () => ({ profiles: f.models, preferences: prefs() }) });
  await tick();
  assert.equal(f.bridge.roleContext().roleModelIds.build_builder, 'gpt-luna');
  const c = await composer(f); c.send('Before the slow catalog');
  assert.equal(c.requests[0].build_roles.builder.model_id, 'gpt-luna');
  catalog.resolve(); await work;
});

await check('confirmed per-role writes update open and late tabs without clobbering other roles', async () => {
  const home = fixture(); home.bridge.loadRoles(prefs());
  const first = fixture(home), second = fixture(home);
  first.bridge.loadRoles(prefs()); second.bridge.loadRoles(prefs());
  const c = await composer(first);
  home.bridge.roleSaved('build_builder', 'openai_codex', 'gpt-terra');
  second.bridge.roleSaved('build_reviewer', 'openai_codex', 'gpt-review');
  assert.equal(first.state.roleModelIds.build_builder, 'gpt-terra');
  assert.equal(home.state.roleModelIds.build_reviewer, 'gpt-review');
  c.send('Fresh run');
  assert.equal(c.requests[0].build_roles.builder.model_id, 'gpt-terra');
  assert.equal(c.requests[0].build_roles.reviewer.model_id, 'gpt-review');
  const late = fixture(home); late.bridge.loadRoles(prefs('gpt-old'));
  assert.equal(late.bridge.roleContext().roleModelIds.build_builder, 'gpt-terra');
  home.bridge.roleSaved('build_builder', '', '');
  c.send('Inherit manager');
  assert.equal(c.requests[1].build_roles.builder, null);
  assert.equal(c.requests[1].build_roles.reviewer.model_id, 'gpt-review');
  first.context.dispatchEvent({ type: 'pagehide' });
  assert.equal(home.events.get('thomas:role-model-saved').size, 3, 'Closed document releases its parent listener');
});

await check('a confirmed save during boot survives stale data and keeps other saved defaults', async () => {
  const home = fixture(), child = fixture(home);
  child.bridge.roleSaved('build_builder', 'openai_codex', 'gpt-new');
  home.bridge.loadRoles(prefs('gpt-stale')); child.bridge.loadRoles(prefs('gpt-stale'));
  assert.equal(home.state.roleModelIds.build_builder, 'gpt-new');
  assert.equal(home.state.roleModelIds.build_reviewer, 'gpt-sol');
  assert.equal(child.bridge.roleContext().roleModelIds.build_builder, 'gpt-new');
});

await check('only a confirmed preferences readback reaches the shared bridge', async () => {
  const f = fixture(); f.bridge.loadRoles(prefs()); f.load('chat_model_accounts.js');
  const child = fixture(f); child.bridge.loadRoles(prefs());
  let accepted = false;
  f.context.fetch = async (_url, options) => options?.method === 'PATCH'
    ? { ok: accepted } : { ok: true, json: async () => ({ advanced: { model: prefs('gpt-new') } }) };
  const accounts = f.context.ThomasChatModelAccounts.create({ state: f.state });
  await assert.rejects(() => accounts.persistRoleModel('build_builder', 'openai_codex', 'gpt-new'));
  assert.equal(child.state.roleModelIds.build_builder, 'gpt-luna');
  accepted = true;
  await accounts.persistRoleModel('build_builder', 'openai_codex', 'gpt-new');
  assert.equal(child.state.roleModelIds.build_builder, 'gpt-new');
});

console.log(JSON.stringify({ passed: checks.length, checks }));
