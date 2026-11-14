// Renders a saved Code turn whose transcript carries a `tool_started` line (2026-10-26) through
// unified_code_events.js's create() seam, with stub deps, and prints the HTML. The line is written so a watcher sees
// a long step while it runs; the step's result is its row, so the start must add nothing to the page.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const eventsPath = process.argv[2];
// The rows, cards and head a turn is drawn from live beside it and load first.
const cardsPath = path.join(path.dirname(eventsPath), 'unified_code_cards.js');

globalThis.window = {};
vm.runInThisContext(fs.readFileSync(cardsPath, 'utf8'), { filename: cardsPath });
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
process.stdout.write(JSON.stringify({
  html: api.turnHtml({
    role: 'agent', ok: true, reason: '1 file(s) changed',
    transcript: lines([
      { fc: 'say', text: 'Running the tests.' },
      { fc: 'tool_started', name: 'check.run', text: 'STARTED-ONLY-MARKER pytest tests/test_x.py' },
      { fc: 'tool_result', name: 'check.run', text: 'RESULT-MARKER 3 passed', is_error: false },
      { fc: 'final', text: 'Done.' },
    ]),
  }),
}));
