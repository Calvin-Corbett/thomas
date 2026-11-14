import { installFeature } from './chat_feature_fixture.mjs';
import path from 'node:path';
// The LIVE unified shell's composer must queue a message sent mid-reply.
//
// Measured 2026-08-05 (w2-chat-followup-correction, deterministic): the wave-1
// queue fix landed in js/runtime/011_chat_games_02.js (the /classic shell),
// but chat.html — the shell actually served at / — has its own send path, and
// its `send()` opened with `if (!text || state.streaming) return;`: Enter
// during a streaming reply was silently dropped. No bubble, no note, no send
// after completion; the composer kept the text while the send button kept the
// active arrow.
//
// This harness drives BOTH halves of the fix:
//   1. wiring in chat.html — send() queues instead of dropping, streamReal
//      drains on completion, the send-button click stops only on an EMPTY
//      composer, and the queue module is actually loaded by the page;
//   2. behavior of the real js/chat_turn_flow.js queue in a vm — visible
//      "Queued — will send when this reply finishes" note, in-order auto-send
//      of multiple queued messages, attachments travelling with their message,
//      and a queued bubble that left the transcript never sending.
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
const modulePath = process.argv[3];
if (!htmlPath || !modulePath) throw new Error('usage: node chat_shell_send_queue.mjs <chat.html> <chat_turn_flow.js>');
const html = fs.readFileSync(htmlPath, 'utf8');
const moduleSource = fs.readFileSync(modulePath, 'utf8');

function htmlFunctionSource(name, nextName) {
  const starts = [`function ${name}(`, `async function ${name}(`];
  let start = -1;
  for (const s of starts) { start = html.indexOf(s); if (start >= 0) break; }
  let end = html.indexOf(`\n    function ${nextName}(`, start);
  if (end < 0) end = html.indexOf(`\n    async function ${nextName}(`, start);
  if (start < 0 || end < 0) throw new Error(`could not extract ${name}`);
  return html.slice(start, end);
}

const checks = {};

// ---- 1. chat.html wiring ----
checks.moduleScriptTagPresent = html.includes('/static/js/chat_turn_flow.js');

