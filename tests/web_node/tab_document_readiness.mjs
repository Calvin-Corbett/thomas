import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const [modePath, docsPath, policyPath, workPath, codePath] = process.argv.slice(2);
const tick = () => new Promise(resolve => setImmediate(resolve));
function classes() {
  const values = new Set();
  return { add: x => values.add(x), remove: x => values.delete(x), contains: x => values.has(x),
    toggle(x, on) { if (on) values.add(x); else values.delete(x); } };
}
function modeFixture(search = '') {
  const buttons = ['chat', 'code', 'work'].map(mode => ({ dataset: { thomasMode: mode },
    classList: classes(), setAttribute() {}, removeAttribute() {}, addEventListener() {}, focus() {} }));
  const elements = new Map(['tc-shell', 'tc-history-label', 'tc-search', 'tc-newchat', 'tc-input', 'tc-mode-surface']
    .map(id => [id, { dataset: {}, focus() {} }]));
  const sandbox = { window: {}, location: { search }, URLSearchParams, document: {
    getElementById: id => elements.get(id), querySelectorAll: () => buttons, querySelector: () => null,
  }};
  vm.runInNewContext(fs.readFileSync(modePath, 'utf8'), sandbox);
  return sandbox.window.ThomasUnifiedModes;
}

const modes = modeFixture();
let releaseHistory;
const slowHistory = new Promise(resolve => { releaseHistory = resolve; });
let codeRefreshes = 0, workRefreshes = 0, codeLeaves = 0, codeBusy = true;
const notices = [];
modes.registerAdapter('code', { enter() {}, leave() { codeLeaves++; },
  refresh() { codeRefreshes++; return slowHistory; }, isBusy: () => codeBusy });
modes.registerAdapter('work', { enter() {}, leave() {},
  refresh() { workRefreshes++; return slowHistory; } });
modes.connect({ renderHistory() {}, modeChanged() {}, announce: text => notices.push(text) });
let entered = false;
const opening = modes.setMode('code').then(value => { entered = value; });
await tick();
assert.equal(entered, true, 'Build display must not wait for its history response');
assert.equal(codeRefreshes, 1, 'One transition starts one history refresh');
assert.equal(await modes.setMode('work'), true, 'A slow Build refresh must not queue-block Work');
assert.equal(await modes.setMode('chat'), true, 'A slow Work refresh must not queue-block Chat');
assert.equal(workRefreshes, 1);
assert.equal(codeLeaves, 1);
assert.equal(codeBusy, true, 'Presentation changes must not cancel the running build');
releaseHistory();
await opening;
await tick();
assert.equal(modes.mode(), 'chat', 'Late history cannot switch back or restore focus to an old mode');
assert.deepEqual(notices, []);
modes.registerAdapter('work', { enter() {}, refresh() { throw new Error('offline'); } });
await modes.setMode('work');
await tick();
assert.equal(modes.mode(), 'work', 'A refresh error must leave the usable Work surface open');
assert.equal(notices.length, 1, 'Active background failures must still be reported');

// Re-selecting Build while its outgoing transition is leaving must reactivate
// its adapter. The mode label can still say code after leave() has disabled it.
const interrupted = modeFixture();
let activeBuild = false, resolveLeave;
const pendingLeave = new Promise(resolve => { resolveLeave = resolve; });
let buildEntries = 0, buildExits = 0;
interrupted.registerAdapter('code', {
  enter() { activeBuild = true; buildEntries++; },
  async leave() { activeBuild = false; buildExits++; await pendingLeave; },
  refresh() {},
});
interrupted.registerAdapter('work', { enter() {}, leave() {}, refresh() {} });
interrupted.connect({});
await interrupted.setMode('code');
const departing = interrupted.setMode('work');
await tick();
assert.equal(activeBuild, false, 'The fixture must interrupt after Build leaves');
const returning = interrupted.setMode('code');
resolveLeave();
await Promise.all([departing, returning]);
assert.equal(interrupted.mode(), 'code');
assert.equal(activeBuild, true, 'Re-selecting Build left its displayed adapter inactive');
assert.equal(buildEntries, 2, 'Returning to the departed mode must re-enter it');
assert.equal(buildExits, 1, 'An already departed adapter must not leave twice');

