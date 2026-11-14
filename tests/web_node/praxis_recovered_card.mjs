import fs from 'node:fs';
import vm from 'node:vm';

const [projectsPath, agentsPath] = process.argv.slice(2);
const snapshots = [
  { ok: true, running: false, run_id: 'run-1', praxis_recovered: {
    run_id: 'run-1', lead_attached: false, agents: [
      { agent_id: 'reader', title: 'Inspect code', kind: 'review', state: 'running', model_used: 'gpt-5.6-luna', attempts: 2 },
      { agent_id: 'writer', title: 'Build module', kind: 'write', state: 'interrupted', execution_origin: 'external_builder', model_used: 'claude-sonnet', attempts: 1 },
    ],
  } },
  { ok: true, running: false, run_id: 'run-1', praxis_recovered: {
    run_id: 'run-1', lead_attached: false, agents: [
      { agent_id: 'reader', title: 'Inspect code', kind: 'review', state: 'completed', model_used: 'gpt-5.6-luna', attempts: 2 },
      { agent_id: 'writer', title: 'Build module', kind: 'write', state: 'interrupted', execution_origin: 'external_builder', model_used: 'claude-sonnet', attempts: 1 },
    ],
  } },
];
const timers = new Map();
let nextTimer = 0;
let streams = 0;
let rendered = '';
globalThis.window = { localStorage: { getItem: () => null, setItem() {}, removeItem() {} }, addEventListener() {}, setInterval() {} };
globalThis.localStorage = window.localStorage;
globalThis.document = { readyState: 'loading', addEventListener() {}, getElementById: () => null };
globalThis.fetch = async url => {
  if (url !== '/api/evolve/agent/status?conversation_id=conv-1') throw new Error(`unexpected URL: ${url}`);
  const value = snapshots.shift();
  if (!value) throw new Error('status was polled after all children became terminal');
  return { ok: true, json: async () => value };
};
globalThis.setTimeout = fn => { const id = ++nextTimer; timers.set(id, fn); return id; };
globalThis.clearTimeout = id => timers.delete(id);
vm.runInThisContext(fs.readFileSync(agentsPath, 'utf8'), { filename: agentsPath });
vm.runInThisContext(fs.readFileSync(projectsPath, 'utf8'), { filename: projectsPath });

const state = { activeId: 'conv-1', contextEpoch: 1, running: false, finishing: false, liveEvents: [], parkedRuns: {}, runStatus: 'ready' };
window.ThomasCodeProjects.configure({ state });
const session = window.ThomasCodeProjects.createTaskSession({
  closeSource() {}, esc: value => String(value), finishBusy() {}, host: () => ({ setBusy() {} }),
  lifecycle: () => ({ contextToken: () => 1, contextMatches: () => true }),
  loadConversation() {}, loadTree() {}, openStream() { streams += 1; },
  pushLiveEvent(event) { state.liveEvents.push(event); },
  recordError() {}, recordPreferenceWarning() {}, refresh() {},
  render() { rendered = state.liveEvents.map(event => window.ThomasCodeAgentRows.render(event, String, false) || event.text || '').join(''); },
  safely() {},
});
const attached = await session.reattachRunFor('conv-1');
if (!attached || state.running || streams) throw new Error('a stopped lead was falsely reattached');
if (state.runStatus !== 'disconnected' || !rendered.includes('lead is not streaming')) throw new Error('lead disconnection was hidden');
if (!rendered.includes('Inspect code') || !rendered.includes('gpt-5.6-luna') || !rendered.includes('running')) throw new Error('read child activity was missing');
if (!rendered.includes('Build module') || !rendered.includes('interrupted')) throw new Error('external writer was falsely resumed');
if (timers.size !== 1) throw new Error('live child status must be polled once');
const [timerId, poll] = timers.entries().next().value;
timers.delete(timerId);
await poll();
if (!rendered.includes('completed') || rendered.includes(' · running')) throw new Error('child completion was not read back');
if (timers.size || streams || state.running) throw new Error('terminal children should stop polling without opening the lead stream');
process.stdout.write(JSON.stringify({ ok: true }));