const sendSource = fs.readFileSync(path.join(path.dirname(htmlPath), 'js/chat_stream_actions.js'), 'utf8').split('function chunkText', 1)[0];
// The silent drop is the measured defect: its exact guard must be gone…
checks.silentDropRemoved = !sendSource.includes('!text || state.streaming) return');
// …and the streaming branch must route into the turn-flow queue instead.
checks.sendQueuesWhileStreaming = /state\.streaming\)\s*\{[^}]*enqueue\(/.test(sendSource);

const streamSource = fs.readFileSync(path.join(path.dirname(htmlPath), 'js/chat_stream_actions.js'), 'utf8');
// Completion must drain the queue so queued messages auto-send in order.
checks.streamCompletionDrains = streamSource.includes('drainQueued');

// The send button: typed text while streaming must SEND (which queues) —
// only an empty composer while busy may stop the run. This is the behavior
// the arrow-vs-stop icon (syncDynamic) has promised all along.
let click, stopped = 0, sent = 0;
const noop = () => {};
const clickContext = {window:{},state:{input:''},isChatBusy:()=>true,
  stopChat:()=>{stopped++;},send:()=>{sent++;}, bindLibraryActions:noop,
  inputEl:{addEventListener:noop},
  document:{addEventListener:noop,querySelectorAll:()=>[],
    getElementById:id=>({addEventListener:(_event,handler)=>{if(id==='tc-send')click=handler;}})}};
installFeature(clickContext, htmlPath, 'shell_bindings');

click();
const emptyStops = stopped === 1 && sent === 0;
clickContext.state.input = 'send this next';click();
checks.clickStopsOnlyWhenComposerEmpty = emptyStops && stopped === 1 && sent === 1;

// ---- 2. queue behavior (real module in a vm) ----
class FakeNote {
  constructor(tag) { this.tagName = String(tag || 'div').toUpperCase(); this.className = ''; this.textContent = ''; this.parent = null; }
  remove() { if (this.parent) { this.parent.notes = this.parent.notes.filter(n => n !== this); this.parent = null; } }
}
class FakeBubble {
  constructor() { this.notes = []; }
  insertAdjacentElement(_where, el) { el.parent = this; this.notes.push(el); return el; }
}

const state = { input: '', docs: [], images: [], messages: [], streaming: false };
const msgRefs = [];
const log = { sent: [], appended: 0, attachmentsRendered: 0 };
const context = {
  window: {},
  document: { createElement: (tag) => new FakeNote(tag) },
  console,
};
vm.createContext(context);
vm.runInContext(moduleSource, context);
checks.moduleExportsQueue = typeof context.window.ThomasChatTurnFlow?.create === 'function';

const flow = context.window.ThomasChatTurnFlow.create({
  state,
  inputEl: { value: '' },
  msgRefs,
  autosize() {},
  syncDynamic() {},
  syncView() {},
  scrollEnd() {},
  renderAttachments() { log.attachmentsRendered += 1; },
  appendMessage(m) {
    log.appended += 1;
    msgRefs[state.messages.indexOf(m)] = { bubbleEl: new FakeBubble() };
  },
  sendNow(text, files) {
    log.sent.push({ text, docs: files.docs.slice(), images: files.images.slice() });
    state.streaming = true; // streamReal sets this synchronously
    files.onAccepted(); // server accepts the queued turn
  },
});

// Queue two messages while a reply streams; both must render, visibly queued.
state.streaming = true;
state.input = 'change tuesday to 9';
state.docs = [{ name: 'menu.txt' }];
const first = flow.enqueue();
state.input = 'and make it for 8 people';
const second = flow.enqueue();
checks.enqueueAccepts = first === true && second === true;
checks.bubblesRenderedAtQueueTime = log.appended === 2
  && state.messages.length === 2
  && state.messages[0].text === 'change tuesday to 9'
  && state.messages[1].text === 'and make it for 8 people';
checks.composerClearedOnQueue = state.input === '' && state.docs.length === 0;
const note0 = msgRefs[0]?.bubbleEl?.notes?.[0];
checks.visibleQueuedNote = Boolean(note0)
  && /queued/i.test(String(note0.textContent))
  && /will send when this reply finishes/i.test(String(note0.textContent));

// Draining while STILL streaming must send nothing.
flow.drainQueued();
checks.noSendWhileStreaming = log.sent.length === 0 && flow.queuedCount() === 2;

// Reply finishes → first queued message sends, WITH its attachments, and its
// note disappears. The second stays parked (its turn comes next completion).
state.input = 'a later unsent draft';
state.docs = [{ name: 'unrelated-draft.txt' }];
state.images = [{ name: 'private-photo.png' }];
state.streaming = false;
flow.drainQueued();
checks.firstSentInOrder = log.sent.length === 1
  && log.sent[0].text === 'change tuesday to 9'
  && log.sent[0].docs.length === 1
  && log.sent[0].docs[0].name === 'menu.txt'
  && log.sent[0].images.length === 0
  && flow.queuedCount() === 1;
checks.unsentDraftAttachmentsUntouched = state.input === 'a later unsent draft'
  && state.docs[0]?.name === 'unrelated-draft.txt'
  && state.images[0]?.name === 'private-photo.png';
checks.noteRemovedOnSend = (msgRefs[0].bubbleEl.notes || []).length === 0;

// Next completion → second sends. Multiple queued messages flow in order.
state.streaming = false;
flow.drainQueued();
checks.secondSentInOrder = log.sent.length === 2 && log.sent[1].text === 'and make it for 8 people';
checks.queuedMessagesDoNotInheritOtherFiles = log.sent[1].docs.length === 0 && log.sent[1].images.length === 0;

// A queued bubble whose message left the transcript (chat switched, edit-resend
// truncation) must never fire into the new conversation.
state.streaming = true;
state.input = 'stale message for the old chat';
flow.enqueue();
state.messages.length = 0; // selectChat/newChat replaced the transcript
state.streaming = false;
flow.drainQueued();
checks.staleQueuedMessageNeverSends = log.sent.length === 2;

const failures = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
if (failures.length > 0) throw new Error(`chat shell send-queue checks failed: ${failures.join(', ')}`);
process.stdout.write(`${JSON.stringify(checks)}\n`);
