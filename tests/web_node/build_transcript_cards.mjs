// The Build transcript's redesigned pieces, under Node.
//
// The 2026-10 redesign draws a Build conversation from unified_code_cards.js
// (work rows, the STEPS card, the proof card, the ask card, the steer chip, the
// live diff, the deliverable's actions) and reads what is
// live from the project with unified_code_live_diff.js. This drives the shipped
// files the way the page does -- cards first, then the event cluster that calls
// them -- and reports one boolean per claim, so the Python side can name what broke.
//
// usage: node build_transcript_cards.mjs <thomas/server/web/js dir>
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const jsDir = process.argv[2];
if (!jsDir) throw new Error('usage: node build_transcript_cards.mjs <web js dir>');

const timers = [];
const context = vm.createContext({
  window: {}, console, Date, JSON, Math, Number, String, Array, Object, Set, Map, Boolean, RegExp, Error, Promise,
  encodeURIComponent,
  setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
  clearTimeout: id => { if (timers[id - 1]) timers[id - 1].fn = null; },
});
for (const file of ['thomas_bot.js', 'unified_code_cards.js', 'unified_code_agents.js', 'unified_code_events.js', 'unified_code_live_diff.js']) {
  vm.runInContext(fs.readFileSync(path.join(jsDir, file), 'utf8'), context, { filename: file });
}
const { ThomasCodeCards: cards, ThomasCodeEvents, ThomasCodeLiveDiff, ThomasCodeAgentRows } = context.window;
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const NARRATIVE = new Set(['approval', 'disconnected', 'done', 'final', 'insight', 'planning', 'say', 'settings', 'steering', 'stopped', 'stopping']);
const events = ThomasCodeEvents.create({
  MAX_PROGRESS_EVENT_CHARS: 420, NARRATIVE_EVENT_KINDS: NARRATIVE,
  state: { running: false, runStartedAt: 0, projectRoot: 'C:\\proj' }, esc,
  codeResults: () => ({ artifactCardsHtml: () => '<!--cards-->', runReportHtml: (_r, o) => `<!--report:${o && o.actions === false ? 'card-only' : 'with-actions'}-->` }),
  surface: () => null, isInternalResultPath: file => String(file).startsWith('.thomas/'),
});
const lines = rows => rows.map(row => JSON.stringify(row)).join('\n');
// Values built inside the vm context carry its own Array prototype.
const plain = value => JSON.parse(JSON.stringify(value));
const strip = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
const checks = {};
async function check(name, run) { await run(); checks[name] = true; }

// ---- work rows -------------------------------------------------------------
await check('verbs read like a person names the step', () => {
  const verb = ev => cards.workRowFace(ev).verb;
  assert.equal(verb({ kind: 'tool_result', name: 'fs.read_file' }), 'Read');
  assert.equal(verb({ kind: 'tool_result', name: 'Reviewer > fs.read_file' }), 'Read', 'a team child prefix is not part of the tool');
  assert.equal(verb({ kind: 'tool_result', name: 'diff.create' }), 'Edited', 'diff.create is the edit, not a comparison');
  assert.equal(verb({ kind: 'tool', name: 'Edit' }), 'Edited');
  assert.equal(verb({ kind: 'tool_result', name: 'fs.write_file' }), 'Wrote');
  assert.equal(verb({ kind: 'tool_result', name: 'TodoWrite' }), 'Planned', 'a todo list is planning, not a file write');
  assert.equal(verb({ kind: 'tool_result', name: 'diff.preview_patch' }), 'Compared');
  assert.equal(verb({ kind: 'tool_result', name: 'shell.exec' }), 'Ran');
  assert.equal(verb({ kind: 'tool_result', name: 'code.search' }), 'Searched');
  assert.equal(verb({ kind: 'tool_result', name: 'check.run' }), 'Checked');
  assert.equal(verb({ kind: 'tool', name: 'run' }), 'Checked', "the engine's own checks are checks");
  assert.equal(cards.workRowFace({ kind: 'tool_result', name: 'check.run' }, { recheck: true }).verb, 'Rechecked');
  assert.equal(verb({ kind: 'error', text: 'boom' }), 'Error');
  assert.equal(verb({ kind: 'meta', receipt: 'model', text: 'Ran on x' }), 'Model');
  assert.equal(verb({ kind: 'tool_result', expectedProbe: true, is_error: true, text: 'not found' }), 'Looked');
  assert.equal(verb({ kind: 'tool_result', name: 'mystery.tool' }), 'Used');
  // The settled contract says how many asks it met, and claims no ✓ of its own.
  const settled = cards.workRowFace({ kind: 'acceptance', items: [{ satisfied: true }, { satisfied: false }] });
  assert.equal(settled.detail, '1 of 2 asks met');
  assert.equal(settled.meta, '');
  assert.equal(cards.workRowFace({ kind: 'tool_result', name: 'check.run', text: 'ok' }, { failed: true }).meta, '✕');
});

