import { installFeature, readChatFeatures } from './chat_feature_fixture.mjs';
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const html = readChatFeatures(process.argv[2]);
const moduleSource = fs.readFileSync(process.argv[3], 'utf8');
const esc = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const context = { window: {}, esc, console, state: { messages: [{ activity: { steps: [], artifacts: [] } }] } };
vm.createContext(context);
vm.runInContext(moduleSource, context);
const flow = context.window.ThomasChatTurnFlow;

Object.assign(context, {
  captureConversation: () => () => true, fetch: async () => ({ ok: true, json: async () => ({ ok: true, skipped: 'already_reported' }) }),
  renderActivity() {}, setExternalBusy() {}, _maybeCollapseActivity() {}, deMd: value => value,
  _handoffStep: (activity, id) => activity.steps.find(step => step.id === id),
  artifactHTML: () => '', _stepsLog: () => '', _activityDetail: () => '',
  canvasLiveHTML: () => { throw new Error('Unverified file previewed'); },
  canvasConstruct: () => { throw new Error('Unverified file previewed'); },
});
installFeature(context, process.argv[2], 'activity_actions', ['_completionVerified', '_mergeArtifacts']);
installFeature(context, process.argv[2], 'delegation_updates', ['handleHandoff', 'reconcileHandoff']);
installFeature(context, process.argv[2], 'activity_view', ['activityHTML']);

const partial = {
  execution_id: 'exec-partial', session_id: 'own-chat', state: 'failed', type: 'delegation_failed',
  proof_status: 'failed', receipt: { ok: false }, artifacts: [],
  partial_artifacts: [{ name: '<draft>.html', path: 'draft.html', kind: 'file', status: 'unverified', url: '/deliverable/exec-partial/draft.html?download=1' }],
};
context.handleHandoff(0, partial);
const activity = context.state.messages[0].activity;
assert.equal(activity.steps[0].status, 'failed');
assert.equal(activity.artifacts.length, 0);
assert.equal(activity.partialArtifacts.length, 1);
const rendered = context.activityHTML(context.state.messages[0]);
assert.match(rendered, /Partial files — not verified/);
assert.match(rendered, /Download &lt;draft&gt;.html/);
assert.match(rendered, /href="\/deliverable\/exec-partial\/draft.html\?download=1" download/);
assert.doesNotMatch(rendered, /<iframe|data-artifact-open|srcdoc|verified deliverables|>Done</);
flow.mergePartialArtifacts(activity, partial);
assert.equal(activity.partialArtifacts.length, 1, 'polling must not duplicate a file');

for (const [state, expected] of [['cancelled', 'cancelled'], ['abandoned', 'failed']]) {
  context.state.messages[0].activity = { steps: [], artifacts: [] };
  const row = { ...partial, type: 'delegation_progress', state };
  context.handleHandoff(0, row);
  const card = context.state.messages[0].activity;
  assert.equal(card.steps[0].status, expected);
  assert.equal(card.partialArtifacts.length, 1);
  card.partialArtifacts = [];
  context.reconcileHandoff(0, row);
  assert.equal(card.steps[0].status, expected, 'polling and streaming use the same terminal state');
  assert.equal(card.partialArtifacts.length, 1, 'polling restores partial files too');
  assert.doesNotMatch(context.activityHTML(context.state.messages[0]), /data-act-cancel|>Done</);
}

const restored = { steps: [], artifacts: [] };
flow.mergeRestoredSteps(restored, flow.planDelegationRestore([
  partial, { ...partial, execution_id: 'other', session_id: 'other-chat' },
], 'own-chat', [{ role: 'assistant' }]));
assert.equal(restored.partialArtifacts.length, 1);
assert.equal(restored.steps[0].status, 'failed');
flow.mergePartialArtifacts(restored, { ...partial, state: 'executing' });
assert.equal(restored.partialArtifacts.length, 0, 'stale partial files must not accompany an active retry');
flow.mergePartialArtifacts(restored, { ...partial, partial_artifacts: [
  { ...partial.partial_artifacts[0], url: 'javascript:alert(1)' },
  { ...partial.partial_artifacts[0], status: 'verified' },
] });
assert.equal(restored.partialArtifacts.length, 0);

const verified = { artifacts: [] };
flow.mergeArtifacts(verified, { artifact_url: '/deliverable/ok/result.txt', artifact_name: 'result.txt' });
flow.mergeArtifacts(verified, { artifacts: [{ id: 'proof', url: '/deliverable/ok/result.txt', name: 'result.txt' }] });
assert.equal(verified.artifacts.length, 1, 'moving the existing merge must preserve deduplication');
const original = { id: 'old', url: '/deliverable/revision/old.png', name: 'old.png' };
const revised = { id: 'new', url: '/deliverable/revision/new.png', name: 'new.png' };
const sibling = { id: 'other', url: '/deliverable/other/report.pdf', name: 'report.pdf' };
const reordered = { artifacts: [original, sibling, revised] };
flow.mergeArtifacts(reordered, { artifacts: [revised, original] });
assert.equal(reordered.artifact.url, revised.url, 'a new primary order must replace the cached old preview');
assert.deepEqual(Array.from(reordered.artifacts, a => a.url), [revised.url, sibling.url, original.url]);
flow.mergeArtifacts(reordered, { artifacts: [revised, revised, original] });
assert.equal(reordered.artifacts.length, 3, 'repeated ordered updates must keep deduplication');
assert.equal(reordered.artifact.url, revised.url);
assert.ok(html.includes('window.ThomasChatTurnFlow.mergePartialArtifacts(a, row);'), 'polling is wired');
process.stdout.write('Partial download rendering, event delivery, restore, scope, and verified deduplication passed.\n');
