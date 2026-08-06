// A message sent while a reply is generating must be QUEUED and auto-sent,
// never dropped and never fired blind at the backend.
//
// Drives the real functions from js/runtime/011_chat_games_02.js in a vm
// context: queueSendJobWhileGenerating() must park the job in pendingSendQueue
// with a visible "Queued" note on the rendered message, and the existing
// drainQueuedSends() must send it once isGenerating goes false -- and must NOT
// send while generation is still running.
import fs from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
if (!sourcePath) throw new Error('usage: node chat_send_queue_while_generating.mjs <011_chat_games_02.js>');
const source = fs.readFileSync(sourcePath, 'utf8');

function functionSource(name) {
  const patterns = [`\nfunction ${name}(`, `\nasync function ${name}(`];
  let start = -1;
  for (const p of patterns) {
    start = source.indexOf(p);
    if (start >= 0) break;
  }
  if (start < 0) throw new Error(`could not extract ${name}`);
  const next = source.slice(start + 1).search(/\n(?:async )?function [A-Za-z_$]/);
  const end = next < 0 ? source.length : start + 1 + next;
  return source.slice(start, end);
}

class FakeElement {
  constructor(tag = 'div') {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.className = '';
    this.textContent = '';
    this.style = {};
    this.type = '';
    this._innerHTML = '';
    this.classList = { add() {}, remove() {}, contains() { return false; } };
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    if (this._innerHTML === '') this.children = [];
  }

  get innerHTML() {
    return this._innerHTML;
  }

  appendChild(el) {
    el.parentNode = this;
    this.children.push(el);
    return el;
  }

  addEventListener() {}

  querySelector(selector) {
    const cls = String(selector).replace(/^\./, '');
    return this.children.find((child) => String(child.className).split(/\s+/).includes(cls)) || null;
  }

  remove() {
    if (this.parentNode) {
      this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
      this.parentNode = null;
    }
  }
}

const log = { rendered: [], sent: [], ensureChatVisible: 0 };
const rowsById = new Map();

const context = {
  HTMLElement: FakeElement,
  console,
  document: {
    createElement: (tag) => new FakeElement(tag),
    getElementById: (id) => rowsById.get(String(id)) || null,
  },
  safeString: (value) => (value === null || value === undefined ? '' : String(value)),
  renderMessage: (msg) => {
    log.rendered.push({ ...msg });
    const row = new FakeElement('div');
    row.id = String(msg.id || '');
    if (row.id) rowsById.set(row.id, row);
    return row;
  },
  ensureChatVisible: () => { log.ensureChatVisible += 1; },
  composerSyncSendButtonState: () => {},
  pushDebugEvent: () => {},
  notifyUser: () => {},
  runChatSendJob: async (job) => { log.sent.push(job); },
  isGenerating: true,
  pendingSendQueue: [],
  queuedSendDrainActive: false,
};
vm.createContext(context);
vm.runInContext(
  [
    functionSource('queueSendJobWhileGenerating'),
    functionSource('clearMessageQueuedNote'),
    functionSource('drainQueuedSends'),
  ].join('\n'),
  context,
);

const job = {
  text: 'change tuesday to 9',
  docsToSend: [],
  imagesToSend: [],
  suggestionUserContext: 'change tuesday to 9',
  clientMessageId: 'u-queued-1',
};

const checks = {};

// 1. Queue while generating: parked, rendered, visibly marked as queued.
context.queueSendJobWhileGenerating(job);
checks.queued = context.pendingSendQueue.length === 1 && context.pendingSendQueue[0] === job;
checks.markedAlreadyRendered = job._alreadyRendered === true;
checks.renderedUserMessage = log.rendered.length === 1
  && log.rendered[0].role === 'user'
  && log.rendered[0].content === 'change tuesday to 9'
  && log.rendered[0].id === 'u-queued-1';
const row = rowsById.get('u-queued-1');
const note = row ? row.querySelector('.message-queued-note') : null;
checks.visibleQueuedNote = Boolean(note) && /queued/i.test(String(note.textContent))
  && /when the current reply finishes/i.test(String(note.textContent));

// 2. Draining while STILL generating must not send anything.
await vm.runInContext('drainQueuedSends()', context);
checks.noSendWhileGenerating = log.sent.length === 0 && context.pendingSendQueue.length === 1;

// 3. Once the reply finishes (isGenerating false), the queued job is sent.
context.isGenerating = false;
await vm.runInContext('drainQueuedSends()', context);
checks.autoSentAfterReply = log.sent.length === 1
  && log.sent[0] === job
  && context.pendingSendQueue.length === 0;

// 4. The queued note is removed once the job actually sends.
context.clearMessageQueuedNote('u-queued-1');
checks.noteClearedOnSend = row ? row.querySelector('.message-queued-note') === null : false;

// 5. Wiring: the isGenerating branch of handleSend must queue, and the old
//    fire-and-forget "interrupt" POST (whose stream nobody read, so the reply
//    could never render) must be gone. The old branch was the only fetch()
//    inside handleSend, so its absence is checked as code, not as a word --
//    a comment may still NAME busy_strategy while explaining the defect.
const handleSendSource = functionSource('handleSend');
checks.handleSendQueues = handleSendSource.includes('queueSendJobWhileGenerating(');
checks.blindInterruptGone = !handleSendSource.includes('fetch(');

const failures = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
if (failures.length > 0) throw new Error(`chat send-queue checks failed: ${failures.join(', ')}`);
process.stdout.write(`${JSON.stringify(checks)}\n`);
