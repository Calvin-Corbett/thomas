import { installFeature } from './chat_feature_fixture.mjs';
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import path from 'node:path';

const source = fs.readFileSync(process.argv[2], 'utf8');
const bridgeSource = fs.readFileSync(path.join(path.dirname(process.argv[2]), 'chat_media_bridge.js'), 'utf8');
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
function harness(fetch, overrides = {}) {
  const messages = [], timers = [];
  const ctx = {
    document: { getElementById: () => null, addEventListener() {} },
    window: { setTimeout: fn => timers.push(fn) }, fetch,
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  ctx.window.ThomasMediaGeneration.init({
    sessionId: () => 'chat-one', prompt: () => 'A man',
    addUser: text => messages.push({ role: 'user', text }),
    addAssistant(text, streaming = false) {
      const message = { role: 'assistant', text, streaming };
      messages.push(message); return message;
    },
    finish(message, text, artifact) { Object.assign(message, { text, streaming: false, artifact }); },
    progress(message, text) { Object.assign(message, { text, streaming: true }); },
    ...overrides,
  });
  return { api: ctx.window.ThomasMediaGeneration, messages, timers };
}
const lanes = response({ lanes: { image: { configured: true } } });
{
  const h = harness(() => { throw new Error('Rendering must not start work'); });
  const esc = text => String(text).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  const html = h.api.renderArtifact({ kind: 'image', name: '<portrait>', url: '/deliverable/exec/image.png' }, esc);
  assert.match(html, /<img src="\/deliverable\/exec\/image.png"/);
  assert.match(html, /alt="&lt;portrait>"/);
  assert.doesNotMatch(html, /iframe/);
  assert.equal(h.api.renderArtifact({ kind: 'image', url: 'javascript:bad()' }, esc), '');
}

{
  const h = harness(async url => url.endsWith('/lanes') ? lanes : response({ error: 'Worker unavailable' }, 500));
  await h.api.create('image', 'A man');
  assert.equal(h.messages.filter(m => m.role === 'assistant').length, 1);
  assert.equal(h.messages.at(-1).streaming, false);
  assert.match(h.messages.at(-1).text, /could not start/);
}
{
  let polls = 0;
  const h = harness(async url => {
    if (url.endsWith('/lanes')) return lanes;
    if (url.endsWith('/generate')) return response({ job_id: 'job-one' });
    if (url.endsWith('/announce')) {
      assert.equal(url, '/api/v2/chat/session/chat-one/delegations/job-one/announce');
      return response({ ok: true, message: 'Saved image result' });
    }
    if (++polls === 1) throw new Error('Temporary network interruption');
    return response({ job: { state: 'completed', deliverable: { url: '/deliverable/job-one/image.png' } } });
  });
  await h.api.create('image', 'A man');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.timers.length, 1);
  assert.equal(h.messages.at(-1).streaming, true);
  h.timers.shift()();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(polls, 2);
  assert.equal(h.messages.at(-1).streaming, false);
  assert.ok(h.messages.at(-1).artifact);
}
{
  let release, posts = 0;
  const blocked = new Promise(resolve => { release = resolve; });
  const h = harness(async url => {
    if (url.endsWith('/lanes')) { await blocked; return lanes; }
    if (url.endsWith('/generate')) { posts++; return response({ job_id: 'job-one' }); }
    if (url.endsWith('/announce')) return response({ ok: true, skipped: 'already_reported' });
    return response({ job: { state: 'cancelled' } });
  });
  const first = h.api.create('image', 'A man');
  await h.api.create('image', 'A man');
  release(); await first;
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(posts, 1);
  assert.equal(h.messages.at(-1).streaming, false);
  assert.match(h.messages.at(-1).text, /interrupted/);
}
{
  let release, posts = 0, conversation = {};
  const ready = new Promise(resolve => { release = resolve; });
  const h = harness(async url => {
    if (url.endsWith('/lanes')) { await ready; return lanes; }
    posts++; return response({});
  }, { conversationToken: () => conversation });
  const request = h.api.create('image', 'A man');
  conversation = {};
  release(); await request;
  assert.equal(posts, 0, 'Switching chats must not submit into the new conversation');
  assert.equal(h.messages.length, 0);
}
{
  let reject, conversation = {};
  const pending = new Promise((_, fail) => { reject = fail; });
  const h = harness(async () => pending, { conversationToken: () => conversation });
  const request = h.api.create('image', 'A bus');
  await new Promise(resolve => setImmediate(resolve));
  conversation = {};
  reject(new Error('Old conversation failed'));
  await request;
  assert.equal(h.messages.length, 0, 'Late preflight error must not appear in another chat');
}
{
  let reject, conversation = {};
  const pending = new Promise((_, fail) => { reject = fail; });
  const h = harness(() => { throw new Error('No HTTP before a session exists'); }, {
    conversationToken: () => conversation, ensureSession: () => pending,
  });
  const request = h.api.create('image', 'A bus');
  conversation = {};
  reject(new Error('Old session allocation failed'));
  await request;
  assert.equal(h.messages.length, 0, 'Late session allocation error must not appear in another chat');
}
{
  let allow = false, posts = 0;
  const h = harness(async url => {
    if (url.endsWith('/lanes')) return lanes;
    if (url.endsWith('/generate')) { posts++; return response({ job_id: 'allowed' }); }
    return response({ job: { state: 'cancelled' } });
  }, { canCreate: () => allow, prompt: () => '' });
  await h.api.create('image', 'A bus');
  assert.equal(posts, 0, 'Pending uploads or active text replies must block media submission');
  assert.equal(h.messages.length, 0);
  allow = true;
  await h.api.create('image');
  assert.equal(h.api.armedMedium(), 'image');
  h.api.resetContext();
  assert.equal(h.api.armedMedium(), '', 'An armed media lane belongs to its original conversation');
  await h.api.create('image', 'A bus');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(posts, 1);
}
{
  const html = fs.readFileSync(process.argv[3], 'utf8');
  const mapping = html.slice(html.indexOf('    function mapRealMessages('), html.indexOf('    async function refreshChats('));
  const restore = html.slice(html.indexOf('    async function restoreVerifiedChatArtifacts('), html.indexOf('    async function restoreDelegationCards('));
  const restoreCards = html.slice(html.indexOf('    async function restoreDelegationCards('), html.indexOf('    let renderedThreadSignature')) + '\n';
  const artifact = { name: 'generated-image.png', kind: 'image', url: '/deliverable/exec-image/generated-image.png' };
  for (const legacy of [false, true]) {
    const painted = [];
    const ctx = { window: {}, state: { activeChat: 'chat-one', sessionId: 'sid', modelLabel: '' }, chatSelectionToken: 7,
      fetch: async () => response({ delegations: [{ execution_id: 'exec-image', session_id: 'sid', artifacts: [artifact] }] }),
      _completionVerified: () => true, _canvasReviewed: () => false,
      threadEl: { innerHTML: '', appendChild: node => painted.push(node) }, msgRefs: [],
      buildMessageNode: (message, index) => ({ message, index }),
      syncDynamic() {}, scrollEnd() {},
      _mergeArtifacts() { throw new Error('An announced artifact must not enter the aggregate fallback'); },
    };
    vm.createContext(ctx); vm.runInContext(bridgeSource, ctx);
    installFeature(ctx, process.argv[3], 'history_view', ['mapRealMessages']);
    installFeature(ctx, process.argv[3], 'session_restore', ['restoreVerifiedChatArtifacts', 'restoreDelegationCards']);
    const metadata = { announce: 'exec-image' };
    if (!legacy) metadata.artifacts = [artifact];
    ctx.state.messages = ctx.mapRealMessages([
      { role: 'assistant', content: 'Your image is ready', metadata },
      { role: 'user', content: 'What is two plus two?' },
      { role: 'assistant', content: 'Four.' },
    ], '');
    if (!legacy) assert.equal(ctx.state.messages[0].artifacts[0].url, artifact.url);
    await ctx.restoreVerifiedChatArtifacts('chat-one', 'sid', 7);
    assert.equal(ctx.state.messages[0].artifacts[0].url, artifact.url);
    assert.equal(ctx.state.messages[2].artifacts, undefined);
    assert.equal(ctx.state.messages[2].activity, undefined);
    assert.equal(painted.length, 3, 'The restored original reply must be repainted');
    vm.runInContext(fs.readFileSync(path.join(path.dirname(process.argv[3]), 'js/chat_turn_flow.js'), 'utf8'), ctx);

    let polled = false;
    ctx.pollDelegations = () => { polled = true; };
    ctx.fetch = async () => response({ delegations: [
      { execution_id: 'exec-image', session_id: 'sid', state: 'verified', artifacts: [artifact] },
      { execution_id: 'exec-other', session_id: 'sid', state: 'executing', summary: 'Another task' },
    ] });
    await ctx.restoreDelegationCards('chat-one', 'sid', 7);
    assert.equal(polled, true, 'The other live execution remains observed');
    assert.deepEqual(Array.from(ctx.state.messages[2].activity.steps, step => step.id), ['exec-other']);
    assert.equal(ctx.state.messages[0].artifacts[0].url, artifact.url);
  }
}
console.log('Media startup, retry, cancellation, duplicate-submit and reply-bound reload checks passed');
