// Renders unified_code_events.js turns straight through its create() seam, with
// stub deps, and reports the HTML for python-side assertions. Four claims:
//
//   1. A run filed as failed whose transcript nevertheless carries a `final`
//      event with text PRODUCED an answer, and that answer must render -- with
//      the failure note alongside, never instead. (The no-auto-reject rule
//      applied to rendering: the pipeline may add sight, it may not discard
//      work the model produced.)
//   2. The stale review-limit excuse is NOT an answer; the existing contract
//      that suppresses it in favour of the authoritative failure summary must
//      survive the change above.
//   3. A deliberately STOPPED run (recorder outcome 'stopped' / reason
//      "stopped by you") renders its own neutral note, not the red failure
//      pipeline.
//   4. On an OK run, recovered tool errors are labelled "failed attempts,
//      recovered" rather than "issues", and the very first read probe of a
//      brand-new empty project is a neutral existence note, not a red row.
import fs from 'node:fs';
import vm from 'node:vm';

const eventsPath = process.argv[2];

globalThis.window = {};
vm.runInThisContext(fs.readFileSync(eventsPath, 'utf8'), { filename: eventsPath });

const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const api = window.ThomasCodeEvents.create({
  MAX_VISIBLE_PROGRESS_EVENTS: 120,
  MAX_PROGRESS_EVENT_CHARS: 420,
  NARRATIVE_EVENT_KINDS: new Set(['approval', 'disconnected', 'done', 'final', 'insight', 'planning', 'say', 'steering', 'stopped', 'stopping']),
  state: { running: false, runStartedAt: 0 },
  esc,
  codeResults: () => ({ artifactCardsHtml: () => '', runReportHtml: () => '' }),
  surface: () => null,
  isInternalResultPath: () => false,
  safely: async action => action(),
  pushLiveEvent: () => {},
  render: () => {},
  send: () => {},
});

const lines = rows => rows.map(row => JSON.stringify(row)).join('\n');

const report = {};

// 1. Failed run that produced a final answer anyway.
report.failedWithAnswer = api.turnHtml({
  role: 'agent', ok: false, reason: 'exited 1',
  transcript: lines([
    { fc: 'say', text: 'Working through the request.' },
    { fc: 'error', text: 'verification failed (exit 1) after fix attempts' },
    { fc: 'final', text: 'THE-PRODUCED-ANSWER: here is what I found in your project.' },
  ]),
});

// 2. Control: the stale review-limit excuse is not an answer and must stay
// replaced by the authoritative summary (pins the existing contract in
// tests/web_node/unified_code_mode_lifecycle.mjs).
report.failedWithStaleExcuse = api.turnHtml({
  role: 'agent', ok: false,
  transcript: lines([
    { fc: 'final', text: 'I cannot continue because the review budget forbids another tool call.' },
    { fc: 'error', text: 'verification failed (exit 1) after fix attempts' },
  ]),
});

// 3a. Stopped run, identified by the recorder's reason wording.
report.stoppedByReason = api.turnHtml({
  role: 'agent', ok: false, returncode: 1,
  reason: 'stopped by you — 2 file(s) had already changed',
  transcript: lines([{ fc: 'say', text: 'partway through the build' }]),
});

// 3b. Stopped run, identified by the recorder's outcome field.
report.stoppedByOutcome = api.turnHtml({
  role: 'agent', ok: false, outcome: 'stopped', reason: 'stopped by you',
  transcript: lines([{ fc: 'say', text: 'partway through the build' }]),
});

// 3c. Control: a genuinely failed run keeps the red failure pipeline.
report.genuinelyFailed = api.turnHtml({
  role: 'agent', ok: false, reason: 'exited 1',
  transcript: lines([{ fc: 'error', text: 'verification failed (exit 1) after fix attempts' }]),
});

// 4a. OK run with recovered tool errors (the model's own scratch-verifier
// retries on the clock build: 7 failed attempts, then success).
report.okWithRecoveredAttempts = api.turnHtml({
  role: 'agent', ok: true, changed_files: ['clock.html'],
  transcript: lines([
    ...Array.from({ length: 7 }, (_v, i) => ({ fc: 'tool_result', name: 'scratch.verify', text: `verifier attempt ${i + 1} failed`, is_error: true })),
    { fc: 'tool_result', name: 'scratch.verify', text: 'verifier passed' },
    { fc: 'final', text: 'Built the clock and verified it ticks.' },
  ]),
});

// 4b. OK run whose FIRST tool_result is the expected read probe of a
// brand-new empty project -- an existence check, not a fault.
report.okWithFirstProbe = api.turnHtml({
  role: 'agent', ok: true, changed_files: ['index.html'],
  transcript: lines([
    { fc: 'tool_result', name: 'fs.read_file', text: 'read failed: index.html not found', is_error: true },
    { fc: 'tool_result', name: 'fs.write_file', text: 'Wrote 4871 chars to index.html' },
    { fc: 'final', text: 'Built the page.' },
  ]),
});

// 4c. Control: a LATER failing read is a real recovered attempt and must keep
// its count -- the probe exemption is for the first existence check only.
report.okWithLaterFailure = api.turnHtml({
  role: 'agent', ok: true, changed_files: ['index.html'],
  transcript: lines([
    { fc: 'tool_result', name: 'fs.read_file', text: 'ok: read index.html' },
    { fc: 'tool_result', name: 'fs.read_file', text: 'read failed: helpers.js not found', is_error: true },
    { fc: 'final', text: 'Built the page.' },
  ]),
});

// 4d. Control: a FAILED run's tool errors are still issues, not "recovered".
report.failedWithIssues = api.turnHtml({
  role: 'agent', ok: false, reason: 'exited 1',
  transcript: lines([
    { fc: 'tool_result', name: 'scratch.verify', text: 'verifier attempt failed', is_error: true },
    { fc: 'error', text: 'agent loop exited 1' },
  ]),
});

process.stdout.write(JSON.stringify(report));
