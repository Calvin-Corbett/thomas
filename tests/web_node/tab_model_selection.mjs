import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { installFeature } from './chat_feature_fixture.mjs';

const [htmlPath, helperPath] = process.argv.slice(2);
const helper = fs.readFileSync(helperPath, 'utf8');
const profiles = [{ name: 'local', models: [
  { id: 'one', available: true }, { id: 'two', available: true }, { id: 'blocked', available: false },
] }];

function documentContext(parent) {
  const state = { profile: '', modelId: '', modelLabel: '', dials: {} };
  const wrap = { dataset: {} }, label = { textContent: '' }, patches = [], events = [];
  const context = vm.createContext({
    state, profilesData: structuredClone(profiles),
    document: { querySelector: () => wrap, getElementById: () => label },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    profileModelOptions: profile => profile.models,
    fetch: async (_url, options) => { patches.push(JSON.parse(options.body)); return {ok:true}; },
    persistModelSelection: (...args) => patches.push(args), saveDials() {}, renderModelMenu() {},
  });
  context.window = context;
  context.parent = parent || context;
  context.dispatchEvent = event => events.push(event);
  vm.runInContext(helper, context);
  installFeature(context, htmlPath, 'model_picker', ['setProfile']);
  context.ThomasChatModelSelection.connect({
    getCurrent: () => ({ profile: state.profile, modelId: state.modelId }),
    getProfiles: () => context.profilesData,
    profileModelOptions: context.profileModelOptions,
    setProfile: context.setProfile,
    renderModelMenu: context.renderModelMenu,
  });
  assert.ok(context.ThomasModelSelection, 'The chat page must connect the loaded model bridge');
  return { context, state, wrap, patches, events };
}

const home = documentContext();
vm.runInContext('setProfile(profilesData[0], profilesData[0].models[1])', home.context);
assert.equal(home.state.modelId, 'two');
assert.equal(home.patches.length, 1);
assert.equal(home.events.length, 1);
assert.equal(home.events[0].type, 'thomas:model-selected');
assert.equal(home.wrap.dataset.modelId, 'two');

const child = documentContext(home.context);
// Boot answers with an older persisted choice than the visible browser bar.
vm.runInContext('setProfile(profilesData[0], profilesData[0].models[0], {persist:false})', child.context);
assert.equal(child.state.modelId, 'two');
assert.equal(child.wrap.dataset.modelId, 'two');
assert.equal(child.patches.length, 0);
assert.equal(child.events.length, 0);
assert.equal(child.context.ThomasModelSelection.select('local', 'blocked'), false);
assert.equal(child.context.ThomasModelSelection.select('unknown', 'two'), false);
assert.equal(child.context.ThomasModelSelection.select('local', 'unknown'), false);
assert.equal(child.state.modelId, 'two');
assert.equal(child.patches.length, 0);
assert.equal(home.context.ThomasModelSelection.select('local', 'one'), true);
assert.equal(home.state.modelId, 'one');
assert.equal(home.patches.length, 1);
console.log(JSON.stringify({ checks: 17, boot_matches_global: true, no_mirror_persistence: true }));
