// Renders two Build turns through unified_code_events.js's turnHtml and reports
// the HTML: one whose engine reported the exact model it ran (`model_used`), one
// from before that was recorded. The header must name the exact model when there
// is one, and fall back to the request -- never invent one -- when there is not.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

// Run by hand with no argument, it renders the repo's own copy of the view.
const eventsPath = process.argv[2]
  || fileURLToPath(new URL('../../thomas/server/web/js/unified_code_events.js', import.meta.url));
// The head and rows a turn is drawn from live beside it and load first.
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

const report = {};

report.reported = api.turnHtml({
  role: 'agent', ok: true, model: 'claude:opus', model_used: 'claude-opus-5-5',
  transcript: lines([
    { fc: 'meta', receipt: 'model', model: 'claude-opus-5-5', source: 'init', text: 'Ran on claude-opus-5-5' },
    { fc: 'final', text: 'Done.' },
  ]),
});

report.unreported = api.turnHtml({
  role: 'agent', ok: true, model: 'claude:opus',
  transcript: lines([{ fc: 'final', text: 'Done.' }]),
});

process.stdout.write(JSON.stringify(report));
