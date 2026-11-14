import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const [projectsPath, lifecyclePath, codePath] = process.argv.slice(2);
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function reconnectFixture(search = '') {
  const status = deferred(), conversation = deferred();
  const state = { activeId: '', contextEpoch: 0, running: false, finishing: false };
  const stored = new Map([['thomas.lastSurface', JSON.stringify({ mode: 'code', codeConversationId: 'old-A' })]]);
  const localStorage = { getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value) };
  const window = { localStorage, location: { search }, ThomasUnifiedModes: { mode: () => 'code' } };
  const box = { window, localStorage, document: { readyState: 'loading', addEventListener() {} },
    fetch: async () => ({ json: () => status.promise }), setTimeout, clearTimeout, console };
  vm.createContext(box);
  vm.runInContext(fs.readFileSync(lifecyclePath, 'utf8'), box);
  vm.runInContext(fs.readFileSync(projectsPath, 'utf8'), box);
  window.ThomasCodeProjects.configure({ state });
  let loads = 0, streams = 0;
  const session = window.ThomasCodeProjects.createTaskSession({
    lifecycle: () => window.ThomasCodeLifecycle, host: () => ({ setBusy() {} }),
    render() {}, pushLiveEvent() {}, openStream() { streams++; },
    async loadConversation(id) {
      loads++;
      const epoch = ++state.contextEpoch;
      await conversation.promise;
      if (epoch !== state.contextEpoch) return false;
      state.activeId = id; state.running = true; streams++;
      return true;
    },
  });
  return { state, status, conversation, session, counts: () => ({ loads, streams }) };
}
const oldStatus = { running: true, run_id: 'run-old-A', session: { conversation_id: 'old-A' } };
const stale = reconnectFixture();
const staleAdoption = stale.session.adoptOrphanRun();
stale.state.contextEpoch++; // A requested task begins loading before /status responds.
stale.status.resolve(oldStatus);
await tick(); stale.conversation.resolve();
assert.equal(await staleAdoption, false);
assert.equal(stale.counts().loads, 0, 'Background reconnect cannot override an explicit pending selection');

const reconnecting = reconnectFixture();
const reconnected = reconnecting.session.adoptOrphanRun();
reconnecting.status.resolve(oldStatus);
await tick();
reconnecting.conversation.resolve();
assert.equal(await reconnected, true);
assert.equal(reconnecting.counts().streams, 1, 'The conversation loader owns reattachment; do not duplicate the stream');

// A Build tab the browser shell opened for a NEW build must stay new while another tab's run is going. The stored
// snapshot is shared by every tab, so it named the running build, and each New build pressed during a run opened
// one more tab showing that same run instead of an empty build.
const freshTab = reconnectFixture('?tc_doc=1&tab_mode=code');
const freshAdoption = freshTab.session.adoptOrphanRun();
freshTab.status.resolve(oldStatus);
await tick(); freshTab.conversation.resolve();
assert.equal(await freshAdoption, false, 'a new Build tab does not adopt the run another tab is on');
assert.equal(freshTab.counts().loads, 0);
// A tab that carries its own conversation is reopened by the shell, and a page outside the shell still reattaches.
const ownTab = reconnectFixture('?tc_doc=1&tab_mode=code&forge_code=old-A');
const ownAdoption = ownTab.session.adoptOrphanRun();
ownTab.status.resolve(oldStatus);
await tick(); ownTab.conversation.resolve();
assert.equal(await ownAdoption, true, 'a reload of the tab that was on the run still reattaches');

const superseded = reconnectFixture();
const supersededAdoption = superseded.session.adoptOrphanRun();
superseded.status.resolve(oldStatus);
await tick();
superseded.state.contextEpoch++;
superseded.state.activeId = 'requested-B';
superseded.conversation.resolve();
assert.equal(await supersededAdoption, false);
assert.equal(superseded.state.activeId, 'requested-B');
assert.equal(superseded.state.running, false);

