// Exercise the shipped boot module and its actual chat.html wiring with slow IO.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const [modulePath, htmlPath] = process.argv.slice(2);
const source = fs.readFileSync(modulePath, 'utf8');
const html = fs.readFileSync(htmlPath, 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const checks = [];
async function check(name, run) { await run(); checks.push(name); }

function fixture(search = '', mode = 'chat') {
  const model = deferred(), history = deferred(), hydration = deferred();
  const state = { messages: [], sessionId: null, input: '', docs: [], images: [], streaming: false,
    surfaceMode: mode, profile: '', modelId: '' };
  const calls = [], warnings = [], posts = [];
  const win = { location: { search, origin: 'http://127.0.0.1:8899' }, parent: { postMessage: (...args) => posts.push(args) } };
  const context = { window: win, URLSearchParams, console: { warn: (...args) => warnings.push(args) } };
  vm.createContext(context); vm.runInContext(source, context);
  let profiles = [], current = true, input = '', stored = { thomas_last_chat: 'other', thomas_last_session: 'session-other' };
  const rows = [{ id: 'other', sessionId: 'session-other' }, { id: 'chosen', sessionId: 'session-chosen' }];
  const deps = {
    state, search, getMode: () => state.surfaceMode, getInput: () => input,
    captureConversation: () => () => current,
    storage: { getItem: key => { calls.push('storage:' + key); return stored[key]; } },
    fetch: url => { calls.push(url); return model.promise; },
    getProfiles: () => profiles, setProfiles: value => { profiles = value; },
    hydrateProfileModels: () => hydration.promise,
    setProfile: (profile, option, options) => { calls.push('profile:' + profile.name); state.profile = profile.name; state.modelId = option?.id || profile.model; if(option&&options?.persist!==false)calls.push('persist-model'); },
    renderModelMenu: () => calls.push('menu'),
    refreshChats: () => { calls.push('history'); return history.promise; }, getChats: () => rows,
    selectChat: id => { calls.push('select:' + id); state.sessionId = rows.find(row => row.id === id).sessionId; },
    ensureSession: async () => { calls.push('session'); state.sessionId = 'fresh'; },
  };
  return { context, api: win.ThomasChatBoot, state, calls, warnings, posts, deps, model, history, hydration,
    loseOwnership: () => { current = false; }, type: value => { input = value; }, setStored: value => { stored = value; },
    models(data = { profiles: [{ name: 'openai_codex', provider: 'openai_codex', model: 'gpt-test' }], default: 'openai_codex' }) {
      model.resolve({ ok: true, json: async () => data }); hydration.resolve();
    },
  };
}

await check('Chat history starts and restores while provider metadata is still pending', async () => {
  const f = fixture(), boot = f.api.start(f.deps);
  assert.deepEqual(f.calls, ['/api/models', 'history']);
  f.history.resolve(); await boot.chat;
  assert.ok(f.calls.includes('select:other'));
  assert.equal(f.state.profile, '');
  f.models(); await boot.ready;
  assert.equal(f.state.profile, 'openai_codex');
});
for (const mode of ['code', 'work']) {
  await check(mode + ' child does not request Chat history, create Chat session, or read global restore', async () => {
    const f = fixture('?tab_mode=' + mode, mode), boot = f.api.start(f.deps);
    await boot.chat;
    assert.deepEqual(f.calls, ['/api/models']);
    f.models(); await boot.ready;
    assert.equal(f.state.sessionId, null);
  });
}
await check('ordinary top-level Build deep link also skips Chat initialization', async () => {
  const f = fixture('?forge_code=saved-build', 'code'), boot = f.api.start(f.deps);
  await boot.chat; assert.deepEqual(f.calls, ['/api/models']); f.models(); await boot.ready;
});
for (const search of ['?tab_mode=chat', '?tab_mode=chat&tab_chat=', '?tab_mode=chat&tab_chat=missing']) {
  await check('fresh or missing child selection never restores another global chat: ' + search, async () => {
    const f = fixture(search), boot = f.api.start(f.deps);
    f.history.resolve(); await boot.chat;
    assert.equal(f.state.sessionId, 'fresh');
    assert.ok(!f.calls.some(call => call.startsWith('storage:') || call.startsWith('select:')));
    f.models(); await boot.ready;
  });
}
await check('explicit child history selects only its requested chat', async () => {
  const f = fixture('?tab_mode=chat&tab_chat=chosen'), boot = f.api.start(f.deps);
  f.history.resolve(); await boot.chat;
  assert.equal(f.state.sessionId, 'session-chosen');
  assert.ok(!f.calls.some(call => call.startsWith('storage:')));
  f.models(); await boot.ready;
});
await check('ordinary reload still falls back to saved session id', async () => {
  const f = fixture(); f.setStored({ thomas_last_session: 'session-chosen' });
  const boot = f.api.start(f.deps); f.history.resolve(); await boot.chat;
  assert.equal(f.state.sessionId, 'session-chosen'); f.models(); await boot.ready;
});
await check('invalid tab mode does not opt into child restore rules', async () => {
  const f = fixture('?tab_mode=arbitrary&tab_chat=chosen'), boot = f.api.start(f.deps);
  f.history.resolve(); await boot.chat;
  assert.equal(f.state.sessionId, 'session-other'); f.models(); await boot.ready;
});
for (const [name, interact] of [
  ['typed draft', f => f.type('new draft')], ['state draft', f => { f.state.input = 'new'; }],
  ['new reply', f => f.state.messages.push({ text: 'new' })], ['new session', f => { f.state.sessionId = 'new'; }],
  ['streaming turn', f => { f.state.streaming = true; }], ['selected conversation', f => f.loseOwnership()],
  ['attached document', f => f.state.docs.push({ name: 'draft.txt' })], ['attached image', f => f.state.images.push({ name: 'draft.png' })],
  ['changed mode', f => { f.state.surfaceMode = 'work'; }],
]) {
  await check('late history cannot clobber ' + name, async () => {
    const f = fixture(), boot = f.api.start(f.deps); interact(f); f.history.resolve(); await boot.chat;
    assert.ok(!f.calls.some(call => call.startsWith('select:') || call === 'session'));
    f.models(); await boot.ready;
  });
}
await check('late model metadata preserves manual model and role choices', async () => {
  const f = fixture('?tab_mode=work', 'work'), boot = f.api.start(f.deps);
  f.state.profile = 'manual'; f.state.modelId = 'picked';
  f.state.roleProfiles = { coder: 'manual' }; f.state.roleModelIds = { coder: 'picked' };
  f.models(); await boot.ready;
  assert.equal(f.state.profile, 'manual'); assert.equal(f.state.modelId, 'picked');
  assert.equal(f.state.roleProfiles.coder, 'manual'); assert.equal(f.state.roleModelIds.coder, 'picked');
  assert.ok(f.calls.includes('menu'));
});
await check('configured model lookup remains case insensitive and requires usable profile', async () => {
  const f = fixture('?tab_mode=work', 'work'), boot = f.api.start(f.deps);
  f.models({ profiles: [{ name: 'keyless', provider: 'anthropic' }, { name: 'local', model: 'local-test' }],
    preferences: { active_profile: 'LOCAL', role_profiles: { coder: 'local' } } });
  await boot.ready; assert.equal(f.state.profile, 'local'); assert.equal(f.state.roleProfiles.coder, 'local');
});
await check('reload restores the saved available model without writing the default back', async () => {
  const f = fixture('?tab_mode=code', 'code'), boot = f.api.start(f.deps);
  f.models({profiles:[{name:'openai_codex',provider:'openai_codex',model:'default-model',
    models:[{id:'default-model',is_default:true},{id:'saved-model',available:true}]}],
    preferences:{active_profile:'openai_codex',model_id:'saved-model'}});
  await boot.ready;
  assert.equal(f.state.modelId,'saved-model');
  assert.ok(!f.calls.includes('persist-model'));
});
await check('a saved model cannot be borrowed from a different fallback provider', async () => {
  const f = fixture('?tab_mode=code', 'code'), boot = f.api.start(f.deps);
  f.models({profiles:[{name:'local',model:'local-default',models:[{id:'saved-model',available:true}]}],
    preferences:{active_profile:'missing',model_id:'saved-model'}});
  await boot.ready;assert.equal(f.state.modelId,'local-default');
});
await check('an unavailable saved model is never selected as available', async () => {
  const f = fixture('?tab_mode=code', 'code'), boot = f.api.start(f.deps);
  f.models({profiles:[{name:'local',model:'available-model',models:[{id:'old-model',available:false}]}],
    preferences:{active_profile:'local',model_id:'old-model'}});
  await boot.ready;assert.equal(f.state.modelId,'available-model');
});
await check('unavailable model metadata neither blocks history nor fabricates a selection', async () => {
  const f = fixture(), boot = f.api.start(f.deps);
  f.model.reject(new Error('offline')); f.history.resolve(); await boot.ready;
  assert.equal(f.state.profile, ''); assert.equal(f.state.sessionId, 'session-other'); assert.equal(f.warnings.length, 1);
});
await check('surface-ready targets own origin before any remote boot work settles', async () => {
  const f = fixture('?tab_mode=work', 'work'), boot = f.api.start(f.deps);
  assert.equal(f.api.notifyReady(), true);
  assert.equal(f.posts[0][0].type, 'thomas:surface-ready'); assert.equal(f.posts[0][1], 'http://127.0.0.1:8899');
  f.context.window.parent = f.context.window; assert.equal(f.api.notifyReady(), false);
  assert.equal(f.posts.length, 1); f.models(); await boot.ready;
});
await check('live HTML registers exactly one helper and signals after synchronous init', async () => {
  assert.equal((html.match(/src="\/static\/js\/chat_boot\.js\?/g) || []).length, 1);
  assert.ok(html.includes('return window.ThomasChatBoot.start({'));
  const ready = html.indexOf('    window.ThomasChatBoot.notifyReady();');
  assert.ok(ready > html.lastIndexOf('    renderAttachments();'));
  assert.ok(ready < html.lastIndexOf('    mountBuildBadge();'));
  assert.ok(ready < html.lastIndexOf('    boot();'));
});

await check('newer saved session wins over a stale history selection on reload', async () => {
  const f = fixture();
  f.setStored({ thomas_last_chat: 'other', thomas_last_session: 'session-chosen' });
  const boot = f.api.start(f.deps); f.history.resolve(); await boot.chat;
  assert.equal(f.state.sessionId, 'session-chosen');
  assert.ok(!f.calls.includes('select:other')); f.models(); await boot.ready;
});
await check('legacy cold start still restores a chat when no session key exists', async () => {
  const f = fixture(); f.setStored({ thomas_last_chat: 'chosen' });
  const boot = f.api.start(f.deps); f.history.resolve(); await boot.chat;
  assert.equal(f.state.sessionId, 'session-chosen'); f.models(); await boot.ready;
});
await check('missing cold start targets allocate a fresh session', async () => {
  const f = fixture(); f.setStored({ thomas_last_chat: 'deleted', thomas_last_session: 'deleted-session' });
  const boot = f.api.start(f.deps); f.history.resolve(); await boot.chat;
  assert.equal(f.state.sessionId, 'fresh'); f.models(); await boot.ready;
});
await check('a Claude-plan selection survives a reload, with no key to its name', async () => {
  const f = fixture(), boot = f.api.start(f.deps);
  f.models({ profiles: [
      { name: 'anthropic', provider: 'anthropic', model: 'sonnet', claude_plan: true,
        models: [{ id: 'sonnet', available: true }] },
      { name: 'local', model: 'local-test' }],
    preferences: { active_profile: 'anthropic', model_id: 'sonnet' } });
  f.history.resolve(); await boot.ready;
  assert.equal(f.state.profile, 'anthropic');
  assert.equal(f.state.modelId, 'sonnet');
  assert.ok(!f.calls.includes('persist-model'));
});
console.log(JSON.stringify({ passed: checks.length, checks }));
