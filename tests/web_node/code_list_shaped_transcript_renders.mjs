// Drives unified_code_events.js through its create() seam with stub deps and
// renders the SAME turn three ways: transcript as the one true string, as a
// single-character array (the measured legacy shape -- 2541 one-char entries,
// w2-code-explain sweep), and as a line array. Reports the HTML of each so the
// python side can assert that a list-shaped transcript already on disk keeps
// rendering exactly what the string shape renders.
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

const transcript = [
  { fc: 'tool_result', name: 'code.project_structure', text: 'empty project', is_error: false },
  { fc: 'say', text: 'Looking at the project now.' },
  { fc: 'final', text: 'THE-ANSWER: this project is empty.' },
].map(row => JSON.stringify(row)).join('\n');

const turnFor = shape => ({ role: 'agent', ok: false, reason: 'exited 1', transcript: shape });

const report = {
  asString: api.turnHtml(turnFor(transcript)),
  asCharArray: api.turnHtml(turnFor(transcript.split(''))),
  asLineArray: api.turnHtml(turnFor(transcript.split('\n'))),
};

process.stdout.write(JSON.stringify(report));