// If both the destination and rollback fail, clicking the original mode is
// a real retry; its unchanged heading must not suppress adapter activation.
const recovery = modeFixture();
let recoveryEntries = 0, recoveryActive = false;
recovery.registerAdapter('code', {
  enter() { recoveryEntries++; if (recoveryEntries === 2) throw new Error('rollback unavailable'); recoveryActive = true; },
  leave() { recoveryActive = false; }, refresh() {},
});
recovery.registerAdapter('work', { enter() { throw new Error('work unavailable'); }, leave() {} });
recovery.connect({});
await recovery.setMode('code');
assert.equal(await recovery.setMode('work'), false);
assert.equal(recoveryActive, false);
assert.equal(await recovery.setMode('code'), true, 'A failed rollback must allow reselecting the original mode');
assert.equal(recoveryActive, true);
assert.equal(recoveryEntries, 3);

const initial = modeFixture('?embed=1&browser=0&tab_mode=work');
let initialEnters = 0;
initial.registerAdapter('work', { enter() { initialEnters++; }, refresh() {} });
initial.connect({});
await tick();
assert.equal(initial.mode(), 'work');
assert.equal(initialEnters, 1, 'A Work document should enter Work directly once');

// Exercise the actual document-tab listener with a shell whose nested resources
// never fire load. The ready message may reveal only the owned same-origin frame.
const windowEvents = new Map();
const origin = 'http://127.0.0.1:8899';
let frame, installs = 0, tab, nextId = 1;
const childShell = { dataset: { surfaceMode: 'work' }, style: { getPropertyValue: () => '' } };
const childDoc = { documentElement: { classList: classes() },
  getElementById: id => id === 'tc-shell' ? childShell : null,
  querySelector: () => null, querySelectorAll: () => [], addEventListener() { installs++; } };
const childWindow = { ThomasChatBoot: {}, document: childDoc };
childDoc.defaultView = childWindow;
const sandbox = { URLSearchParams, CSS: { escape: x => x }, location: { origin, search: '' },
  setTimeout, clearTimeout, localStorage: { getItem: () => '', setItem() {} },
  MutationObserver: class { observe() {} disconnect() {} },
  document: { getElementById: () => null, addEventListener() {},
    createElement(tag) {
      // Only the iframe is the tab's frame; the loading screen over it is a plain element.
      if (tag !== 'iframe') return { className: '', innerHTML: '', setAttribute() {}, classList: classes(), remove() {} };
      const handlers = {};
      frame = { contentDocument: childDoc, contentWindow: childWindow, classList: classes(),
        setAttribute() {}, removeAttribute() {}, addEventListener: (name, fn) => { handlers[name] = fn; }, handlers };
      return frame;
    } },
  window: { ThomasBrowserDocsPolicy: { docUrlFor: () => '/?embed=1&browser=0&tab_mode=work' },
    addEventListener: (name, fn) => windowEvents.set(name, fn) } };
vm.runInNewContext(fs.readFileSync(docsPath, 'utf8'), sandbox);
const docs = sandbox.window.ThomasBrowserDocs.wire({ rowWrap: { appendChild() {} }, asideEl: {},
  makeTab(spec) { tab = { id: nextId++, ...spec }; return tab; },
  activate() {}, setTitle(t, title) { t.title = title; }, setStatus(t, status) { t.status = status; },
  getActiveId: () => tab.id, getTabs: () => tab ? [tab] : [],
  homeTab: { id: 0, mode: 'chat', chatId: '' }, faceFor: x => x });
docs.open({ mode: 'work' });
const ready = windowEvents.get('message');
ready({ origin: 'https://unrelated.invalid', source: childWindow, data: { type: 'thomas:surface-ready' } });
assert.equal(tab.ready, false);
ready({ origin, source: {}, data: { type: 'thomas:surface-ready' } });
assert.equal(tab.ready, false);
ready({ origin, source: childWindow, data: { type: 'thomas:surface-ready' } });
await tick();
assert.equal(tab.ready, true, 'The requested shell must appear without waiting for iframe load');
assert.equal(frame.classList.contains('is-ready'), true);
const installedOnce = installs;
frame.handlers.load();
ready({ origin, source: childWindow, data: { type: 'thomas:surface-ready' } });
await tick();
assert.equal(installs, installedOnce, 'Late load must not install duplicate event handlers');
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
// A load promise belongs to one document, not to the tab forever.
const oldBoot = deferred();
childShell.dataset.surfaceMode = 'chat';
childWindow.ThomasUnifiedModes = { setMode: () => oldBoot.promise };
docs.reload(tab);
frame.handlers.load(); await tick();
assert.equal(tab.ready, false, 'Late readiness from the document being reloaded must be ignored');
frame.contentDocument = { ...childDoc };
frame.handlers.load();
const oldInstalls = installs;
let replacementInstalls = 0;
const replacementDoc = { ...childDoc, addEventListener() { replacementInstalls++; },
  getElementById: id => id === 'tc-shell' ? { ...childShell, dataset: { surfaceMode: 'work' } } : null };
