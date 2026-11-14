import { installFeature } from './chat_feature_fixture.mjs';
import path from 'node:path';
// Exercise the actual picker module without contacting a server or model.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const [modulePath, chatPath] = process.argv.slice(2);
const row = { style: {}, children: [], innerHTML: '', appendChild(el) { this.children.push(el); } };
const readers = [];
const requests = [];
let fetchResult = { ok: true, document: { text: 'Manifest total is 43', attachment_id: 'a'.repeat(32), sha256: 'b'.repeat(64), size_bytes: 100 } };
let completeFetch;
const state = { docs: [], images: [], input: 'Read this', streaming: false };
const context = {
  window: { addEventListener() {} }, document: {
    getElementById: id => id === 'tc-attach-row' ? row : null,
    createElement: () => ({ style: {}, innerHTML: '', attributes: {},
      setAttribute(key, value) { this.attributes[key] = value; },
      appendChild() {}, addEventListener() {} }),
  },
  setTimeout: () => 1, clearTimeout() {}, AbortController,
  FormData: class { append(...args) { this.args = args; } },
  FileReader: class {
    readAsDataURL() { readers.push(this); }
    readAsText() { throw new Error('Binary/text files must use bounded extraction'); }
  },
  fetch: async (url, options) => {
    requests.push({ url, options });
    if (completeFetch === 'defer') await new Promise(resolve => { completeFetch = resolve; });
    return { ok: !fetchResult.error, json: async () => fetchResult };
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(modulePath, 'utf8'), context);
let validity = '';
let reported = 0;
const inputEl = { setCustomValidity(message) { validity = message; }, reportValidity() { reported++; } };
const panels = context.window.ThomasChatComposerPanels.create({
  state, esc: text => String(text).replaceAll('<', '&lt;'), inputEl,
  autosize() {}, syncDynamic() {}, DIAL_FIELDS: [], saveDials() {},
});

await panels.onFiles([{ name: 'manifest.pdf', type: 'application/pdf', size: 100 }]);
assert.equal(requests[0].url, '/api/v2/chat/documents/extract');
assert.equal(state.docs[0].text, 'Manifest total is 43');
assert.equal(state.docs[0].pending, false);
assert.equal(state.docs[0].attachment_id, 'a'.repeat(32));
assert.equal(state.docs[0].sha256, 'b'.repeat(64));
assert.equal(state.docs[0].size_bytes, 100);
fetchResult = { ok: false, error: 'PDF is password-protected' };
await panels.onFiles([{ name: 'locked.pdf', type: 'application/pdf', size: 100 }]);
assert.equal(state.docs[1].error, 'PDF is password-protected');
assert.ok(row.children.some(chip => chip.attributes.role === 'alert' && chip.innerHTML.includes('Not attached')));

// Removing a pending image must not remove another document or resurrect it.
const reading = panels.onFiles([{ name: 'image.png', type: 'image/png', size: 100 }]);
const imagePending = state.docs.findIndex(doc => doc.pending);
state.docs.splice(imagePending, 1);
const retained = state.docs.slice();
readers[0].result = 'data:image/png;base64,abc';
readers[0].onload();
await reading;
assert.deepEqual(state.docs, retained);
assert.equal(state.images.length, 0);

// Completing an upload after switching conversations must not attach it there.
completeFetch = 'defer';
fetchResult = { ok: true, document: { text: 'original conversation file' } };
const originalDocs = state.docs;
const deferred = panels.onFiles([{ name: 'slow.pdf', type: 'application/pdf', size: 100 }]);
assert.ok(originalDocs.some(doc => doc.pending));
state.docs = [];
state.images = [];
completeFetch();
await deferred;
assert.equal(state.docs.length, 0);
assert.ok(originalDocs.some(doc => doc.text === 'original conversation file'));

// Every selected file is pending immediately, even though extraction is serial.
// Removing the first chip cannot make Send available while the next is waiting.
state.docs = []; state.images = [];
completeFetch = 'defer';
const batch = panels.onFiles([
  { name: 'first.pdf', type: 'application/pdf', size: 100 },
  { name: 'second.pdf', type: 'application/pdf', size: 100 },
]);
assert.equal(state.docs.filter(doc => doc.pending).length, 2);
state.docs.splice(0, 1);
assert.equal(panels.attachmentsReady(), false);
completeFetch(); await batch;
assert.equal(state.docs.length, 1);
assert.equal(state.docs[0].name, 'second.pdf');
assert.equal(state.docs[0].pending, false);
reported = 0;

// Enter while extracting must not dispatch or enqueue an incomplete attachment.
const html = fs.readFileSync(chatPath, 'utf8');
state.streaming = true;
state.docs = [{ pending: true }];
context.state = state;
context.inputEl = inputEl;
context.attachmentsReady = panels.attachmentsReady;
context.turnFlow = { enqueue() { throw new Error('Incomplete upload was queued'); } };
installFeature(context, chatPath, 'stream_actions', ['send']);
context.send();
assert.match(validity, /Wait for file extraction/);
assert.equal(reported, 1);

// Drive the page's actual selection reset, not an assumed array replacement.
Object.assign(context, {
  chatSelectionToken: 0, abortController: null, timer: null,
  chatList: [{ id: 'other-chat', sessionId: 'other-session', msgs: [] }],
  localStorage: { setItem() {} }, threadEl: { innerHTML: '', appendChild() {} }, msgRefs: [],
  renderAttachments: panels.renderAttachments,
  threadRenderSignature: () => '', renderedThreadSignature: '',
  hydrateSelectedChat: async () => false, restoreVerifiedChatArtifacts: async () => {}, restoreDelegationCards() {},
});
for (const name of ['showChat', 'resetCanvasForConversation', 'renderChats', 'syncView', 'autosize', 'syncDynamic', 'scrollEnd']) context[name] = () => {};
state.docs = []; state.images = [];
completeFetch = 'defer';
const switchUpload = panels.onFiles([{ name: 'old-draft.pdf', type: 'application/pdf', size: 100 }]);
vm.runInContext(fs.readFileSync(path.join(path.dirname(chatPath), 'js/chat_turn_flow.js'), 'utf8'), context);
const uploadFetch = context.fetch;
context.fetch = (url, options) => String(url).startsWith('/api/v2/chat/session/')
  ? Promise.resolve({ok:false,status:404}) : uploadFetch(url, options);
installFeature(context, chatPath, 'session_restore', ['selectChat']);
context.selectChat('other-chat');
assert.equal(state.docs.length, 0);
completeFetch(); await switchUpload;
assert.equal(state.docs.length, 0);
assert.equal(state.sessionId, 'other-session');
process.stdout.write('Document picker, errors, removal, draft ownership, and pending-send checks passed.\n');
