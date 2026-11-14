"""Drive the shipped chat modules with a browser-shaped Node stand-in."""

import subprocess
from pathlib import Path

DRIVER = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = process.argv[1];
const source = name => fs.readFileSync(root + '/thomas/server/web/js/' + name, 'utf8');
const records = new Map();
let writes = 0, fail = () => false;
const storage = {
  getItem(k) { return records.has(k) ? records.get(k) : null; },
  setItem(k, v) { if (fail(++writes, k, v)) throw Error('full'); records.set(k, v); },
  removeItem(k) { if (fail(++writes, k, null)) throw Error('full'); records.delete(k); }
};
const key = id => 'thomas_chat_queue:' + id;
const saved = id => JSON.parse(storage.getItem(key(id)) || '[]');
function element(tag = 'div') {
  const el = {tag, children: [], removed: false, textContent: '', className: '', style: {},
    get isConnected() { return !this.removed && (!this.parent || this.parent.isConnected); },
    appendChild(child) { this.children.push(child); child.parent = this; return child; },
    replaceChildren() { this.children.forEach(child => { child.removed = true; }); this.children = []; this.textContent = ''; },
    insertAdjacentElement(where, child) { this.parent?.appendChild(child); return child; },
    remove() { this.removed = true; if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this); },
    addEventListener(event, fn) { this['on' + event] = fn; }, click() { this.onclick?.(); this.onClick?.(); },
    focus() {},
    querySelector(selector) {
      if (selector !== '.tc-bubble') return null;
      if (!this.bubble) { this.bubble = element(); this.appendChild(this.bubble); }
      return this.bubble;
    },
  };
  Object.defineProperty(el, 'innerHTML', {get() { return this._html || ''; },
    set(value) { this._html = value; this.children.forEach(child => { child.removed = true; }); this.children = []; this.bubble = null; }});
  return el;
}
function page(autoAccept = true) {
  const state = {activeChat: 'A', sessionId: 'A-session', messages: [{role: 'assistant', text: 'reply'}],
    input: '', docs: [], images: [], streaming: true, profile: 'p', modelId: 'old', modelLabel: 'Old model'};
  const thread = element(), refs = [], input = element('textarea'), sends = [];
  const events = {};
  const ctx = {window: {addEventListener: (type, fn) => { events[type] = fn; }},
    document: {createElement: element, getElementById: () => null}, localStorage: storage,
    fetch: async () => ({ok: false}), console};
  vm.createContext(ctx); vm.runInContext(source('chat_turn_flow.js'), ctx); vm.runInContext(source('chat_session_restore.js'), ctx);
  const draw = m => { const wrap = element(), bubble = element(); wrap.appendChild(bubble); thread.appendChild(wrap); refs[state.messages.indexOf(m)] = {wrapEl: wrap, bubbleEl: bubble}; return wrap; };
  const deps = {state, inputEl: input, msgRefs: refs, threadEl: thread, autosize() {}, syncDynamic() {}, syncView() {},
    renderAttachments() {}, scrollEnd() {}, appendMessage: draw,
    canSendQueued: selection => !selection || selection.modelId === state.modelId,
    sendNow(text, files) { sends.push({chat: state.activeChat, text, files, model: state.modelId}); state.streaming = true; if (autoAccept) files.onAccepted?.(); },
  };
  const queue = ctx.window.ThomasChatTurnFlow.create(deps);
  const notes = () => thread.children.flatMap(row => row.children).filter(n => n.className === 'tc-queued-note' && n.isConnected);
  const button = (note, text) => note.children.find(n => n.textContent === text);
  const put = (text, docs = [], images = []) => { state.input = text; state.docs = docs; state.images = images; assert.equal(queue.enqueue(), true); };
  const chatList = [{id: 'A', sessionId: 'A-session', msgs: [{role: 'assistant', text: 'reply'}]},
    {id: 'B', sessionId: null, msgs: []}];
  const sessionDeps = {state, chatList, threadEl: thread, msgRefs: refs, inputEl: input, chatSelectionToken: 0,
    showChat() {}, renderAttachments() {}, resetCanvasForConversation() {}, renderChats() {}, syncView() {},
    autosize() {}, syncDynamic() {}, scrollEnd() {}, buildMessageNode: m => { const wrap = element(), bubble = element(); wrap.appendChild(bubble); refs[state.messages.indexOf(m)] = {wrapEl: wrap, bubbleEl: bubble}; return wrap; },
    get turnFlow() { return queue; }};
  const session = ctx.window.ThomasChatSessionRestore.create(sessionDeps);
  return {state, thread, refs, sends, queue, notes, button, put, session, sessionDeps, ctx, events, draw, deps};
}
async function run() {
  let p = page();
  p.put('first', [{name: 'report.pdf'}], [{url: 'photo'}]); p.put('second');
  assert.equal(saved('A').length, 2, 'both jobs stored under chat A');
  assert.deepEqual(saved('A')[0].docs, [{name: 'report.pdf'}]); assert.deepEqual(saved('A')[0].images, [{url: 'photo'}]);
  assert.equal(p.button(p.notes()[0], 'Send now'), undefined, 'no send now while streaming');
  await p.session.selectChat('B'); p.queue.drainQueued();
  assert.equal(p.sends.length, 0, 'no cross-chat send'); assert.equal(saved('A').length, 2);
  await p.session.selectChat('A'); await Promise.resolve();
  assert.equal(p.sends.length, 1, 'return immediately sends first');
  assert.equal(p.sends[0].chat, 'A'); assert.equal(p.sends[0].text, 'first');
  assert.equal(p.sends[0].files.docs[0].name, 'report.pdf');
  assert.equal(p.sends[0].files.images[0].url, 'photo'); assert.equal(saved('A').length, 1, 'handed-off message is removed from storage');
  assert.ok(p.button(p.notes()[0], 'Remove'), 'second remains on screen');
  p.state.streaming = false; p.queue.drainQueued();
  assert.equal(p.sends[1].text, 'second'); assert.equal(saved('A').length, 0);
  records.clear(); p = page(); p.put('artifact refresh queue');
  p.sessionDeps._completionVerified = () => true;
  p.sessionDeps._canvasReviewed = () => false;
  p.sessionDeps._mergeArtifacts = (activity, row) => activity.artifacts.push(...row.artifacts);
  p.ctx.window.ThomasChatMediaBridge = {restoreReplies: () => ({restored: true, rows: []})};
  p.ctx.fetch = async () => ({ok: true, json: async () => ({delegations: []})});
  await p.session.restoreVerifiedChatArtifacts('A', 'A-session', 0);
  assert.equal(p.notes().length, 1, 'media redraw restores queued bubble'); assert.equal(saved('A')[0].text, 'artifact refresh queue');
  p.ctx.window.ThomasChatMediaBridge.restoreReplies = () => ({restored: false,
    rows: [{session_id: 'A-session', artifacts: [{name: 'result.txt'}]}]});
  p.ctx.fetch = async () => ({ok: true, json: async () => ({delegations: [{
    session_id: 'A-session', artifacts: [{name: 'result.txt'}]}]})});
  await p.session.restoreVerifiedChatArtifacts('A', 'A-session', 0);
  assert.equal(p.notes().length, 1, 'verified artifact redraw restores queued bubble');
  assert.equal(saved('A')[0].text, 'artifact refresh queue'); records.clear(); p = page(); p.put('reload one'); p.put('reload two');
  let fresh = page(); fresh.state.streaming = false; fresh.state.activeChat = 'B'; await fresh.session.selectChat('A'); await Promise.resolve();
  assert.equal(fresh.sends[0]?.text, 'reload one');
  assert.equal(fresh.notes().length, 1); assert.equal(saved('A').length, 1);
  let again = page(); again.state.streaming = false; again.state.activeChat = 'B'; await again.session.selectChat('A'); await Promise.resolve();
  assert.equal(again.sends[0]?.text, 'reload two', 'a reload cannot resend the handed-off first');
  p = page(); p.put('delete me');
  const removedRow = p.refs.at(-1).wrapEl, removedButtons = p.notes()[0].children; p.button(p.notes()[0], 'Remove').click();
  assert.equal(removedRow.isConnected, false, 'Remove takes away the complete message row');
  assert.ok(removedButtons.every(button => !button.isConnected), 'Remove takes away queued controls');
  assert.equal(p.notes().length, 0); assert.equal(saved('A').length, 0); p.state.streaming = false; p.queue.drainQueued(); assert.equal(p.sends.length, 0);
  p = page(); p.put('waiting'); p.state.streaming = false; p.state.modelId = 'new';
  p.queue.drainQueued();
  assert.match(p.notes()[0].textContent, /Old model/);
  p.button(p.notes()[0], 'Send now').click();
  assert.equal(p.sends[0].model, 'new'); assert.equal(saved('A').length, 0);
  records.clear(); p = page(); p.put('wait through hydration');
  p.state.modelId = 'new'; p.state.streaming = false;
  p.ctx.fetch = async url => ({ok: true, json: async () => url.endsWith('/delegations')
    ? {delegations: []} : {conversation: {messages: [{role: 'assistant', text: 'reply'}]}}});
  p.ctx.window.fetch = p.ctx.fetch;
  p.ctx.window.ThomasChatMediaBridge = {unannouncedRows: () => []};
  p.sessionDeps.mapRealMessages = messages => messages;
  await p.session.selectChat('B'); const hydrated = await p.session.selectChat('A');
  assert.equal(hydrated, true, 'the saved transcript was hydrated');
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  assert.equal(p.notes().length, 1, 'hydrating an unchanged transcript leaves one queued note');
  assert.equal(p.state.messages.filter(m => m.text === 'wait through hydration').length, 1,
    'hydrating the same transcript leaves one queued message in state');
  assert.equal(p.thread.children.filter(el => el.className !== 'tc-queued-note' && !el.removed).length, 2,
    'hydrating an unchanged transcript leaves one queued bubble');
  assert.equal(p.sends.length, 0, 'the unselected model keeps the queued message waiting'); records.clear(); p = page(); p.put('waiting while a normal send starts');
  p.state.streaming = false; p.state.modelId = 'new'; p.queue.drainQueued();
  assert.ok(p.button(p.notes()[0], 'Send now'));
  p.ctx.window.ThomasChatStreamConsumer = {createTextPainter: () => ({paint() {}, settle() {}})};
  p.ctx.window.ThomasChatModelSelection = {ensureCurrent: () => true};
  p.ctx.window.ThomasCodingAgentPicker = {effective: () => ''};
  p.state.dials = {autonomy: 1, fileAccess: 'none', guardrails: 'standard', effort: 'low', memory: false};
  p.ctx.AbortController = AbortController;
  vm.runInContext(source('chat_stream_actions.js'), p.ctx);
  p.deps.turnFlow = p.queue;
  const stream = p.ctx.window.ThomasChatStreamActions.create({...p.deps, turnFlow: p.queue,
    captureConversation: () => () => true, setExternalBusy() {},
    ensureSession: () => new Promise(() => {}), updateStreamingBubble() {},
    renderActivity() {}, canvasDocumentDone() {}, refreshChats() {}});
  stream.streamReal('ordinary new message');
  assert.equal(p.state.streaming, true, 'ordinary stream started');
  assert.equal(p.button(p.notes()[0], 'Send now'), undefined,
    'a normal reply starting hides Send now on a previously waiting note');
  p = page(); p.put('waiting first'); p.put('waiting second');
  p.state.streaming = false; p.state.modelId = 'new'; p.queue.drainQueued();
  assert.ok(p.button(p.notes()[1], 'Send now'), 'all idle queued notes offer Send now');
  p.button(p.notes()[0], 'Send now').click();
  assert.equal(p.button(p.notes()[0], 'Send now'), undefined, 'streaming hides Send now behind sent job');
  records.clear(); fail = () => true;
  p = page(); p.put('memory only');
  assert.match(p.notes()[0].textContent, /reload.*lose/i);
  p.state.streaming = false; p.queue.drainQueued(); assert.equal(p.sends[0].text, 'memory only');
  fail = () => false; records.clear(); writes = 0;
  p = page(); p.put('fits');
  fail = (_, k, value) => k === key('A') && value && JSON.parse(value).length > 1;
  p.put('does not fit');
  assert.match(p.notes()[0].textContent, /reload.*lose/i);
  assert.match(p.notes()[1].textContent, /reload.*lose/i);
  p.state.streaming = false; p.queue.drainQueued(); assert.equal(p.sends[0].text, 'fits');
  assert.equal(saved('A').length, 0); p.state.streaming = false; p.queue.drainQueued(); assert.equal(p.sends[1].text, 'does not fit');
  p = page(); p.put('fits'); p.put('does not fit');
  p.button(p.notes()[1], 'Remove').click(); assert.equal(p.notes().length, 1);
  p.button(p.notes()[0], 'Remove').click(); assert.equal(saved('A').length, 0);
  records.clear(); fail = () => false; writes = 0;
  p = page(); p.put('cannot remove'); p.state.streaming = false;
  fail = (_, k, value) => k === key('A') && value === null;
  p.queue.drainQueued(); assert.equal(p.sends.length, 1, 'request may start while storage retains the copy');
  assert.equal(saved('A').length, 1);
  p.state.streaming = false; p.sends[0].files.onFailed();
  assert.ok(p.button(p.notes()[0], 'Remove')); assert.ok(p.button(p.notes()[0], 'Send now'));
  assert.ok(p.notes()[0].children.some(n => /could not|failed|try again/i.test(n.textContent)));
  fail = () => false; p.button(p.notes()[0], 'Send now').click(); assert.equal(p.sends.length, 2);
  records.clear(); p = page(); p.put('retry remove'); p.state.streaming = false;
  fail = (_, k, value) => k === key('A') && value === null;
  p.button(p.notes()[0], 'Remove').click();
  assert.equal(p.notes().length, 1); assert.ok(p.button(p.notes()[0], 'Remove'));
  assert.ok(p.button(p.notes()[0], 'Send now'));
  assert.ok(p.notes()[0].children.some(n => /could not|failed|try again/i.test(n.textContent)));
  fail = () => false; p.button(p.notes()[0], 'Remove').click();
  assert.equal(p.notes().length, 0); assert.equal(saved('A').length, 0); assert.equal(p.sends.length, 0);
  records.clear(); p = page(); p.state.streaming = false;
  p.state.messages = [{role: 'user', text: 'earlier'}, {role: 'assistant', text: 'reply'}];
  p.thread.innerHTML = ''; p.refs.length = 0;
  p.state.messages.forEach(p.draw);
  p.state.streaming = true; p.put('edit queue one'); p.put('edit queue two');
  p.state.streaming = false; p.state.modelId = 'different';
  const firstBubble = p.refs[0].wrapEl, editDeps = {...p.deps, threadEl: p.thread, msgRefs: p.refs, turnFlow: p.queue,
    THEME_META: {light: {msgRule: '0'}}, avatar: () => '', esc: x => x,
    captureConversation: () => () => true, chatList: [], welcomeEl: element(),
    scrollEl: element(), renderActivity() {}, artifactHTML: () => '',
    shell: element(), sendIconEl: element(), isChatBusy: () => false, syncAttachmentState() {},
    state: p.state};
  editDeps.shell.style.setProperty = () => {}; p.ctx.requestAnimationFrame = callback => callback();
  p.state.theme = 'light'; p.state.sessionId = null;
  p.ctx.window.ThomasChatMediaBridge = {syncContext() {}};
  vm.runInContext(source('chat_message_view.js'), p.ctx);
  const view = p.ctx.window.ThomasChatMessageView.create(editDeps);
  await view.editMessageFrom(0);
  assert.equal(firstBubble.removed, true, 'earlier bubble removed on edit');
  assert.equal(p.notes().length, 2, 'both queued notes restored after edit redraw');
  assert.match(p.notes()[0].textContent, /Old model/);
  p.state.modelId = 'old'; p.queue.drainQueued();
  assert.equal(p.sends[0]?.text, 'edit queue one');
  p.state.streaming = false; p.queue.drainQueued();
  assert.equal(p.sends[1]?.text, 'edit queue two');
  records.clear(); p = page(false); p.put('remove while streaming'); p.put('send next');
  p.state.streaming = false; p.queue.drainQueued();
  p.ctx.window.ThomasChatModelSelection = {ensureCurrent: () => true};
  p.ctx.window.ThomasCodingAgentPicker = {effective: () => ''};
  p.state.dials = {autonomy: 1, fileAccess: 'none', guardrails: 'standard', effort: 'low', memory: false};
  p.ctx.AbortController = AbortController; p.ctx.fetch = async () => ({ok: true});
  let releaseStream, streamStarted;
  const begun = new Promise(resolve => { streamStarted = resolve; });
  p.ctx.window.ThomasChatStreamConsumer = {createTextPainter: paint => ({paint, settle() {}}),
    consume: (_res, emit) => new Promise(resolve => {
      releaseStream = () => { emit({type: 'text', text: 'painted reply'}); resolve(); }; streamStarted();
    })};
  vm.runInContext(source('chat_stream_actions.js'), p.ctx);
  const flow = p.ctx.window.ThomasChatStreamActions.create({...p.deps, turnFlow: p.queue,
    captureConversation: () => () => true, setExternalBusy() {}, ensureSession: async () => 'A-session',
    updateStreamingBubble(idx) { p.refs[idx].bubbleEl.textContent = p.state.messages[idx].text; },
    _settleActivityForReply() {}, renderActivity() {}, canvasDocumentDone() {}, refreshChats() {},
    maybePromptChatGPTConnection: async () => {}});
  const reply = flow.streamReal('earlier reply'); await begun;
  const liveReply = p.refs.at(-1).bubbleEl;
  p.button(p.notes()[0], 'Remove').click(); assert.equal(p.notes().length, 1);
  releaseStream(); await reply;
  assert.equal(liveReply.textContent, 'painted reply');
  assert.equal(p.sends[1]?.text, 'send next');
  records.clear(); p = page(); p.put('guarded send'); p.state.streaming = false;
  p.deps.canSendQueued = () => false; p.queue.drainQueued();
  p.button(p.notes()[0], 'Send now').click();
  assert.equal(p.sends.length, 0); assert.equal(p.notes().length, 1); assert.equal(saved('A')[0].text, 'guarded send');
  assert.match(p.notes()[0].textContent, /model cannot send/i);
  records.clear(); p = page(false); p.put('shared job');
  const copy = page(false); copy.queue.restoreQueued();
  p.state.streaming = false; copy.state.streaming = false;
  assert.equal(p.queue.drainQueued(), true);
  assert.equal(copy.queue.drainQueued(), false, 'the other copy cannot claim an in-flight job');
  p.sends[0].files.onAccepted();
  assert.equal(saved('A').length, 0); assert.equal(copy.queue.drainQueued(), false, 'accepted job is no longer stored');
  records.clear(); p = page(); p.put('after pagehide');
  p.events.pagehide(); p.state.streaming = false;
  assert.equal(p.queue.drainQueued(), false, 'pagehide prevents a new request'); assert.equal(saved('A')[0].text, 'after pagehide');
  p.events.pageshow(); assert.equal(p.queue.drainQueued(), true, 'returning from page cache permits handoff'); assert.equal(p.sends[0].text, 'after pagehide'); assert.equal(saved('A').length, 0, 'accepted handoff clears the stored copy');
  records.clear(); p = page(false); p.put('before network failure'); p.put('still waiting');
  p.state.streaming = false; p.queue.drainQueued();
  p.sends[0].files.onFailed('Network error'); p.state.streaming = false;
  assert.equal(p.queue.drainQueued(), false, 'network error does not drain the next job');
  assert.deepEqual(saved('A').map(job => job.text), ['before network failure', 'still waiting']);
  records.clear(); p = page(false); p.put('first pending'); p.put('second pending');
  p.state.streaming = false; p.queue.drainQueued();
  const firstId = saved('A')[0].id, secondId = saved('A')[1].id;
  const otherTabJob = {id: 'other-tab', text: 'other tab message', docs: [], images: [],
    selection: {modelId: 'old', modelLabel: 'Old model'}};
  storage.setItem(key('A'), JSON.stringify([saved('A')[1], otherTabJob, saved('A')[0]]));
  p.sends[0].files.onFailed('Network error');
  assert.deepEqual(saved('A').map(job => job.id), [firstId, secondId, 'other-tab'],
    'failure retries first and preserves other tabs\' stored jobs');
  assert.equal(saved('A')[0].claim, null, 'failure releases the stored claim');
  for (const leaveDuringReply of [false, true]) {
    records.clear(); p = page(false); p.put('network survivor'); p.put('next survivor');
    p.ctx.window.ThomasChatStreamConsumer = {createTextPainter: () => ({paint() {}, settle() {}}), consume: () => Promise.resolve()};
    p.ctx.window.ThomasChatModelSelection = {ensureCurrent: () => true};
    p.ctx.window.ThomasCodingAgentPicker = {effective: () => ''}; p.ctx.AbortController = AbortController;
    p.state.dials = {autonomy: 1, fileAccess: 'none', guardrails: 'standard', effort: 'low', memory: false};
    let resolveFetch; p.ctx.fetch = () => leaveDuringReply ? new Promise(resolve => { resolveFetch = resolve; }) : Promise.reject(new Error('offline'));
    vm.runInContext(source('chat_stream_actions.js'), p.ctx);
    const flow = p.ctx.window.ThomasChatStreamActions.create({...p.deps, turnFlow: p.queue,
      captureConversation: () => () => true, setExternalBusy() {}, ensureSession: async () => 'A-session',
      updateStreamingBubble() {}, renderActivity() {}, canvasDocumentDone() {}, refreshChats() {}, maybePromptChatGPTConnection: async () => {}});
    const reply = flow.streamReal('ordinary reply');
    if (leaveDuringReply) {
      for (let tick = 0; tick < 20 && !resolveFetch; tick++) await new Promise(resolve => setTimeout(resolve, 0));
      assert.equal(typeof resolveFetch, 'function', 'the reply reached fetch before pagehide');
      p.events.pagehide(); resolveFetch({ok: true});
    }
    await reply;
    assert.deepEqual(saved('A').map(row => row.text), ['network survivor', 'next survivor'], leaveDuringReply ? 'pagehide does not drain storage' : 'failed fetch does not drain storage');
    assert.equal(p.sends.length, 0);
  }
  console.log('queue persistence, conversation ownership, reload, remove, models, edit and failures: passed');
}
run().catch(e => { console.error(e); process.exitCode = 1; });
"""


def test_a_queued_message_is_never_lost():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "-e", DRIVER, str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