for (const beginNewRun of [false, true]) {
  const selected = reconnectFixture();
  selected.state.activeId = 'old-A';
  const attaching = selected.session.reattachRunFor('old-A');
  if (beginNewRun) { selected.state.running = true; selected.state.runId = 'new-run'; }
  else selected.state.contextEpoch++; // activeId stays old until the new load resolves.
  selected.status.resolve(oldStatus);
  assert.equal(await attaching, false);
  assert.equal(selected.counts().streams, 0, 'A delayed per-task status cannot seize a new selection or run');
  if (beginNewRun) assert.equal(selected.state.runId, 'new-run');
}

// A selected Build's transcript must be usable while its file tree is pending.
const codeSource = fs.readFileSync(codePath, 'utf8');
const loadSource = codeSource.slice(codeSource.indexOf('  async function loadConversation('), codeSource.indexOf('  async function send('));
for (const switchAgain of [false, true]) {
  const tree = deferred();
  let renders = 0, reconnects = 0, queues = 0;
  const state = { contextEpoch: 0, activeId: '', running: false };
  const box = { state, canSwitchContext: () => true, clearContextState() {}, encodeURIComponent,
    fetch: async () => ({ ok: true, json: async () => ({ ok: true, conversation: { project_root: '/task' } }) }),
    codeProjects: () => ({ updateProjectButton() {} }),
    lifecycle: () => ({ contextToken: s => ({ epoch: s.contextEpoch, id: s.activeId }),
      contextMatches: (s,t) => s.contextEpoch === t.epoch && s.activeId === t.id }),
    loadChanges: () => tree.promise, loadTree: () => tree.promise,
    render: () => { renders++; }, scrollTranscriptToNewest() {},
    codeResults: () => ({ hydrateArtifactThumbnails: async () => {} }), host: () => ({ renderHistory() {} }),
    reattachRunFor: async () => { reconnects++; }, startNextQueued: () => { queues++; },
  };
  vm.createContext(box); vm.runInContext(loadSource + '\nthis.open = loadConversation;', box);
  const loading = box.open('A');
  await tick();
  assert.equal(renders, 2, 'Build should render opening feedback and then its conversation before slow file/tree responses');
  assert.equal(reconnects, 1, 'Reconnect must not wait behind file discovery');
  if (switchAgain) { state.contextEpoch++; state.activeId = 'B'; }
  const before = renders;
  tree.resolve();
  assert.equal(await loading, !switchAgain);
  assert.equal(queues, switchAgain ? 0 : 1, 'Old selection must not start the new selection queue');
  if (switchAgain) assert.equal(renders, before, 'Late file responses must not repaint a newer task');
}

// The click itself must replace the empty state before a slow conversation fetch answers.
{
  const waiting = deferred();
  const state = { contextEpoch: 0, activeId: '', openingConversationId: '' };
  let openingRender = false;
  const box = { state, canSwitchContext: () => true, clearContextState() { state.activeId = ''; },
    encodeURIComponent, fetch: () => waiting.promise,
    codeProjects: () => ({ updateProjectButton() {} }), lifecycle: () => ({ contextToken: s => ({ epoch: s.contextEpoch, id: s.activeId }), contextMatches: (s, token) => s.contextEpoch === token.epoch && s.activeId === token.id }),
    loadChanges: async () => {}, loadTree: async () => {},
    render() { if (state.openingConversationId === 'A') openingRender = true; }, scrollTranscriptToNewest() {},
    codeResults: () => ({ hydrateArtifactThumbnails: async () => {} }), host: () => ({ renderHistory() {} }),
    reattachRunFor: async () => {}, startNextQueued: () => {},
  };
  vm.createContext(box); vm.runInContext(loadSource + '\nthis.open = loadConversation;', box);
  const loading = box.open('A');
  assert.equal(openingRender, true, 'Opening feedback renders before the conversation request resolves');
  waiting.resolve({ ok: true, json: async () => ({ ok: true, conversation: { project_root: '/task' } }) });
  assert.equal(await loading, true);
  assert.equal(state.openingConversationId, '', 'Opening feedback clears once the conversation arrives');
}

console.log(JSON.stringify({ stale_status_does_not_select: true, reconnect_has_one_stream: true, late_load_does_not_replace_selection: true, per_task_status_respects_epoch: true, per_task_status_respects_new_run: true, transcript_precedes_slow_tree: true, reconnect_starts_with_discovery: true, late_tree_does_not_render_or_start_queue: true }));
