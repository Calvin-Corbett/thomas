// The chat task card's steer box: a named control that reports what happened.
//
// Measured on the live card (2026-09-24): "i also dont like its streaming of
// whats going on its ugly, doenst work or confusing, the is no steer mode."
// Three defects behind that, all on this box:
//
//   1. Pressing Enter left the caret in the input, and renderActivity refused to
//      repaint a card whose steer input had focus (a guard against the
//      delegation poll wiping a half-typed note). So the send produced no
//      "Sending…", no outcome, nothing at all — the control looked dead.
//   2. Every failure read "Couldn't reach the running task just now.", which
//      claims a network problem for a task that had already finished, and the
//      server's actual reason was discarded.
//   3. The heading said "JUMP IN" and the draft lived in the DOM node, so the
//      next poll erased what had been typed.
//
// Drives the real modules: js/steering_language.js (shared wording),
// js/chat_activity_view.js (_activityDetail markup) and
// js/chat_activity_actions.js (steerActivity + renderActivity).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const [languagePath, viewPath, actionsPath] = process.argv.slice(2);
if (!languagePath || !viewPath || !actionsPath) {
  throw new Error('usage: node chat_steer_box_explains_refusals.mjs <steering_language.js> <chat_activity_view.js> <chat_activity_actions.js>');
}

const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const requests = [];
let routes = {};

function reply(url) {
  const match = Object.keys(routes).find(key => String(url).includes(key));
  return routes[match] || { ok: false, status: 500, body: {} };
}

