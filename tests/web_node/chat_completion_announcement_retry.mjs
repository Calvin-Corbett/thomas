import { installFeature, installInlineCore } from './chat_feature_fixture.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error('usage: node chat_completion_announcement_retry.mjs <chat.html>');
const html = fs.readFileSync(htmlPath, 'utf8');

const responses = [
  { ok: false, status: 503 },
  { ok: true, status: 200, json: async () => ({ ok: true, skipped: 'verified_text_missing' }) },
  { ok: true, status: 200, json: async () => ({ ok: true, message: 'Verified result ready.' }) },
];
const timers = [];
const warnings = [];
let fetchCalls = 0;
let appended = 0;
const state = { sessionId: 'session-1', modelLabel: 'GPT-5.6 Sol', messages: [] };
const context = {
  state,
  chatSelectionToken: 0,
  fetch: async () => {
    fetchCalls += 1;
    return responses.shift();
  },
  appendMessage: () => { appended += 1; },
  scrollEnd: () => {},
  setTimeout: (callback, delay) => {
    timers.push({ callback, delay });
    return timers.length;
  },
  console: { warn: (...args) => warnings.push(args) },
};
vm.createContext(context);
installInlineCore(context, htmlPath);
installFeature(context, htmlPath, 'delegation_updates', ['announceCompletion', 'queueCompletionAnnouncement']);

const step = { status: 'completed' };
const flush = () => new Promise(resolve => setImmediate(resolve));
context.queueCompletionAnnouncement(step, 'exec-1');
await flush();
assert.equal(fetchCalls, 1);
assert.equal(step._announced, undefined);
assert.equal(timers.length, 1);
assert.equal(timers[0].delay, 1000);

timers.shift().callback();
await flush();
assert.equal(fetchCalls, 2);
assert.equal(step._announced, undefined);
assert.equal(timers.length, 1);
assert.equal(timers[0].delay, 2000);

timers.shift().callback();
await flush();
assert.equal(fetchCalls, 3);
assert.equal(step._announced, true);
assert.equal(state.messages.at(-1).text, 'Verified result ready.');
assert.equal(appended, 1);
assert.ok(warnings.length >= 2);

// A scheduled retry belongs to the conversation that requested it. After
// switching chats it must not POST that execution ID under the new session.
responses.push({ ok: false, status: 503 });
context.queueCompletionAnnouncement({ status: 'completed' }, 'exec-stale');
await flush();
assert.equal(timers.length, 1);
const beforeSwitchCalls = fetchCalls;
context.chatSelectionToken += 1;
state.sessionId = 'session-2'; state.messages = [];
timers.shift().callback();
await flush();
assert.equal(fetchCalls, beforeSwitchCalls);
assert.equal(appended, 1);

process.stdout.write(JSON.stringify({ fetchCalls, appended, warnings: warnings.length }) + '\n');
