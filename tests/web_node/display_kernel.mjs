// Drives the display kernel (display_kernel.js) and its two built-in renderers (display_builtins.js) in a bare node
// context and prints what they drew as JSON. Run by tests/test_the_display_kernel_shows_words_when_a_block_cannot_draw.py.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const jsDir = process.argv[2] || fileURLToPath(new URL('../../thomas/server/web/js/', import.meta.url));
const load = name => vm.runInThisContext(fs.readFileSync(path.join(jsDir, name), 'utf8'), { filename: name });

globalThis.window = globalThis;
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
load('chat_markdown.js');
window.ThomasMarkdown = window.ThomasChatMarkdown.create({ esc });
load('display_kernel.js');
load('display_builtins.js');
const D = window.ThomasDisplay;
console.warn = () => {};

const attempt = fn => { try { fn(); return 'ok'; } catch (err) { return 'threw: ' + err.message; } };
const report = {};

const md = '**Done.**\n\n| A | B |\n|---|--:|\n| x | 1 |';
report.markdownSame = D.renderBlocks([D.blocks.markdown(md)]) === window.ThomasMarkdown.mdToHtml(md);
report.table = D.renderBlock(D.blocks.table(['Name', 'State'], [['<b>a</b>', 'ok'], ['b', '`x`']], [null, 'right']));
report.tableFallbackText = D.blocks.table(['Name', 'State'], [['a', 'ok']]).fallback_text;

report.registerNoRender = attempt(() => D.register('thing', {}));
report.registerBadType = attempt(() => D.register('Bad Type', { render: () => '' }));
report.makeBlockNoWords = attempt(() => D.makeBlock('table', {}, ''));
report.rawBlockNoWords = D.renderBlock({ type: 'markdown', version: 1, data: { text: 'hi' } });

report.unregistered = D.renderBlock({ type: 'sheet', version: 1, data: {}, fallback_text: 'Q1 <totals>' });
D.register('boom', { render: () => { throw new Error('nope'); } });
report.throws = D.renderBlock({ type: 'boom', version: 1, data: {}, fallback_text: 'words survive' });
D.register('notstring', { render: () => 42 });
report.notString = D.renderBlock({ type: 'notstring', version: 1, data: {}, fallback_text: 'still words' });
report.badTableData = D.renderBlock({ type: 'table', version: 1, data: { headers: 'x' }, fallback_text: 'A | B' });
report.newerThanRenderer = D.renderBlock({ type: 'table', version: 9, data: { headers: ['A'], rows: [] }, fallback_text: 'A' });

D.setEnabled('table', false);
report.switchedOff = D.renderBlock(D.blocks.table(['A'], [['1']]));
D.setEnabled('table', true);
report.switchedOn = D.renderBlock(D.blocks.table(['A'], [['1']])).includes('tc-display-table');

report.swap = (D.register('boom', { render: () => '<i>fixed</i>' }), D.renderBlock({ type: 'boom', version: 1, data: {}, fallback_text: 'x' }));
report.loaded = await D.loadConfig(async () => ({ ok: true, json: async () => ({ disabled: ['table'] }) }));
report.loadedOff = D.isEnabled('table');
report.loadFails = await D.loadConfig(async () => { throw new Error('offline'); });
report.stillOff = D.isEnabled('table');

// Build's reply path: a turn drawn through unified_code_events.js carries the same markdown HTML with the kernel loaded.
const turn = { role: 'agent', ok: true, transcript: JSON.stringify({ fc: 'final', text: ['Done.', '', '| A | B |', '|---|---|', '| x | 1 |'].join(String.fromCharCode(10)) }) };
const drawTurn = () => {
  vm.runInThisContext(fs.readFileSync(path.join(jsDir, 'unified_code_cards.js'), 'utf8'), { filename: 'cards' });
  vm.runInThisContext(fs.readFileSync(path.join(jsDir, 'unified_code_events.js'), 'utf8'), { filename: 'events' });
  const api = window.ThomasCodeEvents.create({
    MAX_VISIBLE_PROGRESS_EVENTS: 120, MAX_PROGRESS_EVENT_CHARS: 420,
    NARRATIVE_EVENT_KINDS: new Set(['approval', 'disconnected', 'done', 'final', 'insight', 'planning', 'say', 'steering', 'stopped', 'stopping']),
    state: { running: false, runStartedAt: 0 }, esc, codeResults: () => ({ artifactCardsHtml: () => '', runReportHtml: () => '' }),
    surface: () => null, isInternalResultPath: () => false, safely: async a => a(), pushLiveEvent: () => {}, render: () => {}, send: () => {},
  });
  return api.turnHtml(turn);
};
const withKernel = drawTurn();
const kernelSaved = window.ThomasDisplay; delete window.ThomasDisplay;
const withoutKernel = drawTurn();
window.ThomasDisplay = kernelSaved;
report.buildReplySame = withKernel === withoutKernel;
D.setEnabled('markdown', false);
report.buildReplyOffShowsWords = drawTurn().includes('tc-display-fallback');
D.setEnabled('markdown', true);
report.buildReplyHasTable = withKernel.includes('<table>');
console.log(JSON.stringify(report));
