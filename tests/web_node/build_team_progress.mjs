import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = { window: {}, console };
vm.createContext(context);
// unified_code_agents.js as chat.html loads it: the tally is the team's, drawn as one line.
for (const file of ['unified_code_cards.js', 'unified_code_agents.js', 'unified_code_events.js', 'unified_code_live_view.js']) {
  vm.runInContext(fs.readFileSync(`thomas/server/web/js/${file}`, 'utf8'), context, { filename: file });
}
const mode = fs.readFileSync('thomas/server/web/js/unified_code_mode.js', 'utf8');
const match = mode.match(/const NARRATIVE_EVENT_KINDS = new Set\((\[[^;]+\])\);/);
assert.ok(match, 'Use the actual shipped mode narrative kinds');
const kinds = vm.runInContext(`new Set(${match[1]})`, context);
const state = { running: true, liveEvents: [], terminalTool: '' };
const events = context.window.ThomasCodeEvents.create({
  state, NARRATIVE_EVENT_KINDS: kinds, MAX_VISIBLE_PROGRESS_EVENTS: 120, MAX_PROGRESS_EVENT_CHARS: 420,
  esc: value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
});
const live = context.window.ThomasCodeLiveView.create({state, MAX_LIVE_EVENTS: 120, ...events});
const rows = context.window.ThomasCodeAgentRows;
const esc = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
// Live: the tally is the team's newest line in the turn's steps slot (the run's
// controls keep it), not one more PLANNING row in the feed each time it moves.
live.pushLiveEvent(input.frame);
assert.equal(state.liveEvents.length, 0, 'the tally takes no place in the feed');
assert.ok(rows.isTeamProgress(input.frame));
const line = rows.teamHtml(input.frame, esc);
assert.ok(line.includes('1/3 files integrated'));
assert.ok(!line.includes('<details'), 'Progress must be visible outside collapsed receipts');
// Replayed: the saved turn shows the newest tally once, never as a feed row.
const restored = events.transcriptEvents({transcript: JSON.stringify(input.raw)});
assert.equal(events.isTechnicalEvent(restored[0]), false);
assert.ok(!events.interleavedActivityHtml(events.progressEvents(restored, null), false).includes('files integrated'));
assert.ok(rows.teamHtml(rows.latestTeamProgress(restored), esc).includes('1/3 files integrated'));
console.log('Live and restored team progress are visible in the shipped browser modules');