const replacementWindow = { ThomasChatBoot: {}, document: replacementDoc };
replacementDoc.defaultView = replacementWindow;
frame.contentDocument = replacementDoc; frame.contentWindow = replacementWindow;
frame.handlers.load();
await tick();
assert.ok(replacementInstalls > 0, 'A replacement document must not reuse an older loading promise');
assert.equal(tab.ready, true);
oldBoot.resolve(); await tick();
assert.equal(installs, oldInstalls, 'A late old document must not install interceptors or claim the replacement');
const replacementOnce = replacementInstalls;
frame.handlers.load(); await tick();
assert.equal(replacementInstalls, replacementOnce, 'Repeated readiness for one document still installs once');

// A readiness signal during navigation must not permanently cache an empty page.
docs.reload(tab);
frame.contentDocument = { ...replacementDoc, getElementById: () => null };
frame.handlers.load(); await tick();
assert.equal(tab.ready, false);
frame.contentDocument = { ...replacementDoc };
frame.handlers.load(); await tick();
assert.equal(tab.ready, true, 'The real document must recover after an early empty-page signal');

// An adapter that fails to enter Work must not show Chat under a Work tab title.
docs.reload(tab);
frame.contentDocument = childDoc; frame.contentWindow = childWindow;
childWindow.ThomasUnifiedModes = { setMode: async () => false };
frame.handlers.load(); await tick();
assert.equal(tab.ready, false, 'A mismatched mode is not a ready Work document');
assert.equal(tab.status, 'error');
assert.equal(tab.title, 'Could not open Work');
docs.reload(tab);
frame.contentDocument = { ...replacementDoc }; frame.contentWindow = replacementWindow;
frame.handlers.load(); await tick();
assert.equal(tab.ready, true, 'A failed mode entry must remain retryable');
assert.equal(tab.title, 'Work', 'A successful retry clears the load error title');

const closedBoot = deferred();
docs.reload(tab);
frame.contentDocument = { ...childDoc };
frame.contentWindow = { ...childWindow, ThomasUnifiedModes: { setMode: () => closedBoot.promise } };
frame.handlers.load();
const beforeCloseInstalls = installs;
frame.remove = () => {};
docs.remove(tab);
closedBoot.resolve(); await tick();
assert.equal(installs, beforeCloseInstalls, 'A closed tab must not install handlers after its old boot finishes');
assert.equal(tab.ready, false, 'A late load must not revive a closed tab');


// Direct document URLs carry the intended surface and exact conversation.
const policyBox = { window: {} };
vm.runInNewContext(fs.readFileSync(policyPath, 'utf8'), policyBox);
const policy = policyBox.window.ThomasBrowserDocsPolicy;
assert.equal(policy.docUrlFor({ mode: 'chat', chatId: 'chat a&b' }), '/?embed=1&browser=0&tab_mode=chat&tab_chat=chat%20a%26b');
assert.equal(policy.docUrlFor({ mode: 'code', chatId: 'fc_1' }), '/?embed=1&browser=0&tab_mode=code&forge_code=fc_1');
assert.equal(policy.docUrlFor({ mode: 'work' }), '/?embed=1&browser=0&tab_mode=work');

// The real adapters must not hide another awaited history fetch in enter().
const never = new Promise(() => {});
const codeSource = fs.readFileSync(codePath, 'utf8');
const codeEnter = codeSource.split('\n').find(line => line.startsWith('    enter: ')).trim().slice(7, -1);
const buildBox = { adapterActive: false, codeProjects: () => ({ updateProjectButton() {}, loadProjectNames() {} }),
  render() {}, refresh: () => never, adoptOrphanRun: () => never, safely: action => action() };