await check('a row names the file, project-relative, and its +/- counts', () => {
  const backend = cards.workRowFace({ kind: 'tool_result', name: 'diff.create', path: 'src/app.js', added: 11, removed: 2, text: 'ok' });
  assert.equal(backend.detail, 'src/app.js');
  assert.equal(backend.metaText, '+11 \u22122');
  // Saved before the backend sent counts: read them off diff.create's own summary.
  const legacy = cards.workRowFace({ kind: 'tool_result', name: 'diff.create', text: 'Replaced 3 line(s) with 5 line(s) in styles.css (indent fixed)' });
  assert.equal(legacy.detail, 'styles.css');
  assert.equal(legacy.metaText, '+5 \u22123');
  const wrote = cards.workRowFace({ kind: 'tool_result', name: 'fs.write_file', text: 'Wrote 4871 chars to index.html' });
  assert.equal(wrote.detail, 'index.html');
  const claude = cards.workRowFace({ kind: 'tool', name: 'Read', text: 'file_path: C:\\proj\\src\\app.js' }, { root: 'C:\\proj' });
  assert.equal(claude.detail, 'src/app.js', 'an absolute path inside the project reads project-relative');
  const outside = cards.workRowFace({ kind: 'tool', name: 'Read', text: 'file_path: C:\\Users\\x\\Downloads\\notes.txt' }, { root: 'C:\\proj' });
  assert.equal(outside.detail, 'Downloads/notes.txt');
  assert.equal(cards.workRowFace({ kind: 'tool_result', name: 'shell.exec', command: 'npm test', text: '3 passed' }).detail, 'npm test');
});

await check('a call and its result are one row that knows how long it took', () => {
  const paired = cards.pairToolCalls([
    { kind: 'tool', name: 'Read', text: 'file_path: /p/app.js', ts: 1000 },
    { kind: 'tool_result', name: 'Read', text: 'line one', ts: 1400 },
    { kind: 'tool_result', name: 'Read', text: 'orphan result', ts: 1500 },
  ]);
  assert.equal(paired.length, 2);
  assert.equal(paired[0].call_text, 'file_path: /p/app.js');
  assert.equal(paired[0].text, 'line one', 'the row body is the result');
  assert.equal(cards.workRowFace(paired[0]).meta, '0.4s');
  // A different agent's result never folds into another's call.
  const crossed = cards.pairToolCalls([
    { kind: 'tool', name: 'Read', text: 'a', agent_id: 'x' },
    { kind: 'tool_result', name: 'Read', text: 'b', agent_id: 'y' },
  ]);
  assert.equal(crossed.length, 2);
  assert.equal(cards.durationLabel(80), '<0.1s');
  assert.equal(cards.durationLabel(12400), '12s');
  assert.equal(cards.durationLabel(108000), '1m 48s');
});

await check('a work row escapes its output into the body and never into markup', () => {
  const html = cards.workRowHtml({ kind: 'tool_result', name: 'shell.exec', command: '<b>x</b>', text: '<script>alert(1)</script>', event_seq: 4 }, {
    esc, failed: () => true, heading: () => 'Ran a <terminal> command', text: '<script>alert(1)</script>', saved: true,
  });
  assert.ok(!html.includes('<script>') && !html.includes('<b>x</b>'));
  assert.ok(html.includes('<pre>&lt;script&gt;alert(1)&lt;/script&gt;</pre>'));
  assert.ok(html.startsWith('<details class="tc-code-work tc-code-receipt tc-code-technical is-error"'));
  assert.ok(html.includes('data-code-event-seq="4"') && html.includes('data-saved="true"') && !html.includes('×'));
  assert.ok(!html.includes('-bot'), 'no bot beside a row');
  assert.ok(!/ph-caret|chev/.test(html), 'no chevrons');
});