const context = {
  window: {},
  console,
  document: { activeElement: null, createElement: () => ({}) },
  async fetch(url, options = {}) {
    requests.push({ url: String(url), body: JSON.parse(String(options.body || '{}')) });
    const row = reply(url);
    return { ok: row.ok, status: row.status, async json() { if (row.unreadable) throw new Error('not json'); return row.body; } };
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(languagePath, 'utf8'), context, { filename: languagePath });
vm.runInContext(fs.readFileSync(viewPath, 'utf8'), context, { filename: viewPath });
vm.runInContext(fs.readFileSync(actionsPath, 'utf8'), context, { filename: actionsPath });

const view = context.window.ThomasChatActivityView.create({ esc, deMd: String, _isTextArtifact: () => false });

// ---- the markup a person reads -----------------------------------------------
const runningActivity = (extra = {}) => Object.assign({
  steps: [{ kind: 'handoff', id: 'exec-1', worker: 'writer', status: 'running' }],
  timeline: [], artifacts: [], artifact: null, expanded: true,
}, extra);

const idle = view._activityDetail(runningActivity());
assert.match(idle, /Steer this running task/, 'the control says what it does');
assert.doesNotMatch(idle, /Jump in/i, 'the unnamed heading is gone');
assert.match(idle, /Applies to this running task, not a new one\./);
assert.match(idle, /<label for="tc-steer-exec-1"/, 'the label points at this card\'s own input');
assert.match(idle, /id="tc-steer-exec-1"/);
assert.match(idle, /Send update</);

const busy = view._activityDetail(runningActivity({ steerBusy: true, steerDraft: 'Use the March data', steerNote: 'Sending your update to this task…' }));
assert.match(busy, /Sending…</, 'the button says it is working');
assert.match(busy, /value="Use the March data" disabled/, 'what was typed survives, and cannot be sent twice');
assert.match(busy, /role="status"/);

const refused = view._activityDetail(runningActivity({ steerFailed: true, steerNote: 'Update not applied: This task is no longer running, so it cannot take an update.' }));
assert.match(refused, /role="alert"/, 'a refusal is announced, not whispered');

// A quoted draft must not break out of the value attribute.
const quoted = view._activityDetail(runningActivity({ steerDraft: '"><img src=x>' }));
assert.doesNotMatch(quoted, /<img src=x>/);

// ---- sending: what lands, and what is said about it --------------------------
const activity = runningActivity();
const state = { sessionId: 'session-1', messages: [{ role: 'assistant', text: 'On it', activity }] };
const input = { value: '', disabled: false, focused: false, focus() { this.focused = true; }, setSelectionRange() {}, hasAttribute: name => name === 'data-steer-input' };
const steerForm = { addEventListener() {}, querySelector: () => input };
const activityEl = {
  innerHTML: '',
  contains: node => node === input,
  querySelector: selector => ({ '[data-steer-form]': steerForm, '[data-steer-input]': input }[selector] || null),
  querySelectorAll: () => [],
};
const actions = context.window.ThomasChatActivityActions.create({
  state,
  msgRefs: [{ activityEl, bubbleEl: null }],
  captureConversation: () => () => true,
  activityHTML: message => view._activityDetail(message.activity),
  esc,
  _settledStatusText: () => null,
  bubbleInner: () => '',
  canvasRender: () => {},
  canvasStop: () => {},
  reportFriction: () => {},
  setExternalBusy: () => {},
  fetchActivityDetail: () => {},
  abortController: null,
});

routes = { '/delegations/exec-1/steer': { ok: true, status: 200, body: { ok: true, action: 'steer', execution_id: 'exec-1' } } };
// The caret is still in the box, exactly as it is after pressing Enter. The
// repaint the send asks for must happen anyway.
context.document.activeElement = input;
await actions.steerActivity(0, 'Use the March data');
assert.equal(requests.length, 1);
assert.equal(requests[0].url, '/api/v2/chat/session/session-1/delegations/exec-1/steer');
assert.deepEqual(requests[0].body, { message: 'Use the March data' });
assert.equal(activity.steerNote, 'Update sent. Thomas will read it at the next safe step.');
assert.equal(activity.steerFailed, false);
assert.equal(activity.steerDraft, '', 'a sent update is not left in the box to send twice');
assert.match(activityEl.innerHTML, /Update sent\./, 'the outcome reached the card even with the caret in the input');
assert.equal(input.focused, true, 'the caret comes back for the next update');

// An unforced repaint mid-typing still leaves the box alone.
activityEl.innerHTML = 'UNTOUCHED';
actions.renderActivity(0);
assert.equal(activityEl.innerHTML, 'UNTOUCHED', 'the delegation poll must not wipe a half-typed note');
context.document.activeElement = null;

// The ledger's own refusal, translated, with the raw execution id kept out.
requests.length = 0;
routes = { '/delegations/exec-1/steer': { ok: false, status: 404, body: { ok: false, error: "No running task matches reference 'exec-1'." } } };
await actions.steerActivity(0, 'Change course');
assert.equal(activity.steerNote, 'Update not applied: This task is no longer running, so it cannot take an update.');
assert.equal(activity.steerFailed, true);
assert.equal(activity.steerDraft, 'Change course', 'a refused update keeps what was typed');
assert.doesNotMatch(activityEl.innerHTML, /No running task matches reference/);
assert.doesNotMatch(activityEl.innerHTML, /Couldn/, 'no blanket "could not reach" for a task that answered');

// The endpoint's machine tokens, translated.
routes = { '/delegations/exec-1/steer': { ok: false, status: 409, body: { ok: false, error: 'session_mismatch' } } };
await actions.steerActivity(0, 'Change course');
assert.equal(activity.steerNote, 'Update not applied: This task belongs to a different conversation.');

// An unreadable body is still a reported failure, not a silent one.
routes = { '/delegations/exec-1/steer': { ok: false, status: 502, unreadable: true, body: {} } };
await actions.steerActivity(0, 'Change course');
assert.equal(activity.steerNote, 'Update not applied: Thomas could not be reached just now.');

// Two submits in flight would queue the same instruction twice.
requests.length = 0;
routes = { '/delegations/exec-1/steer': { ok: true, status: 200, body: { ok: true } } };
const first = actions.steerActivity(0, 'Only once');
const second = actions.steerActivity(0, 'Only once');
await Promise.all([first, second]);
assert.equal(requests.length, 1, 'a second submit while the first is in flight is refused');

// Two workers on one task: partly through is its own outcome.
requests.length = 0;
activity.steps = [
  { kind: 'handoff', id: 'exec-1', worker: 'writer', status: 'running' },
  { kind: 'handoff', id: 'exec-2', worker: 'checker', status: 'running' },
];
routes = {
  '/delegations/exec-1/steer': { ok: true, status: 200, body: { ok: true } },
  '/delegations/exec-2/steer': { ok: false, status: 404, body: { ok: false, error: "No running task matches reference 'exec-2'." } },
};
await actions.steerActivity(0, 'Use the March data');
assert.equal(requests.length, 2);
assert.equal(activity.steerNote, 'Update reached 1 of 2 workers on this task. This task is no longer running, so it cannot take an update.');
assert.equal(activity.steerFailed, false, 'something did land, so it is not a flat refusal');
assert.equal(activity.steerDraft, '', 'it landed somewhere -- resending would double it');

// Nothing running, nothing to steer.
requests.length = 0;
activity.steps = [{ kind: 'handoff', id: 'exec-1', worker: 'writer', status: 'completed' }];
await actions.steerActivity(0, 'Too late');
assert.equal(requests.length, 0);
assert.doesNotMatch(view._activityDetail(activity), /Steer this running task/, 'a settled task offers no steer box');

process.stdout.write(`${JSON.stringify({
  ok: true,
  controlIsNamed: true,
  sendSurvivesTheTypingGuard: true,
  refusalsAreTranslated: true,
  draftKeptOnFailure: true,
  noDoubleSend: true,
  partialSendReported: true,
  settledTaskHasNoBox: true,
})}\n`);
