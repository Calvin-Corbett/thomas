import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const repo = process.argv[2];
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = vm.createContext({ window: {}, console });
for (const file of ['unified_code_cards.js', 'unified_code_events.js', 'unified_code_live_view.js']) {
  vm.runInContext(fs.readFileSync(path.join(repo, 'thomas/server/web/js', file), 'utf8'), context, { filename: file });
}
const state = { running: false, liveEvents: [], terminalTool: '' };
const events = context.window.ThomasCodeEvents.create({
  state, NARRATIVE_EVENT_KINDS: new Set(['say', 'final', 'meta']),
  MAX_VISIBLE_PROGRESS_EVENTS: 100, MAX_PROGRESS_EVENT_CHARS: 4000,
  esc: value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]),
});
const live = context.window.ThomasCodeLiveView.create({
  state, MAX_LIVE_EVENTS: 100, ...events,
});
const replacements = [];
for (const frame of input.frames.filter(frame => frame.type === 'output')) {
  replacements.push(live.pushLiveEvent(frame));
}
assert.deepEqual(replacements.slice(0, 9), [false, true, false, true, false, true, false, false, false]);
const restored = events.transcriptEvents({ transcript: input.transcript });
const keys = ['kind', 'text', 'agent_id', 'agent_title', 'agent_mode', 'model', 'team_id'];
const projection = list => Array.from(list, event => Object.fromEntries(keys.map(key => [key, event[key] ?? null])));
assert.deepEqual(projection(state.liveEvents), projection(restored), 'Live and restored events must retain the same identities');
assert.equal(restored[0].agent_id, 'child-a');
assert.equal(restored[1].agent_id, 'child-b');
assert.equal(restored[0].agent_title, restored[1].agent_title, 'Duplicate titles must not merge distinct children');
assert.equal(restored[0].text, '[Reviewer] Reading source.');
assert.equal(restored[1].text, '[Reviewer] Reading source.');
assert.equal(restored[2].text, 'Lead answer', 'Parent deltas must still coalesce');
assert.equal(restored[2].agent_id, undefined);
assert.equal(restored[3].team_id, 'team-next');
assert.equal(restored[4].model, 'another-model');
assert.equal(restored[5].agent_mode, 'builder');
assert.equal(restored.filter(event => event.text === 'Finished').length, 2, 'Equal child status text is still two events');
for (const field of ['agent_id', 'agent_title', 'agent_mode', 'model', 'team_id', 'secret']) {
  assert.equal(restored.at(-1)[field], undefined, 'Malformed or unapproved metadata must not enter replay');
}

// Whole-block replay suppression is scoped to the speaker whose deltas preceded it.
const raw = [
  { fc: 'say', agent_id: 'a', model: 'selected', text: 'Same answer', delta: true },
  { fc: 'say', agent_id: 'b', model: 'selected', text: 'Same answer' },
  { fc: 'say', agent_id: 'a', model: 'selected', text: 'Same answer' },
  { fc: 'say', text: 'Same answer' },
];
const deduped = events.transcriptEvents({ transcript: raw.map(event => JSON.stringify(event)).join('\n') });
assert.deepEqual(Array.from(deduped, event => event.agent_id ?? 'lead'), ['a', 'b', 'lead']);

