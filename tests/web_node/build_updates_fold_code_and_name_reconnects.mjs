// Draws Build updates through unified_code_events.js's create() seam and prints the HTML (2026-11-09).
//
// Three things a watcher saw in the live app: an update that pasted a long diff filled the screen with code and
// pushed the narrative off it; coming back to a task that had kept running printed a row titled "disconnected";
// and a real drop had no title of its own. A long fenced block now folds behind a line that says how long it is, a
// return reads "Reconnected", and a drop reads "Connection lost".
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const eventsPath = process.argv[2];
if (!eventsPath) throw new Error('usage: node build_updates_fold_code_and_name_reconnects.mjs <unified_code_events.js>');
const cardsPath = path.join(path.dirname(eventsPath), 'unified_code_cards.js');

globalThis.window = {};
vm.runInThisContext(fs.readFileSync(cardsPath, 'utf8'), { filename: cardsPath });
vm.runInThisContext(fs.readFileSync(eventsPath, 'utf8'), { filename: eventsPath });

const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const api = window.ThomasCodeEvents.create({
  MAX_VISIBLE_PROGRESS_EVENTS: 120,
  // Large on purpose: the per-update character fold must not be what hides the code here.
  MAX_PROGRESS_EVENT_CHARS: 100000,
  NARRATIVE_EVENT_KINDS: new Set(['approval', 'disconnected', 'reconnected', 'done', 'final', 'insight', 'planning', 'say', 'steering', 'stopped', 'stopping']),
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

const fence = (lines, word) => '```diff\n' + Array.from({ length: lines }, (_, index) => `+${word} ${index}`).join('\n') + '\n```';
const lines = rows => rows.map(row => JSON.stringify(row)).join('\n');
const turn = rows => api.turnHtml({ role: 'agent', ok: true, reason: '1 file(s) changed', transcript: lines(rows) });

process.stdout.write(JSON.stringify({
  long: turn([
    { fc: 'say', text: `BEFORE-MARKER here is the change:\n${fence(30, 'LONGLINE')}\nAFTER-MARKER that is all of it.` },
    { fc: 'final', text: 'Done.' },
  ]),
  short: turn([
    { fc: 'say', text: `A small one:\n${fence(3, 'SHORTLINE')}` },
    { fc: 'final', text: 'Done.' },
  ]),
  unclosed: turn([
    { fc: 'say', text: 'An update that opens a fence and never closes it: ```js\nconst UNCLOSED = 1;' },
    { fc: 'final', text: 'Done.' },
  ]),
  reconnected: turn([
    { fc: 'reconnected', text: 'Reconnected. This task kept running in the background.' },
    { fc: 'final', text: 'Done.' },
  ]),
  dropped: turn([
    { fc: 'disconnected', text: 'Live updates were interrupted.' },
    { fc: 'final', text: 'Done.' },
  ]),
}));