vm.createContext(buildBox); vm.runInContext('this.enter = ' + codeEnter, buildBox);
let buildReady = false; Promise.resolve(buildBox.enter()).then(() => { buildReady = true; });
await tick(); assert.equal(buildReady, true, 'Build adapter enter must not await history/reconnect');
const workSource = fs.readFileSync(workPath, 'utf8');
const workEnter = workSource.match(/(?:async )?function enter\(\) \{[\s\S]*?\n  \}/)[0];
const workBox = { adapterActive: false, reconcileTimer: null, state: { stage: 'home' },
  clearTimeout() {}, peek: () => null, render() {}, refresh: () => never };
vm.createContext(workBox); vm.runInContext(workEnter + '\nthis.enter = enter;', workBox);
let workReady = false; Promise.resolve(workBox.enter()).then(() => { workReady = true; });
await tick(); assert.equal(workReady, true, 'Work adapter enter must not await history');
// Deduplication belongs to the same pending selection, not every request for
// the same id. A -> B -> A must launch a fresh last A instead of reusing old A.
function openingFixture() {
  const start = codeSource.includes('  const conversationOpens =')
    ? codeSource.indexOf('  const conversationOpens =') : codeSource.indexOf('  window.ThomasCodeMode =');
  const openingSource = codeSource.slice(start, codeSource.indexOf("  // A deliverable's deep link"));
  const state = { activeId: '', conversation: null, contextEpoch: 0 }, pending = [];
  const box = { state, window: {}, document: {}, modes: () => ({ setMode: async () => false }),
    safely: async action => { try { return await action(); } catch (_) { return null; } },
    async loadConversation(id) {
      const epoch = ++state.contextEpoch, gate = deferred(); pending.push({ id, gate });
      await gate.promise;
      if (epoch !== state.contextEpoch) return false;
      state.activeId = id; state.conversation = { id }; return true;
    },
  };
  vm.createContext(box); vm.runInContext(openingSource, box);
  return { state, pending, open: id => box.window.ThomasCodeMode.openConversation(id).catch(() => false) };
}
const duplicate = openingFixture();
const duplicateOne = duplicate.open('A'), duplicateTwo = duplicate.open('A');
await tick(); assert.equal(duplicate.pending.length, 1, 'Same pending selection should load once');
duplicate.pending[0].gate.resolve(); await Promise.all([duplicateOne, duplicateTwo]);
for (const pauseBetween of [false, true]) {
  const owned = openingFixture();
  const first = owned.open('A'); if (pauseBetween) await tick();
  const middle = owned.open('B'); if (pauseBetween) await tick();
  const last = owned.open('A'); await tick();
  assert.deepEqual(owned.pending.map(row => row.id), ['A', 'B', 'A'], 'Revisiting A reused a superseded pending request');
  owned.pending.forEach(row => row.gate.resolve());
  await Promise.all([first, middle, last]);
  assert.equal(owned.state.activeId, 'A', 'The latest requested conversation must own the surface');
}
const differentOwner = openingFixture();
const original = differentOwner.open('A'); await tick();
differentOwner.state.contextEpoch++;
const replacement = differentOwner.open('A'); await tick();
assert.equal(differentOwner.pending.length, 2, 'External selection change must invalidate pending-open deduplication');
differentOwner.pending.forEach(row => row.gate.resolve()); await Promise.all([original, replacement]);
console.log(JSON.stringify({ slow_refresh_nonblocking: true, one_refresh_per_entry: true,
  active_work_preserved: true, interrupted_leave_reenters: true, rollback_can_retry: true,
  direct_mode_boot: true, early_owned_frame_ready: true, duplicate_load_ignored: true,
  foreign_ready_rejected: true, replacement_document_wires: true, stale_boot_ignored: true,
  empty_ready_recovers: true, mode_mismatch_stays_error: true, reload_clears_error: true,
  closed_tab_stays_closed: true, explicit_document_address: true, actual_adapters_enter_without_history: true,
  same_selection_loads_once: true, revisited_selection_gets_new_owner: true, external_selection_invalidates_old_open: true }));
