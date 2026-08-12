// A completed delegation's transcript must not end on a false statement.
//
// Measured defect (2026-08-05, live): the delegation opens with a stored
// bubble — "On it — this is running now, and I'll share the result when it's
// ready." — and when the worker finishes, the Done pill and the deliverable
// card render ABOVE that bubble, so the last thing a reader sees is the stale
// present-tense promise. This harness renders the bubble the way chat.html
// does (bubbleInner over the stored message + its activity) and asserts the
// promise settles into a statement of what actually happened — and that a
// still-running task keeps its honest present tense untouched.
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error('usage: node chat_delegation_status_line_settles.mjs <chat.html>');
const html = fs.readFileSync(htmlPath, 'utf8');

function functionSource(name, nextName) {
  const start = html.indexOf(`function ${name}(`);
  let end = html.indexOf(`\n    function ${nextName}(`, start);
  if (end < 0) end = html.indexOf(`\n    async function ${nextName}(`, start);
  if (start < 0 || end < 0) throw new Error(`could not extract ${name}`);
  return html.slice(start, end);
}

const context = {};
vm.createContext(context);
vm.runInContext(
  [
    functionSource('esc', 'botHTML'),
    functionSource('bubbleInner', 'copyMessageText'),
    functionSource('_mdInline', 'mdToHtml'),
    functionSource('mdToHtml', 'renderCanvas'),
  ].join('\n'),
  context,
);

const PROMISE = "On it — this is running now, and I'll share the result when it's ready.";

function message(overrides) {
  return Object.assign({
    role: 'assistant',
    text: PROMISE,
    streaming: false,
    activity: {
      steps: [{ kind: 'handoff', id: 'exec-1', worker: 'writer', status: 'completed' }],
      artifacts: [],
      artifact: { name: 'packing.txt', url: '/deliverable/abc/packing.txt', kind: 'text' },
    },
  }, overrides);
}

const done = context.bubbleInner(message({}));
const running = context.bubbleInner(message({
  activity: { steps: [{ kind: 'handoff', id: 'exec-1', worker: 'writer', status: 'running' }], artifacts: [], artifact: null },
}));
const failed = context.bubbleInner(message({
  activity: { steps: [{ kind: 'handoff', id: 'exec-1', worker: 'writer', status: 'failed' }], artifacts: [], artifact: null },
}));
// The other stored wording (reasoning_context.py) settles too.
const contextual = context.bubbleInner(message({
  text: "On it — I'm getting this done now and I'll share the result the moment it's ready.",
}));
// A plain reply that never made the promise passes through byte-identical.
const plain = context.bubbleInner(message({ text: 'Here are three ideas for the trip.', activity: undefined }));
// No activity attached (plain stored transcript row) — nothing to settle
// against, so the text stays as stored rather than being guessed at.
const noActivity = context.bubbleInner(message({ activity: undefined }));

const checks = {
  doneDropsThePromise: !/running now/i.test(done),
  doneNamesTheDeliverable: done.includes('packing.txt') && /\bready\b/i.test(done),
  runningKeepsPresentTense: /running now/i.test(running),
  failedTellsTheTruth: !/running now/i.test(failed) && !/\bDone\b/.test(failed),
  otherWordingSettlesToo: !/getting this done now/i.test(contextual),
  plainReplyUntouched: plain.includes('Here are three ideas for the trip.'),
  noActivityLeftAlone: /running now/i.test(noActivity),
};

for (const [name, passed] of Object.entries(checks)) {
  if (!passed) throw new Error(`delegation status-line check failed: ${name}`);
}
process.stdout.write(`${JSON.stringify(checks)}\n`);