await check('every row shows: identical neighbours stay separate and a long run never folds', () => {
  const same = { kind: 'tool_result', name: 'fs.read_file', path: 'a.js', text: 'x' };
  const rows = cards.workRowsHtml([same, same, same], { esc });
  assert.equal((rows.match(/<details class="tc-code-work /g) || []).length, 3);
  assert.ok(!rows.includes('×'));
  const many = Array.from({ length: 11 }, (_v, i) => ({ kind: 'tool_result', name: 'fs.read_file', path: `f${i}.js`, text: `t${i}` }));
  const all = cards.workRowsHtml(many, { esc });
  assert.ok(all.startsWith('<div class="tc-code-receipts">'));
  assert.ok(!all.includes('receipts-more') && !all.includes('more steps'));
  assert.equal((all.match(/<details class="tc-code-work /g) || []).length, 11, 'nothing is dropped or folded');
  assert.equal(cards.summaryRowHtml, undefined, 'the show-work row is gone');
});

// ---- STEPS -----------------------------------------------------------------
await check('the STEPS card counts the step being worked on and times the finished ones', () => {
  const plan = { items: [
    { id: '1', text: 'Map colours', status: 'completed', owner: 'Scout', started_at: 1000, done_at: 10000 },
    { id: '2', text: 'Add <toggle>', status: 'in_progress', owner: 'Wirer', started_at: 10000 },
    { id: '3', text: 'Check asks', status: 'pending', owner: '' },
    { id: '4', text: 'Ship', status: 'blocked', owner: '' },
    { id: '5', text: '   ', status: 'pending' },
  ] };
  const html = cards.stepsHtml({ esc, plan });
  assert.ok(html.includes('<span class="tc-code-plan-count">2 of 4</span>'), 'an empty step is dropped and the active one counts');
  assert.ok(html.includes('style="width:25%"'), 'the bar shows only what is finished');
  assert.ok(html.includes('Add &lt;toggle&gt;'));
  const text = strip(html);
  assert.ok(text.includes('Map colours Scout 9s'));
  assert.ok(text.includes('Add &lt;toggle&gt; Wirer now'));
  assert.ok(html.includes('is-blocked') && text.includes('Ship blocked'));
  assert.equal(cards.stepsHtml({ esc, plan: { items: [] } }), '');
});

await check('a step finishing or starting is one update line, said once', () => {
  const a = { type: 'plan', ts: 1, items: [{ id: '1', text: 'Build the Pong page', status: 'in_progress', started_at: 1000 }, { id: '2', text: 'Test the controls', status: 'pending' }] };
  const b = { type: 'plan', ts: 2, items: [{ id: '1', text: 'Build the Pong page', status: 'completed', started_at: 1000, done_at: 89000 }, { id: '2', text: 'Test the controls', status: 'in_progress', started_at: 89000 }] };
  assert.deepEqual(plain(cards.stepNotes(null, a)), ['Now building the Pong page']);
  assert.deepEqual(plain(cards.stepNotes(a, b)), ['Built the Pong page (1m 28s)', 'Now testing the controls']);
  assert.deepEqual(plain(cards.stepNotes(b, { ...b })), [], 'an unchanged plan says nothing');
  const out = cards.withStepNotes([a, { type: 'say', text: 'x' }, b, { ...b, ts: 3 }]);
  assert.deepEqual(plain(out.filter(e => e.type === 'stepnote').map(e => e.text)), ['Now building the Pong page', 'Built the Pong page (1m 28s)', 'Now testing the controls']);
  assert.equal(out[1].type, 'stepnote', 'the line sits right after the plan that caused it');
  const html = cards.controlEventHtml({ type: 'stepnote', text: 'Built <x>' }, { esc });
  assert.ok(html.includes('tc-code-stepnote') && html.includes('Built &lt;x&gt;'));
});

// ---- proof card --------------------------------------------------------------
const report = (rows, validations = [{ passed: true, evidence: 'STATIC_VERIFY_OK' }], extra = {}) => ({
  outcome: 'completed', validations, rubric_mapping: [{ criterion: 'the run finished without error', status: 'met', evidence: 'x' }, ...rows], ...extra,
});
await check('the proof card names each ask in your words, green when all pass', () => {
  const html = cards.proofHtml({ esc, report: report([
    { criterion: 'follows the system setting', status: 'met', evidence: 'emulated dark' },
    { criterion: 'a toggle <in> the corner', status: 'met', evidence: 'clicked #theme' },
  ]), checks: { ran: 1, passed: 1, failed: 0, skipped: 0 }, detailsHtml: '<div>SECTIONS</div>' });
  assert.ok(html.startsWith('<section class="tc-code-proof"'));
  assert.ok(html.includes('Verifier checked both of your asks'));
  assert.ok(!html.includes('the run finished without error'), 'the run-level row is not one of your asks');
  assert.ok(html.includes('“a toggle &lt;in&gt; the corner”'));
  assert.ok(html.includes('Separate evaluator · 1 of 1 engine check passed'));
  assert.ok(html.includes('SECTIONS'), 'the compact report sections stay one click away');
  assert.ok(!html.includes('data-code-proof-fix'), 'nothing to fix on a passing card');
});

await check('a failed ask turns the card red, says so, and offers the fix', () => {
  const failing = report([
    { criterion: 'export my ticks to a CSV', status: 'met', evidence: 'download fired' },
    { criterion: 'I can open it in Excel', status: 'not_met', evidence: 'dates read as text' },
  ]);
  const html = cards.proofHtml({ esc, report: failing });
  assert.ok(html.includes('tc-code-proof is-problem'));
  assert.ok(html.includes('Verifier found a problem: 1 of 2 asks failed'));
  assert.ok(html.includes("I&#39;m not calling this done."));
  assert.ok(html.includes('data-code-proof-fix="Fix what the Verifier found. These asks failed: &quot;I can open it in Excel&quot;"'));
  assert.ok(html.includes('data-code-proof-trace') && html.includes('data-code-proof-keep'));
  const cardOnly = cards.proofHtml({ esc, report: failing, actions: false });
  assert.ok(!cardOnly.includes('data-code-proof-fix'), 'the caller can place the buttons itself');
  assert.ok(cards.proofActionsHtml({ esc, report: failing }).includes('Fix it'));
  const checkFailed = cards.proofHtml({ esc, report: report([{ criterion: 'a', status: 'met', evidence: 'e' }], [{ passed: false }]) });
  assert.ok(checkFailed.includes('Verifier found a problem: 1 engine check failed'), 'a failed engine check is never a green card');
});

await check('no proof card for a run nobody checked ask by ask', () => {
  assert.equal(cards.proofHtml({ esc, report: report([{ criterion: 'the specific requirements stated in this goal', status: 'unverified', evidence: 'x' }]) }), '');
  assert.equal(cards.proofHtml({ esc, report: report([{ criterion: 'a', status: 'met' }], undefined, { outcome: 'stopped' }) }), '');
  assert.equal(cards.proofHtml({ esc, report: report([{ criterion: 'a', status: 'met' }], undefined, { outcome: 'conversation' }) }), '');
  assert.equal(cards.proofHtml({ esc, report: null }), '');
  const partial = cards.proofHtml({ esc, report: report([{ criterion: 'a', status: 'met' }, { criterion: 'b', status: 'unverified' }]) });
  assert.ok(partial.includes('Verifier checked 1 of your 2 asks') && partial.includes('1 not checked'));
});

// ---- ask / steer / live diff / summary / actions ----------------------------
await check('the ask card offers options as buttons and shrinks once answered', () => {
  const html = cards.askHtml({ esc, question: { question_id: 'q-1', question: 'Keep <badges>?', allow_free_text: true, options: [
    { label: 'Keep it', description: 'Earned is earned', recommended: true }, { label: 'Lose "it"', description: '' },
  ] }, waitingOn: 'Wirer', othersWorking: true });
  assert.ok(html.includes('Thomas is asking') && html.includes('Wirer is waiting on this'));
  assert.ok(html.includes('Keep &lt;badges&gt;?'));
  assert.equal((html.match(/data-code-ask-option data-question-id="q-1"/g) || []).length, 2);
  assert.ok(html.includes('data-label="Lose &quot;it&quot;"'));
  assert.ok(html.includes('tc-code-ask-option is-recommended') && html.includes('Recommended'));
  assert.ok(html.includes('Or type your own answer below. Other agents keep going while you decide.'));
  const alone = cards.askHtml({ esc, question: { question: 'q', options: [{ label: 'a' }], allow_free_text: false } });
  assert.ok(!alone.includes('Other agents') && !alone.includes('type your own'), 'no claim about agents that are not there');
  const busy = cards.askHtml({ esc, question: { question: 'q', options: [{ label: 'a' }] }, busy: true });
  assert.ok(busy.includes('disabled') && busy.includes('aria-busy="true"'));
  const done = cards.askHtml({ esc, question: { question_id: 'q-1', question: 'Keep?', state: 'answered', answer: 'Keep it' } });
  assert.ok(done.includes('tc-code-ask is-answered') && done.includes('You chose: Keep it') && !done.includes('data-code-ask-option'));
});

await check('a steer chip shows its words and how far they got', () => {
  const html = cards.steerChipHtml({ esc, text: 'use a <sun> icon', state: 'acked', to: 'Wirer' });
  assert.ok(html.includes('is-acked') && html.includes('use a &lt;sun&gt; icon') && html.includes('Steer → Wirer'));
  assert.ok(cards.steerChipHtml({ esc, text: 'x', state: 'bogus' }).includes('is-queued'));
});

await check('the live diff draws numbered, tinted lines and a caret while writing', () => {
  const diff = { file: 'index.html', added: 9, removed: 1, agentTitle: 'Wirer', lines: [
    { n: 41, sign: ' ', text: '<header>' }, { n: null, sign: '-', text: 'old' }, { n: 43, sign: '+', text: '<button>' }] };
  const html = cards.liveDiffHtml({ esc, diff });
  assert.ok(html.includes('Wirer is writing') && html.includes('+9') && html.includes('\u22121'));
  assert.ok(html.includes('tc-code-livediff-line is-add') && html.includes('tc-code-livediff-line is-del'));
  assert.ok(html.includes('&lt;button&gt;') && !html.includes('<button>'));
  assert.equal((html.match(/tc-code-livediff-caret/g) || []).length, 1);
  const paused = cards.liveDiffHtml({ esc, diff, paused: true });
  assert.ok(paused.includes('Paused') && !paused.includes('tc-code-livediff-caret'));
  assert.equal(cards.liveDiffHtml({ esc, diff: null }), '');
});

// ---- the event cluster, end to end -------------------------------------------
await check('a saved turn keeps the new fields and reads in the design order', () => {
  const t0 = 1761750000000;
  const turn = {
    role: 'agent', ok: true, model: 'gpt', model_used: 'gpt-5.5', changed_files: ['index.html', '.thomas/run.json'],
    report: { outcome: 'completed' },
    transcript: lines([
      { fc: 'plan', ts: t0, items: [{ id: '1', text: 'Map colours', status: 'completed', owner: 'Scout', started_at: t0, done_at: t0 + 9000 }] },
      { fc: 'say', ts: t0 + 1, text: 'NARRATION' },
      { fc: 'tool_started', ts: t0 + 2, name: 'diff.create', text: 'STARTED-ONLY' },
      { fc: 'tool_result', ts: t0 + 1202, name: 'diff.create', path: 'index.html', added: 3, removed: 1, text: 'Replaced 1 line(s) with 3 line(s) in index.html' },
      { fc: 'tool_result', ts: t0 + 1300, name: 'fs.read_file', path: 'app.js', text: 'x', agent_id: 'c1', agent_title: 'Scout' },
      { fc: 'final', ts: t0 + 108000, text: 'REPLY' },
    ]),
  };
  const parsed = events.transcriptEvents(turn);
  const edit = parsed.find(ev => ev.name === 'diff.create');
  assert.equal(edit.ts, t0 + 1202);
  assert.equal(edit.started_ts, t0 + 2, 'the start line lends its clock to the result');
  assert.equal(edit.path, 'index.html');
  assert.deepEqual(plain([edit.added, edit.removed]), [3, 1]);
  assert.ok(Array.isArray(parsed[0].items), 'a plan keeps its steps');
  const html = events.turnHtml(turn);
  assert.ok(!html.includes('STARTED-ONLY'));
  // Just the name; which model ran rides on its hover title (test_a_build_turn_names_the_model_that_answered).
  assert.ok(!html.includes('<small') && /<strong(?: title="[^"]*")?>Thomas<\/strong>/.test(html), 'the head is just the name');
  assert.ok(html.includes('<div class="tc-code-worked">Worked for 1m 48s</div>'), 'one quiet line after the reply says how long the run took');
  const body = html.split('class="tc-code-turn-body">')[1];
  assert.ok(html.startsWith('<article class="tc-code-turn is-agent" data-code-turn-key="') && html.includes('"><div class="tc-code-turn-body">'), 'the turn has no head of its own');
  assert.ok(!body.includes('tc-code-steps') && !body.includes('show work'), 'nothing folds');
  assert.equal((html.match(/tc-code-message-head/g) || []).length, 1, 'a mid-run note is an update with no name; only his reply carries the head');
  assert.ok(html.includes('tc-code-say is-update') && body.indexOf('tc-code-message-head') > body.indexOf('NARRATION'), 'the note is a quiet update');
  assert.ok(!html.includes('app.js'), 'the helper read has no row');
  assert.ok(body.indexOf('tc-code-plan') < body.indexOf('NARRATION'), 'the STEPS card opens the work');
  assert.ok(body.indexOf('NARRATION') < body.indexOf('<!--report:card-only-->'));
  assert.ok(body.indexOf('<!--report:card-only-->') < body.indexOf('REPLY') && body.indexOf('REPLY') < body.indexOf('<!--cards-->'));
  assert.ok(html.includes('<span class="tc-code-add">+3</span> <span class="tc-code-del">−1</span>'), 'an edit row shows what it changed before how long it took');
});

await check('Thomas is named when he answers your message, and for nothing else mid-run', () => {
  const html = events.interleavedActivityHtml(events.transcriptEvents({ transcript: lines([
    { fc: 'say', text: 'UPDATE-ONE' },
    { fc: 'steering', text: 'Applying your update to this task: x' },
    { fc: 'say', text: 'ACK-OF-STEER' },
    { fc: 'say', text: 'UPDATE-TWO' },
  ]) }), true);
  assert.equal((html.match(/tc-code-message-head/g) || []).length, 1, 'only the answer to the steer is him');
  assert.ok(html.indexOf('tc-code-message-head') < html.indexOf('ACK-OF-STEER') && html.indexOf('tc-code-message-head') > html.indexOf('UPDATE-ONE'));
});

await check('the closing reply shows prose only: finish lines and stray fences are hidden', () => {
  const html = events.replyHtml('Made it.\n\n:::\nEVIDENCE: ok\nVERIFY: python -m pytest tests/x.py');
  assert.ok(html.includes('Made it.') && !html.includes('EVIDENCE') && !html.includes('VERIFY') && !html.includes(':::'));
});

await check('control events draw their own pieces and fold an answer into its question', () => {
  const html = events.interleavedActivityHtml(events.transcriptEvents({ transcript: lines([
    { fc: 'plan', items: [{ id: '1', text: 'x', status: 'pending' }] },
    { fc: 'steering', text: 'SUN ICON', steer_id: 's1' },
    { fc: 'steering', text: 'Applying your update to this task: x' },
    { fc: 'paused', text: 'Paused. Each agent holds after its current step.' },
    { fc: 'resumed', text: 'Resumed after 7s.', paused_ms: 7000 },
    { fc: 'ask', text: 'Keep?', question_id: 'q1', question: 'Keep?', options: [{ label: 'Keep' }, { label: 'Lose' }] },
    { fc: 'answered', text: 'Keep', question_id: 'q1', answer: 'Keep' },
    { fc: 'ask', text: 'Colour?', question_id: 'q2', question: 'Colour?', options: [{ label: 'Red' }] },
  ]) }), true);
  assert.ok(!html.includes('tc-code-plan'), 'a plan draws nothing inline');
  assert.ok(html.includes('tc-code-steerchip is-acked') && html.includes('SUN ICON'));
  assert.ok(html.includes('tc-code-event is-steering'), 'a restart note is not dressed as a delivered steer');
  assert.ok(html.includes('tc-code-quietline is-paused') && html.includes('Resumed after 7s.'));
  assert.ok(html.includes('You chose: Keep') && (html.match(/data-question-id="q1"/g) || []).length === 1);
  assert.ok(html.includes('tc-code-ask is-expired'), 'a saved question nobody answered reads as expired, not as open buttons');
  const live = events.eventHtml({ kind: 'ask', question_id: 'q3', text: 'Now?', options: [{ label: 'Yes' }] }, false);
  assert.ok(live.includes('data-code-ask-option'), 'a live question is answerable');
  assert.ok(!events.isTechnicalEvent({ kind: 'ask' }) && !events.isTechnicalEvent({ kind: 'plan' }));
});

await check('your message is one bubble with no heading', () => {
  const html = events.turnHtml({ role: 'user', text: 'make <it> blue' });
  assert.equal(html, '<article class="tc-code-turn is-user"><div class="tc-code-user-text">make &lt;it&gt; blue</div></article>');
});

await check('a helper status is one quiet line', () => {
  const html = ThomasCodeAgentRows.render({ kind: 'agent_status', agent_id: 'c1', agent_title: 'Wirer', agent_mode: 'builder', model: 'm', agent_state: 'failed', text: '[Wirer] Gave up' }, esc, true);
  assert.ok(html.startsWith('<div class="tc-code-agentline is-failed"'));
  assert.ok(strip(html) === 'Wirer builder · m · failed · Gave up', strip(html));
});

// ---- live diff poller ------------------------------------------------------
await check('parseLastHunk numbers the new file and windows the newest change', () => {
  const diff = [
    'diff --git a/index.html b/index.html', '--- a/index.html', '+++ b/index.html',
    '@@ -1,3 +1,3 @@', ' a', '-b', '+B', ' c',
    '@@ -40,4 +40,6 @@', ' <div>', ' <header class="top">', '-  <old>', '+  <button id="theme">', '+</header>', ' </div>', '\\ No newline at end of file', '',
  ].join('\n');
  const lines = ThomasCodeLiveDiff.parseLastHunk(diff);
  assert.deepEqual(plain(lines.map(line => [line.n, line.sign, line.text])), [
    [40, ' ', '<div>'], [41, ' ', '<header class="top">'], [null, '-', '  <old>'], [42, '+', '  <button id="theme">'], [43, '+', '</header>'], [44, ' ', '</div>'],
  ]);
  const long = ['@@ -0,0 +1,40 @@', ...Array.from({ length: 40 }, (_v, i) => `+line ${i + 1}`)].join('\n');
  const tail = ThomasCodeLiveDiff.parseLastHunk(long);
  assert.equal(tail.length, 12);
  assert.equal(tail[11].n, 40, 'the window ends at the newest line');
  assert.deepEqual(plain(ThomasCodeLiveDiff.parseLastHunk('')), []);
});

await check('parseLastHunk keeps changed lines whose own text starts with ++ or --', () => {
  // app.js went from a, b, ---, c to a, ++count;, b, c: the added line arrives
  // as "+++count;" and the removed rule as "----", inside the hunk.
  const diff = 'diff --git a/app.js b/app.js\n--- a/app.js\n+++ b/app.js\n@@ -1,4 +1,4 @@\n a\n+++count;\n b\n----\n c\n';
  assert.deepEqual(plain(ThomasCodeLiveDiff.parseLastHunk(diff).map(line => [line.n, line.sign, line.text])), [
    [1, ' ', 'a'], [2, '+', '++count;'], [3, ' ', 'b'], [null, '-', '---'], [4, ' ', 'c'],
  ]);
  // A new file whose front matter opens with +++ keeps it, numbered from 1.
  const hugo = 'diff --git a/post.md b/post.md\nnew file mode 100644\n--- /dev/null\n+++ b/post.md\n@@ -0,0 +1,3 @@\n++++\n+title = "x"\n++++\n';
  assert.deepEqual(plain(ThomasCodeLiveDiff.parseLastHunk(hugo).map(line => [line.n, line.text])), [[1, '+++'], [2, 'title = "x"'], [3, '+++']]);
});

// ---- a team's work stays in the drawer ------------------------------------------
const MENU = { agent_id: 'child_aaaaaaaaaaaa', agent_title: 'Menu page helper', agent_mode: 'builder', model: 'gpt-5.6-sol' };
const HOME = { agent_id: 'child_bbbbbbbbbbbb', agent_title: 'Home page helper', agent_mode: 'builder', model: 'gpt-5.6-sol' };
const teamRun = [
  { fc: 'meta', receipt: 'model', text: 'Ran on gpt-5.6-sol', model: 'gpt-5.6-sol' },
  { fc: 'say', text: 'LEAD-SAYS splitting the site into three pages.' },
  { fc: 'planning', name: 'team-progress', team_id: 't1', text: 'Team: 0/2 files integrated · queued 2 · running 0. The lead still checks the combined project.' },
  { fc: 'meta', ...MENU, text: '[Menu page helper] Spawned Menu page helper — isolated file builder · gpt-5.6-sol' },
  { fc: 'meta', ...MENU, receipt: 'model', text: '[Menu page helper] Ran on gpt-5.6-sol' },
  { fc: 'tool_result', ...MENU, name: 'Menu page helper > fs.list_dir', text: '[Menu page helper] workspace' },
  { fc: 'say', ...MENU, text: '\n[Menu page helper] HELPER-PROSE', delta: true },
  { fc: 'planning', name: 'team-progress', team_id: 't1', text: 'Team: 0/2 files integrated · queued 0 · running 2. The lead still checks the combined project.' },
  { fc: 'meta', ...HOME, text: '[Home page helper] Home page helper failed: parent refused integration', is_error: true },
  { fc: 'meta', ...HOME, text: '[Home page helper] Home page helper failed: second word on it', is_error: true },
  { fc: 'meta', team_id: 't1', text: 'Home page helper: failed (index.html)', is_error: true },
  { fc: 'meta', team_id: 't1', text: 'Contact page helper: failed: the builder crashed', is_error: true },
  { fc: 'meta', team_id: 't1', text: 'Menu page helper: integrated (menu.html)', model: 'gpt-5.6-sol' },
  { fc: 'planning', name: 'team-progress', team_id: 't1', text: 'Team: 1/2 files integrated · queued 0 · running 0. The lead still checks the combined project.' },
  { fc: 'tool_result', name: 'fs.read_file', path: 'menu.html', text: 'LEAD-READ' },
  { fc: 'final', text: 'REPLY' },
];

await check('a saved team turn tells the lead’s story, with the team in quiet lines', () => {
  const html = events.turnHtml({ role: 'agent', ok: true, report: null, transcript: lines(teamRun) });
  assert.ok(html.includes('LEAD-SAYS') && html.includes('LEAD-READ') && html.includes('REPLY'));
  assert.ok(!html.includes('HELPER-PROSE') && !html.includes('workspace') && !html.includes('Spawned'), 'a helper’s work has no row in the transcript');
  assert.equal((html.match(/tc-code-work-verb">Model</g) || []).length, 0, 'the model receipt has no row in the transcript (drawer only)');
  assert.ok(!html.includes('[Menu page helper] Ran on'));
  assert.equal((html.match(/team-progress/g) || []).length, 1, 'the tally is one line');
  assert.ok(html.includes('Team: 1/2 files integrated') && !html.includes('0/2 files'), 'the newest tally wins');
  assert.ok(!html.includes('tc-code-event is-planning'), 'no PLANNING block for the tally');
  assert.equal((html.match(/tc-code-agentline is-failed/g) || []).length, 1, 'a failing helper is one dim line');
  assert.ok(html.includes('parent refused integration') && !html.includes('second word on it'));
  assert.ok(!html.includes('failed (index.html)'), 'the team’s own word on that failure is not a second line');
  assert.ok(html.includes('failed: the builder crashed'), 'a failure only the team reported keeps its line');
  assert.ok(/tc-code-agentline is-team[^>]*><span class="tc-code-agentline-name">Menu page helper<\/span><span class="tc-code-agentline-text">integrated \(menu\.html\)/.test(html), 'an integrated notice is one quiet row');
});

await check('directory look-ups and model receipts get no transcript row', () => {
  const cardsMod = cards;
  const html = cardsMod.workRowsHtml([{ kind: 'tool_result', name: 'fs.list_dir', text: '(empty directory)' },
    { kind: 'meta', receipt: 'model', text: 'Ran on gpt-x' }, { kind: 'tool_result', name: 'fs.read_file', path: 'a.js', text: 'x' }], { esc });
  assert.ok(!html.includes('>Looked<') && !html.includes('>Model<') && html.includes('>Read<'));
});

await check('with a plan the STEPS card stands and the tally line does not', () => {
  const planned = [{ fc: 'plan', items: [{ id: '1', text: 'Build pages', status: 'in_progress' }] }, ...teamRun];
  const html = events.turnHtml({ role: 'agent', ok: true, report: null, transcript: lines(planned) });
  assert.ok(!html.includes('tc-code-plan') && !html.includes('Team: 1/2'));
});

await check('the live feed drops a team’s work and leaves a question to its own slot', () => {
  const live = teamRun.map(row => ({ type: 'output', kind: row.fc, ...row }));
  const shown = events.progressEvents(live, null);
  assert.ok(!shown.some(ev => ev.agent_id && !ThomasCodeAgentRows.isHelperError(ev)), 'only a helper’s failure reaches the feed');
  assert.ok(!shown.some(ev => ThomasCodeAgentRows.isTeamProgress(ev)));
  assert.ok(ThomasCodeAgentRows.hiddenLive({ kind: 'tool', ...MENU, name: 'x' }, []), 'a helper frame is hidden live');
  assert.ok(!ThomasCodeAgentRows.hiddenLive({ kind: 'steering', ...MENU, steer_id: 's', text: 'yours' }, []), 'your steer to a helper is yours');
  const failed = { kind: 'meta', ...HOME, is_error: true, text: 'Home page helper failed: x' };
  assert.ok(!ThomasCodeAgentRows.hiddenLive(failed, []) && ThomasCodeAgentRows.hiddenLive({ ...failed }, [failed]), 'one failure line per helper, live too');
  const asked = events.interleavedActivityHtml([{ kind: 'say', text: 'hi' }, { kind: 'ask', question_id: 'q', text: 'Now?', options: [{ label: 'Yes' }] }], false);
  assert.ok(!asked.includes('data-code-ask-option'), 'live, the question is drawn by its own slot');
});

await check('the lead’s bookkeeping that a card already shows stays out of the transcript', () => {
  const kept = ThomasCodeAgentRows.forTranscript([
    { kind: 'planning', text: 'Build team models · Task manager: gpt-5.6-sol · Builders: gpt-5.6-sol' },
    { kind: 'tool_result', name: 'plan.update', text: 'Plan shown to the person: 0 of 3 done.' },
    { kind: 'tool_started', name: 'ask.user', text: 'question' },
    { kind: 'tool_result', name: 'fs.write_file', text: 'Wrote 460 lines to index.html' },
    { kind: 'plan', items: [] },
    { kind: 'say', text: 'Building it now.' },
  ]).map(ev => ev.name || ev.kind);
  assert.deepEqual(plain(kept), ['fs.write_file', 'plan', 'say']);
});

await check('the poller ignores what was already changed and follows the file that moves', async () => {
  const answers = [
    { ok: true, files: [{ file: 'old.txt', added: 5, removed: 0, diff: '@@ -0,0 +1 @@\n+kept from before' }] },
    { ok: true, files: [{ file: 'old.txt', added: 5, removed: 0, diff: '@@ -0,0 +1 @@\n+kept from before' }, { file: 'index.html', added: 1, removed: 0, diff: '@@ -1 +1,2 @@\n a\n+b' }] },
    { ok: true, files: [{ file: 'old.txt', added: 5, removed: 0, diff: '@@ -0,0 +1 @@\n+kept from before' }, { file: 'index.html', added: 1, removed: 0, diff: '@@ -1 +1,2 @@\n a\n+b' }] },
    { ok: false },
  ];
  const urls = [];
  const seen = [];
  const poller = ThomasCodeLiveDiff.create({
    fetchJson: async url => { urls.push(url); return answers.shift(); },
    onChange: state => seen.push(state),
    agentFor: file => (file === 'index.html' ? 'Wirer' : ''),
  });
  poller.start('run 1');
  const tick = async () => { const next = timers.shift(); if (next && next.fn) await next.fn(); };
  await tick();
  assert.equal(poller.current(), null, 'the first answer is only a baseline');
  await tick();
  assert.equal(poller.current().file, 'index.html');
  assert.equal(poller.current().agentTitle, 'Wirer');
  assert.deepEqual(plain(poller.current().lines.map(line => line.sign)), [' ', '+']);
  await tick();
  assert.equal(seen.length, 1, 'an unchanged answer reports nothing');
  await tick();
  assert.equal(poller.current().file, 'index.html', 'a failed poll keeps what was shown');
  assert.equal(urls[0], '/api/evolve/agent/live-diff?run_id=run%201');
  poller.stop();
  assert.equal(poller.current(), null);
  assert.equal(seen.at(-1), null, 'stopping clears the block');
});

process.stdout.write(JSON.stringify(checks));
