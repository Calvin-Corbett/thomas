// The one composer, in every mode: what you send is taken, queued in view, or left in the box (2026-11-09).
//
// Work used to answer a message sent mid-reply with a bare `return`, and the shell reported success whatever the
// mode did, so the box cleared and the words were gone. This drives the shell's send() against adapters that take a
// message, queue it and refuse it, and draws Work's transcript and strip with a message waiting in the queue.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const [shellPath, supportPath] = process.argv.slice(2);
if (!shellPath || !supportPath) throw new Error('usage: node composer_keeps_what_you_send.mjs <unified_mode_shell.js> <unified_work_support.js>');

const buttons = ['chat', 'code', 'work'].map(mode => ({
  dataset: { thomasMode: mode }, classList: { toggle() {} }, setAttribute() {}, removeAttribute() {}, addEventListener() {}, focus() {},
}));
const elements = new Map(['tc-shell', 'tc-history-label', 'tc-search', 'tc-newchat', 'tc-input', 'tc-mode-surface'].map(id => [id, { dataset: {}, focus() {} }]));
globalThis.window = {};
globalThis.location = { search: '' };
globalThis.document = {
  getElementById: id => elements.get(id) || null,
  querySelectorAll: selector => (selector === '[data-thomas-mode]' ? buttons : []),
  querySelector: () => null,
};
vm.runInThisContext(fs.readFileSync(shellPath, 'utf8'), { filename: shellPath });
const modes = window.ThomasUnifiedModes;

let workAnswer = () => Promise.resolve();
const seen = [];
modes.registerAdapter('work', {
  async enter() {}, async leave() {}, async refresh() {}, isBusy: () => false,
  send(text, context) { seen.push({ text, context }); return workAnswer(); },
});
modes.connect({});

// In Chat the shell routes nothing: Chat sends its own.
assert.equal(modes.send('hello', {}), false, 'Chat is not an adapter');

await modes.setMode('work');
assert.equal(modes.mode(), 'work');

// A mode that takes the message (an async send answers a promise) is a yes.
assert.equal(modes.send('first', { docs: [{ name: 'a.txt' }], images: [] }), true);
assert.deepEqual(seen[0].context.docs, [{ name: 'a.txt' }], 'what you attached reaches the mode');

// A mode that refuses says so, and the caller keeps the text.
workAnswer = () => false;
assert.equal(modes.send('second', {}), 'refused');

// Work's own page: a message waiting in the queue is drawn where you can see it.
const sandbox = { window: {}, document: { querySelector: () => null }, console };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(supportPath, 'utf8'), sandbox, { filename: supportPath });
const state = {
  apps: [], activeApp: { id: 'app', name: 'Mail', goal: 'Sort mail' }, actionBusy: false, laneRail: [], laneProposals: [],
  stage: 'onboarding', running: true, liveTasks: [], runState: 'working',
  messages: [{ role: 'user', text: 'Sort my mail every morning' }, { role: 'assistant', text: 'Which account?' }],
  queuedSends: [{ text: 'QUEUED-MARKER the work one', files: { docs: [], images: [] }, generation: 1 }],
  structuredOnboardingState: { workflows: [] },
};
const support = sandbox.window.ThomasWorkSupport.create({
  state,
  esc: value => String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;'),
  activeWorkflowFor: () => null, statusPill: () => '', safeArtifactHref: () => '', onboardingBrief: () => '',
  jsonRequest: async () => ({}), appUrl: value => value, contextSettings: () => ({}),
});
const wizard = support.onboardingHtml();
assert.match(wizard, /You · queued/);
assert.match(wizard, /QUEUED-MARKER the work one/);
assert.match(wizard, /Sends when Thomas finishes this reply\./);
assert.ok(wizard.indexOf('Which account?') < wizard.indexOf('QUEUED-MARKER'), 'the waiting message comes after what was already said');
const strip = support.peekRows();
assert.ok(strip.some(row => row.role === 'user' && /QUEUED-MARKER.*queued/.test(row.text)), 'the strip above the composer shows it too');

state.queuedSends = [];
assert.ok(!support.onboardingHtml().includes('queued'), 'nothing waiting, nothing drawn');

console.log(JSON.stringify({ shellReportsWhatTheModeDid: true, workShowsItsQueue: true }));
