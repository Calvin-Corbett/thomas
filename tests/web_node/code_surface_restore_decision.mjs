// Runtime proof for the reload-restore decision in unified_code_projects.js.
//
// Measured problem (sweeps/w2-code-stop): F5 during or after a Code task lands
// on the Chat welcome screen and the task has to be hunted out of the sidebar.
// The fix persists the last active surface {mode, codeConversationId} in
// localStorage and, on a boot with NO explicit destination, replays the stored
// Code conversation through the existing `?forge_code=<cid>` deep-link path.
//
// This harness proves the decision function directly: what gets stored, when a
// restore is allowed, and — above all — that a restore can never steal an
// explicit deep link or a landing the reader chose.
import fs from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];

const storage = new Map();
const historyWrites = [];
const setModeCalls = [];

globalThis.window = {
  localStorage: {
    getItem: key => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => { storage.set(key, String(value)); },
    removeItem: key => { storage.delete(key); },
  },
  location: { href: 'http://127.0.0.1:8899/', pathname: '/', search: '', hash: '' },
  history: { replaceState: (_state, _title, url) => { historyWrites.push(String(url)); } },
  addEventListener() {},
  setInterval() { return 0; },
  ThomasUnifiedModes: {
    mode: () => 'chat',
    setMode: mode => { setModeCalls.push(String(mode)); return Promise.resolve(true); },
  },
};
globalThis.document = {
  readyState: 'loading',
  visibilityState: 'visible',
  addEventListener() {},
  getElementById() { return null; },
};

vm.runInThisContext(fs.readFileSync(sourcePath, 'utf8'), { filename: sourcePath });

const surfaceApi = window.ThomasCodeSurface;
if (!surfaceApi) throw new Error('window.ThomasCodeSurface is not exported — the reload-restore module is missing');
for (const name of ['surfaceSnapshot', 'decideSurfaceRestore', 'persistSurface', 'restoreLastSurface']) {
  if (typeof surfaceApi[name] !== 'function') throw new Error(`ThomasCodeSurface.${name} is not a function`);
}

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

// --- What gets stored -------------------------------------------------------
const codeSnap = surfaceApi.surfaceSnapshot('code', 'fc_20260806T001149_4c6b7a');
expect(codeSnap && codeSnap.mode === 'code' && codeSnap.codeConversationId === 'fc_20260806T001149_4c6b7a',
  'a Code surface snapshot must carry the open conversation id');
const chatSnap = surfaceApi.surfaceSnapshot('chat', 'fc_stale_cid');
expect(chatSnap && chatSnap.mode === 'chat' && chatSnap.codeConversationId === '',
  'a Chat surface snapshot must NOT drag a stale Code conversation id along');
expect(surfaceApi.surfaceSnapshot('bogus', 'x') === null, 'an unknown mode is not a surface');

// --- The restore decision ---------------------------------------------------
const storedCode = JSON.stringify({ mode: 'code', codeConversationId: 'fc_abc123' });
const decide = (raw, landing) => surfaceApi.decideSurfaceRestore(raw, landing);

let decision = decide(storedCode, { search: '', hash: '' });
expect(decision.restore === true && decision.cid === 'fc_abc123',
  'a clean boot with a stored Code conversation must restore it');

decision = decide(storedCode, { search: '?forge_code=fc_explicit', hash: '' });
expect(decision.restore === false, 'restore must never steal an explicit forge_code deep link');

decision = decide(storedCode, { search: '?nav=work', hash: '' });
expect(decision.restore === false, 'restore must never steal any other explicit query landing');

decision = decide(storedCode, { search: '', hash: '#somewhere' });
expect(decision.restore === false, 'restore must never steal a hash landing the reader chose');

decision = decide(JSON.stringify({ mode: 'chat', codeConversationId: '' }), { search: '', hash: '' });
expect(decision.restore === false, 'a stored Chat surface is the default — no restore work to do');

decision = decide(JSON.stringify({ mode: 'code', codeConversationId: '' }), { search: '', hash: '' });
expect(decision.restore === true && decision.cid === '', 'Code mode with no open task restores the mode only');

decision = decide('not json at all', { search: '', hash: '' });
expect(decision.restore === false, 'an unreadable snapshot must decide quietly against restoring');

decision = decide('', { search: '', hash: '' });
expect(decision.restore === false, 'no snapshot, no restore');

// --- Runtime restore: reuses the forge_code deep-link path ------------------
storage.set('thomas.lastSurface', storedCode);
surfaceApi.restoreLastSurface();
expect(historyWrites.length === 1 && historyWrites[0] === '/?forge_code=fc_abc123',
  `restore must inject the stored cid through the deep-link URL (got ${JSON.stringify(historyWrites)})`);

// An explicit deep link already in the URL stays untouched.
window.location.href = 'http://127.0.0.1:8899/?forge_code=fc_explicit';
window.location.search = '?forge_code=fc_explicit';
surfaceApi.restoreLastSurface();
expect(historyWrites.length === 1, 'an explicit deep link in the URL must not be overwritten by restore');
window.location.href = 'http://127.0.0.1:8899/';
window.location.search = '';

// Mode-only restore goes through the modes host, not the URL.
storage.set('thomas.lastSurface', JSON.stringify({ mode: 'code', codeConversationId: '' }));
surfaceApi.restoreLastSurface();
expect(historyWrites.length === 1 && setModeCalls.length === 1 && setModeCalls[0] === 'code',
  'Code mode with no task restores via setMode("code"), not a URL rewrite');

// --- Persistence writes the surface it sees ---------------------------------
window.ThomasCodeProjects.configure({ state: { activeId: 'fc_live_1', projectNames: {} } });
window.ThomasUnifiedModes.mode = () => 'code';
surfaceApi.persistSurface();
expect(storage.get('thomas.lastSurface') === JSON.stringify({ mode: 'code', codeConversationId: 'fc_live_1' }),
  'persist must record the open Code conversation');
window.ThomasUnifiedModes.mode = () => 'chat';
surfaceApi.persistSurface();
expect(storage.get('thomas.lastSurface') === JSON.stringify({ mode: 'chat', codeConversationId: '' }),
  'switching back to Chat must persist Chat as the last surface');

console.log(JSON.stringify({
  ok: true,
  restoredUrl: historyWrites[0],
  modeOnlyRestores: setModeCalls,
}));
