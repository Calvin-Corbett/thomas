// How a widget's blocks are drawn (js/attention_widget_view.js), checked without a browser (2026-11-09).
//
// A widget is blocks Thomas names and the page draws in the app's own style. Each kind draws its part, every word a
// block carries is escaped, and a card whose kind is "widget" puts its blocks in a container the page can refill
// without redrawing the card around them.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const widgetPath = process.argv[2];
if (!widgetPath) throw new Error('usage: node attention_widgets.mjs <attention_widget_view.js>');
globalThis.window = {};
vm.runInThisContext(fs.readFileSync(widgetPath, 'utf8'), { filename: widgetPath });
vm.runInThisContext(fs.readFileSync(path.join(path.dirname(widgetPath), 'attention_card_view.js'), 'utf8'));
const draw = blocks => window.ThomasAttentionWidgetView.blocksHtml(blocks);
const view = window.ThomasAttentionView;

// A meter: its number, a bar that wide, a tick at the limit, and a state when it is at or past the limit.
const meter = draw([{ type: 'meter', label: 'CPU', value: 62.4, mark: 90, hint: 'Thomas holds new work at 90%' }]);
assert.match(meter, /<span>CPU<\/span><b>62%<\/b>/);
assert.match(meter, /role="meter" aria-label="CPU" aria-valuemin="0" aria-valuemax="100" aria-valuenow="62"/);
assert.match(meter, /<i style="width:62\.4%"><\/i><u style="left:90%" title="Limit 90%"><\/u>/);
assert.match(meter, /<small class="tc-attn-hint">Thomas holds new work at 90%<\/small>/);
assert.ok(!meter.includes('is-over'));
assert.match(draw([{ type: 'meter', label: 'CPU', value: 95, mark: 90 }]), /class="tc-attn-meter is-over"/);
const empty = draw([{ type: 'meter', label: 'CPU', value: null, mark: null }]);
assert.match(empty, /<b>—<\/b>/, 'a meter with no reading yet says so, never 0%');
assert.ok(!empty.includes('aria-valuenow') && !empty.includes('<u '));

// A reading, rows, steps and a spark line.
assert.match(draw([{ type: 'reading', label: 'Context', value: '48,210', unit: 'of 200,000 tokens' }]), /<span class="tc-attn-label">Context<\/span><div class="tc-attn-total"><b>48,210<\/b><span>of 200,000 tokens<\/span>/);
const rows = draw([{ type: 'rows', label: 'Thomas', rows: [{ label: 'Version', value: '0.19.52' }, { label: 'Restart', value: 'Restarting', note: 'waiting 4 min' }] }]);
assert.match(rows, /<div class="tc-attn-row"><span>Version<\/span><b>0\.19\.52<\/b><\/div>/);
assert.match(rows, /<em>waiting 4 min<\/em>/);
assert.match(draw([{ type: 'rows', rows: [] }]), /Nothing to show yet\./);
const steps = draw([{ type: 'steps', steps: [{ label: 'Draw the court', state: 'done', note: '1m 24s' }, { label: 'Add scoring', state: 'active' }, { label: 'Check it', state: 'pending' }] }]);
assert.match(steps, /<span class="tc-attn-steps-count">1 of 3<\/span>/);
assert.match(steps, /<i style="width:33%"><\/i>/);
assert.match(steps, /class="tc-attn-step is-done"><span class="tc-attn-step-mark" aria-hidden="true">✓<\/span>/);
assert.match(steps, /class="tc-attn-step is-active"/);
const spark = draw([{ type: 'spark', label: 'CPU', unit: '%', points: [10, 20, 30] }]);
assert.match(spark, /<b>30%<\/b>/);
assert.match(spark, /<polyline points="0\.0,26\.0 50\.0,14\.0 100\.0,2\.0"/);
assert.match(draw([{ type: 'spark', label: 'CPU', points: [5] }]), /Collecting readings…/);

// Buttons answer like a question's; a toggle is a real switch, and a locked one cannot be pressed.
assert.match(draw([{ type: 'buttons', options: [{ id: 'open', label: 'Open task' }, { id: 'pause', label: 'Pause' }] }]), /class="tc-attn-option is-first" data-attn-option="open">Open task<\/button><button type="button" class="tc-attn-option" data-attn-option="pause">Pause/);
const on = draw([{ type: 'toggle', setting: 'row:agents', label: 'Agents page', on: true }]);
assert.match(on, /<span>Agents page<\/span><button type="button" role="switch" aria-checked="true" aria-label="Agents page" data-attn-toggle="row:agents">/);
const locked = draw([{ type: 'toggle', setting: 'row:chat', label: 'Chat', on: true, locked: true }]);
assert.match(locked, /data-attn-toggle="row:chat" disabled/);

// Every word a block carries is escaped, and a kind the page does not know draws nothing.
const hostile = draw([
  { type: 'text', text: '<img src=x onerror=alert(1)>' },
  { type: 'rows', rows: [{ label: '<b>x</b>', value: '"><script>' }] },
  { type: 'toggle', setting: 'row:"onmouseover="x', label: '<i>y</i>' },
  { type: 'iframe', src: 'https://example.com' },
]);
assert.ok(!/<img src=x|<script>|<b>x<\/b>|<i>y<\/i>|<iframe/.test(hostile));
assert.match(hostile, /data-attn-toggle="row:&quot;onmouseover=&quot;x"/);

// A widget card holds its blocks in one container, draws its buttons once, and keeps its signature while readings move.
const card = { id: 'w1', kind: 'widget', tone: 'info', title: 'This PC', body: '', options: [{ id: 'open', label: 'Open task' }], blocks: [{ type: 'meter', label: 'CPU', value: 10 }, { type: 'buttons', options: [{ id: 'open', label: 'Open task' }] }] };
const html = view.cardHtml(card);
assert.match(html, /<div class="tc-attn-blocks" data-attn-blocks>/);
assert.equal((html.match(/data-attn-option="open"/g) || []).length, 1, 'the button is drawn by its block, not a second time by the card');
const moved = { ...card, blocks: [{ type: 'meter', label: 'CPU', value: 70 }, card.blocks[1]] };
assert.equal(view.signature(card), view.signature(moved), 'new readings do not redraw the card');
assert.notEqual(view.blocksSignature(card), view.blocksSignature(moved), 'they refill its blocks');

console.log(JSON.stringify({ everyBlockDraws: true, wordsAreEscaped: true, readingsRefillInPlace: true }));
