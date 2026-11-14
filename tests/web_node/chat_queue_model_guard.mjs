import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const [htmlPath, flowPath, selectionPath, pickerPath] = process.argv.slice(2);
const html = fs.readFileSync(htmlPath, 'utf8');
const binding = marker => {
  const start = html.indexOf(marker);
  assert.ok(start >= 0, `Missing production binding ${marker}`);
  const end = html.indexOf('\n    });', start);
  assert.ok(end > start);
  return html.slice(start, end + '\n    });'.length);
};
const state = {
  input: 'queued original', activeChat: 'original-chat', profile: 'local', modelId: 'one', modelLabel: 'One',
  messages: [], docs: [{ name: 'original.txt', text: 'original content' }],
  images: [{ name: 'original.png', data: 'original pixels' }], streaming: true, dials: {},
};
const profilesData = [{ name: 'local', models: [
  { id: 'one', display_name: 'One', available: true },
  { id: 'two', display_name: 'Two', available: true },
] }];
const notes = [], calls = [], msgRefs = [], validation = [];
const rows = new Map();
const storage = {
  getItem: key => rows.get(key) || null,
  setItem: (key, value) => rows.set(key, value),
  removeItem: key => rows.delete(key),
};
const inputEl = { value: state.input, setCustomValidity: value => validation.push(value), reportValidity() {} };
let desired = { profile: 'local', modelId: 'one' };
const context = vm.createContext({
  state, profilesData, inputEl, msgRefs, console, localStorage: storage,
  document: {
    querySelector: () => ({ dataset: {} }), getElementById: () => ({ textContent: '' }),
    createElement: () => { const note = { removed: 0, replaceChildren() {}, remove() { this.removed += 1; } }; notes.push(note); return note; },
  },
  CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
  autosize() {}, syncDynamic() {}, syncView() {}, renderAttachments() {}, scrollEnd() {},
  saveDials() {}, renderModelMenu() {}, _pendingCanvasIntent: false, detectVisualIntent: () => false,
  appendMessage() { msgRefs.push({ bubbleEl: { insertAdjacentElement() {}, isConnected: true } }); },
  streamReal(text, files) {
    calls.push({ text, files, profile: state.profile, modelId: state.modelId });
    state.streaming = true;
    files.onAccepted();
  },
});
context.window = context;
context.parent = { ThomasModelSelection: { current: () => desired } };
context.dispatchEvent = () => {};
for (const file of [flowPath, selectionPath, pickerPath]) vm.runInContext(fs.readFileSync(file, 'utf8'), context);
vm.runInContext(`
  const { profileModelOptions, setProfile } = ThomasChatModelPicker.create({ state, profilesData, saveDials });
  ${binding('window.ThomasChatModelSelection.connect({')}
  ${binding('const turnFlow = window.ThomasChatTurnFlow.create({')}
  globalThis.queue = turnFlow;
`, context);
assert.equal(context.queue.enqueue(), true);
assert.equal(context.queue.queuedCount(), 1);
assert.equal(state.input, '');
const queuedText = state.messages[0];
assert.equal(queuedText.text, 'queued original');
state.input = 'next unsent draft'; inputEl.value = state.input;
state.docs = [{ name: 'draft.txt', text: 'new draft' }];
state.images = [{ name: 'draft.png', data: 'new draft pixels' }];

// A model can disappear after queueing, including while it is still selected.
profilesData[0].models[0].available = false;
state.streaming = false;
assert.equal(context.queue.drainQueued(), false);
assert.equal(context.queue.queuedCount(), 1);
assert.equal(notes[0].removed, 0);
assert.match(notes[0].textContent, /Queued.*One.*available and selected/);
assert.equal(calls.length, 0);

// A different valid global selection cannot silently change this queued job.
profilesData[0].models[0].available = true;
desired = { profile: 'local', modelId: 'two' };
assert.equal(context.queue.drainQueued(), false);
await Promise.resolve(); await Promise.resolve();
assert.equal(state.modelId, 'two');
assert.equal(context.queue.queuedCount(), 1);
assert.equal(notes[0].removed, 0);
assert.equal(calls.length, 0);

// Choosing the original model drains once through the actual selection callback.
desired = { profile: 'local', modelId: 'one' };
assert.equal(context.ThomasModelSelection.select('local', 'one'), true);
assert.equal(calls.length, 0, 'resumption must wait until selection has settled');
await Promise.resolve(); await Promise.resolve();
assert.equal(context.queue.queuedCount(), 0);
assert.equal(notes[0].removed, 1);
assert.equal(calls.length, 1);
assert.equal(calls[0].profile, 'local'); assert.equal(calls[0].modelId, 'one');
assert.equal(calls[0].text, 'queued original');
assert.equal(calls[0].files.docs[0].text, 'original content');
assert.equal(calls[0].files.images[0].data, 'original pixels');
assert.equal(state.input, 'next unsent draft');
assert.equal(state.docs[0].text, 'new draft');
assert.equal(state.images[0].data, 'new draft pixels');
context.ThomasChatModelSelection.changed(false);
await Promise.resolve();
assert.equal(calls.length, 1, 'another selection notification cannot duplicate the request');

// Switching chats retains the original queue without sending it into the new one.
state.input = 'old conversation'; inputEl.value = state.input;
assert.equal(context.queue.enqueue(), true);
state.activeChat = 'another-chat'; state.messages = []; state.streaming = false;
assert.equal(context.queue.drainQueued(), false);
assert.equal(context.queue.queuedCount(), 0);
assert.equal(JSON.parse(storage.getItem('thomas_chat_queue:original-chat'))[0].text, 'old conversation');
assert.equal(calls.length, 1);
console.log(JSON.stringify({ blocked_retained: true, original_model: true, resumed_once: true, files_retained: true, draft_preserved: true, stale_conversation: true }));
