"""Exercise production model selection and queue retention through the live bindings."""

import shutil
import subprocess
from pathlib import Path

import pytest

DRIVER = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = process.argv[1];
const read = name => fs.readFileSync(root + '/thomas/server/web/js/' + name, 'utf8');
const saved = new Map();
const storage = {
  getItem: key => saved.get(key) || null,
  setItem: (key, value) => saved.set(key, value),
  removeItem: key => saved.delete(key),
};
function element() {
  return {children: [], removed: false, textContent: '',
    get isConnected() { return !this.removed; },
    appendChild(child) { this.children.push(child); return child; },
    replaceChildren() { this.children = []; },
    insertAdjacentElement(where, child) { notes.push(child); },
    remove() { this.removed = true; },
    addEventListener(event, action) { this['on' + event] = action; },
    click() { this.onclick?.(); },
  };
}
const notes = [], calls = [], refs = [];
const state = {activeChat: 'A', input: 'queued original', profile: 'local', modelId: 'one',
  modelLabel: 'One', messages: [], docs: [{name: 'original.txt', text: 'original content'}],
  images: [{name: 'original.png', data: 'original pixels'}], streaming: true};
const profiles = [{name: 'local', models: [
  {id: 'one', display_name: 'One', available: true},
  {id: 'two', display_name: 'Two', available: true},
]}];
let desired = {profile: 'local', modelId: 'one'};
const input = {value: state.input, setCustomValidity() {}, reportValidity() {}};
const ctx = {window: {}, document: {createElement: element,
  querySelector: () => ({dataset: {}}), getElementById: () => input}, localStorage: storage, console};
ctx.window.parent = {ThomasModelSelection: {current: () => desired}};
ctx.window.dispatchEvent = () => {};
ctx.window.CustomEvent = class {};
vm.createContext(ctx);
for (const name of ['chat_turn_flow.js', 'chat_model_selection.js']) vm.runInContext(read(name), ctx);
const selection = ctx.window.ThomasChatModelSelection;
let queue;
const adapter = {
  state, getCurrent: () => ({profile: state.profile, modelId: state.modelId}),
  getProfiles: () => profiles, profileModelOptions: profile => profile.models,
  setProfile(profile, model) { state.profile = profile.name; state.modelId = model.id; selection.changed(false); },
  renderModelMenu() {}, selectionChanged() { Promise.resolve().then(() => queue.drainQueued()); },
};
selection.connect(adapter);
queue = ctx.window.ThomasChatTurnFlow.create({state, inputEl: input, msgRefs: refs,
  autosize() {}, syncDynamic() {}, syncView() {}, renderAttachments() {}, scrollEnd() {},
  appendMessage(message) { refs[state.messages.indexOf(message)] = {bubbleEl: element()}; },
  canSendQueued: original => selection.ensureCurrent(input) &&
    (!original || (original.profile === state.profile && original.modelId === state.modelId)),
  sendNow(text, files) { calls.push({chat: state.activeChat, text, files,
    profile: state.profile, modelId: state.modelId}); state.streaming = true; files.onAccepted(); },
});
const stored = chat => JSON.parse(storage.getItem('thomas_chat_queue:' + chat) || '[]');
const buttons = note => note.children.map(child => child.textContent);
async function run() {
  assert.equal(queue.enqueue(), true);
  assert.equal(queue.queuedCount(), 1);
  assert.equal(state.input, '');
  assert.equal(state.messages[0].text, 'queued original');
  assert.equal(stored('A')[0].docs[0].text, 'original content');
  assert.equal(stored('A')[0].images[0].data, 'original pixels');
  state.input = 'next unsent draft'; input.value = state.input;
  state.docs = [{name: 'draft.txt', text: 'new draft'}];
  state.images = [{name: 'draft.png', data: 'new draft pixels'}];
  profiles[0].models[0].available = false; state.streaming = false;
  assert.equal(queue.drainQueued(), false);
  assert.equal(queue.queuedCount(), 1);
  assert.match(notes[0].textContent, /Queued.*One.*available and selected/);
  assert.equal(calls.length, 0);
  profiles[0].models[0].available = true;
  desired = {profile: 'local', modelId: 'two'};
  assert.equal(queue.drainQueued(), false);
  await Promise.resolve(); await Promise.resolve();
  assert.equal(state.modelId, 'two');
  assert.equal(queue.queuedCount(), 1);
  assert.equal(calls.length, 0);
  assert.deepEqual(buttons(notes[0]), ['Remove', 'Send now']);
  desired = {profile: 'local', modelId: 'one'};
  assert.equal(ctx.window.ThomasModelSelection.select('local', 'one'), true);
  assert.equal(calls.length, 0, 'wait for the selection callback');
  await Promise.resolve(); await Promise.resolve();
  assert.equal(queue.queuedCount(), 0);
  assert.equal(stored('A').length, 0, 'handoff must remove the stored copy');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].chat, 'A');
  assert.equal(calls[0].modelId, 'one');
  assert.equal(calls[0].text, 'queued original');
  assert.equal(calls[0].files.docs[0].text, 'original content');
  assert.equal(calls[0].files.images[0].data, 'original pixels');
  assert.equal(state.input, 'next unsent draft');
  assert.equal(state.docs[0].text, 'new draft');
  assert.equal(state.images[0].data, 'new draft pixels');
  selection.changed(false); await Promise.resolve();
  assert.equal(calls.length, 1, 'selection notification cannot duplicate the request');
  state.input = 'old conversation'; input.value = state.input;
  assert.equal(queue.enqueue(), true);
  const waiting = notes.at(-1);
  state.messages = []; state.streaming = false;
  assert.equal(queue.drainQueued(), false, 'do not send without its visible bubble');
  assert.equal(queue.queuedCount(), 1, 'redraw cannot silently discard it');
  assert.equal(stored('A')[0].text, 'old conversation');
  assert.equal(waiting.removed, false);
  state.activeChat = 'B';
  assert.equal(queue.drainQueued(), false);
  assert.equal(calls.length, 1, 'chat B cannot receive chat A queue');
  state.activeChat = 'A'; queue.redraw();
  assert.equal(queue.queuedCount(), 1);
  assert.equal(state.messages[0].text, 'old conversation');
  assert.ok(notes.at(-1).textContent.includes('Queued'));
  state.activeChat = 'new'; state.sessionId = null; state.messages = []; state.streaming = true;
  state.input = 'waiting for identity'; input.value = state.input;
  assert.equal(queue.enqueue(), true); assert.equal(stored('new').length, 0);
  assert.equal(stored('C').length, 0, 'no premature storage under a guessed chat');
  state.activeChat = 'C'; queue.redraw();
  assert.equal(stored('C')[0].text, 'waiting for identity', 'persist after real chat ID is known');
  assert.ok(notes.at(-1).textContent.includes('Queued'));
  console.log('model guard and conversation-owned queue: passed');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
"""


def test_queued_model_guard_preserves_and_resumes_the_original_turn():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the actual Chat queue factory check")
    root = Path(__file__).resolve().parents[1]
    web = root / "thomas/server/web"
    result = subprocess.run(
        [
            node,
            str(root / "tests/web_node/chat_queue_model_guard.mjs"),
            str(web / "chat.html"),
            str(web / "js/chat_turn_flow.js"),
            str(web / "js/chat_model_selection.js"),
            str(web / "js/chat_model_picker.js"),
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_model_guard_retains_stale_bubbles_and_waits_for_real_chat_id():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the queue's stale-bubble check")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "-e", DRIVER, str(root)],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
