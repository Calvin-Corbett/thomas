import { installFeature, installModelFixture } from './chat_feature_fixture.mjs';
// Execute the live shell functions and transport with controlled network timing.
// DOM text, controller ownership, requests, and draft files are asserted together.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const htmlPath = process.argv[2];
const html = fs.readFileSync(htmlPath, 'utf8');
const jsDir = path.join(path.dirname(htmlPath), 'js');
function source(name, next) {
  const start = html.search(new RegExp(`(?:async )?function ${name}\\(`));
  const end = html.slice(start).search(new RegExp(`\\n    (?:async )?function ${next}\\(`));
  assert.ok(start >= 0 && end > 0, `live ${name} function is present`);
  return html.slice(start, start + end) + '\n';
}
const init = html.slice(html.indexOf('    function captureConversation('), html.indexOf('    const msgRefs ='));
const threadSignatureState = html.slice(html.indexOf('    let renderedThreadSignature'), html.indexOf('    async function hydrateSelectedChat('));
const wiring = html.slice(html.indexOf('    const turnFlow ='), html.indexOf('    window.ThomasChatMediaBridge.bind('));
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function harness() {
  const requests = [], sessions = [], frames = new Map(), storage = new Map();
  const state = { messages: [{ role: 'user', text: 'A question' }], sessionId: 'session-A',
    activeChat: 'chat-A', docs: [], images: [], dials: {}, input: '', profile: '', modelLabel: '' };
  let paints = 0, effects = 0, serial = 0;
  const ctx = { console, AbortController, DOMException, TextDecoder, URLSearchParams, window: { location: { search: "" } }, state,
    chatSelectionToken: 0, abortController: null, timer: null, _pendingCanvasIntent: false,
    profilesData: [], msgRefs: [], inputEl: { value: '', focus() {} },
    threadEl: { innerHTML: '', appendChild() {} }, canvasState: {},
    chatList: [{ id: 'chat-B', sessionId: 'session-B', msgs: [
      { role: 'user', text: 'B question' }, { role: 'assistant', text: 'B answer' }] }],
    localStorage: { setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k), getItem: k => storage.get(k) },
    document: { activeElement: null, createElement: () => ({ remove() {} }) },
    requestAnimationFrame(fn) { frames.set(++serial, fn); return serial; },
    cancelAnimationFrame: id => frames.delete(id), setTimeout, clearTimeout, clearInterval,
    fetch(url, opts = {}) {
      if (url === '/api/issues') return Promise.resolve({ok:true});
      // These turn-ownership cases keep their cached transcript when hydration has no server copy.
      if (url.startsWith('/api/v2/chat/session/') && !opts.method) return Promise.resolve({ ok: false, status: 404 });
      const request = { ...deferred(), url, opts };
      if (url === '/api/session/new') sessions.push(request);
      else {
        requests.push(request);
        opts.signal?.addEventListener('abort', () => request.reject(new DOMException('Stopped', 'AbortError')), { once: true });
      }
      return request.promise;
    },
    buildMessageNode(m, idx) {
      const node = { textContent: m.text, insertAdjacentElement() {} };
      ctx.msgRefs[idx] = { bubbleEl: node }; return node;
    },
    appendMessage(m) { ctx.buildMessageNode(m, state.messages.indexOf(m)); },
    updateStreamingBubble(idx) { paints++; ctx.msgRefs[idx].bubbleEl.textContent = state.messages[idx].text; },
    renderActivity() {}, detectVisualIntent: () => false,
    maybePromptChatGPTConnection: async () => {}, restoreVerifiedChatArtifacts: async () => {},
    restoreDelegationCards() {}, hydrateProfileModels: async () => {},
  };
  for (const name of ['setExternalBusy', 'scrollEnd', 'renderAttachments', 'showChat', 'resetCanvasForConversation',
    'renderChats', 'syncView', 'autosize', 'syncDynamic', 'reportFriction', '_settleActivityForReply', 'setProfile', 'renderModelMenu']) ctx[name] = () => {};
  for (const name of ['canvasDocumentDone', 'refreshChats', 'canvasStop', 'canvasRender', 'reconcileHandoff',
    'applyModelRuntimeReceipt', 'handleHandoff', 'handleTaskContract', 'addToolStep', 'finishToolStep']) ctx[name] = () => { effects++; };
  vm.createContext(ctx);
  installModelFixture(ctx, htmlPath);
  for (const file of ['chat_turn_flow.js', 'chat_stream_consumer.js', 'chat_boot.js']) vm.runInContext(fs.readFileSync(path.join(jsDir, file), 'utf8'), ctx);
  ctx.document.getElementById ||= () => null;
  vm.runInContext(init + source('boot', 'modeChanged'), ctx);
  ctx.ensureSession = vm.runInContext('ensureSession', ctx);
  installFeature(ctx, htmlPath, 'stream_actions', ['chunkText', 'streamReal']);
  installFeature(ctx, htmlPath, 'session_restore', ['newChat', 'hydrateSelectedChat', 'selectChat']);
  installFeature(ctx, htmlPath, 'message_view', ['editMessageFrom']);
  installFeature(ctx, htmlPath, 'activity_actions', ['cancelTask', 'stopChat', 'isChatBusy', 'requestTaskCancel']);
  installFeature(ctx, htmlPath, 'delegation_updates', ['announceCompletion', 'queueCompletionAnnouncement', 'pollDelegations']);
  vm.runInContext(wiring, ctx);
  ctx.turnFlow = vm.runInContext('turnFlow', ctx);

  return { ctx, state, requests, sessions, storage, frames, counts: () => ({ paints, effects }),
    run: code => vm.runInContext(code, ctx),
    session(index = 0, sid = 'created-session') { sessions[index].resolve({ ok: true, json: async () => ({ session_id: sid }) }); },
    reply(index = 0, text = 'answer') { requests[index].resolve({ ok: true, text: async () => JSON.stringify({ type: 'text', text }) + '\n' }); },
    flush() { for (const fn of frames.values()) fn(); frames.clear(); },
  };
}
const checks = [];
async function check(name, run) { await run(); checks.push(name); }

