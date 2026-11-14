/* "Improve Thomas" selects Thomas's own source as the project, and a message sent with it selected starts a
 * Thomas project and moves the chat to it. Runs the shipped self_edit_controls.js. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context = { window: {} };
vm.createContext(context);
vm.runInContext(fs.readFileSync('thomas/server/web/js/self_edit_controls.js', 'utf8'), context);
const { selectThomas, startFromChat } = context.window.ThomasSelfEdit;

// The button picks the running checkout, the way a project card is picked: choose(root, label).
const asked = [];
context.fetch = async url => {
  asked.push(url);
  return { ok: true, json: async () => ({ build: { root: 'C:\\Users\\you\\Thomas' } }) };
};
const chosen = [];
await selectThomas(async (root, label) => { chosen.push([root, label]); });
assert.deepEqual(asked, ['/api/health']);
assert.deepEqual(chosen, [['C:\\Users\\you\\Thomas', 'Thomas']]);

// No source folder known: it says so instead of picking nothing.
context.fetch = async () => ({ ok: true, json: async () => ({ build: {} }) });
await assert.rejects(selectThomas(async () => assert.fail('nothing may be chosen')), /own source folder/);

// A message sent with Thomas selected starts a Thomas project with the words as typed, then opens it.
let posted = null;
context.fetch = async (url, init) => {
  posted = { url, method: init?.method, body: JSON.parse(init?.body || '{}') };
  return { ok: true, json: async () => ({ ok: true, conversation_id: 'fc_new', execution_id: 'thomas-1' }) };
};
const opened = [];
// In THIS tab, the way a conversation switch opens: without `withinTab` it went through the cross-tab navigator,
// which opened a second Build tab on the project and left the first one unable to start a new build.
context.window.ThomasCodeMode = { openConversation: async (cid, options) => { assert.equal(options?.withinTab, true); opened.push(cid); } };
const started = await startFromChat('  make the Send button blue  ');
assert.equal(posted.url, '/api/self/projects');
assert.equal(posted.method, 'POST');
assert.equal(posted.body.request, 'make the Send button blue');
assert.ok(posted.body.settings, 'the Build dials ride along');
assert.deepEqual(opened, ['fc_new']);
assert.equal(started.execution_id, 'thomas-1');

// A refusal reaches the person in the route's own words, and nothing is opened.
opened.length = 0;
context.fetch = async () => ({ ok: false, json: async () => ({ ok: false, error: 'Autonomy 3 may not edit Thomas' }) });
await assert.rejects(startFromChat('anything'), /Autonomy 3 may not edit Thomas/);
assert.deepEqual(opened, []);

console.log('Improve Thomas selects Thomas, and the chat starts a Thomas project: checks passed');
