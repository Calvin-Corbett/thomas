// Drive js/chat_composer_panels.js with the values chat.html hands it, in a bare
// VM. The browser can prove state/esc/DIAL_FIELDS/saveDials cross the boundary by
// opening the menus; inputEl/autosize/syncDynamic are only reachable through a
// speech result, so they are driven here with a stubbed SpeechRecognition.
import fs from 'node:fs';
import vm from 'node:vm';

const modulePath = process.argv[2];
if (!modulePath) throw new Error('usage: node chat_composer_panels.mjs <chat_composer_panels.js>');

function fakeEl() {
  return {
    style: {}, title: '', value: '', innerHTML: '', dataset: {}, _on: {},
    addEventListener(type, fn) { this._on[type] = fn; },
    setAttribute() {}, focus() {}, appendChild() {}, closest: () => null,
    getBoundingClientRect: () => ({ left: 0, width: 200, height: 120 }),
    querySelectorAll: () => [],
  };
}

const mic = fakeEl();
const win = { addEventListener() {} };
const doc = {
  getElementById: (id) => (id === 'tc-mic-btn' ? mic : null),
  querySelectorAll: () => [],
  createElement: () => fakeEl(),
};
const ctx = { window: win, document: doc, setTimeout: () => 0, clearTimeout: () => {} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(modulePath, 'utf8'), ctx);

if (!win.ThomasChatComposerPanels || typeof win.ThomasChatComposerPanels.create !== 'function') {
  throw new Error('chat_composer_panels.js did not publish window.ThomasChatComposerPanels.create');
}

const inputEl = { value: '' };
let autosized = 0;
let synced = 0;
const state = { input: '', listening: false, docs: [], images: [], dials: {} };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const panels = win.ThomasChatComposerPanels.create({
  state,
  esc,
  inputEl,
  autosize: () => { autosized += 1; },
  syncDynamic: () => { synced += 1; },
  DIAL_FIELDS: [],
  saveDials: () => {},
});

state.libraryProjects = [
  { name: 'Nova', request_title: 'A <b>bold</b> title', entry_path: 'apps/index.html', root_path: 'C:/p/nova', artifact_url: '/deliverable/nova' },
  { name: 'Orbit', request_title: 'Orbit', entry_path: 'orbit/index.html', root_path: 'C:/p/orbit' },
];
const card = panels.libraryCardHTML(state.libraryProjects[0], 0);

win.SpeechRecognition = function SpeechRecognitionStub() {
  win._recognition = this;
  this.start = () => {};
  this.stop = () => {};
};
panels.setupMic();
mic._on.click();
win._recognition.onresult({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: 'book the flight' } }] });

state.libraryFilter = 'orbit';
const filtered = panels.libraryVisibleProjects().map((p) => p.name);
state.libraryFilter = '';

const checks = {
  cardEscapes: card.includes('&lt;b&gt;bold&lt;/b&gt;') && !card.includes('<b>bold</b>'),
  cardPreviewHolder: card.includes('data-lib-frame="/deliverable/nova"'),
  cardMonogram: card.includes('>A</span>'),
  relativeWhen: panels.relativeWhen(new Date(Date.now() - 3 * 3600 * 1000).toISOString()) === '3 hours ago',
  filters: filtered.length === 1 && filtered[0] === 'Orbit',
  unfiltered: panels.libraryVisibleProjects().length === 2,
  micUsesInputEl: inputEl.value === 'book the flight' && state.input === 'book the flight',
  micUsesAutosize: autosized === 1,
  micUsesSyncDynamic: synced === 1,
};

for (const [name, passed] of Object.entries(checks)) {
  if (!passed) throw new Error(`composer panel check failed: ${name}`);
}
process.stdout.write(`${JSON.stringify(checks)}\n`);