await check('ordinary streaming paints and cleans its controller', async () => {
  const h = harness(), p = h.ctx.streamReal('A question'); await tick();
  h.reply(); await p;
  assert.equal(h.state.messages[1].text, 'answer');
  assert.equal(h.ctx.msgRefs[1].bubbleEl.textContent, 'answer');
  assert.equal(h.state.streaming, false); assert.equal(h.ctx.abortController, null);
});
await check('old abort cannot overwrite B or clear its active controller', async () => {
  const h = harness(), p = h.ctx.streamReal('A question'); await tick();
  h.ctx.selectChat('chat-B');
  const next = h.ctx.streamReal('B follow-up'), controller = h.ctx.abortController;
  await p; await tick();
  assert.equal(h.state.messages[1].text, 'B answer');
  assert.equal(h.ctx.msgRefs[1].bubbleEl.textContent, 'B answer');
  assert.equal(h.ctx.abortController, controller); assert.equal(h.state.streaming, true);
  h.reply(1, 'B follow-up answer'); await next;
});
await check('New Chat during abort leaves an empty usable transcript', async () => {
  const h = harness(), p = h.ctx.streamReal('A question'); await tick();
  h.ctx.newChat(); await p; h.session(); await tick(); h.flush();
  assert.equal(h.state.messages.length, 0); assert.equal(h.state.streaming, false);
  assert.equal(h.state.sessionId, 'created-session');
});
await check('late events and scheduled paints never affect the new selection', async () => {
  const h = harness(), p = h.ctx.streamReal('A question'); await tick();
  let sink;
  h.requests[0].resolve({ ok: true, body: new ReadableStream({ start(c) { sink = c; } }) });
  await tick();
  const emit = event => sink.enqueue(new TextEncoder().encode(JSON.stringify(event) + '\n'));
  emit({ type: 'text', text: 'old partial' }); await tick();
  h.ctx.selectChat('chat-B'); const before = h.counts(); h.flush();
  for (const type of ['thinking', 'tool_start', 'model_runtime', 'delegation_started', 'task_phase', 'error', 'done'])
    emit({ type, text: 'late', session_id: 'session-A', error: 'old failure' });
  sink.close(); await p;
  assert.deepEqual(h.counts(), before); assert.equal(h.state.sessionId, 'session-B');
  assert.equal(h.ctx.msgRefs[1].bubbleEl.textContent, 'B answer');
});
await check('Stop during pending session creation is immediate and keeps queued sends usable', async () => {
  const h = harness(); h.state.sessionId = null;
  const p = h.ctx.streamReal('A question'); h.ctx.abortController.abort(); await p;
  assert.match(h.state.messages[1].text, /\[stopped\]/); assert.equal(h.state.streaming, false);
  assert.equal(h.requests.length, 0);
  const next = h.ctx.streamReal('follow-up'); assert.equal(h.sessions.length, 1);
  h.session(); await tick(); h.reply(); await next;
});
await check('late New Chat response cannot replace selected B session', async () => {
  const h = harness(); h.ctx.newChat(); h.ctx.selectChat('chat-B'); h.session(); await tick();
  assert.equal(h.state.activeChat, 'chat-B'); assert.equal(h.state.sessionId, 'session-B');
  assert.equal(h.storage.get('thomas_last_session'), 'session-B');
});
await check('new selections isolate concurrent session requests', async () => {
  const h = harness(); h.ctx.newChat(); h.ctx.newChat();
  h.session(1, 'newest'); await tick(); h.session(0, 'stale'); await tick();
  assert.equal(h.state.sessionId, 'newest'); assert.equal(h.storage.get('thomas_last_session'), 'newest');
});
await check('first send shares session creation and snapshots attachments before awaiting', async () => {
  const h = harness(); h.ctx.newChat();
  h.state.docs = [{ name: 'sent.txt' }]; const p = h.ctx.streamReal('A question');
  h.state.docs = [{ name: 'draft.txt' }]; h.state.images = [{ name: 'draft.png' }];
  assert.equal(h.sessions.length, 1); h.session(); await tick();
  const payload = JSON.parse(h.requests[0].opts.body);
  assert.deepEqual(payload.docs, [{ name: 'sent.txt' }]); assert.deepEqual(payload.images, []);
  assert.equal(payload.session_id, 'created-session');
  assert.equal(h.state.docs[0].name, 'draft.txt'); assert.equal(h.state.images[0].name, 'draft.png');
  h.reply(); await p;
});
await check('Stop drains only queued attachments and preserves the unsent draft', async () => {
  const h = harness(), p = h.ctx.streamReal('A question'); await tick();
  h.state.input = 'queued'; h.state.docs = [{ name: 'queued.txt' }]; h.run('turnFlow.enqueue()');
  h.state.input = 'unsent'; h.state.docs = [{ name: 'draft.txt' }]; h.state.images = [{ name: 'draft.png' }];
  h.ctx.abortController.abort(); await p; await tick();
  const payload = JSON.parse(h.requests[1].opts.body);
  assert.equal(payload.message, 'queued'); assert.deepEqual(payload.docs, [{ name: 'queued.txt' }]);
  assert.deepEqual(payload.images, []); assert.equal(h.state.input, 'unsent');
  assert.equal(h.state.docs[0].name, 'draft.txt'); assert.equal(h.state.images[0].name, 'draft.png');
  h.reply(1); await tick(); assert.equal(h.state.streaming, false);
});
await check('late boot never restores over an explicitly selected chat', async () => {
  const h = harness(); h.state.sessionId = null; h.state.messages = [];
  const boot = h.ctx.boot(); h.ctx.selectChat('chat-B');
  h.requests[0].resolve({ ok: false }); await boot;
  assert.equal(h.state.sessionId, 'session-B'); assert.equal(h.sessions.length, 0);
});
await check('late edit and announcement cannot change the selected transcript', async () => {
  const h = harness(), edit = h.ctx.editMessageFrom(0);
  h.ctx.selectChat('chat-B'); h.requests[0].resolve({ ok: true }); await edit;
  assert.equal(h.state.messages[0].text, 'B question'); assert.equal(h.state.input, '');
  const announcement = h.ctx.announceCompletion('worker-B');
  h.ctx.newChat(); h.requests[1].resolve({ ok: true, json: async () => ({ ok: true, message: 'old result' }) });
  assert.equal(await announcement, false); assert.equal(h.state.messages.length, 0);
  h.session(); await tick();
});
await check('late task cancellation never aborts a different conversation', async () => {
  const h = harness();
  h.state.messages[0].activity = { steps: [{ kind: 'handoff', status: 'running', id: 'worker-A' }] };
  h.state.messages[0].streaming = true;
  const cancel = h.ctx.cancelTask(0); h.ctx.selectChat('chat-B');
  const controller = new AbortController(); h.ctx.abortController = controller;
  h.requests[0].resolve({ ok: true, json: async () => ({ ok: true }) }); await cancel;
  assert.equal(controller.signal.aborted, false);
});
await check('pending delegation poll stops after changing conversations', async () => {
  const h = harness(); let wake;
  h.ctx.setTimeout = fn => { wake = fn; return 1; };
  h.state.messages[0].activity = { steps: [{ kind: 'handoff', status: 'running', id: 'worker-A' }] };
  const poll = h.ctx.pollDelegations(0); h.ctx.selectChat('chat-B'); wake(); await poll;
  assert.equal(h.requests.length, 0);
});

await check('first send from blank Chat clears the prior restore row without New Chat', async () => {
  const h = harness(); h.state.sessionId = null; h.state.activeChat = null;
  h.state.messages = []; h.storage.set('thomas_last_chat', 'old-chat');
  h.storage.set('thomas_last_session', 'old-session');
  const turn = h.ctx.streamReal('new chat without the New Chat button');
  h.session(0, 'new-session'); await tick(); h.reply(); await turn;
  assert.equal(h.storage.get('thomas_last_session'), 'new-session');
  assert.equal(h.storage.has('thomas_last_chat'), false);
});
console.log(JSON.stringify({ passed: checks.length, checks }));