// Rendering applies additional progress and receipt grouping after ingestion.
// Equal visible text from different children must survive those layers as well.
const progress = events.progressEvents(restored, null);
assert.equal(progress.filter(event => event.text === '[Reviewer] Reading source.').length, 2);
assert.equal(progress.filter(event => event.text === 'Finished').length, 2);
const final = { ...restored[1], kind: 'final' };
const beforeFinal = events.progressEvents([...restored, final], final);
assert.ok(beforeFinal.some(event => event.agent_id === 'child-a' && event.text === final.text));
assert.ok(!beforeFinal.some(event => event.agent_id === 'child-b' && event.text === final.text));
const parentRepeats = events.progressEvents([{ kind: 'say', text: 'Retrying' }, { kind: 'say', text: 'Retrying' }], null);
assert.equal(parentRepeats.length, 2, 'a note said twice is shown twice');
assert.deepEqual(parentRepeats.map(event => event.text), ['Retrying', 'Retrying']);
const toolA = { ...restored[0], kind: 'tool_result', name: 'Reviewer > fs.read_file', text: 'Read source.txt' };
const toolB = { ...toolA, agent_id: 'child-b' };
// The grouped technical block is gone (2026-10 redesign): work rows are the one
// rendering, so the identity rule is held there -- a different child, title,
// mode, model or team is a different row.
for (const field of ['agent_id', 'agent_title', 'agent_mode', 'model', 'team_id']) {
  const changed = { ...toolA, [field]: 'another-value' };
  const inline = events.interleavedActivityHtml([toolA, changed], true);
  assert.equal((inline.match(/class="tc-code-work tc-code-receipt tc-code-technical"/g) || []).length, 2, field);
}
const inline = events.interleavedActivityHtml([toolA, toolA, toolB], true);
assert.equal((inline.match(/class="tc-code-work tc-code-receipt tc-code-technical"/g) || []).length, 3, 'every row shows');
assert.ok(!inline.includes('×'), 'identical rows are not merged into a count');
const narrative = events.interleavedActivityHtml(progress, true);
assert.equal((narrative.match(/\[Reviewer\] Reading source\./g) || []).length, 2);

// A lead shell call may overlap a child's file read. The explicit result name
// wins over the last start event; old unnamed CLI results still use the tracker.
const tracker = { name: '' };
events.annotateTerminalEvent({ kind: 'tool', agent_id: 'a', name: 'Reviewer > fs.read_file' }, tracker);
events.annotateTerminalEvent({ kind: 'tool', name: 'shell.exec' }, tracker);
const childRead = events.annotateTerminalEvent({ kind: 'tool_result', agent_id: 'a', name: 'Reviewer > fs.read_file' }, tracker);
const parentShell = events.annotateTerminalEvent({ kind: 'tool_result', name: 'shell.exec' }, tracker);
assert.equal(childRead.terminal, undefined, 'A child file result cannot inherit the lead terminal label');
assert.equal(parentShell.terminalTool, 'shell.exec', 'An overlapping explicit shell result keeps its own label');
events.annotateTerminalEvent({ kind: 'tool', name: 'shell.exec' }, tracker);
assert.equal(events.annotateTerminalEvent({ kind: 'tool_result', text: 'legacy result' }, tracker).terminalTool, 'shell.exec');
events.annotateTerminalEvent({ kind: 'tool', name: 'shell.exec' }, tracker);
events.annotateTerminalEvent({ kind: 'tool', agent_id: 'a', name: 'Reviewer > fs.read_file' }, tracker);
events.annotateTerminalEvent({ kind: 'tool_result', agent_id: 'a', name: 'Reviewer > fs.read_file' }, tracker);
assert.equal(tracker.name, 'shell.exec', 'A named child call must preserve the pending lead terminal tracker');
const unnamedChild = events.annotateTerminalEvent({ kind: 'tool_result', agent_id: 'a', text: 'no name' }, tracker);
assert.equal(unnamedChild.terminal, undefined, 'An unnamed child result must not borrow the lead terminal');
assert.equal(events.annotateTerminalEvent({ kind: 'tool_result', text: 'lead legacy result' }, tracker).terminalTool, 'shell.exec');
const toolTrace = [
  { fc: 'tool', name: 'shell.exec' },
  { fc: 'tool', agent_id: 'a', name: 'Reviewer > fs.read_file' },
  { fc: 'tool_result', agent_id: 'a', name: 'Reviewer > fs.read_file', text: 'Source read' },
  { fc: 'tool_result', text: 'Unnamed lead shell result' },
];
const restoredTools = events.transcriptEvents({ transcript: toolTrace.map(event => JSON.stringify(event)).join('\n') });
assert.equal(restoredTools[2].terminal, undefined, 'Restore applies identity before terminal attribution');
assert.equal(restoredTools[3].terminalTool, 'shell.exec', 'Restore keeps the pending lead terminal through child activity');
process.stdout.write(JSON.stringify({ live_and_restore_identity: true, parent_deltas: true, speaker_scoped_replay: true, rendered_identity: true }));
